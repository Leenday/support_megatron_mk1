---
paths:
  - "**/*.py"
---

# Python conventions

- Python ≥ 3.12. Use modern syntax: `list[str]`, `X | None`, `type` aliases where helpful.
- Type hints on all public functions. Data structures are Pydantic v2 models (`BaseModel`, `model_validate`, `model_json_schema`), not dicts.
- Settings come only from `megatron.settings.Settings` (pydantic-settings, `.env`); never read `os.environ` elsewhere.
- Library code under `src/megatron/` uses `logging`, never `print`. Only the CLI prints.
- Raise specific exceptions; don't catch bare `Exception` except at the CLI boundary.
- Tests live in `tests/`, named `test_<module>.py`, plain pytest functions and fixtures. No network or LLM calls in unit tests: fake the adapter.
- Style is whatever `ruff format` and `ruff check` say; don't hand-format against them.
- Docstrings: one line for obvious functions; explain *why* for anything non-obvious.
