"""Department config: loading and validating `config/departments.yaml`.

A department is any routing target: a department, a queue, a support line or a category.
Each dataset or deployment can have its own config file (`DEPARTMENTS_PATH`).
"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, model_validator

LanguageCode = str  # ISO 639-1, e.g. "ru", "en", "de"


class Department(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name_ru: str
    name_en: str
    description: str
    tags: list[str] = Field(min_length=1)
    language: LanguageCode
    # Optional: datasets and real requests rarely come with the departments' load.
    capacity: int | None = Field(default=None, gt=0)
    open_tickets: int | None = Field(default=None, ge=0)
    fallback: bool = False

    @model_validator(mode="after")
    def _check_load(self) -> Self:
        if (self.capacity is None) != (self.open_tickets is None):
            raise ValueError(f"{self.id}: give both capacity and open_tickets, or neither")
        return self

    @property
    def load(self) -> float | None:
        """Share of capacity in use, capped at 1; None when the load is unknown."""
        if self.capacity is None or self.open_tickets is None:
            return None
        return min(self.open_tickets / self.capacity, 1.0)


class RoutingWeights(BaseModel):
    w_match: float = Field(default=0.7, ge=0)
    w_load: float = Field(default=0.3, ge=0)


class DepartmentsConfig(BaseModel):
    languages: list[LanguageCode] = Field(
        default=["ru", "en"], min_length=1, description="ticket languages; the first is the default"
    )
    routing: RoutingWeights = RoutingWeights()
    departments: list[Department] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_departments(self) -> Self:
        bad_codes = [code for code in self.languages if len(code) != 2 or not code.islower()]
        if bad_codes:
            raise ValueError(f"languages must be ISO 639-1 codes like 'en', got {bad_codes}")
        ids = [d.id for d in self.departments]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate department ids: {duplicates}")
        fallbacks = [d.id for d in self.departments if d.fallback]
        if len(fallbacks) != 1:
            raise ValueError(f"exactly one fallback department is required, got {fallbacks}")
        unknown = sorted({d.language for d in self.departments} - set(self.languages))
        if unknown:
            raise ValueError(f"department languages {unknown} are not in languages")
        # Routing compares loads across departments, so they must be known for all or none.
        if len({d.load is None for d in self.departments}) > 1:
            raise ValueError("give capacity and open_tickets for all departments or for none")
        return self

    @property
    def ids(self) -> list[str]:
        return [d.id for d in self.departments]

    @property
    def fallback(self) -> Department:
        return next(d for d in self.departments if d.fallback)

    @property
    def has_load(self) -> bool:
        return self.departments[0].load is not None

    def get(self, department_id: str) -> Department:
        for d in self.departments:
            if d.id == department_id:
                return d
        raise KeyError(department_id)


def load_departments(path: Path) -> DepartmentsConfig:
    with path.open(encoding="utf-8") as f:
        return DepartmentsConfig.model_validate(yaml.safe_load(f))
