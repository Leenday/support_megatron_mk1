"""Test sets from support-ticket exports (#7): clean the text, strip leaks, sample, split.

A row of an export (CSV or JSON Lines) becomes a `Request`: the text is one or more columns
joined, `expected` is the label column turned into a department id ("Technical Support" ->
"technical_support"). Only those columns are read, so anything recorded after the request
(resolution, replies, assignee) never reaches the model.

The gold subset is a sample of the test part with the ticket fields labelled by hand; the
draft fills in what regular expressions can find and leaves the rest to the reviewer.
"""

import csv
import html
import json
import logging
import random
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from megatron.inputs import Request

logger = logging.getLogger(__name__)

Row = dict[str, Any]

# Issue-tracker keys (PROJ-123) and links to them name the queue that handled the request.
TRACKER_KEY = r"\b[A-Z][A-Z0-9]+-\d+\b:?"
TRACKER_LINK = r"https?://\S*?[A-Z][A-Z0-9]+-\d+\S*"

# Export noise, replaced in this order.
NOISE = [
    (re.compile(r"\\n"), "\n"),  # newlines escaped twice in some CSV exports
    (re.compile(r"\r\n?"), "\n"),
    (re.compile(r"<br\s*/?>", re.IGNORECASE), "\n"),
    (re.compile(r"\\([\[\]_*+#.!-])"), r"\1"),  # markdown escapes: \[phone], \+7
    # Markdown links keep their text: [[phone]](tel:[phone]) -> [phone]
    (re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\([^)\s]*\)"), r"\1"),
    (re.compile(r"\[image\]", re.IGNORECASE), ""),
    (re.compile(r"\{#[^}]*\}"), ""),  # form-template field markers
    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"\*\*|__"), ""),
]


