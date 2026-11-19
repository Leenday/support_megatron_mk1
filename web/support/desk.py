"""The specialist's dashboard (#18): queue, "My tickets", ticket page and its actions.

Specialists see their department's tickets and admins all of them (`visible_tickets`, the
same rules as the API). The actions themselves are in `support.workflow`; these views only
check who may see the ticket, call the action and show the outcome.
"""

from collections.abc import Callable
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.utils.translation import get_language, gettext_lazy
from django.utils.translation import gettext as _

from support import workflow
from support.forms import CloseForm, DeskFilterForm, ReturnForm, TicketEditForm
from support.models import Department, System, Ticket, TicketEvent, User
from support.services import visible_tickets

LISTS = {
    "queue": gettext_lazy("Queue"),
    "mine": gettext_lazy("My tickets"),
    "all": gettext_lazy("All tickets"),
}
ROWS = 200  # a page this long is enough for one department; filters narrow it down


def staff(request: HttpRequest) -> User:
    """The logged-in specialist or admin; anyone else gets 403."""
    user = request.user
    if isinstance(user, User) and (
        user.is_superuser or user.has_role("Specialist") or user.has_role("Admin")
    ):
        return user
    raise PermissionDenied


def staff_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @login_required
    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        staff(request)
        return view(request, *args, **kwargs)

    return wrapper


def language() -> str:
    return get_language() or settings.LANGUAGE_CODE


def department_names() -> dict[str, str]:
    lang = language()
    return {d.id: d.name(lang) for d in Department.objects.all()}


def find_ticket(user: User, pk: int) -> Ticket:
    """A ticket the user may see: of the visible ones, or assigned to the user."""
    found = (
        visible_tickets(user).filter(pk=pk).first()
        or Ticket.objects.select_related("department", "assignee", "request")
        .filter(pk=pk, assignee=user)
        .first()
    )
    if found is None:
        raise Http404
    return found


@staff_only
def queue(request: HttpRequest) -> HttpResponse:
    user = staff(request)
    current = request.GET.get("list", "queue")
    if current not in LISTS:
        current = "queue"
    visible = visible_tickets(user)
    queue_tickets = visible.filter(status=Ticket.Status.NEW)
    mine = Ticket.objects.select_related("department", "assignee").filter(assignee=user)
    tickets = {"queue": queue_tickets, "mine": mine, "all": visible}[current]

    form = DeskFilterForm(request.GET)
    tag = system = ""
    if form.is_valid():
        if form.cleaned_data["status"] and current != "queue":
            tickets = tickets.filter(status=form.cleaned_data["status"])
        if form.cleaned_data["since"]:
            tickets = tickets.filter(created_at__date__gte=form.cleaned_data["since"])
        if form.cleaned_data["until"]:
            tickets = tickets.filter(created_at__date__lte=form.cleaned_data["until"])
        tag = form.cleaned_data["tag"].strip().lower()
        system = form.cleaned_data["system"]
    if current == "mine":
        # Open tickets first: they are the specialist's work; done ones are history.
        tickets = tickets.order_by(F("closed_at").asc(nulls_first=True), "created_at")
    if tag or system:
        # In Python rather than SQL: JSON containment is not portable to SQLite (the tests).
        rows = [
            t
            for t in tickets
            if (not tag or tag in (x.lower() for x in t.tags))
            and (not system or system in t.systems)
        ]
    else:
        rows = list(tickets[: ROWS + 1])  # one more than shown tells whether there are more
    names = department_names()
    counts = {"queue": queue_tickets.count(), "mine": mine.filter(status__in=Ticket.OPEN).count()}
    context = {
        "lists": [(key, label, counts.get(key)) for key, label in LISTS.items()],
        "current": current,
        "form": form,
        "rows": [(t, names[t.department_id]) for t in rows[:ROWS]],
        "more": len(rows) > ROWS,
        "is_specialist": user.has_role("Specialist"),
        "department": names.get(user.department_id or "", ""),
    }
    return render(request, "support/desk_queue.html", context)


