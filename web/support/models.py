"""Data model of the service (#15).

Departments live in the database once the service runs; `config/departments.yaml` only
seeds them (`import_departments`) and receives copies (`export_departments`). A request
keeps the original text and the extraction log; it has one or more tickets (one per part
when a request is split by department, #45; today always one).
"""

import hashlib
import secrets
from typing import TYPE_CHECKING

from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from megatron.departments import DepartmentsConfig, RoutingWeights

DEFAULT_ROUTING = RoutingWeights()
DEFAULT_LANGUAGES = DepartmentsConfig.model_fields["languages"].default

if TYPE_CHECKING:
    # Reverse relations, declared for the type checker (Django adds them at runtime).
    from django.db.models.fields.related_descriptors import RelatedManager

# Requester accounts are optional. The public form still works without signing in.
REQUESTER_ROLE = "Requester"
SPECIALIST_ROLE = "Specialist"
ADMIN_ROLE = "Admin"
ROLES = (SPECIALIST_ROLE, ADMIN_ROLE)
ACCOUNT_ROLES = (REQUESTER_ROLE, *ROLES)
ROLE_LABELS = {
    REQUESTER_ROLE: _("Requester"),
    SPECIALIST_ROLE: _("Specialist"),
    ADMIN_ROLE: _("Administrator"),
}


# Module-level functions: migrations can only serialize importable callables as defaults.
def default_rank_match() -> list[float]:
    return list(DEFAULT_ROUTING.rank_match)


def default_languages() -> list[str]:
    return list(DEFAULT_LANGUAGES)


def new_access_code() -> str:
    """Secret part of a request's status link, so request numbers cannot be enumerated."""
    return secrets.token_urlsafe(12)


class User(AbstractUser):
    """An optional requester account or a member of staff."""

    class Meta(AbstractUser.Meta):  # ty: ignore[invalid-attribute-override]
        constraints = [
            models.UniqueConstraint(
                Lower("email"), condition=~Q(email=""), name="unique_user_email_ci"
            )
        ]

    department = models.ForeignKey(
        "Department",
        verbose_name=_("Department"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specialists",
        help_text=_("Specialists only: the department whose tickets they work on."),
    )

    def __str__(self) -> str:
        return self.email or self.username

    def get_short_name(self) -> str:
        return self.first_name or self.email or self.username

    def has_role(self, role: str) -> bool:
        return self.groups.filter(name=role).exists()

    def can_access_admin(self) -> bool:
        return self.is_active and (self.is_superuser or self.has_role(ADMIN_ROLE))


class Department(models.Model):
    id = models.CharField(
        _("Department ID"),
        primary_key=True,
        max_length=50,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "lowercase letters, digits and _")],
        help_text=_("Stable id: the model returns it, and the YAML import matches by it."),
    )
    name_ru = models.CharField(_("Name in Russian"), max_length=200)
    name_en = models.CharField(_("Name in English"), max_length=200)
    description = models.TextField(
        _("Description"),
        help_text=_("The model reads this to choose the department: describe what it handles."),
    )
    tags = models.JSONField(
        _("Tags"), default=list, blank=True, help_text=_("Keywords, shown to the model as well.")
    )
    language = models.CharField(
        _("Language"), max_length=2, help_text=_("Language of the department's tickets.")
    )
    capacity = models.PositiveIntegerField(
        _("Capacity"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=_("Open tickets the department can handle at once; empty = load not used."),
    )
    fallback = models.BooleanField(
        _("Fallback"), default=False, help_text=_("Receives requests that fit no other department.")
    )
    active = models.BooleanField(
        _("Active"), default=True, help_text=_("Inactive departments are not offered to the model.")
    )

    class Meta:
        verbose_name = _("department")
        verbose_name_plural = _("departments")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["fallback"], condition=Q(fallback=True), name="one_fallback_department"
            )
        ]

    def __str__(self) -> str:
        return self.name_en

    def name(self, language: str) -> str:
        """Display name in the interface language: Russian for "ru", English otherwise."""
        return self.name_ru if language == "ru" else self.name_en


