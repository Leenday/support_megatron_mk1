from pathlib import Path

import pytest

from megatron.departments import DepartmentsConfig, load_departments

CONFIG_PATH = Path(__file__).parents[1] / "config" / "departments.yaml"
QUEUES_PATH = Path(__file__).parent / "data" / "queues.yaml"


@pytest.fixture
def departments_path() -> Path:
    return CONFIG_PATH


@pytest.fixture
def departments() -> DepartmentsConfig:
    return load_departments(CONFIG_PATH)


@pytest.fixture
def queues_path() -> Path:
    """Dataset-style config: other languages (en, de) and no load."""
    return QUEUES_PATH


@pytest.fixture
def queues(queues_path) -> DepartmentsConfig:
    return load_departments(queues_path)
