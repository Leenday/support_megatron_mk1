"""Evaluation (#12): score the answers of a backend on a labelled set.

Department: accuracy and macro-F1 of the model's best fit against `expected`, next to two
baselines trained on the dev part: the majority class and TF-IDF + logistic regression.
Fields: precision, recall and F1 per field on the hand-checked gold subset (#7). A failed
request counts as an empty ticket, so failures lower accuracy and recall instead of
dropping out. The sets are small, so the main scores come with bootstrap ranges.
"""

import random
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from megatron.inputs import Request
from megatron.testset import GoldTicket
from megatron.ticket import RoutedTicket, Ticket

TEXT_FIELDS = ("who", "where", "when", "what")
FIELDS = (*TEXT_FIELDS, "identifiers")

# A free-text field matches the gold value when their word overlap (token F1) reaches this.
MATCH_THRESHOLD = 0.5
# Words are compared by their first letters: a crude stemmer for Russian and English
# ("отправляются" / "отправились", "crashes" / "crash").
STEM_LENGTH = 5


class Result(BaseModel):
    """One line of a results file, as `megatron --file -o` and `megatron-eval --run` write it."""

    model_config = ConfigDict(extra="ignore")

    id: str | int | None = None
    request: str
    expected: str | None = None
    ticket: RoutedTicket | None = None
    error: str | None = None
    seconds: float | None = None
    attempts: int | None = None
    dropped_identifiers: list[str] = []

    @property
    def best_fit(self) -> str | None:
        return self.ticket.candidates[0] if self.ticket else None


def load_results(path: Path) -> list[Result]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Result.model_validate_json(line) for line in lines if line.strip()]


# --- Matching ------------------------------------------------------------------------------


def stems(text: str | None) -> Counter[str]:
    return Counter(word[:STEM_LENGTH] for word in re.findall(r"\w+", (text or "").lower()))


def token_f1(gold: str | None, predicted: str | None) -> float:
    """Word overlap of two texts, 0..1 (SQuAD-style F1 over stems)."""
    g, p = stems(gold), stems(predicted)
    common = sum((g & p).values())
    if not common:
        return 0.0
    precision, recall = common / p.total(), common / g.total()
    return 2 * precision * recall / (precision + recall)


def normalize_identifier(value: str) -> str:
    return value.strip().strip(".,;:()\"'«»").lower()


