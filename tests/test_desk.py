"""The specialist's dashboard (web/support/desk.py, workflow.py, #18)."""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from megatron.departments import load_departments
from support import workflow
from support.models import Request, Ticket, TicketEvent, User
from support.services import import_departments

pytestmark = pytest.mark.django_db

RU = {"accept-language": "ru"}


@pytest.fixture(autouse=True)
def departments(departments_path):
    import_departments(load_departments(departments_path))


def make_user(username, role="Specialist", department="network"):
    user = User.objects.create_user(username, password="unused-in-tests", department_id=department)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def make_ticket(department="network", candidates=("network", "software"), tags=("vpn",), **kw):
    request = Request.objects.create(text=kw.pop("text", "VPN не работает"), contact="a@b.c")
    ticket = Ticket.objects.create(
        request=request,
        what="VPN не работает",
        summary=kw.pop("summary", "Не работает VPN"),
        tags=list(tags),
        candidates=list(candidates),
        language="ru",
        department_id=department,
        **kw,
    )
    TicketEvent.objects.create(
        ticket=ticket, kind=TicketEvent.Kind.CREATED, data={"department": department}
    )
    return ticket


@pytest.fixture
def ivan():
    return make_user("ivan")


def act(client, ticket, action, data=None, **kw):
    url = reverse("desk_action", kwargs={"pk": ticket.pk, "action": action})
    return client.post(url, data or {}, **kw)


def test_login_required_and_staff_only(client):
    response = client.get(reverse("desk"))
    assert response.status_code == 302
    assert response["location"].startswith("/login/")
    client.force_login(make_user("bot", role=None, department=None))
    assert client.get(reverse("desk")).status_code == 403


def test_login_page_leads_to_the_dashboard(client, ivan):
    page = client.get("/login/", headers=RU).content.decode()
    assert "Вход для сотрудников" in page
    response = client.post("/login/", {"username": "ivan", "password": "unused-in-tests"})
    assert response["location"] == reverse("desk")


def test_queue_is_the_departments_new_tickets_oldest_first(client, ivan):
    first = make_ticket(summary="Первая")
    second = make_ticket(summary="Вторая")
    make_ticket(department="hardware", candidates=["hardware"], summary="Чужая")
    make_ticket(summary="Уже в работе", status=Ticket.Status.IN_PROGRESS)
    client.force_login(ivan)

    response = client.get(reverse("desk"), headers=RU)
    assert [t.pk for t, _ in response.context["rows"]] == [first.pk, second.pk]
    page = response.content.decode()
    assert "Очередь" in page and "Сеть и связь" in page
    assert "Чужая" not in page


def test_take_makes_it_mine(client, ivan):
    ticket = make_ticket()
    client.force_login(ivan)

    response = act(client, ticket, "take", follow=True, headers=RU)
    ticket.refresh_from_db()
    assert (ticket.status, ticket.assignee, ticket.taken_at is not None) == (
        Ticket.Status.IN_PROGRESS,
        ivan,
        True,
    )
    assert ticket.events.filter(kind=TicketEvent.Kind.TAKEN, actor=ivan).exists()
    assert "Заявка теперь ваша" in response.content.decode()
    mine = client.get(reverse("desk") + "?list=mine").context["rows"]
    assert [t.pk for t, _ in mine] == [ticket.pk]


def test_the_same_ticket_cannot_be_taken_twice(client, ivan):
    ticket = make_ticket()
    workflow.take(ticket.pk, ivan)
    petr = make_user("petr")
    client.force_login(petr)

    response = act(client, ticket, "take", follow=True, headers=RU)
    ticket.refresh_from_db()
    assert ticket.assignee == ivan
    assert "Заявку уже взяли" in response.content.decode()
    assert ticket.events.filter(kind=TicketEvent.Kind.TAKEN).count() == 1
    with pytest.raises(workflow.ActionRefused):
        workflow.take(ticket.pk, petr)


def test_other_departments_tickets_are_not_found(client, ivan):
    other = make_ticket(department="hardware", candidates=["hardware"])
    client.force_login(ivan)
    assert client.get(reverse("desk_ticket", kwargs={"pk": other.pk})).status_code == 404
    assert act(client, other, "take").status_code == 404


def test_return_goes_to_the_next_candidate_then_the_fallback(ivan):
    ticket = make_ticket(candidates=["network", "software"])
    workflow.take(ticket.pk, ivan)

    ticket = workflow.return_ticket(ticket.pk, ivan, "Это не сеть, а почта")
    assert (ticket.department_id, ticket.status, ticket.assignee) == (
        "software",
        Ticket.Status.NEW,
        None,
    )
    assert ticket.taken_at is None
    event = ticket.events.get(kind=TicketEvent.Kind.RETURNED)
    assert event.data == {"from": "network", "to": "software", "reason": "Это не сеть, а почта"}

    # Never back to a department that had it: network is tried, so the fallback is next.
    ticket = workflow.return_ticket(ticket.pk, make_user("olga", department="software"), "нет")
    assert ticket.department_id == "general"
    with pytest.raises(workflow.ActionRefused):
        workflow.return_ticket(ticket.pk, make_user("gen", department="general"), "нет")


def test_return_prefers_the_busy_best_fit(ivan):
    """Routed to the second candidate for load: "Return" offers the model's best fit."""
    ticket = make_ticket(department="software", candidates=["network", "software"])
    ticket = workflow.return_ticket(ticket.pk, make_user("olga", department="software"), "не наше")
    assert ticket.department_id == "network"


