# Megatron-mk1

Free-text support request (RU/EN) → validated JSON ticket (who, where, when, what, summary, tags, department, language) → routed to the best-fitting, least-loaded department. Iteration 1 = console app; iteration 2 = Django service. Plan and issues: README.md, GitHub issues #1–#23.

## Commands

- `uv sync` — create `.venv` and install everything (dev group included)
- `uv run pytest` — tests
- `uv run ruff check --fix . && uv run ruff format .` — lint and format
- `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg` — once per clone
- `uv run megatron "text"` — CLI
- `docker compose build` · `docker compose run --rm tests` · `docker compose run --rm megatron "text"`

## Layout

- `src/megatron/` — the package (src layout). `settings.py` reads `.env`.
- `config/departments.yaml` — departments and routing weights; the ticket's `department` enum is built from it.
- `tests/` — pytest, no network calls.
- `compose.yaml`, `Dockerfile` — containers. Ollama runs natively on the Mac host (Docker on macOS has no Metal GPU); containers reach it at `http://host.docker.internal:11434`. The `ollama-cpu` compose profile is a CPU-only fallback.

## Rules

- Git: simplified git-flow, branches `feature/<issue>-<slug>` from `develop`, Conventional Commits. Full procedure: the `git-workflow` skill.
- Never add `Co-Authored-By: Claude` or "Generated with Claude Code" to commits or PRs.
- Ask before pushing, opening PRs, or changing GitHub issues.
- Python conventions: `.claude/rules/python.md`.
