"""The vocabulary grown from specialists' answers and the validator's review (#57)."""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from megatron.departments import load_departments
from megatron.llm import FakeExtractor
from support import vocabulary, workflow
from support.models import (
    Proposal,
    Request,
    RoutingSettings,
    System,
    Ticket,
    TicketEvent,
    User,
)
from support.services import create_ticket, import_departments

pytestmark = pytest.mark.django_db

RU = {"accept-language": "ru"}
# "Битрикс" is in no system's spellings: the fake model finds no system in it.
TEXT = "Не открывается Битрикс24, CRM не грузит сделки"


@pytest.fixture(autouse=True)
def departments(departments_path):
    import_departments(load_departments(departments_path))


def make_user(username, role="Specialist", department="software"):
    user = User.objects.create_user(username, password="unused-in-tests", department_id=department)
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def ivan():
    return make_user("ivan")


@pytest.fixture
def petr():
    return make_user("petr")


@pytest.fixture
def vera():
    return make_user("vera", role="Validator", department=None)


def taken(user, text="Не открывается Битрикс24", where="Битрикс24"):
    """A ticket of the user's department made by the fake model, taken by the user."""
    request = create_ticket(text, extractor_factory=FakeExtractor)
    ticket = request.tickets.get()
    Ticket.objects.filter(pk=ticket.pk).update(department_id=user.department_id, where=where)
    return workflow.take(ticket.pk, user)


def systems_of(text):
    return create_ticket(text, extractor_factory=FakeExtractor).tickets.get().systems


def test_spelling_proposed_on_closing_approved_and_used_by_the_next_request(ivan, vera):
    assert systems_of("Битрикс24 не грузит сделки") == []
    before = Request.objects.latest("pk").vocabulary_version

    ticket = taken(ivan)
    workflow.close(ticket.pk, ivan, systems=[], proposal=("Битрикс24", "crm"))
    proposal = Proposal.objects.get(kind=Proposal.Kind.SPELLING)
    assert (proposal.status, proposal.system_id, proposal.proposed_by) == ("pending", "crm", ivan)
    closing = ticket.events.get(kind=TicketEvent.Kind.STATUS_CHANGED)
    assert closing.data["systems_confirmed"] is False  # something was missing
    assert closing.data["proposal"] == "Битрикс24"

    vocabulary.approve(proposal.pk, vera)
    assert "Битрикс24" in System.objects.get(pk="crm").spellings
    proposal.refresh_from_db()
    assert (proposal.status, proposal.reviewed_by) == ("approved", vera)

    assert systems_of("Битрикс24 не грузит сделки") == ["crm"]  # no restart, no training
    assert Request.objects.latest("pk").vocabulary_version != before


def test_new_system_gets_the_validators_id_and_name(ivan, vera):
    ticket = taken(ivan, text="Не работает Jira", where="Jira")
    workflow.close(ticket.pk, ivan, proposal=("Jira", None))
    proposal = Proposal.objects.get(kind=Proposal.Kind.NEW_SYSTEM)

    with pytest.raises(workflow.ActionRefused, match="Идентификатор"):
        vocabulary.approve(proposal.pk, vera, system_id="Jira!")
    with pytest.raises(workflow.ActionRefused, match="уже есть"):
        vocabulary.approve(proposal.pk, vera, system_id="crm")
    system = vocabulary.approve(proposal.pk, vera, system_id="tracker", name="Jira")

    assert (system.id, system.name, system.spellings) == ("tracker", "Jira", ["Jira"])
    assert systems_of("Jira снова не открывается") == ["tracker"]