def test_return_from_the_page(client, ivan):
    ticket = make_ticket()
    client.force_login(ivan)
    page = client.get(reverse("desk_ticket", kwargs={"pk": ticket.pk}), headers=RU)
    assert "Заявка уйдёт в отдел «ПО и учётные записи»" in page.content.decode()

    response = act(client, ticket, "return", {"reason": "почта"}, follow=True, headers=RU)
    assert "Возвращена в отдел «ПО и учётные записи»" in response.content.decode()
    assert act(client, ticket, "return", {"reason": ""}).status_code == 404  # no longer ours


def test_close_confirms_or_corrects_the_department(client, ivan):
    right, wrong = make_ticket(), make_ticket()
    for ticket in (right, wrong):
        workflow.take(ticket.pk, ivan)
    client.force_login(ivan)

    act(client, right, "close", {"correct": "yes"})
    assert act(client, wrong, "close", {"correct": "no"}).status_code == 400  # which one?
    act(client, wrong, "close", {"correct": "no", "department": "software"})

    for ticket, correct, department in ((right, True, None), (wrong, False, "software")):
        ticket.refresh_from_db()
        assert ticket.status == Ticket.Status.DONE
        assert ticket.closed_at is not None
        event = ticket.events.get(kind=TicketEvent.Kind.STATUS_CHANGED)
        assert event.data["department_correct"] is correct
        assert event.data["correct_department"] == department
    page = client.get(reverse("desk_ticket", kwargs={"pk": wrong.pk}), headers=RU)
    assert "Выполнена; должна была уйти в отдел «ПО и учётные записи»" in (page.content.decode())


def test_only_the_assignee_closes_or_edits(ivan):
    ticket = make_ticket()
    petr = make_user("petr")
    with pytest.raises(workflow.ActionRefused):
        workflow.close(ticket.pk, ivan)  # not taken yet
    workflow.take(ticket.pk, ivan)
    with pytest.raises(workflow.ActionRefused):
        workflow.close(ticket.pk, petr)
    with pytest.raises(workflow.ActionRefused):
        workflow.edit(ticket.pk, petr, {"summary": "чужая"})


def test_edit_records_old_and_new_values(client, ivan):
    ticket = make_ticket()
    workflow.take(ticket.pk, ivan)
    client.force_login(ivan)

    act(
        client,
        ticket,
        "edit",
        {
            "who": "Иванов",
            "where": "",
            "when": "",
            "what": ticket.what,
            "summary": "VPN у бухгалтерии",
            "tags": "vpn, бухгалтерия",
        },
    )
    ticket.refresh_from_db()
    assert (ticket.who, ticket.where, ticket.summary) == ("Иванов", None, "VPN у бухгалтерии")
    assert ticket.tags == ["vpn", "бухгалтерия"]
    event = ticket.events.get(kind=TicketEvent.Kind.EDITED)
    assert event.data == {
        "who": [None, "Иванов"],
        "summary": ["Не работает VPN", "VPN у бухгалтерии"],
        "tags": [["vpn"], ["vpn", "бухгалтерия"]],
    }


def test_filters_by_status_tag_and_date(client, ivan):
    vpn = make_ticket(tags=["vpn"])
    wifi = make_ticket(tags=["Wi-Fi"], status=Ticket.Status.DONE)
    client.force_login(ivan)

    def shown(query):
        return [t.pk for t, _ in client.get(reverse("desk") + query).context["rows"]]

    assert shown("?list=all") == [vpn.pk, wifi.pk]
    assert shown("?list=all&status=done") == [wifi.pk]
    assert shown("?list=all&tag=wi-fi") == [wifi.pk]
    today = vpn.created_at.date().isoformat()
    assert shown(f"?list=all&since={today}&until={today}") == [vpn.pk, wifi.pk]
    assert shown("?list=all&until=2000-01-01") == []


def test_admin_sees_every_department(client):
    make_ticket()
    make_ticket(department="hardware", candidates=["hardware"])
    client.force_login(make_user("boss", role="Admin", department=None))
    assert len(client.get(reverse("desk")).context["rows"]) == 2


def test_actions_need_post(client, ivan):
    ticket = make_ticket()
    client.force_login(ivan)
    url = reverse("desk_action", kwargs={"pk": ticket.pk, "action": "take"})
    assert client.get(url).status_code == 405
    assert act(client, ticket, "delete").status_code == 404


def test_admin_sets_the_specialists_department(admin_client):
    page = admin_client.get(reverse("admin:support_user_add")).content.decode()
    assert 'name="department"' in page


def test_admin_saves_a_ticket_without_identifiers(admin_client):
    """#19: an empty JSON list counted as a missing value, so the admin could not reassign."""
    ticket = make_ticket(tags=[])
    url = reverse("admin:support_ticket_change", args=[ticket.pk])
    data = {
        "request": ticket.request_id,
        "what": ticket.what,
        "identifiers": "[]",
        "summary": ticket.summary,
        "tags": "[]",
        "candidates": '["network", "software"]',
        "language": "ru",
        "department": "software",
        "status": "new",
    }
    response = admin_client.post(url, data)
    assert response.status_code == 302, response.context["adminform"].form.errors
    ticket.refresh_from_db()
    assert ticket.department_id == "software"
