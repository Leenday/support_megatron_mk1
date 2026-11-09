"""The pipeline as a service (#15): request text -> saved, routed ticket.

One entry point for the form (#17), the API (#42) and the admin, so they all route the same
way as the CLI: the `megatron` package does the extraction and the routing, this module
only feeds it the departments from the database and saves the result.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

import yaml
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from megatron.departments import Department as DepartmentConfig
from megatron.departments import DepartmentsConfig, RoutingWeights, load_departments
from megatron.llm import BackendError, ExtractionError, Extractor, build_extractor
from megatron.prompt import PROMPT_VERSION
from megatron.routing import route, score_candidates
from megatron.settings import Settings
from support.models import Department, Request, RoutingSettings, Ticket, TicketEvent, User

logger = logging.getLogger(__name__)

ExtractorFactory = Callable[[DepartmentsConfig], Extractor]


def departments_config() -> DepartmentsConfig:
    """The active departments with their current load, in the CLI's config format.

    The load is the department's open tickets (New, In progress) over its capacity; it is
    used only when every active department has a capacity, as in the YAML config.
    """
    departments = list(Department.objects.filter(active=True))
    open_tickets = dict(
        Ticket.objects.filter(status__in=Ticket.OPEN)
        .values("department")
        .annotate(n=Count("pk"))
        .values_list("department", "n")
    )
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
    )


def default_extractor(config: DepartmentsConfig) -> Extractor:
    return build_extractor(config, Settings())


def create_ticket(
    text: str,
    contact: str = "",
    requester: User | None = None,
    extractor_factory: ExtractorFactory | None = None,
) -> Request:
    """Extract, route and save; returns the request, with its ticket or its error.

    A failed extraction is saved with the error, so no request is lost. The model call is
    outside the transaction: it takes seconds, and nothing is written until it returns.
    """
    config = departments_config()
    # Looked up at call time, so tests can replace `default_extractor` for the views too.
    extractor = (extractor_factory or default_extractor)(config)
    request = Request(
        text=text,
        contact=contact,
        requester=requester,
        model=extractor.model,
        prompt_version=PROMPT_VERSION,
    )
    start = time.perf_counter()
    try:
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
            },
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
    header = (
        f"# Exported from the service database on {timezone.localtime():%Y-%m-%d %H:%M %Z}"
        " (manage.py export_departments).\n"
        "# open_tickets is the load at that moment. See config/departments.yaml for the fields.\n\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