def test_nobody_approves_their_own_proposal(ivan, vera):
    admin = make_user("boss", role="Admin")
    ticket = taken(admin)
    workflow.close(ticket.pk, admin, proposal=("Битрикс24", "crm"))
    proposal = Proposal.objects.get()

    with pytest.raises(workflow.ActionRefused, match="Своё"):
        vocabulary.approve(proposal.pk, admin)
    with pytest.raises(workflow.ActionRefused, match="только валидатор"):
        vocabulary.approve(proposal.pk, ivan)  # a specialist is not a reviewer
    assert Proposal.objects.get().status == Proposal.Status.PENDING
    vocabulary.approve(proposal.pk, vera)


def test_similar_proposals_group_and_rejected_ones_are_not_asked_again(ivan, petr, vera):
    for user, text in ((ivan, "Битрикс24"), (petr, "«битрикс24»"), (ivan, "Битрикс24")):
        ticket = taken(user)
        workflow.close(ticket.pk, user, proposal=(text, "crm"))
    [group] = vocabulary.vocabulary_groups()
    assert len(group.proposals) == 3
    assert group.specialists == ["ivan", "petr"]
    assert group.texts[0] == "Битрикс24"

    vocabulary.reject(group.first.pk, vera, "это не CRM, а портал")
    assert not vocabulary.vocabulary_groups()
    assert Proposal.objects.filter(status=Proposal.Status.REJECTED).count() == 3

    ticket = taken(petr)
    workflow.close(ticket.pk, petr, proposal=("битрикс24", "crm"))
    again = Proposal.objects.latest("pk")
    assert (again.status, again.comment) == ("rejected", "это не CRM, а портал")
    assert not vocabulary.vocabulary_groups()


def test_spelling_approved_automatically_by_enough_specialists(ivan, petr):
    settings = RoutingSettings.load()
    settings.spelling_auto_approve = 2
    settings.save()
    workflow.close(taken(ivan).pk, ivan, proposal=("Битрикс24", "crm"))
    assert "Битрикс24" not in System.objects.get(pk="crm").spellings  # one specialist
    workflow.close(taken(petr).pk, petr, proposal=("битрикс24", "crm"))

    assert "Битрикс24" in System.objects.get(pk="crm").spellings
    assert set(Proposal.objects.values_list("status", "reviewed_by")) == {("approved", None)}
    # A new system is never approved automatically.
    workflow.close(taken(ivan, where="Jira").pk, ivan, proposal=("Jira", None))
    workflow.close(taken(petr, where="Jira").pk, petr, proposal=("Jira", None))
    assert not System.objects.filter(name="Jira").exists()


def test_validator_confirms_or_reverts_an_edit_and_history_keeps_both(ivan, vera):
    first, second = taken(ivan), taken(ivan)
    workflow.edit(first.pk, ivan, {"when": "с утра"})
    workflow.edit(second.pk, ivan, {"when": "вчера", "summary": "Битрикс24 не открывается"})
    confirm, revert = Proposal.objects.filter(kind=Proposal.Kind.FIELD_EDIT).order_by("pk")
    assert revert.changes["when"] == [None, "вчера"]

    vocabulary.review_edit(confirm.pk, vera, confirm=True)
    with pytest.raises(workflow.ActionRefused, match="почему"):
        vocabulary.review_edit(revert.pk, vera, confirm=False)
    vocabulary.review_edit(revert.pk, vera, confirm=False, comment="в тексте нет даты")

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.when == "с утра"
    assert second.when is None
    assert second.summary == "Не открывается Битрикс24"
    kinds = list(second.events.values_list("kind", flat=True))
    assert kinds[-2:] == [TicketEvent.Kind.EDITED, TicketEvent.Kind.REVIEWED]
    review = second.events.get(kind=TicketEvent.Kind.REVIEWED)
    assert review.actor == vera
    assert review.data["reverted"]["when"] == ["вчера", None]
    assert review.data["comment"] == "в тексте нет даты"
    assert second.events.get(kind=TicketEvent.Kind.EDITED).data["when"] == [None, "вчера"]
    own = Proposal.objects.create(
        kind=Proposal.Kind.FIELD_EDIT, ticket=first, proposed_by=vera, changes={"when": [1, 2]}
    )
    with pytest.raises(workflow.ActionRefused, match="Своё"):
        vocabulary.review_edit(own.pk, vera, confirm=True)


