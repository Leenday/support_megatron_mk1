"""What a specialist does with a ticket (#18): take, edit, return, close.

Every action locks the ticket's row (`select_for_update`) and checks its state inside the
transaction, so two specialists pressing "Take" at once cannot both get it: the second one
waits for the lock, then sees the ticket already in progress. Every action is recorded as a
`TicketEvent`; the events are the ticket's history on its page and the data for the accuracy
in operation (#16) and the triage time (#43).
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from support.models import Department, Ticket, TicketEvent, User

EDITABLE = ("who", "where", "when", "what", "summary", "tags")


class ActionRefused(Exception):
    """The ticket's state does not allow the action; the message is shown to the user."""


def locked(ticket_id: int) -> Ticket:
    return Ticket.objects.select_for_update().get(pk=ticket_id)


def require_own(ticket: Ticket, user: User) -> None:
    if ticket.status != Ticket.Status.IN_PROGRESS or ticket.assignee_id != user.pk:
        raise ActionRefused(_("Only the specialist working on the ticket can do this."))


@transaction.atomic
def take(ticket_id: int, user: User) -> Ticket:
    ticket = locked(ticket_id)
    if ticket.status != Ticket.Status.NEW:
        raise ActionRefused(_("The ticket is already taken."))
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.assignee = user
    ticket.taken_at = timezone.now()
    ticket.save(update_fields=["status", "assignee", "taken_at"])
    TicketEvent.objects.create(ticket=ticket, kind=TicketEvent.Kind.TAKEN, actor=user)
    return ticket


@transaction.atomic
def edit(ticket_id: int, user: User, values: dict) -> Ticket:
    """Change the extracted fields of one's own ticket; the event keeps the old and new values."""
    ticket = locked(ticket_id)
    require_own(ticket, user)
    changes = {
        field: [getattr(ticket, field), values[field]]
        for field in EDITABLE
        if field in values and values[field] != getattr(ticket, field)
    }
    if changes:
        for field, (_old, new) in changes.items():
            setattr(ticket, field, new)
        ticket.save(update_fields=list(changes))
        TicketEvent.objects.create(
            ticket=ticket, kind=TicketEvent.Kind.EDITED, actor=user, data=changes
        )
    return ticket


def next_department(ticket: Ticket) -> str | None:
    """Where "Return" sends the ticket: the model's best untried candidate, else the fallback.

    "Untried" = the ticket has not been in that department yet, so a ticket routed to its
    second candidate because the first was busy goes back to the first, and a ticket is never
    bounced between two departments. None when even the fallback has had it.
    """
    tried = {ticket.department_id} | {
        e.data.get("from") for e in ticket.events.filter(kind=TicketEvent.Kind.RETURNED)
    }
    active = set(Department.objects.filter(active=True).values_list("id", flat=True))
    for candidate in ticket.candidates:
        if candidate in active and candidate not in tried:
            return candidate
    fallback = Department.objects.filter(fallback=True, active=True).first()
    if fallback is not None and fallback.id not in tried:
        return fallback.id
    return None


@transaction.atomic
def return_ticket(ticket_id: int, user: User, reason: str) -> Ticket:
    """Send the ticket to the next department as New; it counts as "wrong department"."""
    ticket = locked(ticket_id)
    if ticket.status == Ticket.Status.DONE:
        raise ActionRefused(_("A done ticket cannot be returned."))
    if ticket.status == Ticket.Status.IN_PROGRESS:
        require_own(ticket, user)
    to = next_department(ticket)
    if to is None:
        raise ActionRefused(
            _("There is no other department to return the ticket to; ask an admin.")
        )
    TicketEvent.objects.create(
        ticket=ticket,
        kind=TicketEvent.Kind.RETURNED,
        actor=user,
        data={"from": ticket.department_id, "to": to, "reason": reason},
    )
    ticket.department_id = to
    ticket.status = Ticket.Status.NEW
    ticket.assignee = None
    ticket.taken_at = None
    ticket.save(update_fields=["department", "status", "assignee", "taken_at"])
    return ticket


@transaction.atomic
def close(ticket_id: int, user: User, correct_department: str | None = None) -> Ticket:
    """Mark the ticket done, with the specialist's answer to "Was the department right?".

    `correct_department` None means "yes"; otherwise it is the department that should have
    got the ticket. The answer is quality monitoring, not training data (#18, #16).
    """
    ticket = locked(ticket_id)
    require_own(ticket, user)
    if correct_department == ticket.department_id:
        correct_department = None
    if (
        correct_department is not None
        and not Department.objects.filter(pk=correct_department).exists()
    ):
        raise ActionRefused(_("Unknown department."))
    ticket.status = Ticket.Status.DONE
    ticket.closed_at = timezone.now()
    ticket.save(update_fields=["status", "closed_at"])
    TicketEvent.objects.create(
        ticket=ticket,
        kind=TicketEvent.Kind.STATUS_CHANGED,
        actor=user,
        data={
            "from": Ticket.Status.IN_PROGRESS.value,
            "to": Ticket.Status.DONE.value,
            "department_correct": correct_department is None,
            "correct_department": correct_department,
        },
    )
    return ticket
