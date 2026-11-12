"""Systems vocabulary (#34): config, matcher, schema and prompt."""

import pytest
from pydantic import ValidationError

from megatron.departments import DepartmentsConfig
from megatron.prompt import build_system_prompt
from megatron.systems import find_systems
from megatron.ticket import build_ticket_model

ANSWER = {
    "who": None,
    "where": "VPN",
    "systems": ["vpn"],
    "when": None,
    "what": "VPN отключается",
    "identifiers": [],
    "summary": "Отключается VPN",
    "tags": ["vpn"],
    "candidates": ["network"],
    "language": "ru",
}


def test_config_has_a_vocabulary(departments):
    assert "vpn" in departments.system_ids
    assert all(s.spellings for s in departments.systems)


def test_duplicate_system_ids_rejected(departments):
    data = departments.model_dump()
    data["systems"].append(data["systems"][0])
    with pytest.raises(ValidationError, match="duplicate system ids"):
        DepartmentsConfig.model_validate(data)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Не работает впн и почта в Outlookе", ["email", "vpn"]),  # inflected, Cyrillic
        ("принтеры на третьем этаже не печатают", ["printer"]),
        ("Не открывается общая сетевая папка", ["network_drive"]),
        ("Не могу зайти в 1С", ["erp_1c"]),
        ("максимально срочно, помогите", []),  # a short spelling inside a longer word
        ("помогите пожалуйста", []),
    ],
)
def test_find_systems_by_spellings(departments, text, found):
    assert find_systems(text, departments.systems) == found


def test_schema_limits_systems_to_the_vocabulary(departments):
    Ticket = build_ticket_model(departments)
    systems = Ticket.model_json_schema()["properties"]["systems"]
    assert systems["items"]["enum"] == departments.system_ids
    assert "systems" in Ticket.model_json_schema()["required"]
    assert Ticket.model_validate(ANSWER).systems == ["vpn"]
    with pytest.raises(ValidationError):
        Ticket.model_validate({**ANSWER, "systems": ["jira"]})  # not in the vocabulary


def test_without_a_vocabulary_systems_can_only_be_empty(departments):
    config = departments.model_copy(update={"systems": []})
    Ticket = build_ticket_model(config)
    assert Ticket.model_json_schema()["properties"]["systems"]["maxItems"] == 0
    assert Ticket.model_validate({**ANSWER, "systems": []}).systems == []
    with pytest.raises(ValidationError):
        Ticket.model_validate(ANSWER)


def test_prompt_lists_the_systems_with_spellings(departments):
    prompt = build_system_prompt(departments)
    assert "Systems:\n- email: E-mail (почта, e-mail, email, Outlook, Exchange)" in prompt
    assert '"systems"' in prompt
    plain = build_system_prompt(departments.model_copy(update={"systems": []}))
    assert "Systems:" not in plain and '"systems"' not in plain