class System(models.Model):
    """A system or channel of the domain with its spellings (#34): the ticket's `systems`.

    The model sees the active ones as an enum, like the departments, so it cannot invent a
    system; "where" stays free text next to it.
    """

    id = models.CharField(
        _("System ID"),
        primary_key=True,
        max_length=50,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "lowercase letters, digits and _")],
        help_text=_("Stable id: the model returns it, and the YAML import matches by it."),
    )
    name = models.CharField(_("Name"), max_length=200)
    spellings = models.JSONField(
        _("Spellings"),
        default=list,
        help_text=_(
            "How requests write it: names, abbreviations, transliterations. The model reads them."
        ),
    )
    active = models.BooleanField(
        _("Active"), default=True, help_text=_("Inactive systems are not offered.")
    )

    class Meta:
        verbose_name = _("system")
        verbose_name_plural = _("systems")
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class RoutingSettings(models.Model):
    """One row: the routing weights and ticket languages of `config/departments.yaml`."""

    w_match = models.FloatField(
        _("Profile weight"), default=DEFAULT_ROUTING.w_match, validators=[MinValueValidator(0)]
    )
    w_load = models.FloatField(
        _("Load weight"), default=DEFAULT_ROUTING.w_load, validators=[MinValueValidator(0)]
    )
    rank_match = models.JSONField(
        _("Rank scores"),
        default=default_rank_match,
        help_text=_("Profile match of the model's 1st, 2nd, ... candidate, decreasing."),
    )
    languages = models.JSONField(
        _("Ticket languages"),
        default=default_languages,
        help_text=_("ISO 639-1 codes; the first is the default."),
    )

    class Meta:
        verbose_name = verbose_name_plural = _("routing settings")

    def __str__(self) -> str:
        return str(_("Routing settings"))

    @classmethod
    def load(cls) -> "RoutingSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Request(models.Model):
    """What a requester sent, with the extraction log; kept even when extraction failed.

    Requesters need no account: `contact` is how to reach them. `requester` is set only when
    a logged-in user sends the request.
    """

    tickets: "RelatedManager[Ticket]"

    text = models.TextField(_("Request text"))
    contact = models.CharField(
        _("Contact"),
        max_length=200,
        blank=True,
        help_text=_("E-mail, phone or messenger of the requester."),
    )
    requester = models.ForeignKey(
        User,
        verbose_name=_("Requester"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requests",
    )
    created_at = models.DateTimeField(_("Created"), auto_now_add=True)
    model = models.CharField(_("Model"), max_length=100, blank=True)
    prompt_version = models.CharField(_("Prompt version"), max_length=20, blank=True)
    attempts = models.PositiveSmallIntegerField(_("Attempts"), null=True)
    dropped_identifiers = models.JSONField(_("Dropped identifiers"), default=list, blank=True)
    seconds = models.FloatField(_("Seconds"), null=True)
    error = models.TextField(_("Error"), blank=True)
    access_code = models.CharField(
        max_length=32,
        default=new_access_code,
        editable=False,
        help_text=_("Secret part of the requester's status link."),
    )

    class Meta:
        verbose_name = _("request")
        verbose_name_plural = _("request log")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Request {self.pk}"


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")

    OPEN = (Status.NEW, Status.IN_PROGRESS)  # count towards the department's load

    events: "RelatedManager[TicketEvent]"

    request = models.ForeignKey(
        Request, verbose_name=_("Request"), on_delete=models.CASCADE, related_name="tickets"
    )
    who = models.TextField(_("Who"), null=True, blank=True)
    where = models.TextField(_("Where"), null=True, blank=True)
    systems = models.JSONField(
        _("Systems"), default=list, blank=True, help_text=_("System ids, see System.")
    )
    when = models.TextField(_("When"), null=True, blank=True)
    what = models.TextField(_("What"))
    # blank: an empty list is a valid answer, and the admin form must accept it (#19).
    identifiers = models.JSONField(_("Identifiers"), default=list, blank=True)
    summary = models.CharField(_("Summary"), max_length=300)
    tags = models.JSONField(_("Tags"), default=list, blank=True)
    candidates = models.JSONField(
        _("Model's candidates"), default=list, help_text=_("Department ids, best fit first.")
    )
    language = models.CharField(_("Language"), max_length=2)
    department = models.ForeignKey(
        Department, verbose_name=_("Department"), on_delete=models.PROTECT, related_name="tickets"
    )
    status = models.CharField(
        _("Status"), max_length=20, choices=Status.choices, default=Status.NEW
    )
    assignee = models.ForeignKey(
        User,
        verbose_name=_("Assignee"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )
    created_at = models.DateTimeField(_("Created"), auto_now_add=True)
    taken_at = models.DateTimeField(_("Taken"), null=True, blank=True)
    closed_at = models.DateTimeField(_("Closed"), null=True, blank=True)

    class Meta:
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        ordering = ["created_at"]
        indexes = [models.Index(fields=["department", "status"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.summary}"


class TicketEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", _("Created")
        TAKEN = "taken", _("Taken")
        STATUS_CHANGED = "status_changed", _("Status changed")
        EDITED = "edited", _("Edited")
        RETURNED = "returned", _("Returned")
        REASSIGNED = "reassigned", _("Reassigned")

    ticket = models.ForeignKey(
        Ticket, verbose_name=_("Ticket"), on_delete=models.CASCADE, related_name="events"
    )
    kind = models.CharField(_("Event type"), max_length=20, choices=Kind.choices)
    actor = models.ForeignKey(
        User,
        verbose_name=_("Actor"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=_("Empty = the system."),
    )
    data = models.JSONField(_("Event data"), default=dict, blank=True)
    at = models.DateTimeField(_("Event time"), auto_now_add=True)

    class Meta:
        verbose_name = _("ticket event")
        verbose_name_plural = _("ticket events")
        ordering = ["at", "pk"]

    def __str__(self) -> str:
        return f"{self.kind} #{self.ticket_id}"


class ApiToken(models.Model):
    """Personal API token for scripts and integrations (#42); the browser uses the session.

    Only a hash is stored, so a copy of the database gives no working tokens; the token
    itself is shown once, by `manage.py create_api_token`. Revoking = deleting the row.
    """

    PREFIX = "mk1_"

    user = models.ForeignKey(
        User, verbose_name=_("User"), on_delete=models.CASCADE, related_name="api_tokens"
    )
    name = models.CharField(
        _("Name"), max_length=100, help_text=_("What the token is for, e.g. the script.")
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    hint = models.CharField(
        _("Hint"),
        max_length=12,
        editable=False,
        help_text=_("Start of the token, to tell tokens apart."),
    )
    created_at = models.DateTimeField(_("Created"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("Last used"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.hint}… ({self.name})"

    @staticmethod
    def hash(key: str) -> str:
        # A token is 32 random bytes, so a plain SHA-256 is enough (no salt or slow hash).
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, user: User, name: str) -> tuple["ApiToken", str]:
        """Create a token; returns the row and the token, which is not stored anywhere."""
        key = cls.PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, name=name, key_hash=cls.hash(key), hint=key[:12])
        return token, key
