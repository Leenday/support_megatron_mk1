"""Ticket schema.

The `department` and `language` fields must take values from the config. Because those
lists come from the config, the concrete model is built at runtime by `build_ticket_model`;
its JSON schema has both fields as an `enum`, which is what constrained decoding
(Ollama / GigaChat structured outputs) needs.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from megatron.departments import DepartmentsConfig


class Ticket(BaseModel):
    """Fields shared by every ticket. `department` and `language` are narrowed in
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
    department: str = Field(description="Id of the department that should handle the ticket")
    language: str = Field(description="Language the ticket fields are written in")


def build_ticket_model(config: DepartmentsConfig) -> type[Ticket]:
    """Return a Ticket subclass whose `department` and `language` only accept config values."""
    # Built from runtime values on purpose: static checkers cannot follow it, Pydantic can.
    department_ids = Literal[tuple(config.ids)]  # ty: ignore[invalid-type-form]
    languages = Literal[tuple(config.languages)]  # ty: ignore[invalid-type-form]
    return create_model(
        "Ticket",
        __base__=Ticket,
        department=(
            department_ids,
            Field(description="Id of the department that should handle the ticket"),
        ),
        language=(languages, Field(description="Language the ticket fields are written in")),
    )


def keep_quoted_identifiers(ticket: Ticket, text: str) -> Ticket:
    """Drop identifiers that do not occur in the request text.

    Small models fill the field with invented codes (seen with qwen3:1.7b: "user123" for a
    request without any); an identifier is only useful if it is copied exactly.
    """
    kept = [i for i in ticket.identifiers if i and i in text]
    if kept == ticket.identifiers:
        return ticket
    return ticket.model_copy(update={"identifiers": kept})
