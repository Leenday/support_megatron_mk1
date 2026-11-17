"""Triage time: a person triaging requests by hand against checking the service's tickets (#43).

The business goal is 30 % less time from a request to a ticket taken into work. Without real
specialists, the part the system changes is measured: triage. Each request is triaged once,
either by hand (read it, choose the department, write who / where / when / what) or by
checking the ticket the service made (the same form, filled by the model; fix what is wrong).
The halves swap between participants (crossover), so nobody sees a request twice, and the
modes alternate in blocks, so getting faster with practice does not favour one mode.
"""

import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Collection, Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from megatron.evaluation import Result, Score
from megatron.inputs import Request

FIELDS = ("who", "where", "when", "what")
BLOCK = 5


class Mode(StrEnum):
    MANUAL = "manual"
    SERVICE = "service"


class Fields(BaseModel):
    department: str | None = None
    who: str | None = None
    where: str | None = None
    when: str | None = None
    what: str | None = None


class PlanItem(BaseModel):
    """A request of the measurement with the service's answer to it."""

    id: str
    text: str
    expected: str | None
    half: str  # "A" or "B"
    service: Fields  # what the service filled in, shown in the service mode
    model_seconds: float  # the model's time to the ticket, from the results file


class Answer(BaseModel):
    """One triaged request, as the page records it."""

    id: str
    participant: str
    mode: Mode
    seconds: float  # from showing the request to "Done", measured in the browser
    fields: Fields
    model_seconds: float = 0.0  # added to the person's time in the service mode

    @property
    def total_seconds(self) -> float:
        return self.seconds + (self.model_seconds if self.mode is Mode.SERVICE else 0.0)


def build_plan(
    requests: Sequence[Request],
    results: Sequence[Result],
    *,
    size: int,
    seed: int,
    exclude: Collection[str] = (),
) -> list[PlanItem]:
    """`size` requests with a ticket from the service, in the label proportions, split into
    halves A and B with the labels balanced between them."""
    answered = {str(r.id): r for r in results if r.ticket is not None}
    pool = [r for r in requests if str(r.id) in answered and str(r.id) not in exclude]
    if len(pool) < size:
        raise ValueError(f"only {len(pool)} requests with a ticket, {size} needed")
    rng = random.Random(seed)
    groups: dict[str, list[Request]] = defaultdict(list)
    for r in pool:
        groups[r.expected or ""].append(r)
    for g in groups.values():
        rng.shuffle(g)
    # Largest remainder: each label gets its share of `size`.
    shares = {k: size * len(g) / len(pool) for k, g in groups.items()}
    counts = {k: int(v) for k, v in shares.items()}
    for k in sorted(shares, key=lambda k: shares[k] - counts[k], reverse=True)[
        : size - sum(counts.values())
    ]:
        counts[k] += 1
    items = []
    chosen = [r for label in sorted(groups) for r in groups[label][: counts[label]]]
    for i, r in enumerate(chosen):  # alternating across labels keeps both halves equal
        ticket = answered[str(r.id)].ticket
        assert ticket is not None
        items.append(
            PlanItem(
                id=str(r.id),
                text=r.text,
                expected=r.expected,
                half="AB"[i % 2],
                service=Fields(
                    department=ticket.department,
                    **{f: getattr(ticket, f) for f in FIELDS},
                ),
                model_seconds=answered[str(r.id)].seconds or 0.0,
            )
        )
    rng.shuffle(items)
    return items


def manual_half(swap: bool) -> str:
    return "B" if swap else "A"


def sequence(plan: Sequence[PlanItem], *, swap: bool) -> list[tuple[PlanItem, Mode]]:
    """The order one participant sees: blocks of `BLOCK` requests, by hand and checking in
    turn. Participant 1 triages half A by hand and starts by hand; the swapped participant
    triages half B by hand and starts by checking."""
    manual = [p for p in plan if p.half == manual_half(swap)]
    service = [p for p in plan if p.half != manual_half(swap)]
    queues = [(manual, Mode.MANUAL), (service, Mode.SERVICE)]
    if swap:
        queues.reverse()
    order: list[tuple[PlanItem, Mode]] = []
    while any(q for q, _ in queues):
        for q, mode in queues:
            order += [(p, mode) for p in q[:BLOCK]]
            del q[:BLOCK]
    return order


