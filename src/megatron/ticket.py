"""Ticket schema.

The `candidates` and `language` fields must take values from the config. Because those
lists come from the config, the concrete model is built at runtime by `build_ticket_model`;
its JSON schema has both fields as an `enum`, which is what constrained decoding
(Ollama / OpenAI structured outputs) needs. The model returns a `Ticket`; routing turns it
into a `RoutedTicket` with the chosen `department`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from megatron.departments import DepartmentsConfig

CANDIDATES_DESCRIPTION = "Ids of the departments that could handle the ticket, best fit first"


class Ticket(BaseModel):
    """Fields shared by every ticket. `candidates` and `language` are narrowed in
    `build_ticket_model`."""

    model_config = ConfigDict(extra="forbid")

    who: str | None = Field(description="Who reports the problem or is affected; null if unknown")
    where: str | None = Field(
        description="Place, system, service or channel where the problem is; null if unknown"
    )
    when: str | None = Field(description="When it happened, as stated; null if unknown")
    what: str = Field(description="What is wrong, in one or two sentences")
    identifiers: list[str] = Field(
        description="Codes copied verbatim from the request: phone numbers, message, order or "
        "ticket IDs, account names, logins. Not names, places or problem words; empty if none"
    )
    summary: str = Field(description="Short title of the ticket, up to 10 words")
    tags: list[str] = Field(description="3-6 short keywords")
    candidates: list[str] = Field(min_length=1, description=CANDIDATES_DESCRIPTION)
    language: str = Field(description="Language the ticket fields are written in")

    @field_validator("candidates")
    @classmethod
    def _drop_repeated(cls, v: list[str]) -> list[str]:
        # A repeated id adds nothing to the ranking; keep its first (best) position.
        return list(dict.fromkeys(v))


class RoutedTicket(Ticket):
    department: str = Field(description="Department chosen by routing, one of the candidates")


def build_ticket_model(config: DepartmentsConfig) -> type[Ticket]:
    """Return a Ticket subclass whose `candidates` and `language` only accept config values."""
    # Built from runtime values on purpose: static checkers cannot follow it, Pydantic can.
    department_ids = Literal[tuple(config.ids)]  # ty: ignore[invalid-type-form]
    languages = Literal[tuple(config.languages)]  # ty: ignore[invalid-type-form]
    return create_model(
        "Ticket",
        __base__=Ticket,
        candidates=(
            list[department_ids],
            Field(
                min_length=1,
                max_length=len(config.routing.rank_match),
                description=CANDIDATES_DESCRIPTION,
            ),
        ),
        language=(languages, Field(description="Language the ticket fields are written in")),
    )


def keep_fallback_alone(ticket: Ticket, fallback: str) -> Ticket:
    """Drop the fallback department when the model also named a real one.

    The fallback means "fits no other department", so any other candidate contradicts it.
    Small models add it anyway, even first (seen with qwen3:1.7b: ["general", "security"]
    for a phishing e-mail), which would send the ticket to the fallback.
    """
    others = [c for c in ticket.candidates if c != fallback]
    if not others or others == ticket.candidates:
        return ticket
    return ticket.model_copy(update={"candidates": others})


def keep_quoted_identifiers(ticket: Ticket, text: str) -> Ticket:
    """Drop identifiers that do not occur in the request text.

    Small models fill the field with invented codes (seen with qwen3:1.7b: "user123" for a
    request without any); an identifier is only useful if it is copied exactly.
    """
    kept = [i for i in ticket.identifiers if i and i in text]
    if kept == ticket.identifiers:
        return ticket
    return ticket.model_copy(update={"identifiers": kept})
