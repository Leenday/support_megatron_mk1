"""A department correction at closing goes to a validator before it becomes a label (#67)."""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from megatron.departments import load_departments
from megatron.llm import FakeExtractor
from support import services, vocabulary, workflow
from support.desk import describe
from support.models import Department, Proposal, Ticket, TicketEvent, User
from support.services import create_ticket, import_departments

pytestmark = pytest.mark.django_db

RU = {"accept-language": "ru"}
TEXT = "Не открывается CRM"


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
def vera():
    return make_user("vera", role="Validator", department=None)


def closed(user, correct_department=None, text=TEXT):
    """A ticket of the user's department, taken and closed with the given answer."""
    ticket = create_ticket(text, extractor_factory=FakeExtractor).tickets.get()
    Ticket.objects.filter(pk=ticket.pk).update(department_id=user.department_id)
    workflow.take(ticket.pk, user)
    return workflow.close(ticket.pk, user, correct_department=correct_department)


def test_a_correction_waits_for_the_validator_and_is_not_history_yet(ivan):
    right = closed(ivan, text="CRM не грузит сделки")
    wrong = closed(ivan, correct_department="network")

    proposal = Proposal.objects.get()
    assert (proposal.kind, proposal.status) == (Proposal.Kind.DEPARTMENT, Proposal.Status.PENDING)
    assert (proposal.ticket, proposal.proposed_by) == (wrong, ivan)
    assert proposal.changes == {"department_id": ["software", "network"]}
    assert services.confirmed_history() == [(right.request.text, "software")]
    # The answer "yes", or the same department again, proposes nothing.
    closed(ivan, correct_department="software")
    assert Proposal.objects.count() == 1


def test_confirmed_correction_joins_the_history_with_the_new_department(ivan, vera):
    ticket = closed(ivan, correct_department="network")
    vocabulary.review_edit(Proposal.objects.get().pk, vera, confirm=True)

    assert services.confirmed_history() == [(TEXT, "network")]
    ticket.refresh_from_db()
    assert ticket.department_id == "software"  # the closed ticket itself does not move
    event = ticket.events.get(kind=TicketEvent.Kind.REVIEWED)
    assert describe(event, {"network": "Сеть"}).startswith(
        "Валидатор подтвердил исправление отдела на «Сеть»"
    )
    # A department switched off later no longer gives labels.
    Department.objects.filter(pk="network").update(active=False)
    assert services.confirmed_history() == []


def test_rejected_correction_is_never_history_and_is_measured(ivan, vera):
    closed(ivan, correct_department="network")
    closed(ivan, correct_department="hardware")
    first, second = Proposal.objects.order_by("pk")
    with pytest.raises(workflow.ActionRefused):
        vocabulary.review_edit(first.pk, vera, confirm=False)
    vocabulary.review_edit(first.pk, vera, confirm=False, comment="это была CRM")

    assert services.confirmed_history() == []
    measures = services.routing_measures()
    assert (measures.corrections_reviewed, measures.corrections_rejected) == (1, 1)
    vocabulary.review_edit(second.pk, vera, confirm=True)
    measures = services.routing_measures()
    assert (measures.corrections_reviewed, measures.rejected_share) == (2, 0.5)
    assert services.confirmed_history() == [(TEXT, "hardware")]


def test_nobody_reviews_their_own_correction(ivan):
    admin = make_user("boss", role="Admin", department="software")
    closed(admin, correct_department="network")
    with pytest.raises(workflow.ActionRefused):
        vocabulary.review_edit(Proposal.objects.get().pk, admin, confirm=True)
    with pytest.raises(workflow.ActionRefused):
        vocabulary.review_edit(Proposal.objects.get().pk, ivan, confirm=True)


def test_review_page_shows_and_decides_a_correction(client, ivan, vera):
    closed(ivan, correct_department="network")
    client.force_login(vera)
    page = client.get(reverse("desk_review"), headers=RU).content.decode()
    software = Department.objects.get(pk="software").name("ru")
    network = Department.objects.get(pk="network").name("ru")
    assert f"{software} → {network}" in page
    assert "Отклонить" in page
    assert "Исправления отдела, отклонённые валидатором" in page

    url = reverse("desk_review_action", kwargs={"pk": Proposal.objects.get().pk, "action": "edit"})
    response = client.post(
        url, {"decision": "revert", "comment": "это CRM"}, headers=RU, follow=True
    )
    assert "Исправление отклонено." in response.content.decode()
    assert Proposal.objects.get().status == Proposal.Status.REJECTED
    page = client.get(reverse("desk_review"), headers=RU).content.decode()
    assert "100 % (1 / 1)" in page
