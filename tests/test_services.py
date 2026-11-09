"""The web service's pipeline and department import/export (web/support, #15)."""

import json
from typing import Any

import pytest
import yaml
from django.contrib.auth.models import Group
from django.core.checks import run_checks
from django.core.management import call_command
from django.test import override_settings

from megatron.departments import DepartmentsConfig, load_departments
from megatron.llm import Extractor, FakeExtractor, Messages
from support.models import ROLES, Department, Request, RoutingSettings, Ticket, TicketEvent
from support.services import (
    create_ticket,
    departments_config,
    export_departments,
    import_departments,
)

pytestmark = pytest.mark.django_db

ANSWER = {
    "who": "Петров",
    "where": "сетевая папка",
    "when": None,
    "what": "Не открывается сетевая папка",
    "identifiers": [],
    "summary": "Не открывается сетевая папка",
    "tags": ["сеть", "папка"],
    "candidates": ["network", "software"],
    "language": "ru",
}


class FixedExtractor(Extractor):
    """Gives the same answer to every request, like a model that is sure."""

    def __init__(self, config: DepartmentsConfig, answer: str) -> None:
        super().__init__(config, "fixed", "test", max_retries=2)
        self.answer = answer
        self.calls = 0

    def complete(self, messages: Messages, schema: dict[str, Any]) -> str:
        self.calls += 1
        return self.answer


def fixed(answer: dict | str = ANSWER):
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    return lambda config: FixedExtractor(config, text)


@pytest.fixture
def imported(departments_path) -> DepartmentsConfig:
    config = load_departments(departments_path)
    import_departments(config)
    return config


def open_tickets(department_id: str, n: int, status: str = Ticket.Status.NEW) -> None:
    request = Request.objects.create(text="earlier request")
    for _ in range(n):
        Ticket.objects.create(
            request=request,
            what="x",
            summary="x",
            language="ru",
            department_id=department_id,
            status=status,
        )


# --- Departments: YAML <-> database ------------------------------------------------------


def test_import_creates_departments_and_routing(imported):
    assert sorted(Department.objects.values_list("id", flat=True)) == sorted(imported.ids)
    routing = RoutingSettings.load()
    assert routing.rank_match == imported.routing.rank_match
    assert routing.languages == imported.languages
    assert Department.objects.get(fallback=True).id == imported.fallback.id


def test_import_updates_and_deactivates_but_never_deletes(imported):
    data = imported.model_dump()
    data["departments"] = [d for d in data["departments"] if d["id"] != "security"]
    data["departments"][1]["description"] = "New description"
    counts = import_departments(DepartmentsConfig.model_validate(data))

    assert counts == {"created": 0, "updated": len(imported.ids) - 1, "deactivated": 1}
    assert not Department.objects.get(id="security").active
    changed = data["departments"][1]["id"]
    assert Department.objects.get(id=changed).description == "New description"
    assert "security" not in departments_config().ids


def test_import_moves_the_fallback(imported):
    data = imported.model_dump()
    for d in data["departments"]:
        d["fallback"] = d["id"] == "hardware"
    import_departments(DepartmentsConfig.model_validate(data))
    assert list(Department.objects.filter(fallback=True).values_list("id", flat=True)) == [
        "hardware"
    ]


def test_import_command_if_empty_keeps_the_database(departments_path, imported):
    Department.objects.filter(id="network").update(description="Edited in the admin")
    call_command("import_departments", departments_path, if_empty=True)
    assert Department.objects.get(id="network").description == "Edited in the admin"


def test_load_comes_from_open_tickets(imported):
    open_tickets("network", 3)
    open_tickets("network", 1, Ticket.Status.IN_PROGRESS)
    open_tickets("network", 5, Ticket.Status.DONE)
    network = departments_config().get("network")
    assert network.open_tickets == 4
    assert network.capacity
    assert network.load == 4 / network.capacity


def test_no_load_when_a_department_has_no_capacity(imported):
    Department.objects.filter(id="network").update(capacity=None)
    assert not departments_config().has_load


def test_export_round_trip(imported):
    open_tickets("hardware", 2)
    exported = DepartmentsConfig.model_validate(yaml.safe_load(export_departments()))
    assert exported.ids == sorted(imported.ids)
    assert exported.routing == imported.routing
    assert exported.get("hardware").open_tickets == 2
    assert exported.fallback.id == imported.fallback.id


# --- create_ticket ---------------------------------------------------------------------


def test_create_ticket_saves_request_ticket_and_event(imported):
    request = create_ticket(
        "Не открывается сетевая папка. Петров", "petrov@example.com", extractor_factory=fixed()
    )

    assert request.contact == "petrov@example.com"
    assert request.requester is None
    assert (request.model, request.attempts, request.error) == ("fixed", 1, "")
    ticket = request.tickets.get()
    assert ticket.department_id == "network"
    assert ticket.status == Ticket.Status.NEW
    assert ticket.who == "Петров"
    assert ticket.candidates == ["network", "software"]
    event = ticket.events.get()
    assert event.kind == TicketEvent.Kind.CREATED
    assert event.actor is None
    assert set(event.data["scores"]) == {"network", "software"}


def test_busy_department_loses_a_near_tie_to_a_free_one(imported):
    # network is the best fit (match 1.0) but full; software (match 0.6) is free:
    # 0.7 * 1.0 + 0.3 * 0 = 0.70 < 0.7 * 0.6 + 0.3 * 1 = 0.72
    assert create_ticket("folder", extractor_factory=fixed()).tickets.get().department_id == (
        "network"
    )
    open_tickets("network", Department.objects.get(id="network").capacity)
    moved = create_ticket("folder", extractor_factory=fixed()).tickets.get()
    assert moved.department_id == "software"
    assert moved.candidates[0] == "network"


def test_failed_extraction_keeps_the_request(imported):
    request = create_ticket("text", extractor_factory=fixed("not json"))
    assert Request.objects.filter(pk=request.pk).exists()
    assert "no valid ticket after 3 attempts" in request.error
    assert not request.tickets.exists()


def test_inactive_department_is_not_offered(imported):
    Department.objects.filter(id="network").update(active=False)
    with pytest.raises(ValueError, match="network"):
        # The model cannot answer with it: the schema enum no longer has it.
        fixed()(departments_config()).ticket_model.model_validate(ANSWER)


def test_fake_backend_needs_no_model(imported):
    request = create_ticket("Не работает VPN", extractor_factory=FakeExtractor)
    assert request.tickets.get().department_id == "network"


# --- Roles and settings --------------------------------------------------------------------


def test_staff_roles_exist():
    assert set(Group.objects.values_list("name", flat=True)) >= set(ROLES)
    assert "Requester" not in ROLES  # requesters need no account


def test_secret_key_is_required_without_debug():
    from django.conf import settings

    with override_settings(DEBUG=False, SECRET_KEY=settings.DEVELOPMENT_KEY):
        assert "support.E001" in [m.id for m in run_checks()]
    with override_settings(DEBUG=False, SECRET_KEY="x" * 50):
        assert "support.E001" not in [m.id for m in run_checks()]


@pytest.mark.parametrize(("accept", "expected"), [("en-US,en;q=0.9", "Log in"), ("", "Войти")])
def test_interface_follows_the_browser_language(client, accept, expected):
    response = client.get("/admin/login/", headers={"accept-language": accept})
    assert expected in response.content.decode()