def test_closing_form_confirms_systems_and_proposes_in_one_submit(client, ivan):
    ticket = taken(ivan, text="Не открывается CRM", where="CRM")
    assert ticket.systems == ["crm"]
    client.force_login(ivan)
    page = client.get(reverse("desk_ticket", kwargs={"pk": ticket.pk}), headers=RU)
    assert "Системы" in page.content.decode()
    url = reverse("desk_action", kwargs={"pk": ticket.pk, "action": "close"})

    # Proposing a spelling without choosing the system is refused, nothing is closed.
    form = {"correct": "yes", "systems_shown": "True", "systems": ["crm", "vpn"]}
    response = client.post(url, form | {"proposal": "spelling", "proposal_text": "црмка"})
    assert response.status_code == 400
    client.post(
        url, form | {"proposal": "spelling", "proposal_text": "црмка", "proposal_system": "crm"}
    )

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.DONE
    assert ticket.systems == ["crm", "vpn"]
    event = ticket.events.get(kind=TicketEvent.Kind.STATUS_CHANGED)
    assert event.data["systems"] == [["crm"], ["crm", "vpn"]]
    assert Proposal.objects.get().text == "црмка"


def test_closing_without_the_systems_keeps_the_models(ivan):
    ticket = taken(ivan, text="Не открывается CRM", where="CRM")
    workflow.close(ticket.pk, ivan)
    ticket.refresh_from_db()
    assert ticket.systems == ["crm"]
    assert ticket.events.get(kind=TicketEvent.Kind.STATUS_CHANGED).data["systems_confirmed"]


def test_review_page_for_validators_and_admins_only(client, ivan, vera):
    workflow.close(taken(ivan).pk, ivan, systems=[], proposal=("Битрикс24", "crm"))
    workflow.close(taken(ivan, text="Не открывается CRM", where="CRM").pk, ivan)
    client.force_login(ivan)
    assert client.get(reverse("desk_review")).status_code == 403
    client.force_login(vera)
    page = client.get(reverse("desk_review"), headers=RU).content.decode()
    assert "Битрикс24" in page
    assert "Системы подтверждены по неделям" in page
    assert "1 (50 %)" in page  # of two closed tickets, one kept the model's systems
    [group] = vocabulary.vocabulary_groups()
    url = reverse("desk_review_action", kwargs={"pk": group.first.pk, "action": "approve"})
    assert client.post(url).status_code == 302
    assert "Битрикс24" in System.objects.get(pk="crm").spellings
    # A validator reviews but does not work tickets.
    other = taken(ivan)
    assert (
        client.post(reverse("desk_action", kwargs={"pk": other.pk, "action": "return"})).status_code
        == 403
    )
    admin = make_user("boss", role="Admin", department=None)
    client.force_login(admin)
    assert client.get(reverse("desk_review")).status_code == 200


def test_spot_check_by_specialist(ivan, petr, vera):
    workflow.close(taken(ivan, text="Не открывается CRM", where="CRM").pk, ivan)
    workflow.close(taken(ivan, text="Не открывается CRM", where="CRM").pk, ivan)
    edited = taken(petr, text="Не открывается CRM", where="CRM")
    workflow.edit(edited.pk, petr, {"when": "вчера"})
    workflow.close(edited.pk, petr)
    vocabulary.review_edit(Proposal.objects.get().pk, vera, confirm=False, comment="нет даты")

    rows = {r.name: r for r in vocabulary.by_specialist()}
    assert (rows["ivan"].closed, rows["ivan"].untouched_share) == (2, 1.0)
    assert (rows["petr"].closed, rows["petr"].untouched, rows["petr"].confirmed_share) == (1, 0, 0)
