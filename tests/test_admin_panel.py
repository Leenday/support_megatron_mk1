import pytest
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from support.models import ADMIN_ROLE, SPECIALIST_ROLE, User

pytestmark = pytest.mark.django_db

PASSWORD = "Test6Test7"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
def test_seeded_admin_can_log_in_with_email(client):
    response = client.post(
        reverse("admin:login"), {"username": "TEST@test.test", "password": PASSWORD}
    )

    assert response.url == reverse("admin:index")
    assert "Управление пользователями" in client.get(response.url).content.decode()
    assert client.get(reverse("admin:support_user_changelist")).status_code == 200


def test_specialist_can_log_in_but_cannot_manage_users(client):
    specialist = User.objects.create_user(
        username="specialist", email="specialist@example.org", password=PASSWORD, is_staff=True
    )
    specialist.groups.add(Group.objects.get(name=SPECIALIST_ROLE))
    index = reverse("admin:index")
    assert client.get(index).status_code == 302

    response = client.post(
        reverse("admin:login"), {"username": specialist.email, "password": PASSWORD}
    )

    assert response.url == index
    assert "Управление пользователями" not in client.get(index).content.decode()
    assert client.get(reverse("admin:support_user_changelist")).status_code == 403
    assert client.post(reverse("admin:support_user_add")).status_code == 403
    change = reverse("admin:support_user_change", args=[specialist.pk])
    assert client.get(change).status_code == 403


def test_admin_can_create_and_edit_users(client):
    client.force_login(User.objects.get(email="test@test.test"))
    specialist = Group.objects.get(name=SPECIALIST_ROLE)
    add = reverse("admin:support_user_add")
    email = "new@example.org"
    fields = {"email": email, "role": specialist.pk, "password1": PASSWORD, "password2": PASSWORD}

    assert client.post(add, fields).status_code == 302
    user = User.objects.get(email=email)
    assert user.check_password(PASSWORD)
    assert list(user.groups.values_list("name", flat=True)) == [SPECIALIST_ROLE]
    assert client.post(add, fields | {"email": email.upper()}).status_code == 200
    assert User.objects.filter(email__iexact=email).count() == 1

    change = reverse("admin:support_user_change", args=[user.pk])
    admin = Group.objects.get(name=ADMIN_ROLE)
    assert client.post(change, {"email": email, "role": admin.pk}).status_code == 302
    user.refresh_from_db()
    assert not user.is_active
    assert list(user.groups.values_list("name", flat=True)) == [ADMIN_ROLE]
