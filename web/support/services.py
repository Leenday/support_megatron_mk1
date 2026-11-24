"""The pipeline as a service (#15): request text -> saved, routed ticket.

One entry point for the form (#17), the API (#42) and the admin, so they all route the same
way as the CLI: the `megatron` package does the extraction and the routing, this module
only feeds it the departments from the database and saves the result.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from itertools import groupby
from operator import itemgetter
from pathlib import Path

import yaml
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from pydantic import BaseModel, Field

from megatron.classifier import DepartmentClassifier
from megatron.departments import Department as DepartmentConfig
from megatron.departments import DepartmentsConfig, RoutingWeights, load_departments
from megatron.departments import System as SystemConfig
from megatron.examples import ExampleIndex
from megatron.inputs import Request as SolvedRequest
from megatron.inputs import load_requests
from megatron.llm import BackendError, ExtractionError, Extractor, build_extractor
from megatron.prompt import PROMPT_VERSION
from megatron.routing import route, score_candidates
from megatron.settings import Settings
from megatron.ticket import RoutedTicket
from support.models import (
    Department,
    HistoryTicket,
    Request,
    RoutingSettings,
    System,
    Ticket,
    TicketEvent,
    User,
)
from support.vocabulary import vocabulary_version

logger = logging.getLogger(__name__)

ExtractorFactory = Callable[[DepartmentsConfig], Extractor]


def open_ticket_counts() -> dict[str, int]:
    """Open tickets (New, In progress) per department id; departments without any are absent."""
    return dict(
        Ticket.objects.filter(status__in=Ticket.OPEN)
        .values("department")
        .annotate(n=Count("pk"))
        .values_list("department", "n")
    )


def department_accuracy() -> dict[str, tuple[int, int]]:
    """Correct decisions and all assessed decisions per department."""
    kinds = TicketEvent.Kind
    events = (
        TicketEvent.objects.filter(
            Q(kind__in=(kinds.CREATED, kinds.RETURNED, kinds.REASSIGNED))
            | Q(kind=kinds.STATUS_CHANGED, data__has_key="department_correct")
        )
        .order_by("ticket_id", "at", "pk")
        .values_list("ticket_id", "kind", "data", "ticket__department_id")
        .iterator()
    )
    correct: Counter[str] = Counter()
    assessed: Counter[str] = Counter()
    for _, history in groupby(events, key=itemgetter(0)):
        rows = list(history)
        department = next(
            (
                source
                for _, kind, data, _ in rows
                if (
                    source := data.get(
                        "department" if kind in (kinds.CREATED, kinds.STATUS_CHANGED) else "from"
                    )
                )
            ),
            rows[0][3],
        )
        for _, kind, data, _ in rows:
            if kind == kinds.CREATED:
                department = data.get("department") or department
            elif kind == kinds.STATUS_CHANGED:
                target = data.get("department") or department
                assessed[target] += 1
                correct[target] += int(data["department_correct"] is True)
            else:
                if kind == kinds.RETURNED:
                    assessed[data.get("from") or department] += 1
                department = data.get("to") or department
    return {department: (correct[department], count) for department, count in assessed.items()}


def departments_config() -> DepartmentsConfig:
    """The active departments with their current load, in the CLI's config format.

    The load is the department's open tickets (New, In progress) over its capacity; it is
    used only when every active department has a capacity, as in the YAML config.
    """
    departments = list(Department.objects.filter(active=True))
    open_tickets = open_ticket_counts()
    with_load = all(d.capacity for d in departments)
    routing = RoutingSettings.load()
    return DepartmentsConfig(
        languages=routing.languages,
        routing=RoutingWeights(
            w_match=routing.w_match, w_load=routing.w_load, rank_match=routing.rank_match
        ),
        departments=[
            DepartmentConfig(
                id=d.id,
                name_ru=d.name_ru,
                name_en=d.name_en,
                description=d.description,
                tags=d.tags,
                language=d.language,
                capacity=d.capacity if with_load else None,
                open_tickets=open_tickets.get(d.id, 0) if with_load else None,
                fallback=d.fallback,
            )
            for d in departments
        ],
        systems=[
            SystemConfig(id=x.id, name=x.name, spellings=x.spellings)
            for x in System.objects.filter(active=True)
        ],
    )


def confirmed_history() -> list[tuple[str, str]]:
    """(text, department) of the tickets whose department is confirmed (#73): the imported
    history and the closed tickets whose specialist answered "the department was right".

    Corrections ("it should have gone to X") are left out until a validator confirms them
    (#67): a specialist's correction is wrong often enough to teach the classifier errors.
    """
    active = set(Department.objects.filter(active=True).values_list("id", flat=True))
    imported = HistoryTicket.objects.filter(department_id__in=active).values_list(
        "text", "department_id"
    )
    closed = (
        Ticket.objects.filter(
            status=Ticket.Status.DONE,
            department_id__in=active,
            events__kind=TicketEvent.Kind.STATUS_CHANGED,
            events__data__department_correct=True,
        )
        .values_list("request__text", "department_id")
        .distinct()
    )
    return [*imported, *closed]


class HistoryModels(BaseModel, arbitrary_types_allowed=True):
    """What the service learns from the confirmed history: a classifier that checks the
    model (#73) and the similar solved tickets shown to the model as examples (#67)."""

    classifier: DepartmentClassifier
    examples: ExampleIndex


EXAMPLES = 5  # solved tickets shown before a request (#67: 5 helped on the EN test)

# Rebuilt only when the history changed by a tenth (at least 20 tickets): training on
# thousands of tickets takes seconds, a request must not wait for it each time.
_trained: HistoryModels | None = None


def history_models() -> HistoryModels | None:
    """The models of the confirmed history, or None while it is too small (or abstaining is
    off): then the service routes as before, by the model with its descriptions alone."""
    global _trained
    minimum = RoutingSettings.load().abstain_min_history
    history = confirmed_history() if minimum else []
    if not minimum or len(history) < minimum:
        return None
    size = _trained.classifier.size if _trained else 0
    if _trained is None or abs(len(history) - size) >= max(20, size // 10):
        texts, departments = zip(*history, strict=True)
        try:
            classifier = DepartmentClassifier(texts, departments)
        except ValueError:  # one department only: nothing to tell apart
            return None
        index = ExampleIndex([SolvedRequest(text=t, expected=d) for t, d in history])
        _trained = HistoryModels(classifier=classifier, examples=index)
    return _trained


class RoutingMeasures(BaseModel):
    """How routing does in operation (#73), for the review page."""

    tickets: int
    abstained: int = Field(
        description="sent to the fallback for triage: model and history disagreed"
    )
    closed_routed: int = Field(description="closed tickets routed automatically, with an answer")
    wrong_routed: int = Field(description="of those, closed as 'it should have gone to X'")
    reassigned: int = Field(description="tickets returned or reassigned at least once")
    history: int = Field(description="tickets with a confirmed department")
    history_needed: int = Field(description="the threshold; 0 = abstaining off")

    @property
    def routed_share(self) -> float | None:
        return 1 - self.abstained / self.tickets if self.tickets else None

    @property
    def wrong_share(self) -> float | None:
        return self.wrong_routed / self.closed_routed if self.closed_routed else None

    @property
    def reassigned_share(self) -> float | None:
        return self.reassigned / self.tickets if self.tickets else None


def routing_measures() -> RoutingMeasures:
    kinds = TicketEvent.Kind
    abstained = set(
        TicketEvent.objects.filter(kind=kinds.CREATED, data__check__abstained=True).values_list(
            "ticket_id", flat=True
        )
    )
    answers = dict(
        TicketEvent.objects.filter(
            kind=kinds.STATUS_CHANGED, data__has_key="department_correct"
        ).values_list("ticket_id", "data__department_correct")
    )
    routed_answers = [correct for ticket, correct in answers.items() if ticket not in abstained]
    return RoutingMeasures(
        tickets=Ticket.objects.count(),
        abstained=len(abstained),
        closed_routed=len(routed_answers),
        wrong_routed=sum(correct is False for correct in routed_answers),
        reassigned=TicketEvent.objects.filter(kind__in=(kinds.RETURNED, kinds.REASSIGNED))
        .values("ticket_id")
        .distinct()
        .count(),
        history=len(confirmed_history()),
        history_needed=RoutingSettings.load().abstain_min_history,
    )


def import_history(path: Path, replace: bool = False) -> int:
    """Import solved tickets (.jsonl with `text` and `expected`, the department id) as the
    confirmed history; returns how many were imported."""
    requests = load_requests(path)
    known = set(Department.objects.values_list("id", flat=True))
    unknown = sorted({r.expected or "" for r in requests} - known)
    if unknown:
        raise ValueError(f"unknown departments: {', '.join(unknown)}")
    with transaction.atomic():
        if replace:
            HistoryTicket.objects.all().delete()
        HistoryTicket.objects.bulk_create(
            HistoryTicket(text=r.text, department_id=r.expected) for r in requests
        )
    return len(requests)


def default_extractor(config: DepartmentsConfig) -> Extractor:
    return build_extractor(config, Settings())


class ExtractResult(BaseModel):
    """What the CLI prints for one request: the routed ticket and how it was obtained."""

    model: str = Field(examples=["gpt-5.4-mini"])
    prompt_version: str = Field(examples=["v3"])
    ticket: RoutedTicket
    attempts: int = Field(examples=[1], description="Model calls it took to get a valid ticket")
    dropped_identifiers: list[str] = Field(
        examples=[[]], description="Identifiers the model gave that are not in the request text"
    )
    seconds: float = Field(examples=[1.4])


def extract(text: str, extractor_factory: ExtractorFactory | None = None) -> ExtractResult:
    """Extract and route without saving anything, exactly as the CLI does.

    Raises `ExtractionError` or `BackendError` like the extractor.
    """
    config = departments_config()
    extractor = (extractor_factory or default_extractor)(config)
    if trained := history_models():
        extractor.use_examples(trained.examples, EXAMPLES)
    start = time.perf_counter()
    extraction = extractor.extract_detailed(text)
    return ExtractResult(
        model=extractor.model,
        prompt_version=extractor.prompt_version,
        ticket=route(extraction.ticket, config),
        attempts=extraction.attempts,
        dropped_identifiers=extraction.dropped_identifiers,
        seconds=round(time.perf_counter() - start, 1),
    )


def visible_tickets(user: User) -> QuerySet[Ticket]:
    """The tickets a user may see: admins and validators all, specialists their department's,
    others their own.

    "Others" are accounts that send requests through the API, such as an integration.
    Validators see every ticket because proposals and edits come from all departments (#57).
    """
    tickets = Ticket.objects.select_related("department", "assignee", "request")
    if user.is_superuser or user.has_role("Admin") or user.has_role("Validator"):
        return tickets
    if user.has_role("Specialist"):
        return (
            tickets.filter(department_id=user.department_id)
            if user.department_id
            else tickets.none()
        )
    return tickets.filter(request__requester=user)


def create_ticket(
    text: str,
    contact: str = "",
    requester: User | None = None,
    extractor_factory: ExtractorFactory | None = None,
) -> Request:
    """Extract, route and save; returns the request, with its ticket or its error.

    A failed extraction is saved with the error, so no request is lost, and so is a request
    that meets a misconfigured backend (no API key). The model call is outside the
    transaction: it takes seconds, and nothing is written until it returns.
    """
    config = departments_config()
    request = Request(
        text=text,
        contact=contact,
        requester=requester,
        prompt_version=PROMPT_VERSION,
        vocabulary_version=vocabulary_version(),
    )
    start = time.perf_counter()
    trained = None
    try:
        # Looked up at call time, so tests can replace `default_extractor` for the views too.
        extractor = (extractor_factory or default_extractor)(config)
        trained = history_models()
        if trained:
            extractor.use_examples(trained.examples, EXAMPLES)
        request.model = extractor.model
        request.prompt_version = extractor.prompt_version
        extraction = extractor.extract_detailed(text)
    except (ExtractionError, BackendError) as e:
        logger.warning("request not turned into a ticket: %s", e)
        request.seconds = round(time.perf_counter() - start, 1)
        request.error = str(e)
        request.save()
        return request
    request.seconds = round(time.perf_counter() - start, 1)
    request.attempts = extraction.attempts
    request.dropped_identifiers = extraction.dropped_identifiers

    routed = route(extraction.ticket, config)
    scores = score_candidates(extraction.ticket, config)
    # Abstain (#73): with a confirmed history, a classifier checks the model's best fit; when
    # they disagree, a person triages the ticket in the fallback department.
    check = None
    if trained:
        suggested, probability = trained.classifier.predict(text)
        best = extraction.ticket.candidates[0]
        check = {
            "history": suggested,
            "probability": round(probability, 2),
            "agree": suggested == best,
        }
        if not check["agree"] and routed.department != config.fallback.id:
            routed = routed.model_copy(update={"department": config.fallback.id})
            check["abstained"] = True
    with transaction.atomic():
        request.save()
        ticket = Ticket.objects.create(
            request=request,
            **routed.model_dump(exclude={"department"}),
            department_id=routed.department,
        )
        TicketEvent.objects.create(
            ticket=ticket,
            kind=TicketEvent.Kind.CREATED,
            data={
                "department": routed.department,
                "scores": {d: round(s, 3) for d, s in scores.items()},
                "load": {d: config.get(d).load for d in scores},
            }
            | ({"check": check} if check else {})
            | ({"examples": extraction.examples} if extraction.examples else {}),
        )
    return request


@transaction.atomic
def import_departments(config: DepartmentsConfig) -> dict[str, int]:
    """Create or update departments by id; deactivate those not in the config, never delete.

    Departments are referenced by tickets, so a department missing from the file only stops
    being offered to the model. The current load is not imported: it comes from the tickets.
    """
    # Only one fallback may exist at a time (a database constraint), so clear the old first.
    Department.objects.filter(fallback=True).exclude(id=config.fallback.id).update(fallback=False)
    counts = {"created": 0, "updated": 0}
    for d in config.departments:
        _, created = Department.objects.update_or_create(
            id=d.id,
            defaults={
                "name_ru": d.name_ru,
                "name_en": d.name_en,
                "description": d.description,
                "tags": d.tags,
                "language": d.language,
                "capacity": d.capacity,
                "fallback": d.fallback,
                "active": True,
            },
        )
        counts["created" if created else "updated"] += 1
    counts["deactivated"] = (
        Department.objects.filter(active=True).exclude(id__in=config.ids).update(active=False)
    )
    # Systems are imported the same way: by id, missing ones deactivated (#34).
    for x in config.systems:
        System.objects.update_or_create(
            id=x.id, defaults={"name": x.name, "spellings": x.spellings, "active": True}
        )
    System.objects.filter(active=True).exclude(id__in=config.system_ids).update(active=False)
    counts["systems"] = len(config.systems)
    routing = RoutingSettings.load()
    routing.w_match = config.routing.w_match
    routing.w_load = config.routing.w_load
    routing.rank_match = config.routing.rank_match
    routing.languages = config.languages
    routing.save()
    return counts


def import_departments_file(path: Path) -> dict[str, int]:
    return import_departments(load_departments(path))


def export_departments() -> str:
    """The active departments as YAML in the format of `config/departments.yaml`.

    `open_tickets` is the load at the moment of export, so the CLI routes like the service.
    """
    data = departments_config().model_dump(mode="json", exclude_none=True)
    for d in data["departments"]:
        if not d["fallback"]:
            del d["fallback"]
    if not data["systems"]:
        del data["systems"]
    header = (
        f"# Exported from the service database on {timezone.localtime():%Y-%m-%d %H:%M %Z}"
        " (manage.py export_departments).\n"
        "# open_tickets is the load at that moment. See config/departments.yaml for the fields.\n\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
