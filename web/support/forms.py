from math import isfinite
from typing import cast
from uuid import uuid4

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserChangeForm,
    UserCreationForm,
    UsernameField,
)
from django.contrib.auth.models import Group
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from pydantic import ValidationError

from megatron.departments import RoutingWeights
from support.models import (
    ROLE_LABELS,
    ROLES,
    SPECIALIST_ROLE,
    Department,
    RoutingSettings,
    System,
    Ticket,
    User,
)


class DeskLoginForm(AuthenticationForm):
    username = UsernameField(
        label=format_lazy("Email / {}", _("Username")),
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Email addresses can be longer than usernames.
        identifier = cast(UsernameField, self.fields["username"])
        identifier.max_length = 254
        identifier.widget.attrs["maxlength"] = 254

    def clean(self):
        identifier = self.cleaned_data.get("username", "")
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
            if user is not None:
                self.cleaned_data["username"] = user.username
        return super().clean()


class AdminLoginForm(DeskLoginForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.can_access_admin():
            raise self.get_invalid_login_error()


class RoleField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return ROLE_LABELS[obj.name]


class AccountRoleForm(forms.ModelForm):
    role = RoleField(
        queryset=Group.objects.filter(name__in=ROLES).order_by("name"), label=_("Role")
    )

    def clean(self):
        super().clean()
        data = self.cleaned_data
        role = data.get("role")
        if role is not None:
            if role.name == SPECIALIST_ROLE:
                if not data.get("department") or not data["department"].active:
                    self.add_error(
                        "department", _("Choose an active department for the specialist.")
                    )
            else:
                data["department"] = None
        return data


class StaffCreationForm(AccountRoleForm, UserCreationForm):
    email = forms.EmailField(label="Email", max_length=254)

    class Meta(UserCreationForm.Meta):  # ty: ignore[invalid-attribute-override]
        model = User
        fields = ("email", "department")

    def save(self, commit=True):
        self.instance.username = uuid4().hex
        return super().save(commit=commit)


class StaffChangeForm(AccountRoleForm, UserChangeForm):
    email = forms.EmailField(label="Email", max_length=254)

    class Meta(UserChangeForm.Meta):  # ty: ignore[invalid-attribute-override]
        model = User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "role" in self.fields:
            self.initial["role"] = self.instance.groups.filter(name__in=ROLES).first()


class DepartmentAdminForm(forms.ModelForm):
    make_fallback = forms.BooleanField(
        label=_("Fallback"),
        required=False,
        help_text=_(
            "Send requests here when no other department fits. "
            "Selecting this replaces the current fallback."
        ),
    )

    class Meta:
        model = Department
        exclude = ("fallback",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["make_fallback"] = self.instance.fallback

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if "tags" in data:
            tags = data["tags"]
            if (
                not isinstance(tags, list)
                or not tags
                or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
            ):
                self.add_error("tags", _("Enter a non-empty JSON list of tags."))
        if "language" in data and data["language"] not in RoutingSettings.load().languages:
            self.add_error("language", _("Choose a language enabled in routing settings."))
        if data.get("make_fallback") and not data.get("active"):
            self.add_error("active", _("The fallback department must be active."))
        elif self.instance.fallback and not data.get("make_fallback"):
            self.add_error("make_fallback", _("Select a different fallback department first."))
        return data


class RoutingAdminForm(forms.ModelForm):
    class Meta:
        model = RoutingSettings
        fields = (
            "w_match",
            "w_load",
            "rank_match",
            "languages",
            "spelling_auto_approve",
            "abstain_min_history",
        )

    def clean(self):
        super().clean()
        data = self.cleaned_data
        for field in ("w_match", "w_load"):
            if field in data and (not isfinite(data[field]) or data[field] < 0):
                self.add_error(field, _("Enter a finite, non-negative weight."))
        if "rank_match" in data:
            try:
                RoutingWeights.model_validate({"rank_match": data["rank_match"]}, strict=True)
            except ValidationError:
                self.add_error(
                    "rank_match",
                    _("Enter strictly decreasing numbers between 0 and 1, excluding 0."),
                )
        languages = data.get("languages")
        if "languages" in data:
            if (
                not isinstance(languages, list)
                or not languages
                or any(
                    not isinstance(code, str) or len(code) != 2 or not code.islower()
                    for code in languages
                )
            ):
                self.add_error(
                    "languages", _("Enter a JSON list of language codes such as ru and en.")
                )
            elif Department.objects.filter(active=True).exclude(language__in=languages).exists():
                self.add_error("languages", _("Keep all languages used by active departments."))
        return data


class TicketAdminForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = "__all__"

    def clean(self):
        super().clean()
        data = self.cleaned_data
        department = data.get("department")
        assignee = data.get("assignee")
        if "department" in self.changed_data and department and not department.active:
            self.add_error("department", _("Choose an active department."))
        if (
            "assignee" in self.changed_data
            and assignee
            and department
            and (
                not assignee.is_active
                or assignee.department_id != department.pk
                or not assignee.has_role(SPECIALIST_ROLE)
            )
        ):
            self.add_error("assignee", _("Choose an active specialist from this department."))
        return data


class RequestForm(forms.Form):
    text = forms.CharField(
        label=_("Describe the problem in your own words"),
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 8, "autofocus": True}),
        help_text=_("Russian or English. Who, where, when and what happened, if you know."),
    )
    contact = forms.CharField(
        label=_("How to reach you"),
        max_length=200,
        help_text=_("E-mail, phone or messenger."),
    )


class TagsField(forms.CharField):
    """Tags as one comma-separated line."""

    def prepare_value(self, value):
        return ", ".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        text = super().to_python(value) or ""
        return list(dict.fromkeys(t.strip() for t in text.split(",") if t.strip()))


class DeskFilterForm(forms.Form):
    """Filters of the dashboard lists (story 21); every field is optional."""

    status = forms.ChoiceField(
        label=_("Status"),
        required=False,
        choices=[("", _("Any"))] + Ticket.Status.choices,
    )
    tag = forms.CharField(label=_("Tag"), required=False, max_length=50)
    system = forms.ChoiceField(label=_("System"), required=False)
    since = forms.DateField(
        label=_("From"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    until = forms.DateField(
        label=_("To"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["system"]
        assert isinstance(field, forms.ChoiceField)
        field.choices = [("", _("Any"))] + [
            (x.id, x.name) for x in System.objects.filter(active=True)
        ]


class TicketEditForm(forms.Form):
    who = forms.CharField(label=_("Who"), required=False, max_length=500)
    where = forms.CharField(label=_("Where"), required=False, max_length=500)
    when = forms.CharField(label=_("When"), required=False, max_length=500)
    what = forms.CharField(label=_("What"), max_length=1000)
    summary = forms.CharField(label=_("Summary"), max_length=300)
    tags = TagsField(label=_("Tags"), required=False, help_text=_("Separated by commas."))

    def clean(self):
        super().clean()
        data = self.cleaned_data
        # An empty optional field means "unknown", stored as null like the model's answer.
        for field in ("who", "where", "when"):
            if field in data and not data[field]:
                data[field] = None
        return data


class ReturnForm(forms.Form):
    reason = forms.CharField(
        label=_("Why it is not for this department"),
        max_length=500,
        widget=forms.TextInput(),
    )


class DepartmentField(forms.ModelChoiceField):
    """Departments named in the interface language."""

    language = "ru"

    def label_from_instance(self, obj: Department) -> str:
        return obj.name(self.language)


class CloseForm(forms.Form):
    correct = forms.ChoiceField(
        label=_("Was the department right?"),
        choices=[("yes", _("Yes")), ("no", _("No, it should have gone to:"))],
        widget=forms.RadioSelect,
        initial="yes",
    )
    department = DepartmentField(
        label=_("Department"),
        empty_label=_("Choose a department"),
        queryset=Department.objects.filter(active=True),
        required=False,
    )
    # The ticket's systems, prefilled with the model's answer: a right ticket costs no click.
    systems = forms.MultipleChoiceField(
        label=_("Systems"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Untick a wrong one, tick a missing one."),
    )
    proposal = forms.ChoiceField(
        label=_("Does “Where” name a system missing from the list?"),
        choices=[
            ("none", _("No, not a system")),
            ("new", _("Yes, a new system")),
            ("spelling", _("Yes, another spelling of:")),
        ],
        widget=forms.RadioSelect,
        initial="none",
        required=False,  # not sent = "no"
    )
    # Unticking every box sends no `systems` at all; this tells it from a client that never
    # showed them, whose ticket keeps the model's systems.
    systems_shown = forms.BooleanField(required=False, initial=True, widget=forms.HiddenInput)
    proposal_system = forms.ChoiceField(label=_("System"), required=False)
    proposal_text = forms.CharField(
        label=_("As the request writes it"),
        required=False,
        max_length=200,
        widget=forms.TextInput(),
        help_text=_("A validator approves it before it reaches the vocabulary."),
    )

    def __init__(self, *args, language: str = "ru", exclude: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["department"]
        assert isinstance(field, DepartmentField)
        field.queryset = Department.objects.filter(active=True).exclude(pk=exclude)
        field.language = language
        active = list(System.objects.filter(active=True).values_list("id", "name"))
        known = {i for i, _ in active}
        inactive = [x for x in self.initial.get("systems", []) if x not in known]
        names = dict(System.objects.filter(pk__in=inactive).values_list("id", "name"))
        # A system deactivated since the ticket was made still shows, to be kept or removed.
        cast(forms.MultipleChoiceField, self.fields["systems"]).choices = [
            *active,
            *((x, names.get(x, x)) for x in inactive),
        ]
        cast(forms.ChoiceField, self.fields["proposal_system"]).choices = [
            ("", _("Choose a system")),
            *active,
        ]

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if data.get("correct") == "no" and not data.get("department"):
            self.add_error("department", _("Choose the department that should have got it."))
        kind = data.get("proposal") or "none"
        if kind != "none" and not (data.get("proposal_text") or "").strip():
            self.add_error("proposal_text", _("Write the system as the request names it."))
        if kind == "spelling" and not data.get("proposal_system"):
            self.add_error("proposal_system", _("Choose the system it is a spelling of."))
        return data

    def confirmed_systems(self) -> list[str] | None:
        """The systems as the specialist left them, or None when the form did not show them."""
        return self.cleaned_data["systems"] if self.cleaned_data.get("systems_shown") else None

    def vocabulary_proposal(self) -> tuple[str, str | None] | None:
        """(text, system id or None for a new system), or None when nothing is proposed."""
        data = self.cleaned_data
        match data.get("proposal"):
            case "new":
                return data["proposal_text"], None
            case "spelling":
                return data["proposal_text"], data["proposal_system"]
        return None


class ApproveForm(forms.Form):
    system_id = forms.CharField(label=_("System ID"), required=False, max_length=50)
    name = forms.CharField(label=_("Name"), required=False, max_length=200)


class RejectForm(forms.Form):
    reason = forms.CharField(label=_("Reason"), max_length=500)


class EditReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[("confirm", _("Confirm")), ("revert", _("Revert"))], widget=forms.HiddenInput
    )
    comment = forms.CharField(label=_("Comment"), required=False, max_length=500)
