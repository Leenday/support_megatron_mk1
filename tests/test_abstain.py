"""Abstaining from routing when the model and the confirmed history disagree (#73)."""

import json

import pytest
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.urls import reverse

from megatron.classifier import DepartmentClassifier
from megatron.departments import load_departments
from megatron.llm import FakeExtractor
from support import services, workflow
from support.models import HistoryTicket, RoutingSettings, TicketEvent, User
from support.services import create_ticket, import_departments

pytestmark = pytest.mark.django_db

PRINTER = [
    "The printer is broken, paper jam",
    "Printer prints blank pages",
    "Printer in room 5 does not print",
    "The office printer shows an error",
]
VPN = [
    "VPN does not connect from home",
    "VPN connection drops every hour",
    "Cannot reach the VPN server",
    "VPN asks for the password again and again",
]


@pytest.fixture(autouse=True)
def departments(departments_path):
    import_departments(load_departments(departments_path))
    services._trained = None  # the cache must not leak from another test
    settings = RoutingSettings.load()
    settings.abstain_min_history = 8
    settings.save()


def history(printer="hardware", vpn="network"):
    HistoryTicket.objects.bulk_create(
        [HistoryTicket(text=t, department_id=printer) for t in PRINTER]
        + [HistoryTicket(text=t, department_id=vpn) for t in VPN]
    )


def ticket_of(text):
    return create_ticket(text, extractor_factory=FakeExtractor).tickets.get()


def check_of(ticket):
    return ticket.events.get(kind=TicketEvent.Kind.CREATED).data.get("check")


def test_classifier_predicts_a_department_with_its_probability():
    classifier = DepartmentClassifier(PRINTER + VPN, ["hardware"] * 4 + ["network"] * 4)
    department, probability = classifier.predict("printer jams the paper")
    assert department == "hardware" and 0.5 < probability <= 1
    with pytest.raises(ValueError):
        DepartmentClassifier(PRINTER, ["hardware"] * 4)


def test_without_enough_history_the_model_routes_alone():
    HistoryTicket.objects.create(text=PRINTER[0], department_id="network")
    ticket = ticket_of("The printer is broken again")
    assert ticket.department_id == "hardware"
    assert check_of(ticket) is None
    assert "examples" not in ticket.events.get(kind=TicketEvent.Kind.CREATED).data
    assert not ticket.request.prompt_version.endswith("+examples")


def test_agreement_routes_as_before():
    history()
    ticket = ticket_of("The printer is broken again")
    assert ticket.department_id == "hardware"
    assert check_of(ticket) | {"probability": 0} == {
        "history": "hardware",
        "probability": 0,
        "agree": True,
    }


def test_disagreement_sends_the_ticket_to_triage():
    history(printer="network", vpn="hardware")  # the history routes printers elsewhere
    ticket = ticket_of("The printer is broken again")
    assert ticket.department_id == "general"  # the fallback, where a person triages
    assert ticket.candidates == ["hardware"]  # the model's answer is kept for the triage
    check = check_of(ticket)
    assert (check["history"], check["agree"], check["abstained"]) == ("network", False, True)


def test_the_history_gives_the_model_examples_and_the_ticket_lists_them():
    history()
    ticket = ticket_of("The printer is broken again")
    examples = ticket.events.get(kind=TicketEvent.Kind.CREATED).data["examples"]
    assert len(examples) == 5 and examples[0][1] == "hardware"
    assert ticket.request.prompt_version.endswith("+examples")


def test_abstaining_can_be_switched_off():
    history(printer="network", vpn="hardware")
    settings = RoutingSettings.load()
    settings.abstain_min_history = 0
    settings.save()
    assert ticket_of("The printer is broken again").department_id == "hardware"


def make_user(username, role="Specialist", department="hardware"):
    user = User.objects.create_user(username, password="unused-in-tests", department_id=department)
    user.groups.add(Group.objects.get(name=role))
    return user


def test_only_confirmed_closed_tickets_join_the_history():
    ivan = make_user("ivan")
    right = ticket_of("The printer is broken again")
    workflow.take(right.pk, ivan)
    workflow.close(right.pk, ivan)
    wrong = ticket_of("Printer prints blank pages again")
    workflow.take(wrong.pk, ivan)
    workflow.close(wrong.pk, ivan, correct_department="software")
    # A correction is not trusted until a validator confirms it (#67).
    assert services.confirmed_history() == [("The printer is broken again", "hardware")]


def test_measures_count_triage_wrong_routes_and_returns():
    history(printer="network", vpn="hardware")
    ivan = make_user("ivan", department="network")
    triaged = ticket_of("The printer is broken again")  # disagreement: to triage
    routed = ticket_of("VPN does not connect from the office")  # disagreement too
    services._trained = None
    HistoryTicket.objects.all().delete()
    history()
    agreed = ticket_of("VPN connection drops again")  # agreement: routed to network
    workflow.take(agreed.pk, ivan)
    workflow.close(agreed.pk, ivan, correct_department="software")
    workflow.return_ticket(routed.pk, make_user("anna", department="general"), "not ours")

    measures = services.routing_measures()
    assert (measures.tickets, measures.abstained) == (3, 2)
    assert (measures.closed_routed, measures.wrong_routed) == (1, 1)
    assert measures.reassigned == 1
    assert measures.routed_share == pytest.approx(1 / 3)
    assert triaged.department_id == "general"


def test_import_history_command(tmp_path):
    path = tmp_path / "history.jsonl"
    rows = [{"text": t, "expected": "hardware"} for t in PRINTER]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    call_command("import_history", str(path))
    call_command("import_history", str(path), "--replace")
    assert HistoryTicket.objects.count() == 4

    path.write_text(json.dumps({"text": "x", "expected": "nowhere"}), encoding="utf-8")
    with pytest.raises(CommandError, match="nowhere"):
        call_command("import_history", str(path))


def test_ticket_page_explains_the_triage_and_the_review_page_shows_measures(client):
    history(printer="network", vpn="hardware")
    ticket = ticket_of("The printer is broken again")
    anna = make_user("anna", department="general")
    client.force_login(anna)
    page = client.get(reverse("desk_ticket", args=[ticket.pk]), headers={"accept-language": "en"})
    text = page.content.decode()
    assert "the history of solved tickets “Network and communications”" in text
    assert "for triage: the model and the history disagreed" in text
    assert "Similar solved tickets shown to the model" in text

    client.force_login(make_user("vera", role="Validator", department=None))
    review = client.get(reverse("desk_review"), headers={"accept-language": "en"}).content.decode()
    assert "Routed automatically" in review and "0 % (1 sent to triage)" in review
