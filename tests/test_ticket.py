import pytest
from pydantic import ValidationError

from megatron.ticket import build_ticket_model

VALID = {
    "who": "Ivanov, accounting",
    "where": "room 214",
    "when": "this morning",
    "what": "The printer does not print, shows a paper jam error.",
    "identifiers": ["HP-4015"],
    "summary": "Printer paper jam in room 214",
    "tags": ["printer", "paper jam"],
    "department": "hardware",
    "language": "en",
}


def test_valid_ticket(departments):
    Ticket = build_ticket_model(departments)
    ticket = Ticket.model_validate(VALID)
    assert ticket.department == "hardware"


def test_unknown_fields_may_be_null(departments):
    Ticket = build_ticket_model(departments)
    ticket = Ticket.model_validate({**VALID, "who": None, "where": None, "when": None})
    assert ticket.who is None


def test_unknown_department_rejected(departments):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "department": "accounting"})


def test_extra_field_rejected(departments):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "priority": "high"})


def test_json_schema_has_department_enum(departments):
    schema = build_ticket_model(departments).model_json_schema()
    assert schema["properties"]["department"]["enum"] == departments.ids
    assert schema["properties"]["language"]["enum"] == ["ru", "en"]
    assert set(schema["required"]) == set(VALID)


def test_language_outside_config_rejected(departments):
    Ticket = build_ticket_model(departments)
    with pytest.raises(ValidationError):
        Ticket.model_validate({**VALID, "language": "de"})


def test_languages_come_from_config(queues):
    Ticket = build_ticket_model(queues)
    assert Ticket.model_json_schema()["properties"]["language"]["enum"] == ["en", "de"]
    ticket = Ticket.model_validate({**VALID, "department": "billing", "language": "de"})
    assert ticket.language == "de"
