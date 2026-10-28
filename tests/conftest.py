from pathlib import Path

import pytest

from megatron.departments import DepartmentsConfig, load_departments

CONFIG_PATH = Path(__file__).parents[1] / "config" / "departments.yaml"


@pytest.fixture
def departments_path() -> Path:
    return CONFIG_PATH


@pytest.fixture
def departments() -> DepartmentsConfig:
    return load_departments(CONFIG_PATH)
