"""Rules for the fields with a fixed shape (#35): identifiers and dates.

Identifiers and dates look the same in every request, so regular expressions find them
exactly and cannot invent them. The rules only post-process the model's ticket, never
replace it. `Extractor` applies the shape filter (an identifier that does not look like one
is dropped), so the CLI, the API and the service all do.

The additions (codes the model missed, an empty "when" filled from an explicit date) are off
by default: measured on the saved gold results (docs/results.md, #35) they lowered the
identifier precision from 0.93 to 0.64 on RU, because the model already finds nearly every
identifier and the patterns also catch numbers that are not identifiers. `megatron-eval
--rules` measures both variants without calling the model again.
"""

import re

from pydantic import BaseModel

from megatron.ticket import Ticket

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

EMAIL = re.compile(IDENTIFIER_PATTERNS[0])
PLACEHOLDER = re.compile(IDENTIFIER_PATTERNS[2])
# A login or a host name: Latin letters and digits joined by "." or "_" (a.smirnova,
# ivan_petrov, portal.example.ru). Not "-": hyphenated words (Wi-Fi, e-mail) are words, and
# codes with "-" have digits (INC-20417).
LOGIN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._][A-Za-z0-9]+)+")
# A lone year is a date, not an identifier ("since 2024").
YEAR = re.compile(r"(?:19|20)\d{2}")


class RulesLog(BaseModel):
    """What the rules changed in one ticket, recorded next to the model's answer."""

    shape_dropped: list[str] = []
    added_identifiers: list[str] = []
    when_from_rule: str | None = None


def looks_like_identifier(value: str) -> bool:
    """Has a digit, or is an e-mail, a placeholder or a login; plain words are not."""
    value = value.strip()
    return bool(
        re.search(r"\d", value)
        or EMAIL.fullmatch(value)
        or PLACEHOLDER.fullmatch(value)
        or LOGIN.fullmatch(value)
    )


def find_dates(text: str) -> list[re.Match[str]]:
    return list(re.finditer(DATE_PATTERN, text, re.IGNORECASE))


def blank_dates(text: str, dates: list[re.Match[str]]) -> str:
    """The text with the dates replaced by spaces, so a year or an hour is not an identifier."""
    for match in dates:
        text = text[: match.start()] + " " * len(match.group()) + text[match.end() :]
    return text


def find_identifiers(text: str) -> list[str]:
    """Identifier candidates in order of appearance, without repeats or overlaps."""
    found: dict[int, str] = {}
    for pattern in IDENTIFIER_PATTERNS:
        for match in re.finditer(pattern, text):
            covered = any(
                start <= match.start() < start + len(value) for start, value in found.items()
            )
            if not covered:
                found[match.start()] = match.group().strip()
    return list(dict.fromkeys(found[start] for start in sorted(found)))


def apply_rules[T: Ticket](ticket: T, text: str, *, add: bool = False) -> tuple[T, RulesLog]:
    """The ticket with the rules applied, and what they changed.

    With `add`, codes the model missed are added and an empty "when" is filled. The model's
    identifiers win: a code the rules find is added only when it does not overlap one the
    model gave ("INC-20417" is not added next to the model's "20417").
    """
    log = RulesLog()
    kept = []
    for value in ticket.identifiers:
        (kept if looks_like_identifier(value) else log.shape_dropped).append(value)

    if not add:
        if not log.shape_dropped:
            return ticket, log
        return ticket.model_copy(update={"identifiers": kept}), log

    dates = find_dates(text)
    known = [i.lower() for i in kept]
    for value in find_identifiers(blank_dates(text, dates)):
        lower = value.lower()
        if YEAR.fullmatch(value) or any(lower in k or k in lower for k in known):
            continue
        log.added_identifiers.append(value)
        known.append(lower)

    when = ticket.when
    if not (when or "").strip() and dates:
        when = log.when_from_rule = ", ".join(dict.fromkeys(m.group() for m in dates))

    if not (log.shape_dropped or log.added_identifiers or log.when_from_rule):
        return ticket, log
    update = {"identifiers": kept + log.added_identifiers, "when": when}
    return ticket.model_copy(update=update), log
