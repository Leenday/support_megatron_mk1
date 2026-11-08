from typing import cast
from uuid import uuid4

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group

from support.models import ROLES, User


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
        if not user.groups.filter(name__in=ROLES).exists():
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
        fields = ("email",)

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
