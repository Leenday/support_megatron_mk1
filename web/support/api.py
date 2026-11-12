"""JSON API (#42): the CLI's results over HTTP, documented at /api/docs.

Django Ninja builds the OpenAPI schema from Pydantic models, so the ticket in the responses is
the package's own `RoutedTicket`. Callers are staff or integration accounts: the browser
session works, and scripts send a personal token (`Authorization: Bearer mk1_...`, see
`manage.py create_api_token`). What a caller sees follows `services.visible_tickets`.
"""

from datetime import datetime

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import NinjaAPI, Query, Schema, Status
from ninja.renderers import JSONRenderer
from ninja.security import HttpBearer, django_auth
from pydantic import ConfigDict, Field
from pydantic.config import JsonDict

from megatron.llm import BackendError, ExtractionError
from megatron.ticket import RoutedTicket
from support import services
from support.models import ApiToken, Department, Ticket, User
from support.views import status_url

TEXT = Field(
    min_length=1,
    max_length=5000,
    description="The request in the requester's own words, Russian or English",
    examples=["Не работает VPN с утра, Иванов из бухгалтерии не может подключиться"],
)


class TokenAuth(HttpBearer):
    """`Authorization: Bearer <token>`; the token's user must be active."""

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        found = (
            ApiToken.objects.select_related("user")
            .filter(key_hash=ApiToken.hash(token), user__is_active=True)
            .first()
        )
        if found is None:
            return None
        ApiToken.objects.filter(pk=found.pk).update(last_used_at=timezone.now())
        request.user = found.user
        return found.user


class Utf8Renderer(JSONRenderer):
    """Russian text as is, not as \\uXXXX escapes, so curl output stays readable."""

    json_dumps_params = {"ensure_ascii": False}


api = NinjaAPI(
    title="Megatron-mk1 API",
    version="1",
    description=__doc__ or "",
    auth=[TokenAuth(), django_auth],
    urls_namespace="api",
    renderer=Utf8Renderer(),
)


def caller(request: HttpRequest) -> User:
    """The authenticated user; both auth methods set `request.user` to a `User`."""
    assert isinstance(request.user, User)
    return request.user


class TextIn(Schema):
    text: str = TEXT


class RequestIn(TextIn):
    contact: str = Field(
        "",
        max_length=200,
        description="How to reach the requester: e-mail, phone or messenger",
        examples=["ivanov@example.com"],
    )


class Error(Schema):
    detail: str = Field(examples=["gpt-5.4-mini returned no valid ticket after 3 attempts"])
    request: int | None = Field(
        None, description="Number of the saved request, when the request was saved anyway"
    )


TICKET_EXAMPLE: JsonDict = {
    "id": 17,
    "request": 21,
    "status": "new",
    "assignee": None,
    "created_at": "2026-11-10T09:15:02+03:00",
    "taken_at": None,
    "closed_at": None,
    "who": "Иванов, бухгалтерия",
    "where": "VPN",
    "systems": ["vpn"],
    "when": "с утра",
    "what": "Не удаётся подключиться к VPN",
    "identifiers": [],
    "summary": "Сотрудник бухгалтерии не может подключиться к VPN",
    "tags": ["vpn", "сеть", "подключение"],
    "candidates": ["network", "software"],
    "language": "ru",
    "department": "network",
}


class TicketOut(RoutedTicket):
    """A saved ticket: the model's fields, the routed department and the processing state."""

    model_config = ConfigDict(json_schema_extra={"examples": [TICKET_EXAMPLE]})

    id: int
    request: int = Field(description="Number of the request the ticket was made from")
    status: Ticket.Status
    assignee: str | None = Field(description="Username of the specialist working on it")
    created_at: datetime
    taken_at: datetime | None
    closed_at: datetime | None

    @classmethod
    def of(cls, ticket: Ticket) -> "TicketOut":
        return cls(
            id=ticket.pk,
            request=ticket.request_id,
            status=Ticket.Status(ticket.status),
            assignee=ticket.assignee.username if ticket.assignee else None,
            created_at=ticket.created_at,
            taken_at=ticket.taken_at,
            closed_at=ticket.closed_at,
            who=ticket.who,
            where=ticket.where,
            systems=ticket.systems,
            when=ticket.when,
            what=ticket.what,
            identifiers=ticket.identifiers,
            summary=ticket.summary,
            tags=ticket.tags,
            candidates=ticket.candidates,
            language=ticket.language,
            department=ticket.department_id,
        )