@dataclass(frozen=True)
class Counts:
    """True positives, false positives and false negatives of one field."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    # None when undefined: nothing given (precision), nothing expected (recall), or neither
    # (F1) - a field the requests never mention is not a zero.
    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        errors = self.fp + self.fn
        return 2 * self.tp / (2 * self.tp + errors) if self.tp + errors else None


def field_counts(gold: GoldTicket, ticket: Ticket | None) -> dict[str, Counts]:
    """Counts per field for one request; no ticket (a failure) is an empty ticket.

    A free-text value that does not match the gold one is both a false positive (a wrong
    value was given) and a false negative (the right one was missed), as in slot filling.
    """
    counts = {}
    for field in TEXT_FIELDS:
        expected = getattr(gold, field) or None
        given = (getattr(ticket, field) or "").strip() or None if ticket else None
        hit = expected is not None and given is not None
        hit = hit and token_f1(expected, given) >= MATCH_THRESHOLD
        counts[field] = Counts(
            tp=int(hit),
            fp=int(given is not None and not hit),
            fn=int(expected is not None and not hit),
        )
    expected_ids = {normalize_identifier(i) for i in gold.identifiers}
    given_ids = {normalize_identifier(i) for i in ticket.identifiers} if ticket else set()
    given_ids.discard("")
    counts["identifiers"] = Counts(
        tp=len(expected_ids & given_ids),
        fp=len(given_ids - expected_ids),
        fn=len(expected_ids - given_ids),
    )
    return counts


def total(counts: Iterable[dict[str, Counts]]) -> dict[str, Counts]:
    summed = dict.fromkeys(FIELDS, Counts())
    for c in counts:
        summed = {f: summed[f] + c[f] for f in FIELDS}
    return summed


# --- Scores --------------------------------------------------------------------------------

Pair = tuple[str, str | None]  # (expected department, predicted department or None)


def accuracy(pairs: Sequence[Pair]) -> float:
    return sum(e == p for e, p in pairs) / len(pairs) if pairs else 0.0


def macro_f1(pairs: Sequence[Pair]) -> float:
    """Mean F1 over the expected departments, so a small department weighs as much as a big one."""
    labels = sorted({e for e, _ in pairs})
    scores = []
    for label in labels:
        tp = sum(e == label and p == label for e, p in pairs)
        fp = sum(e != label and p == label for e, p in pairs)
        fn = sum(e == label and p != label for e, p in pairs)
        scores.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return statistics.fmean(scores) if scores else 0.0


@dataclass(frozen=True)
class Score:
    value: float
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.value:.2f} ({self.low:.2f}–{self.high:.2f})"


def bootstrap[T](
    items: Sequence[T], score: Callable[[Sequence[T]], float | None], rounds: int, seed: int
) -> Score | None:
    """The score with its 95 % range over `rounds` resamples of the items.

    None if the score is undefined on the items; resamples where it is undefined are skipped.
    """
    value = score(items)
    if value is None:
        return None
    rng = random.Random(seed)
    resampled = (score(rng.choices(items, k=len(items))) for _ in range(rounds))
    values = sorted(v for v in resampled if v is not None)
    low, high = values[int(0.025 * len(values))], values[max(int(0.975 * len(values)) - 1, 0)]
    return Score(value, low, high)


# --- Baselines -----------------------------------------------------------------------------


def majority_baseline(train: Sequence[Request], test: Sequence[Request]) -> list[str]:
    """Always the most frequent department of the training part."""
    label = Counter(r.expected for r in train).most_common(1)[0][0] or ""
    return [label] * len(test)


def tfidf_baseline(train: Sequence[Request], test: Sequence[Request]) -> list[str]:
    """TF-IDF over character n-grams + logistic regression, trained on the training part.

    Character n-grams within words cope with Russian inflection without a stemmer.
    """
    labels = [r.expected or "" for r in train]
    if len(set(labels)) < 2:
        return majority_baseline(train, test)
    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    model.fit([r.text for r in train], labels)
    return [str(label) for label in model.predict([r.text for r in test])]


# --- Report --------------------------------------------------------------------------------


class SystemReport(BaseModel):
    """Scores of one system (a backend's results or a baseline) on one set."""

    name: str
    requests: int
    accuracy: Score | None
    macro_f1: Score | None
    # Only for models: baselines give one department and no ticket.
    in_candidates: float | None = None
    valid: Score | None = None
    first_try: float | None = None
    gold: int = 0
    fields: dict[str, Counts] = {}
    field_f1: dict[str, Score | None] = {}
    dropped: int = 0
    tickets_with_dropped: int = 0
    seconds_median: float | None = None
    seconds_p90: float | None = None


def department_report(
    name: str, pairs: Sequence[Pair], rounds: int, seed: int, **extra: object
) -> SystemReport:
    return SystemReport.model_validate(
        {
            "name": name,
            "requests": len(pairs),
            "accuracy": bootstrap(pairs, accuracy, rounds, seed),
            "macro_f1": bootstrap(pairs, macro_f1, rounds, seed),
            **extra,
        }
    )


def model_report(
    name: str, results: Sequence[Result], gold: Sequence[GoldTicket], rounds: int, seed: int
) -> SystemReport:
    pairs = [(r.expected or "", r.best_fit) for r in results]
    tickets = [r for r in results if r.ticket]
    by_id = {str(r.id): r for r in results}
    checked = [g for g in gold if g.checked and str(g.id) in by_id]
    per_request = [field_counts(g, by_id[str(g.id)].ticket) for g in checked]
    seconds = sorted(r.seconds for r in results if r.seconds is not None)
    return department_report(
        name,
        pairs,
        rounds,
        seed,
        in_candidates=sum(bool(r.ticket and r.expected in r.ticket.candidates) for r in results)
        / len(results),
        valid=bootstrap([r.ticket is not None for r in results], statistics.fmean, rounds, seed),
        # Results saved before attempts were recorded have none.
        first_try=sum(r.attempts == 1 for r in tickets) / len(results)
        if any(r.attempts for r in tickets)
        else None,
        gold=len(checked),
        fields=total(per_request),
        field_f1={
            f: bootstrap(per_request, lambda s, f=f: total(s)[f].f1, rounds, seed) for f in FIELDS
        }
        if per_request
        else {},
        dropped=sum(len(r.dropped_identifiers) for r in results),
        tickets_with_dropped=sum(bool(r.dropped_identifiers) for r in results),
        seconds_median=statistics.median(seconds) if seconds else None,
        seconds_p90=seconds[int(0.9 * (len(seconds) - 1))] if seconds else None,
    )


def render(set_name: str, reports: Sequence[SystemReport]) -> str:
    """Markdown tables: departments for every system, fields for the models."""

    def cell(value: object, digits: int = 2) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    n = reports[0].requests if reports else 0
    lines = [
        f"## {set_name}: department (test, {n} requests)",
        "",
        "| System | Accuracy | Macro-F1 | Expected in candidates | Valid | Valid 1st try "
        "| s/request median · p90 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        seconds = (
            f"{r.seconds_median:.1f} · {r.seconds_p90:.1f}" if r.seconds_median is not None else "—"
        )
        lines.append(
            f"| {r.name} | {cell(r.accuracy)} | {cell(r.macro_f1)} | {cell(r.in_candidates)} "
            f"| {cell(r.valid)} | {cell(r.first_try)} | {seconds} |"
        )
    models = [r for r in reports if r.field_f1]
    if models:
        lines += [
            "",
            f"## {set_name}: fields (gold, {models[0].gold} requests): F1 (range), P / R",
            "",
            "| System | " + " | ".join(FIELDS) + " | Dropped identifiers |",
            "|---|" + "---|" * (len(FIELDS) + 1),
        ]
        for r in models:
            cells = [
                f"{cell(r.field_f1[f])}<br>{cell(r.fields[f].precision)} / "
                f"{cell(r.fields[f].recall)}"
                for f in FIELDS
            ]
            dropped = f"{r.dropped} in {r.tickets_with_dropped} of {r.requests} tickets"
            lines.append(f"| {r.name} | " + " | ".join(cells) + f" | {dropped} |")
    return "\n".join(lines) + "\n"