def changed_fields(answer: Answer, plan_item: PlanItem) -> list[str]:
    """What the person changed in the service's ticket (department and the four fields)."""
    before, after = plan_item.service, answer.fields
    return [
        f
        for f in ("department", *FIELDS)
        if (getattr(before, f) or "").strip() != (getattr(after, f) or "").strip()
    ]


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def two_sample_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    score: Callable[[Sequence[float], Sequence[float]], float],
    rounds: int,
    seed: int,
) -> Score:
    """A score of two independent samples with its 95 % range: each sample is resampled
    separately, since the two modes saw different requests."""
    rng = random.Random(seed)
    values = sorted(
        score(rng.choices(a, k=len(a)), rng.choices(b, k=len(b))) for _ in range(rounds)
    )
    low, high = values[int(0.025 * rounds)], values[max(int(0.975 * rounds) - 1, 0)]
    return Score(score(a, b), low, high)


def reduction(manual: Sequence[float], service: Sequence[float]) -> float:
    """How much shorter the median time with the service is, as a share of the manual one."""
    return 1 - statistics.median(service) / statistics.median(manual)


class ModeReport(BaseModel):
    n: int
    median: float
    p90: float
    mean: float
    department_accuracy: float | None


class TriageReport(BaseModel):
    participants: list[str]
    manual: ModeReport
    service: ModeReport  # person + model
    check_median: float  # the person's own time in the service mode
    model_median: float
    reduction: Score
    kept_department: float  # share of service tickets whose department the person kept
    untouched: float  # share of service tickets the person did not change at all


def mode_report(answers: Sequence[Answer], plan: dict[str, PlanItem]) -> ModeReport:
    times = [a.total_seconds for a in answers]
    labelled = [a for a in answers if plan[a.id].expected]
    accuracy = (
        sum(a.fields.department == plan[a.id].expected for a in labelled) / len(labelled)
        if labelled
        else None
    )
    return ModeReport(
        n=len(answers),
        median=statistics.median(times),
        p90=percentile(times, 0.9),
        mean=statistics.fmean(times),
        department_accuracy=accuracy,
    )


def report(
    answers: Sequence[Answer], plan: Sequence[PlanItem], *, rounds: int = 2000, seed: int = 0
) -> TriageReport:
    by_id = {p.id: p for p in plan}
    manual = [a for a in answers if a.mode is Mode.MANUAL]
    service = [a for a in answers if a.mode is Mode.SERVICE]
    if not manual or not service:
        raise ValueError("both modes need answers")
    return TriageReport(
        participants=sorted({a.participant for a in answers}),
        manual=mode_report(manual, by_id),
        service=mode_report(service, by_id),
        check_median=statistics.median(a.seconds for a in service),
        model_median=statistics.median(a.model_seconds for a in service),
        reduction=two_sample_bootstrap(
            [a.total_seconds for a in manual],
            [a.total_seconds for a in service],
            reduction,
            rounds,
            seed,
        ),
        kept_department=sum(a.fields.department == by_id[a.id].service.department for a in service)
        / len(service),
        untouched=sum(not changed_fields(a, by_id[a.id]) for a in service) / len(service),
    )


def render(set_name: str, r: TriageReport) -> str:
    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x:.0%}"

    rows = [
        ("By hand", r.manual),
        ("Service: model + the person's check", r.service),
    ]
    lines = [
        f"# Triage time: {set_name}",
        "",
        f"Participants: {', '.join(r.participants)}. Seconds per request.",
        "",
        "| Mode | Requests | Median | p90 | Mean | Department right |",
        "|---|---|---|---|---|---|",
        *(
            f"| {name} | {m.n} | {m.median:.1f} | {m.p90:.1f} | {m.mean:.1f} "
            f"| {pct(m.department_accuracy)} |"
            for name, m in rows
        ),
        "",
        f"**Median time reduction: {r.reduction.value:.0%}** "
        f"(95 % range {r.reduction.low:.0%} – {r.reduction.high:.0%}; goal 30 %).",
        "",
        f"- In the service mode the person's check took {r.check_median:.1f} s (median) and the "
        f"model {r.model_median:.1f} s.",
        f"- The person kept the service's department in {pct(r.kept_department)} of tickets "
        f"and left {pct(r.untouched)} of tickets unchanged.",
        "",
    ]
    return "\n".join(lines)


def load_answers(path: Path) -> list[Answer]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Answer.model_validate_json(line) for line in lines if line.strip()]


def load_plan(path: Path) -> list[PlanItem]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [PlanItem.model_validate_json(line) for line in lines if line.strip()]


def write_plan(path: Path, plan: Sequence[PlanItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(p.model_dump_json() + "\n" for p in plan), encoding="utf-8")
