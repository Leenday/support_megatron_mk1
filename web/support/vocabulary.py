"""The systems vocabulary grown from the specialists' work, checked by a validator (#57).

A specialist closing a ticket confirms its systems and may propose a new system or another
spelling of a known one; a specialist's hand edit of a field is proposed the same way. A
validator (or an admin) approves or rejects each group of similar proposals, and nobody
reviews their own. An approved vocabulary change is written to `System` at once, so the
next request gets it in the prompt and the schema: no restart and no training. A rejected
proposal is remembered, and the same text is not asked again.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from megatron.systems import ENDING
from support.models import (
    Proposal,
    RoutingSettings,
    System,
    Ticket,
    TicketEvent,
    User,
)
from support.workflow import ActionRefused, locked

# Ticket fields a specialist may edit by hand; their edits go to the validator.
REVIEWED_FIELDS = ("who", "where", "when", "what", "summary", "tags")
TRAILING_ENDING = re.compile(rf"(?<=\w{{3}}){ENDING}$")


def vocabulary_version() -> str:
    """A short hash of the active systems and their spellings, stored with each request
    like `prompt_version`, so a change in quality can be traced to a vocabulary change."""
    rows = list(System.objects.filter(active=True).order_by("id").values_list("id", "spellings"))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:8]


def normalise(text: str) -> str:
    """The grouping key: case, spacing, quotes and one case ending do not matter, as in
    `megatron.systems` ("Битрикс", "битриксе", "«Битрикс»" are one proposal)."""
    words = re.sub(r"[\"'«»“”]", "", text).casefold().split()
    if words:
        words[-1] = TRAILING_ENDING.sub("", words[-1])
    return " ".join(words)


def known_spelling(system: System, text: str) -> bool:
    key = normalise(text)
    return any(normalise(s) == key for s in [system.name, *system.spellings])


def propose_system(ticket: Ticket, user: User, text: str, system: System | None) -> Proposal:
    """A new system (`system` None) or another spelling of `system`, from closing a ticket.

    A text rejected before for the same system is recorded as rejected again, so the
    validator is not asked twice; a spelling the system already has needs no proposal.
    """
    text = " ".join(text.split())
    kind = Proposal.Kind.SPELLING if system else Proposal.Kind.NEW_SYSTEM
    key = normalise(text)
    proposal = Proposal(
        kind=kind, ticket=ticket, proposed_by=user, system=system, text=text, key=key
    )
    same = Proposal.objects.filter(kind=kind, system=system, key=key)
    rejected = same.filter(status=Proposal.Status.REJECTED).order_by("-reviewed_at").first()
    if system is not None and known_spelling(system, text):
        proposal.status = Proposal.Status.APPROVED
        proposal.reviewed_at = timezone.now()
        proposal.comment = "already in the vocabulary"
    elif rejected is not None:
        proposal.status = Proposal.Status.REJECTED
        proposal.reviewed_by = rejected.reviewed_by
        proposal.reviewed_at = timezone.now()
        proposal.comment = rejected.comment
    proposal.save()
    if proposal.status == Proposal.Status.PENDING and system is not None:
        auto_approve_spelling(proposal)
    return proposal


def auto_approve_spelling(proposal: Proposal) -> None:
    """Approve a spelling without a validator when enough different specialists proposed it
    (`RoutingSettings.spelling_auto_approve`; 0 = off, the default)."""
    needed = RoutingSettings.load().spelling_auto_approve
    group = pending_group(proposal)
    if needed and len({p.proposed_by_id for p in group}) >= needed:
        apply_vocabulary(group[0], reviewer=None, system_id="", name="")  # the first spelling
        decide(group, None, Proposal.Status.APPROVED, "approved automatically")


def propose_edit(ticket: Ticket, user: User, changes: dict) -> Proposal | None:
    """A specialist's hand edit of the model's fields, for the validator to confirm or revert."""
    reviewed = {f: v for f, v in changes.items() if f in REVIEWED_FIELDS}
    if not reviewed:
        return None
    return Proposal.objects.create(
        kind=Proposal.Kind.FIELD_EDIT, ticket=ticket, proposed_by=user, changes=reviewed
    )


def pending_group(proposal: Proposal) -> list[Proposal]:
    return list(
        Proposal.objects.filter(
            kind=proposal.kind,
            system=proposal.system,
            key=proposal.key,
            status=Proposal.Status.PENDING,
        ).select_related("proposed_by", "ticket")
    )


# Simple Russian transliteration for system ids: slugify drops Cyrillic, so "Битрикс24" would
# become "24", which is not a valid id (#70).
CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip


def system_id_for(text: str) -> str:
    """A valid system id (`[a-z][a-z0-9_]*`) suggested from how a request writes the system."""
    latin = "".join(CYRILLIC.get(c, c) for c in text.lower())
    slug = slugify(latin).replace("-", "_")
    if not slug:
        return "system"
    return slug if slug[0].isalpha() else f"system_{slug}"


@dataclass
class Group:
    """Similar pending vocabulary proposals, shown and decided as one."""

    first: Proposal
    proposals: list[Proposal] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [text for text, _ in Counter(p.text for p in self.proposals).most_common()]

    @property
    def specialists(self) -> list[str]:
        return sorted({str(p.proposed_by) for p in self.proposals if p.proposed_by})

    @property
    def tickets(self) -> list[int]:
        return sorted({p.ticket_id for p in self.proposals})[:5]

    @property
    def suggested_id(self) -> str:
        return system_id_for(self.texts[0])


def vocabulary_groups() -> list[Group]:
    groups: dict[tuple, Group] = {}
    pending = Proposal.objects.filter(
        kind__in=Proposal.VOCABULARY, status=Proposal.Status.PENDING
    ).select_related("proposed_by", "system")
    for p in pending:
        group = groups.setdefault((p.kind, p.system_id, p.key), Group(first=p))
        group.proposals.append(p)
    # The most requested first: they affect the most tickets.
    return sorted(groups.values(), key=lambda g: -len(g.proposals))


def pending_edits() -> QuerySet[Proposal]:
    return Proposal.objects.filter(
        kind=Proposal.Kind.FIELD_EDIT, status=Proposal.Status.PENDING
    ).select_related("proposed_by", "ticket")


def require_reviewer(user: User, proposals: list[Proposal]) -> None:
    if not user.can_review():
        raise ActionRefused(_("Only a validator or an admin can review proposals."))
    if any(p.proposed_by_id == user.pk for p in proposals):
        raise ActionRefused(_("Nobody reviews their own proposal: ask another validator."))


def decide(
    proposals: list[Proposal], reviewer: User | None, status: str, comment: str = ""
) -> None:
    now = timezone.now()
    for p in proposals:
        p.status, p.reviewed_by, p.reviewed_at, p.comment = status, reviewer, now, comment
        p.save(update_fields=["status", "reviewed_by", "reviewed_at", "comment"])


def apply_vocabulary(proposal: Proposal, reviewer: User | None, system_id: str, name: str) -> None:
    """Write the approved change to `System`: the next request sees it."""
    if proposal.kind == Proposal.Kind.SPELLING:
        system = System.objects.select_for_update().get(pk=proposal.system_id)
        if not known_spelling(system, proposal.text):
            system.spellings = [*system.spellings, proposal.text]
            system.save(update_fields=["spellings"])
        return
    system_id = system_id or system_id_for(proposal.text)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", system_id):
        raise ActionRefused(_("The system id must be lowercase Latin letters, digits and _."))
    if System.objects.filter(pk=system_id).exists():
        raise ActionRefused(_("A system with this id already exists."))
    system = System.objects.create(
        id=system_id, name=name or proposal.text, spellings=[proposal.text], active=True
    )
    Proposal.objects.filter(pk=proposal.pk).update(system=system)


@transaction.atomic
def approve(proposal_id: int, reviewer: User, system_id: str = "", name: str = "") -> System:
    """Approve a vocabulary proposal with every pending one like it."""
    proposal = Proposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.kind not in Proposal.VOCABULARY or proposal.status != Proposal.Status.PENDING:
        raise ActionRefused(_("This proposal is already reviewed."))
    group = pending_group(proposal)
    require_reviewer(reviewer, group)
    apply_vocabulary(proposal, reviewer, system_id, name)
    proposal.refresh_from_db()
    for p in group:
        p.system = proposal.system
        p.save(update_fields=["system"])
    decide(group, reviewer, Proposal.Status.APPROVED)
    assert proposal.system is not None
    return proposal.system


@transaction.atomic
def reject(proposal_id: int, reviewer: User, reason: str) -> None:
    proposal = Proposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.status != Proposal.Status.PENDING:
        raise ActionRefused(_("This proposal is already reviewed."))
    group = pending_group(proposal) if proposal.kind in Proposal.VOCABULARY else [proposal]
    require_reviewer(reviewer, group)
    decide(group, reviewer, Proposal.Status.REJECTED, reason)


@transaction.atomic
def review_edit(proposal_id: int, reviewer: User, confirm: bool, comment: str = "") -> Ticket:
    """Confirm a specialist's field edit, or revert it to the model's values.

    The ticket's history keeps the edit, the decision and, on a revert, the values put back.
    A field changed again since the edit is left as it is.
    """
    proposal = Proposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.kind != Proposal.Kind.FIELD_EDIT or proposal.status != Proposal.Status.PENDING:
        raise ActionRefused(_("This edit is already reviewed."))
    require_reviewer(reviewer, [proposal])
    if not confirm and not comment.strip():
        raise ActionRefused(_("Say why the edit is reverted."))
    ticket = locked(proposal.ticket_id)
    reverted = {}
    if not confirm:
        for name, (old, new) in proposal.changes.items():
            if getattr(ticket, name) == new:
                setattr(ticket, name, old)
                reverted[name] = [new, old]
        if reverted:
            ticket.save(update_fields=list(reverted))
    TicketEvent.objects.create(
        ticket=ticket,
        kind=TicketEvent.Kind.REVIEWED,
        actor=reviewer,
        data={
            "proposal": proposal.pk,
            "decision": "confirmed" if confirm else "reverted",
            "fields": list(proposal.changes),
            "reverted": reverted,
            "comment": comment,
        },
    )
    decide(
        [proposal],
        reviewer,
        Proposal.Status.APPROVED if confirm else Proposal.Status.REJECTED,
        comment,
    )
    return ticket


# --- Measured in operation ----------------------------------------------------------------


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


@dataclass
class WeekRow:
    week: date
    closed: int = 0
    systems_confirmed: int = 0

    @property
    def share(self) -> float | None:
        return self.systems_confirmed / self.closed if self.closed else None


@dataclass
class SpecialistRow:
    name: str
    closed: int = 0
    untouched: int = 0  # closed with no correction at all: systems, department, fields
    edits: int = 0
    edits_confirmed: int = 0
    edits_reverted: int = 0

    @property
    def untouched_share(self) -> float | None:
        return self.untouched / self.closed if self.closed else None

    @property
    def confirmed_share(self) -> float | None:
        decided = self.edits_confirmed + self.edits_reverted
        return self.edits_confirmed / decided if decided else None


def closing_events() -> QuerySet[TicketEvent]:
    return TicketEvent.objects.filter(
        kind=TicketEvent.Kind.STATUS_CHANGED, data__has_key="systems_confirmed"
    ).select_related("actor")


def weekly_systems(weeks: int = 8) -> list[WeekRow]:
    """Per week: closed tickets and the share whose systems the specialist confirmed as they
    were (no system removed or added)."""
    rows: dict[date, WeekRow] = {}
    since = timezone.now() - timedelta(weeks=weeks)
    for event in closing_events().filter(at__gte=since):
        week = week_start(timezone.localdate(event.at))
        row = rows.setdefault(week, WeekRow(week))
        row.closed += 1
        row.systems_confirmed += bool(event.data.get("systems_confirmed"))
    return sorted(rows.values(), key=lambda r: r.week, reverse=True)


def by_specialist() -> list[SpecialistRow]:
    """Spot check: who closes tickets without any correction (one who never corrects may not
    be checking), and how many of their edits validators confirmed."""
    rows: dict[int | None, SpecialistRow] = {}
    edited: defaultdict[int | None, set[int]] = defaultdict(set)
    for p in Proposal.objects.filter(kind=Proposal.Kind.FIELD_EDIT).select_related("proposed_by"):
        if p.proposed_by is None:
            continue
        row = rows.setdefault(p.proposed_by_id, SpecialistRow(str(p.proposed_by)))
        row.edits += 1
        row.edits_confirmed += p.status == Proposal.Status.APPROVED
        row.edits_reverted += p.status == Proposal.Status.REJECTED
        edited[p.proposed_by_id].add(p.ticket_id)
    for event in closing_events():
        if event.actor is None:
            continue
        row = rows.setdefault(event.actor_id, SpecialistRow(str(event.actor)))
        row.closed += 1
        row.untouched += (
            bool(event.data.get("systems_confirmed"))
            and bool(event.data.get("department_correct"))
            and event.ticket_id not in edited[event.actor_id]
        )
    return sorted(rows.values(), key=lambda r: r.name)


def corrections_by_system() -> list[tuple[str, int, int]]:
    """Per system: how often specialists removed it from a ticket and added it to one."""
    removed: Counter[str] = Counter()
    added: Counter[str] = Counter()
    for event in closing_events():
        before, after = event.data.get("systems", [[], []])
        removed.update(set(before) - set(after))
        added.update(set(after) - set(before))
    names = dict(System.objects.values_list("id", "name"))
    return sorted(
        ((names.get(s, s), removed[s], added[s]) for s in set(removed) | set(added)),
        key=lambda r: -(r[1] + r[2]),
    )
