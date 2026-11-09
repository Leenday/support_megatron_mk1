"""JSON API (web/support/api.py, #42): token and session auth, visibility by role, errors."""

import json

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from megatron.departments import load_departments
from megatron.llm import ExtractionError, FakeExtractor
from support.models import ApiToken, Request, Ticket, User
from support.services import create_ticket, import_departments

pytestmark = pytest.mark.django_db

VPN = "Не работает VPN, сеть пропала"
PRINTER = "The printer on the third floor does not print"


class FailingExtractor(FakeExtractor):
    def extract_detailed(self, text):
        raise ExtractionError("fake returned no valid ticket after 3 attempts")


@pytest.fixture(autouse=True)
def service(departments_path, monkeypatch):
    import_departments(load_departments(departments_path))
    monkeypatch.setattr("support.services.default_extractor", FakeExtractor)


def make_user(username, role=None, department=None):
    user = User.objects.create_user(username, password="unused-in-tests", department_id=department)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def bearer(user):
    _, key = ApiToken.issue(user, "tests")
    return {"authorization": f"Bearer {key}"}


@pytest.fixture
def bot():
    """An integration account: no role, sends requests and sees only its own."""
    return make_user("bot")


def post(client, url, data, headers):
    return client.post(url, json.dumps(data), content_type="application/json", headers=headers)


def test_docs_and_schema_are_open(client):
    assert client.get("/api/docs").status_code == 200
    schema = client.get("/api/openapi.json").json()
    assert {"/api/extract", "/api/tickets", "/api/tickets/{ticket_id}", "/api/departments"} <= set(
        schema["paths"]
    )
    # The response schema is the package's ticket, with an example for Swagger UI.
    ticket = schema["components"]["schemas"]["TicketOut"]
    assert {"who", "where", "candidates", "department", "status"} <= set(ticket["properties"])
    assert ticket["examples"][0]["department"] == "network"


def test_without_credentials_is_401(client):
    assert client.get("/api/tickets").status_code == 401
    assert post(client, "/api/extract", {"text": VPN}, {}).status_code == 401
    assert (
        client.get("/api/tickets", headers={"authorization": "Bearer mk1_wrong"}).status_code == 401
    )


def test_inactive_users_token_is_refused(client, bot):
    headers = bearer(bot)
    bot.is_active = False
    bot.save()
    assert client.get("/api/tickets", headers=headers).status_code == 401


def test_create_ticket_with_a_token(client, bot):
    response = post(
        client, "/api/tickets", {"text": VPN, "contact": "ivanov@example.com"}, bearer(bot)
    )

    assert response.status_code == 201
    saved = Request.objects.get()
    assert saved.requester == bot
    assert saved.contact == "ivanov@example.com"
    body = response.json()
    assert body["request"] == saved.pk
    assert body["status_url"] == f"http://testserver/status/{saved.pk}-{saved.access_code}/"
    [ticket] = body["tickets"]
    assert ticket["department"] == "network"
    assert ticket["status"] == "new"
    assert ticket["id"] == saved.tickets.get().pk
    assert ApiToken.objects.get().last_used_at is not None


def test_extract_saves_nothing(client, bot):
    response = post(client, "/api/extract", {"text": VPN}, bearer(bot))

    assert response.status_code == 200
    body = response.json()
    assert body["ticket"]["department"] == "network"
    assert body["model"] == "fake"
    assert body["attempts"] == 1
    assert not Request.objects.exists()


def test_extraction_error_is_502_and_the_request_is_kept(client, bot, monkeypatch):
    monkeypatch.setattr("support.services.default_extractor", FailingExtractor)
    headers = bearer(bot)

    response = post(client, "/api/tickets", {"text": VPN}, headers)
    assert response.status_code == 502
    saved = Request.objects.get()
    assert response.json() == {"detail": saved.error, "request": saved.pk}
    assert "no valid ticket" in saved.error

    response = post(client, "/api/extract", {"text": VPN}, headers)
    assert response.status_code == 502
    assert response.json()["request"] is None


def test_empty_text_is_422(client, bot):
    assert post(client, "/api/tickets", {"text": ""}, bearer(bot)).status_code == 422


def test_what_each_role_sees(client, bot):
    vpn = create_ticket(VPN, requester=bot).tickets.get()
    printer = create_ticket(PRINTER).tickets.get()
    assert (vpn.department_id, printer.department_id) == ("network", "hardware")
    admin = make_user("admin", "Admin")
    specialist = make_user("net", "Specialist", department="network")
    no_department = make_user("new", "Specialist")

    def seen(user):
        return [t["id"] for t in client.get("/api/tickets", headers=bearer(user)).json()["items"]]

    assert seen(admin) == [vpn.pk, printer.pk]
    assert seen(specialist) == [vpn.pk]
    assert seen(bot) == [vpn.pk]
    assert seen(no_department) == []
    # A ticket outside the caller's view is "not found", like a missing one.
    assert client.get(f"/api/tickets/{printer.pk}", headers=bearer(specialist)).status_code == 404
    assert client.get(f"/api/tickets/{vpn.pk}", headers=bearer(specialist)).json()["id"] == vpn.pk


def test_ticket_filters_and_pages(client):
    admin = make_user("admin", "Admin")
    first = create_ticket(VPN).tickets.get()
    create_ticket(PRINTER)
    create_ticket("VPN снова отваливается")
    Ticket.objects.filter(pk=first.pk).update(status=Ticket.Status.DONE)
    headers = bearer(admin)

    def ids(query):
        return client.get(f"/api/tickets?{query}", headers=headers).json()

    assert ids("department=network")["count"] == 2
    assert ids("department=network&status=new")["count"] == 1
    page = ids("limit=1&offset=1")
    assert (page["count"], len(page["items"])) == (3, 1)
    assert client.get("/api/tickets?status=lost", headers=headers).status_code == 422


def test_departments_with_load(client, bot):
    create_ticket(VPN)
    by_id = {d["id"]: d for d in client.get("/api/departments", headers=bearer(bot)).json()}

    network = by_id["network"]
    assert network["open_tickets"] == 1
    assert network["load"] == round(1 / network["capacity"], 3)
    assert by_id["hardware"]["open_tickets"] == 0
    assert sum(d["fallback"] for d in by_id.values()) == 1


def test_browser_session_works(client):
    client.force_login(make_user("admin", "Admin"))
    assert client.get("/api/departments").status_code == 200


def test_create_api_token_command(client, bot, capsys):
    call_command("create_api_token", "bot", "--name", "curl")
    key = capsys.readouterr().out.strip()

    assert key.startswith("mk1_")
    assert ApiToken.objects.get().name == "curl"
    assert ApiToken.objects.get().key_hash != key  # only the hash is stored
    response = client.get("/api/departments", headers={"authorization": f"Bearer {key}"})
    assert response.status_code == 200
