# Megatron-mk1

Free-text support request (RU/EN) → validated JSON ticket (who, where, when, what, summary, tags, department, language) → routed to the best-fitting, least-loaded department. Iteration 1 = console app; iteration 2 = Django service. Plan and issues: README.md, GitHub issues #1–#23.

## Commands

- `uv sync` — create `.venv` and install everything (dev group included)
- `uv run pytest` — tests
- `uv run ruff check --fix . && uv run ruff format .` — lint and format
- `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg` — once per clone
- `uv run megatron "text"` — CLI
- `docker compose up -d ollama` · `docker compose run --rm ollama-pull` · `docker compose run --rm megatron "text"` · `docker compose run --rm tests`

## Layout

- `src/megatron/` — the package (src layout). `settings.py` reads `.env`.
- `config/departments.yaml` — departments and routing weights; the ticket's `department` enum is built from it.
- `tests/` — pytest, no network calls.
- `.github/workflows/ci.yml` — GitHub Actions: ruff, pytest (3.12, 3.13), Docker build.
- `compose.yaml`, `Dockerfile` — containers. Ollama is the `ollama` compose service (CPU on macOS; `compose.gpu.yaml` for NVIDIA). A native Ollama can be used via `OLLAMA_BASE_URL_DOCKER=http://host.docker.internal:11434`. qwen3:8b needs ~6 GB free RAM in Docker.

## Rules

- Git: simplified git-flow, branches `feature/<issue>-<slug>` from `develop`, Conventional Commits. Full procedure: the `git-workflow` skill.
- Never add `Co-Authored-By: Claude` or "Generated with Claude Code" to commits or PRs.
- Ask before pushing, opening PRs, or changing GitHub issues.
- Python conventions: `.claude/rules/python.md`.