def clean_text(text: str, leaks: Iterable[str] = ()) -> str:
    """Remove export noise and every match of the `leaks` regular expressions."""
    text = html.unescape(text).replace("\xa0", " ")
    for pattern, replacement in NOISE:
        text = pattern.sub(replacement, text)
    for leak in leaks:
        text = re.sub(leak, " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def label_to_id(label: str) -> str:
    """Department id for a dataset label: "Technical Support" -> "technical_support"."""
    department_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", department_id):
        raise ValueError(f"label {label!r} gives no valid department id")
    return department_id


def read_rows(path: Path) -> list[Row]:
    """Rows of a .csv (with a header) or .jsonl export."""
    with path.open(encoding="utf-8", newline="") as f:
        if path.suffix == ".csv":
            return list(csv.DictReader(f))
        return [json.loads(line) for line in f if line.strip()]


def to_requests(
    rows: Iterable[Row],
    text_fields: list[str],
    label_field: str,
    id_field: str | None = None,
    leaks: Iterable[str] = (),
) -> list[Request]:
    """Requests with a non-empty text and a label; repeated texts are kept once."""
    leaks = list(leaks)
    requests: dict[str, Request] = {}
    skipped = 0
    for number, row in enumerate(rows, 1):
        parts = (clean_text(str(row.get(f) or ""), leaks) for f in text_fields)
        text = "\n\n".join(p for p in parts if p)
        label = str(row.get(label_field) or "").strip()
        if not text or not label or text in requests:
            skipped += 1
            continue
        request_id = row.get(id_field, number) if id_field else number
        requests[text] = Request(text=text, id=request_id, expected=label_to_id(label))
    if skipped:
        logger.info("skipped %d rows: empty text, no label or a repeated text", skipped)
    return list(requests.values())


def by_label(requests: Iterable[Request], seed: int) -> dict[str, list[Request]]:
    """Requests grouped by label, each group shuffled with the seed."""
    groups: defaultdict[str, list[Request]] = defaultdict(list)
    for request in requests:
        groups[request.expected or ""].append(request)
    rng = random.Random(seed)
    for label in sorted(groups):
        rng.shuffle(groups[label])
    return dict(sorted(groups.items()))


def sample(requests: list[Request], per_label: int | None, seed: int) -> list[Request]:
    """At most `per_label` requests of each label (all of them when None)."""
    picked = [r for group in by_label(requests, seed).values() for r in group[:per_label]]
    random.Random(seed).shuffle(picked)
    return picked


def split(
    requests: list[Request], dev_share: float, seed: int
) -> tuple[list[Request], list[Request]]:
    """Dev and test parts with the same label proportions; every label keeps one test request."""
    dev: list[Request] = []
    test: list[Request] = []
    for group in by_label(requests, seed).values():
        n_dev = min(round(len(group) * dev_share), len(group) - 1)
        dev += group[:n_dev]
        test += group[n_dev:]
    rng = random.Random(seed)
    rng.shuffle(dev)
    rng.shuffle(test)
    return dev, test


def pick_gold(test: list[Request], size: int, seed: int) -> list[Request]:
    """`size` test requests taken from the labels in turn, so small labels are not missed."""
    groups = list(by_label(test, seed).values())
    picked: list[Request] = []
    while len(picked) < size and any(groups):
        for group in groups:
            if group and len(picked) < size:
                picked.append(group.pop(0))
    return picked


def label_counts(requests: Iterable[Request]) -> Counter[str]:
    return Counter(r.expected or "" for r in requests)


def write_requests(path: Path, requests: Iterable[Request]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (r.model_dump_json(exclude_none=True) + "\n" for r in requests)
    path.write_text("".join(lines), encoding="utf-8")


# --- Gold subset ---------------------------------------------------------------------------

IDENTIFIER_PATTERNS = [
    r"[\w.+-]+@[\w-]+\.[\w.-]*\w",  # e-mail
    r"\+?\d[\d ()-]{8,}\d",  # phone number
    r"<[a-z_]+>|\[[a-z_]+\]",  # anonymisation placeholders: <acc_num>, [phone]
    r"\b(?=[\w-]*\d)[A-Za-z][\w-]*\d[\w-]*\b",  # codes with letters and digits: ORD-1042
    r"\b\d{4,}\b",  # long numbers: account, order or client ids
]
DATE_PATTERN = (
    r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b"
    r"|\b(?:yesterday|today|this morning|вчера|сегодня|с утра)\b"
)


class GoldTicket(BaseModel):
    """A request with its hand-checked ticket fields; `checked` marks the reviewed ones."""

    id: str | int
    expected: str = Field(description="department id from the dataset label")
    checked: bool = False
    text: str
    who: str | None = None
    where: str | None = None
    when: str | None = None
    what: str | None = None
    identifiers: list[str] = []


def find_identifiers(text: str) -> list[str]:
    """Identifier candidates for the draft, in order of appearance, without repeats."""
    found: dict[int, str] = {}
    for pattern in IDENTIFIER_PATTERNS:
        for match in re.finditer(pattern, text):
            covered = any(
                start <= match.start() < start + len(value) for start, value in found.items()
            )
            if not covered:
                found[match.start()] = match.group().strip()
    # A long number is often a year or a time, so the reviewer still decides.
    return list(dict.fromkeys(found[start] for start in sorted(found)))


def draft_gold(request: Request) -> GoldTicket:
    """Gold draft: identifiers and dates found by regular expressions, the rest left empty."""
    dates = list(re.finditer(DATE_PATTERN, request.text, re.IGNORECASE))
    # Blank the dates out, so a year or an hour is not taken for an identifier.
    text = request.text
    for match in dates:
        text = text[: match.start()] + " " * len(match.group()) + text[match.end() :]
    return GoldTicket(
        id=request.id if request.id is not None else "",
        expected=request.expected or "",
        text=request.text,
        when=", ".join(dict.fromkeys(m.group() for m in dates)) or None,
        identifiers=find_identifiers(text),
    )


class _LiteralDumper(yaml.SafeDumper):
    """Multi-line strings as `|` blocks, so the text stays readable when reviewing."""


_LiteralDumper.add_representer(
    str,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    ),
)


def write_gold(path: Path, tickets: Iterable[GoldTicket]) -> None:
    data = [t.model_dump() for t in tickets]
    text = yaml.dump(data, Dumper=_LiteralDumper, allow_unicode=True, sort_keys=False, width=100)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_gold(path: Path) -> list[GoldTicket]:
    with path.open(encoding="utf-8") as f:
        return [GoldTicket.model_validate(item) for item in yaml.safe_load(f) or []]
