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

# Auth groups, created by migration 0002. Requesters have no role and no account: the form is
# open, and they give a contact and get a status link instead (#17).
SPECIALIST_ROLE = "Specialist"
ADMIN_ROLE = "Admin"
ROLES = (SPECIALIST_ROLE, ADMIN_ROLE)


# Module-level functions: migrations can only serialize importable callables as defaults.
def default_rank_match() -> list[float]:
    return list(DEFAULT_ROUTING.rank_match)


def default_languages() -> list[str]:
    return list(DEFAULT_LANGUAGES)


def new_access_code() -> str:
    """Secret part of a request's status link, so request numbers cannot be enumerated."""
    return secrets.token_urlsafe(12)


class User(AbstractUser):
    """Staff of the service; the role is the user's group, one of `ROLES`."""

    class Meta(AbstractUser.Meta):  # ty: ignore[invalid-attribute-override]
        constraints = [
            models.UniqueConstraint(
                Lower("email"), condition=~Q(email=""), name="unique_user_email_ci"
            )
        ]

    department = models.ForeignKey(
        "Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="specialists",
        help_text="Specialists only: the department whose tickets they work on.",
    )

    def __str__(self) -> str:
        return self.email or self.username

    def get_short_name(self) -> str:
        return self.first_name or self.email or self.username

    def has_role(self, role: str) -> bool:
        return self.groups.filter(name=role).exists()


class Department(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=50,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "lowercase letters, digits and _")],
        help_text="Stable id: the model returns it, and the YAML import matches by it.",
    )
    name_ru = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    description = models.TextField(
        help_text="The model reads this to choose the department: describe what it handles."
    )
    tags = models.JSONField(
        default=list, blank=True, help_text="Keywords, shown to the model as well."
    )
    language = models.CharField(max_length=2, help_text="Language of the department's tickets.")
    capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Open tickets the department can handle at once; empty = load not used.",
    )
    fallback = models.BooleanField(
        default=False, help_text="Receives requests that fit no other department."
    )
    active = models.BooleanField(
        default=True, help_text="Inactive departments are not offered to the model."
    )

    class Meta:
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
        primary_key=True,
        max_length=50,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "lowercase letters, digits and _")],
        help_text="Stable id: the model returns it, and the YAML import matches by it.",
    )
    name = models.CharField(max_length=200)
    spellings = models.JSONField(
        default=list,
        help_text="How requests write it: names, abbreviations, transliterations. "
        "The model reads them.",
    )
    active = models.BooleanField(default=True, help_text="Inactive systems are not offered.")

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class RoutingSettings(models.Model):
    """One row: the routing weights and ticket languages of `config/departments.yaml`."""

    w_match = models.FloatField(default=DEFAULT_ROUTING.w_match, validators=[MinValueValidator(0)])
    w_load = models.FloatField(default=DEFAULT_ROUTING.w_load, validators=[MinValueValidator(0)])
    rank_match = models.JSONField(
        default=default_rank_match,
        help_text="Profile match of the model's 1st, 2nd, ... candidate, decreasing.",
    )
    languages = models.JSONField(
        default=default_languages, help_text="ISO 639-1 codes; the first is the default."
    )

    class Meta:
        verbose_name = verbose_name_plural = "routing settings"

    def __str__(self) -> str:
        return "Routing settings"

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

    text = models.TextField()
    contact = models.CharField(
        max_length=200, blank=True, help_text="E-mail, phone or messenger of the requester."
    )
    requester = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_version = models.CharField(max_length=20, blank=True)
    attempts = models.PositiveSmallIntegerField(null=True)
    dropped_identifiers = models.JSONField(default=list, blank=True)
    seconds = models.FloatField(null=True)
    error = models.TextField(blank=True)
    access_code = models.CharField(
        max_length=32,
        default=new_access_code,
        editable=False,
        help_text="Secret part of the requester's status link.",
    )

    class Meta:
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

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="tickets")
    who = models.TextField(null=True, blank=True)
    where = models.TextField(null=True, blank=True)
    systems = models.JSONField(default=list, blank=True, help_text="System ids, see System.")
    when = models.TextField(null=True, blank=True)
    what = models.TextField()
    # blank: an empty list is a valid answer, and the admin form must accept it (#19).
    identifiers = models.JSONField(default=list, blank=True)
    summary = models.CharField(max_length=300)
    tags = models.JSONField(default=list, blank=True)
    candidates = models.JSONField(default=list, help_text="Department ids, best fit first.")
    language = models.CharField(max_length=2)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="tickets")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assignee = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_tickets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    taken_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["department", "status"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.summary}"


class TicketEvent(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        TAKEN = "taken", "Taken"
        STATUS_CHANGED = "status_changed", "Status changed"
        EDITED = "edited", "Edited"
        RETURNED = "returned", "Returned"
        REASSIGNED = "reassigned", "Reassigned"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, help_text="Empty = the system."
    )
    data = models.JSONField(default=dict, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "pk"]

    def __str__(self) -> str:
        return f"{self.kind} #{self.ticket_id}"


class ApiToken(models.Model):
    """Personal API token for scripts and integrations (#42); the browser uses the session.

    Only a hash is stored, so a copy of the database gives no working tokens; the token
    itself is shown once, by `manage.py create_api_token`. Revoking = deleting the row.
    """

    PREFIX = "mk1_"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=100, help_text="What the token is for, e.g. the script.")
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    hint = models.CharField(
        max_length=12, editable=False, help_text="Start of the token, to tell tokens apart."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API token"

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
