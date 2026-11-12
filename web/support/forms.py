from typing import cast
from uuid import uuid4

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from support.models import ROLES, Department, System, Ticket, User


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
        if not user.is_superuser and not user.groups.filter(name__in=ROLES).exists():
            raise self.get_invalid_login_error()


def role_field():
    return forms.ModelChoiceField(
        queryset=Group.objects.filter(name__in=ROLES).order_by("name"), label="Роль"
    )


class StaffCreationForm(UserCreationForm):
    email = forms.EmailField(label="Email", max_length=254)
    role = role_field()

    class Meta(UserCreationForm.Meta):  # ty: ignore[invalid-attribute-override]
        model = User
        fields = ("email", "department")

    def save(self, commit=True):
        self.instance.username = uuid4().hex
        return super().save(commit=commit)


class StaffChangeForm(UserChangeForm):
    email = forms.EmailField(label="Email", max_length=254)
    role = role_field()

    class Meta(UserChangeForm.Meta):  # ty: ignore[invalid-attribute-override]
        model = User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "role" in self.fields:
            self.initial["role"] = self.instance.groups.filter(name__in=ROLES).first()


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
