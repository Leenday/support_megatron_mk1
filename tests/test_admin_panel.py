import pytest
import yaml
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse

from support.models import (
    REQUESTER_ROLE,
    SPECIALIST_ROLE,
    Department,
    Request,
    Ticket,
    TicketEvent,
    User,
)
from support.services import department_accuracy, departments_config, import_departments_file
from support.workflow import close, return_ticket, take

pytestmark = pytest.mark.django_db

PASSWORD = "Test6Test7"


def admin_sign_in(client, email):
    url = reverse("admin:login")
    return client.post(
        url,
        {"username": email, "password": PASSWORD, "next": client.get(url).context["next"]},
    )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
def test_seeded_admin_can_log_in_with_email(client):
    response = admin_sign_in(client, "TEST@test.test")

    assert response.url == reverse("admin:index")
    assert reverse("admin:support_user_changelist") in client.get(response.url).content.decode()
    assert client.get(reverse("admin:support_user_changelist")).status_code == 200

    client.logout()
    response = client.post(reverse("login"), {"username": "TEST@test.test", "password": PASSWORD})
    assert response.url == reverse("desk")


def test_specialist_can_use_desk_but_cannot_access_admin(client):
    specialist = User.objects.create_user(
        username="specialist", email="specialist@example.org", password=PASSWORD, is_staff=True
    )
    specialist.groups.add(Group.objects.get(name=SPECIALIST_ROLE))
    index = reverse("admin:index")
    assert client.get(index).status_code == 302

    response = admin_sign_in(client, specialist.email)
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert "_auth_user_id" not in client.session

    response = client.post(reverse("login"), {"username": specialist.email, "password": PASSWORD})
    assert response.url == reverse("desk")
    assert client.get(response.url).status_code == 200
    for url in (
        index,
        reverse("admin:support_user_changelist"),
        reverse("admin:support_department_export"),
    ):
        assert client.get(url).url.startswith(reverse("admin:login") + "?next=")


def test_superuser_with_email_can_sign_in_without_a_role(client):
    user = User.objects.create_superuser(
        username="root", email="root@example.org", password=PASSWORD
    )
    response = admin_sign_in(client, user.email)
    assert response.url == reverse("admin:index")
    assert client.get(reverse("admin:support_department_changelist")).status_code == 200


def test_admin_can_create_and_edit_users(client):
    client.force_login(User.objects.get(email="test@test.test"))
    specialist = Group.objects.get(name=SPECIALIST_ROLE)
    add = reverse("admin:support_user_add")
    email = "new@example.org"
    department = Department.objects.create(id="network", name_en="Network", language="en")
    fields = {"email": email, "role": specialist.pk, "password1": PASSWORD, "password2": PASSWORD}
    assert client.post(add, fields).status_code == 200
    fields["department"] = department.pk

    assert client.post(add, fields).status_code == 302
    user = User.objects.get(email=email)
    assert user.check_password(PASSWORD)
    assert user.department_id == department.pk
    assert list(user.groups.values_list("name", flat=True)) == [SPECIALIST_ROLE]
    assert client.post(add, fields | {"email": email.upper()}).status_code == 200
    assert User.objects.filter(email__iexact=email).count() == 1

    change = reverse("admin:support_user_change", args=[user.pk])
    requester = Group.objects.get(name=REQUESTER_ROLE)
    fields = {"email": email, "role": requester.pk, "is_active": "on"}
    assert client.post(change, fields).status_code == 302
    user.refresh_from_db()
    assert user.is_active
    assert user.department_id is None
    assert list(user.groups.values_list("name", flat=True)) == [REQUESTER_ROLE]
    assert client.post(change, fields | {"is_active": ""}).status_code == 302
    user.refresh_from_db()
    assert not user.is_active


def test_admin_manages_departments_routing_and_export(client, departments_path):
    import_departments_file(departments_path)
    client.force_login(User.objects.get(email="test@test.test"))
    department = {
        "id": "billing",
        "name_ru": "Оплата",
        "name_en": "Billing",
        "description": "Payments",
        "tags": '["invoice"]',
        "language": "en",
        "capacity": 4,
        "active": "on",
    }
    add = reverse("admin:support_department_add")
    assert client.post(add, department).status_code == 302
    assert "billing" in departments_config().ids
    change = reverse("admin:support_department_change", args=["billing"])
    assert client.post(change, department | {"make_fallback": "on"}).status_code == 302
    assert departments_config().fallback.id == "billing"
    assert client.post(change, department | {"active": ""}).status_code == 200
    assert departments_config().fallback.id == "billing"

    settings = client.get(reverse("admin:support_routingsettings_changelist"))
    assert settings.url == reverse("admin:support_routingsettings_change", args=[1])
    weights = {"w_match": 0.5, "w_load": 0.5, "rank_match": "[1, 0.4]", "languages": '["ru","en"]'}
    assert client.post(settings.url, weights | {"rank_match": "[0.4, 1]"}).status_code == 200
    assert client.post(settings.url, weights | {"w_load": -1}).status_code == 200
    assert client.post(settings.url, weights).status_code == 302
    response = client.get(reverse("admin:support_department_export"))
    assert response.status_code == 200
    exported = yaml.safe_load(response.content)
    assert exported["routing"]["rank_match"] == [1, 0.4]
    assert any(row["id"] == "billing" and row["fallback"] for row in exported["departments"])


def test_admin_reassigns_with_audit_and_sees_requests_and_accuracy(client, departments_path):
    import_departments_file(departments_path)
    admin = User.objects.get(email="test@test.test")
    client.force_login(admin)
    specialist = User.objects.create_user(username="operator", department_id="software")
    request = Request.objects.create(text="Example", model="model-v1")
    failed = Request.objects.create(text="Other request", error="Backend unavailable")
    ticket = Ticket.objects.create(
        request=request,
        summary="Test",
        what="Problem",
        candidates=["network", "software"],
        language="en",
        department_id="network",
    )
    return_ticket(ticket.pk, specialist, "Wrong department")
    take(ticket.pk, specialist)
    close(ticket.pk, specialist)
    assert department_accuracy() == {"network": (0, 1), "software": (1, 1)}

    url = reverse("admin:support_ticket_change", args=[ticket.pk])
    response = client.post(
        url,
        {
            "request": request.pk,
            "summary": "Updated",
            "what": ticket.what,
            "language": "en",
            "candidates": '["network", "software"]',
            "department": "network",
            "status": "done",
            "assignee": specialist.pk,
        },
    )
    assert response.status_code == 302
    audit = ticket.events.get(kind=TicketEvent.Kind.REASSIGNED)
    assert (audit.data["from"], audit.data["to"], audit.actor_id) == (
        "software",
        "network",
        admin.pk,
    )
    assert ticket.events.get(kind=TicketEvent.Kind.EDITED).data["summary"] == ["Test", "Updated"]
    assert "Reassigned" in client.get(url, headers={"accept-language": "en"}).content.decode()
    assert department_accuracy() == {"network": (0, 1), "software": (1, 1)}
    changelist = client.get(reverse("admin:support_department_changelist")).content.decode()
    assert "100% (1/1)" in changelist
    assert "0% (0/1)" in changelist
    log = client.get(reverse("admin:support_request_changelist"), {"result": "failed"})
    assert [row.pk for row in log.context["cl"].result_list] == [failed.pk]