def describe(event: TicketEvent, names: dict[str, str]) -> str:
    """One line of the ticket's history, in the interface language."""
    data = event.data
    match event.kind:
        case TicketEvent.Kind.CREATED:
            return _("Created and routed to “%(department)s”") % {
                "department": names.get(data.get("department", ""), data.get("department"))
            }
        case TicketEvent.Kind.TAKEN:
            return _("Taken in progress")
        case TicketEvent.Kind.EDITED:
            labels = [
                str(field.verbose_name)
                for field in Ticket._meta.concrete_fields
                if field.attname in data
            ]
            return _("Edited: %(fields)s") % {"fields": ", ".join(labels)}
        case TicketEvent.Kind.RETURNED:
            return _("Returned from “%(from)s” to “%(to)s”: %(reason)s") % {
                "from": names.get(data["from"], data["from"]),
                "to": names.get(data["to"], data["to"]),
                "reason": data.get("reason", ""),
            }
        case TicketEvent.Kind.REASSIGNED:
            if data["from"] == data["to"]:
                return _("Assignee changed")
            return _("Reassigned from “%(from)s” to “%(to)s”") % {
                "from": names.get(data["from"], data["from"]),
                "to": names.get(data["to"], data["to"]),
            }
        case TicketEvent.Kind.STATUS_CHANGED if "department_correct" in data:
            if data.get("department_correct"):
                return _("Done; the department was right")
            return _("Done; it should have gone to “%(department)s”") % {
                "department": names.get(data.get("correct_department") or "", "?")
            }
    return event.get_kind_display()


def show_ticket(request: HttpRequest, ticket: Ticket, **forms) -> HttpResponse:
    user = staff(request)
    names = department_names()
    system_names = dict(System.objects.values_list("id", "name"))
    own = ticket.status == Ticket.Status.IN_PROGRESS and ticket.assignee_id == user.pk
    can_return = ticket.status == Ticket.Status.NEW or own
    next_department = workflow.next_department(ticket) if can_return else None
    context = {
        "ticket": ticket,
        "department": names[ticket.department_id],
        "candidates": [names.get(c, c) for c in ticket.candidates],
        "systems": [system_names.get(x, x) for x in ticket.systems],
        "saved": ticket.request,
        "events": [(e, describe(e, names)) for e in ticket.events.select_related("actor")],
        "can_take": ticket.status == Ticket.Status.NEW,
        "own": own,
        "edit_form": forms.get("edit_form")
        or TicketEditForm(initial={f: getattr(ticket, f) for f in workflow.EDITABLE}),
        "return_form": forms.get("return_form") or ReturnForm(),
        "next_department": names.get(next_department or "") if can_return else None,
        "can_return": can_return,
        "close_form": forms.get("close_form")
        or CloseForm(language=language(), exclude=ticket.department_id),
    }
    return render(request, "support/desk_ticket.html", context, status=400 if forms else 200)


@staff_only
def ticket_page(request: HttpRequest, pk: int) -> HttpResponse:
    return show_ticket(request, find_ticket(staff(request), pk))


@staff_only
def act(request: HttpRequest, pk: int, action: str) -> HttpResponse:
    """POST /desk/tickets/<pk>/<action>/: take, edit, return or close."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user = staff(request)
    ticket = find_ticket(user, pk)
    try:
        match action:
            case "take":
                workflow.take(pk, user)
                messages.success(request, _("The ticket is yours now."))
            case "edit":
                form = TicketEditForm(request.POST)
                if not form.is_valid():
                    return show_ticket(request, ticket, edit_form=form)
                workflow.edit(pk, user, form.cleaned_data)
                messages.success(request, _("Changes saved."))
            case "return":
                form = ReturnForm(request.POST)
                if not form.is_valid():
                    return show_ticket(request, ticket, return_form=form)
                returned = workflow.return_ticket(pk, user, form.cleaned_data["reason"])
                messages.success(
                    request,
                    _("Returned to “%(department)s”.")
                    % {"department": returned.department.name(language())},
                )
                return redirect("desk")
            case "close":
                form = CloseForm(request.POST, language=language(), exclude=ticket.department_id)
                if not form.is_valid():
                    return show_ticket(request, ticket, close_form=form)
                right = form.cleaned_data["correct"] == "yes"
                department = None if right else form.cleaned_data["department"].pk
                workflow.close(pk, user, correct_department=department)
                messages.success(request, _("The ticket is done."))
            case _:
                raise Http404
    except workflow.ActionRefused as e:
        messages.error(request, str(e))
    return redirect("desk_ticket", pk=pk)
