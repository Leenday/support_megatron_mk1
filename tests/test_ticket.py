import pytest
from pydantic import ValidationError

from megatron.ticket import build_ticket_model, keep_fallback_alone, keep_quoted_identifiers

VALID = {
    "who": "Ivanov, accounting",
    "where": "room 214",
    "when": "this morning",
    "what": "The printer does not print, shows a paper jam error.",
    "identifiers": ["HP-4015"],
    "summary": "Printer paper jam in room 214",
    "tags": ["printer", "paper jam"],
    "candidates": ["hardware", "software"],
    "language": "en",
}


def test_valid_ticket(departments):
    Ticket = build_ticket_model(departments)
    ticket = Ticket.model_validate(VALID)
    assert ticket.candidates == ["hardware", "software"]


def test_unknown_fields_may_be_null(departments):
    Ticket = build_ticket_model(departments)
    ticket = Ticket.model_validate({**VALID, "who": None, "where": None, "when": None})
    assert ticket.who is None


@pytest.mark.parametrize(
    "candidates",
    [[], ["accounting"], ["hardware", "network", "software", "security"]],
    ids=["none", "unknown", "more than rank_match"],
)
def test_bad_candidates_rejected(departments, candidates):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "candidates": candidates})


def test_repeated_candidates_dropped(departments):
    Ticket = build_ticket_model(departments)
    ticket = Ticket.model_validate({**VALID, "candidates": ["network", "hardware", "network"]})
    assert ticket.candidates == ["network", "hardware"]


def test_extra_field_rejected(departments):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "priority": "high"})


def test_json_schema_has_department_enum(departments):
    schema = build_ticket_model(departments).model_json_schema()
    candidates = schema["properties"]["candidates"]
    assert candidates["items"]["enum"] == departments.ids
    assert (candidates["minItems"], candidates["maxItems"]) == (1, 3)
    assert schema["properties"]["language"]["enum"] == ["ru", "en"]
    assert set(schema["required"]) == set(VALID)


def test_language_outside_config_rejected(departments):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "language": "de"})


def test_languages_come_from_config(queues):
    Ticket = build_ticket_model(queues)
    assert Ticket.model_json_schema()["properties"]["language"]["enum"] == ["en", "de"]
    ticket = Ticket.model_validate({**VALID, "candidates": ["billing"], "language": "de"})
    assert ticket.language == "de"


def test_identifiers_not_in_the_request_are_dropped(departments):
    ticket = build_ticket_model(departments).model_validate(
        {**VALID, "identifiers": ["INC-20417", "user123", ""]}
    )
    kept = keep_quoted_identifiers(ticket, "Не могу войти, заявка INC-20417")
    assert kept.identifiers == ["INC-20417"]


@pytest.mark.parametrize(
    ("candidates", "kept"),
    [
        (["general", "security"], ["security"]),
        (["security", "general", "network"], ["security", "network"]),
        (["general"], ["general"]),
        (["security", "network"], ["security", "network"]),
    ],
)
def test_fallback_is_dropped_next_to_a_real_department(departments, candidates, kept):
    ticket = build_ticket_model(departments).model_validate({**VALID, "candidates": candidates})
    assert keep_fallback_alone(ticket, "general").candidates == kept
