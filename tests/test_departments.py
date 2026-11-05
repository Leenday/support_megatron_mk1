from pathlib import Path

import pytest
from pydantic import ValidationError

from megatron.departments import DepartmentsConfig, load_departments


def test_config_loads(departments):
    assert departments.ids == ["hardware", "network", "software", "security", "general"]
    assert departments.fallback.id == "general"
    assert departments.routing.w_match + departments.routing.w_load == pytest.approx(1.0)


def test_dataset_queues_config_loads():
    path = Path(__file__).parents[1] / "config" / "queues_en.yaml"
    queues = load_departments(path)
    # Ids as megatron-testset derives them from the dataset's queue labels.
    assert len(queues.ids) == 10
    assert "service_outages_and_maintenance" in queues.ids
    assert queues.fallback.id == "general_inquiry"
    assert not queues.has_load


def test_display_names_in_both_languages(departments):
    software = departments.get("software")
    assert (software.name_ru, software.name_en) == ("ПО и учётные записи", "Software and accounts")


def test_load_is_share_of_capacity(departments):
    assert departments.get("network").load == pytest.approx(5 / 8)


def _raw(departments: DepartmentsConfig) -> dict:
    return departments.model_dump()


def test_duplicate_ids_rejected(departments):
    raw = _raw(departments)
    raw["departments"][1]["id"] = "hardware"
    with pytest.raises(ValidationError, match="duplicate"):
        DepartmentsConfig.model_validate(raw)


@pytest.mark.parametrize("fallback_flags", [[False] * 5, [True, False, False, False, True]])
def test_exactly_one_fallback(departments, fallback_flags):
    raw = _raw(departments)
    for dept, flag in zip(raw["departments"], fallback_flags, strict=True):
        dept["fallback"] = flag
    with pytest.raises(ValidationError, match="fallback"):
        DepartmentsConfig.model_validate(raw)


def test_zero_capacity_rejected(departments):
    raw = _raw(departments)
    raw["departments"][0]["capacity"] = 0
    with pytest.raises(ValidationError):
        DepartmentsConfig.model_validate(raw)


def test_languages_default_to_ru_en(departments):
    assert departments.languages == ["ru", "en"]


def test_load_and_routing_are_optional(queues):
    assert queues.languages == ["en", "de"]
    assert not queues.has_load
    assert queues.get("billing").load is None
    assert queues.routing.w_match == pytest.approx(0.7)


def test_capacity_needs_open_tickets(departments):
    raw = _raw(departments)
    raw["departments"][0]["open_tickets"] = None
    with pytest.raises(ValidationError, match="both capacity and open_tickets"):
        DepartmentsConfig.model_validate(raw)


def test_load_for_all_departments_or_none(departments):
    raw = _raw(departments)
    raw["departments"][0]["capacity"] = raw["departments"][0]["open_tickets"] = None
    with pytest.raises(ValidationError, match="all departments or for none"):
        DepartmentsConfig.model_validate(raw)


def test_department_language_must_be_listed(departments):
    raw = _raw(departments)
    raw["departments"][0]["language"] = "de"
    with pytest.raises(ValidationError, match="not in languages"):
        DepartmentsConfig.model_validate(raw)


def test_language_codes_are_iso_639_1(departments):
    raw = _raw(departments)
    raw["languages"] = ["ru", "English"]
    with pytest.raises(ValidationError, match="ISO 639-1"):
        DepartmentsConfig.model_validate(raw)


@pytest.mark.parametrize(
    "rank_match", [[], [0.6, 1.0], [1.0, 1.0], [1.5, 0.5], [1.0, 0.0]], ids=str
)
def test_rank_match_must_decrease_within_0_1(departments, rank_match):
    raw = _raw(departments)
    raw["routing"]["rank_match"] = rank_match
    with pytest.raises(ValidationError):
        DepartmentsConfig.model_validate(raw)