class RequestOut(Schema):
    request: int = Field(examples=[21])
    status_url: str = Field(
        description="Status page for the requester, with the request's secret code",
        examples=["http://localhost:8000/status/21-Hk3vQ0a1Zb9xY2cD/"],
    )
    tickets: list[TicketOut]


class DepartmentOut(Schema):
    id: str = Field(examples=["network"])
    name_ru: str = Field(examples=["Сеть и связь"])
    name_en: str = Field(examples=["Network and communications"])
    tags: list[str] = Field(examples=[["vpn", "wi-fi", "интернет"]])
    language: str = Field(examples=["ru"])
    capacity: int | None = Field(examples=[10])
    open_tickets: int = Field(description="Tickets New or In progress", examples=[4])
    load: float | None = Field(
        description="open_tickets / capacity; null without a capacity", examples=[0.4]
    )
    fallback: bool = Field(examples=[False])
    active: bool = Field(examples=[True])


@api.post(
    "/extract",
    response={200: services.ExtractResult, 502: Error},
    summary="Text → ticket, not saved",
    tags=["tickets"],
)
def extract(request: HttpRequest, body: TextIn):
    """Exactly the CLI result, for integrations and checks: nothing is saved or assigned."""
    try:
        return services.extract(body.text)
    except (ExtractionError, BackendError) as e:
        return Status(502, Error(detail=str(e)))


@api.post(
    "/tickets",
    response={201: RequestOut, 502: Error},
    summary="Create a ticket",
    tags=["tickets"],
)
def create_ticket(request: HttpRequest, body: RequestIn):
    """Saves the request and routes its ticket, as the request form does.

    When the model gives no ticket, the request is still saved: 502 with its number.
    """
    saved = services.create_ticket(body.text, contact=body.contact, requester=caller(request))
    if saved.error:
        return Status(502, Error(detail=saved.error, request=saved.pk))
    out = RequestOut(
        request=saved.pk,
        status_url=request.build_absolute_uri(status_url(saved)),
        tickets=[TicketOut.of(t) for t in saved.tickets.select_related("assignee")],
    )
    return Status(201, out)


class TicketFilter(Schema):
    status: Ticket.Status | None = None
    department: str | None = Field(None, examples=["network"])
    limit: int = Field(100, ge=1, le=500)
    offset: int = Field(0, ge=0)


class TicketPage(Schema):
    count: int = Field(description="Matching tickets in all pages", examples=[1])
    items: list[TicketOut]


@api.get("/tickets", response=TicketPage, summary="List tickets", tags=["tickets"])
def list_tickets(request: HttpRequest, filters: Query[TicketFilter]):
    """Oldest first. Admins see all tickets, specialists their department's, others their own."""
    tickets = services.visible_tickets(caller(request))
    if filters.status:
        tickets = tickets.filter(status=filters.status)
    if filters.department:
        tickets = tickets.filter(department_id=filters.department)
    page = tickets[filters.offset : filters.offset + filters.limit]
    return TicketPage(count=tickets.count(), items=[TicketOut.of(t) for t in page])


@api.get(
    "/tickets/{ticket_id}",
    response={200: TicketOut, 404: Error},
    summary="Get a ticket",
    tags=["tickets"],
)
def get_ticket(request: HttpRequest, ticket_id: int):
    """404 also for a ticket the caller may not see, so its existence is not revealed."""
    return TicketOut.of(get_object_or_404(services.visible_tickets(caller(request)), pk=ticket_id))


@api.get(
    "/departments",
    response=list[DepartmentOut],
    summary="Departments with their load",
    tags=["departments"],
)
def list_departments(request: HttpRequest):
    open_tickets = services.open_ticket_counts()
    result = []
    for d in Department.objects.all():
        n = open_tickets.get(d.id, 0)
        result.append(
            DepartmentOut(
                id=d.id,
                name_ru=d.name_ru,
                name_en=d.name_en,
                tags=d.tags,
                language=d.language,
                capacity=d.capacity,
                open_tickets=n,
                load=round(n / d.capacity, 3) if d.capacity else None,
                fallback=d.fallback,
                active=d.active,
            )
        )
    return result
