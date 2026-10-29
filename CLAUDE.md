# Megatron-mk1

Free-text support request (RU/EN) → validated JSON ticket (who, where, when, what, summary, tags, department, language) → routed to the best-fitting, least-loaded department. Iteration 1 = console app; iteration 2 = Django service. Plan and issues: README.md, GitHub issues.

## Commands

- `uv sync` — create `.venv` and install everything (dev group included)
- `uv run pytest` — tests
- `uv run ruff check --fix . && uv run ruff format .` — lint and format
- `uv run ty check` · `uv run deptry .` — types, dependencies (`uv run pre-commit run --all-files` runs everything)
- `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg` — once per clone
- `uv run megatron "text"` — CLI (`--file requests.txt`, `-o out/result.json`; JSON Lines with `--file`)
- `uv run megatron-testset export.csv --text subject,body --label queue --out data/local/en` — test set from a ticket export: dev/test JSONL + `gold.yaml` draft (README "Test sets")
- `docker compose run --rm demo` (data/demo_requests.jsonl → tickets, ✓/✗ against `expected`) · `docker compose run --rm megatron "text"` · `docker compose run --rm tests`

## Layout

- `src/megatron/` — the package (src layout): `settings.py` (.env), `departments.py` (config loader), `ticket.py` (ticket schema: the model returns ranked `candidates`, routing adds `department`), `routing.py` (weighted score over the candidates), `prompt.py`, `inputs.py` (request files: .txt or .jsonl with `text`/`expected`), `llm.py` (`Extractor`: schema-constrained output + retry; `OllamaExtractor`, `OpenAIExtractor`, picked by `LLM_BACKEND`), `__main__.py` (CLI, `--file`), `testset.py` + `testset_cli.py` (test sets: cleaning, leak stripping, dev/test split, gold drafts).
- `config/departments.yaml` — departments and routing weights; the ticket's `candidates` enum is built from it.
- `config/queues_en.yaml` — queues of the public dataset Tobi-Bueck (English test set).
- `data/` — demo requests; `data/local/` — real requests and datasets, never committed (git-ignored + pre-commit hook).
- `tests/` — pytest, no network calls; `tests/data/queues.yaml` — dataset-style config (en/de, no load).
- `.github/workflows/ci.yml` — GitHub Actions: ruff, ty, deptry, pytest (3.12, 3.13), Docker build. `pr-title.yml` — PR title into `develop` must be a Conventional Commit.
- `compose.yaml`, `Dockerfile` — containers. Ollama is the `ollama` compose service on CPU with `qwen3:1.7b` (qwen3:8b does not fit the Docker VM); `ollama-pull` downloads the model. Another Ollama: `OLLAMA_BASE_URL_DOCKER` + `--no-deps`.

## Rules

- Git: every change goes through a PR into `develop` (squash; the user merges). Never merge locally or push to `develop`/`main`. Full procedure: the `git-workflow` skill.
- Never add `Co-Authored-By: Claude` or "Generated with Claude Code" to commits or PRs.
- Ask before pushing, opening PRs, or changing GitHub issues.
- Python conventions: `.claude/rules/python.md`.
