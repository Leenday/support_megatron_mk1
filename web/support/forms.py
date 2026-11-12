from math import isfinite
from typing import cast
from uuid import uuid4

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from pydantic import ValidationError

from megatron.departments import RoutingWeights
from support.models import (
    ACCOUNT_ROLES,
    ROLE_LABELS,
    SPECIALIST_ROLE,
    Department,
    RoutingSettings,
    System,
    Ticket,
    User,
)


class DeskLoginForm(AuthenticationForm):
    def clean(self):
        identifier = self.cleaned_data.get("username", "")
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
            if user is not None:
                self.cleaned_data["username"] = user.username
        return super().clean()


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.username_field = User._meta.get_field("email")
        email_field = cast(forms.EmailField, self.fields["username"])
        email_field.max_length = 254
        email_field.widget.attrs["maxlength"] = 254

    def clean(self):
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if email and password:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                User().set_password(password)
                raise self.get_invalid_login_error()
            self.user_cache = authenticate(self.request, username=user.username, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.can_access_admin():
            raise self.get_invalid_login_error()


class RoleField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return ROLE_LABELS[obj.name]


class AccountRoleForm(forms.ModelForm):
    role = RoleField(
        queryset=Group.objects.filter(name__in=ACCOUNT_ROLES).order_by("name"), label=_("Role")
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
            self.initial["role"] = self.instance.groups.filter(name__in=ACCOUNT_ROLES).first()


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
        fields = ("w_match", "w_load", "rank_match", "languages")

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

    def __init__(self, *args, language: str = "ru", exclude: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["department"]
        assert isinstance(field, DepartmentField)
        field.queryset = Department.objects.filter(active=True).exclude(pk=exclude)
        field.language = language

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if data.get("correct") == "no" and not data.get("department"):
            self.add_error("department", _("Choose the department that should have got it."))
        return data
