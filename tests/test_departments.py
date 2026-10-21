import pytest
from pydantic import ValidationError

from megatron.departments import DepartmentsConfig


def test_config_loads(departments):
    assert departments.ids == ["hardware", "network", "software", "security", "general"]
    assert departments.fallback.id == "general"
    assert departments.routing.w_match + departments.routing.w_load == pytest.approx(1.0)


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
