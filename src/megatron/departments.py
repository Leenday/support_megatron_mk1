"""Department config: loading and validating `config/departments.yaml`."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator

Language = Literal["ru", "en"]


class Department(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    tags: list[str] = Field(min_length=1)
    language: Language
    capacity: int = Field(gt=0)
    open_tickets: int = Field(ge=0)
    fallback: bool = False

    @property
    def load(self) -> float:
        """Share of capacity in use, capped at 1."""
        return min(self.open_tickets / self.capacity, 1.0)


class RoutingWeights(BaseModel):
    w_match: float = Field(ge=0)
    w_load: float = Field(ge=0)


class DepartmentsConfig(BaseModel):
    routing: RoutingWeights
    departments: list[Department] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_departments(self) -> Self:
        ids = [d.id for d in self.departments]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate department ids: {duplicates}")
        fallbacks = [d.id for d in self.departments if d.fallback]
        if len(fallbacks) != 1:
            raise ValueError(f"exactly one fallback department is required, got {fallbacks}")
        return self

    @property
    def ids(self) -> list[str]:
        return [d.id for d in self.departments]

    @property
    def fallback(self) -> Department:
        return next(d for d in self.departments if d.fallback)

    def get(self, department_id: str) -> Department:
        for d in self.departments:
            if d.id == department_id:
                return d
        raise KeyError(department_id)


def load_departments(path: Path) -> DepartmentsConfig:
    with path.open(encoding="utf-8") as f:
        return DepartmentsConfig.model_validate(yaml.safe_load(f))
