# Megatron-mk1

Free-text support request (RU/EN) → validated JSON ticket (who, where, when, what, summary, tags, department, language) → routed to the best-fitting, least-loaded department. Iteration 1 = console app; iteration 2 = Django service. Plan and issues: README.md, GitHub issues.

## Commands

- `uv sync` — create `.venv` and install everything (dev group included)
- `uv run pytest` — tests
- `uv run ruff check --fix . && uv run ruff format .` — lint and format
- `uv run ty check` · `uv run deptry .` — types, dependencies (`uv run pre-commit run --all-files` runs everything)
- `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg` — once per clone
- `uv run megatron "text"` — CLI (`--file requests.txt`, `-o out/result.json`; JSON Lines with `--file`; `--backend openai --model gpt-5.4-nano` override `.env`, also in `megatron-eval`)
- `uv run megatron-testset export.csv --text subject,body --label queue --out data/local/en` — test set from a ticket export: dev/test JSONL + `gold.yaml` draft (README "Test sets")
- `uv run megatron-eval data/local/en --run` — run the backend on `test.jsonl` (resumable) and report departments, fields on gold, baselines (majority, TF-IDF) with bootstrap ranges → `out/eval/<set>/report.md`; without `--run` only the report. Docker: `docker compose run --rm eval ...`; prompt tuning only on dev: `--part dev --name <variant>` (bump `PROMPT_VERSION` in `prompt.py` on every prompt change)
- `docker compose run --rm demo` (data/demo_requests.jsonl → tickets, ✓/✗ against `expected`) · `docker compose run --rm megatron "text"` · `docker compose run --rm tests`
- `docker compose up web` — Django + Postgres on :8000 (needs `DJANGO_SECRET_KEY` or `DJANGO_DEBUG=true`); `python web/manage.py import_departments|export_departments <yaml>`, `create_api_token <user>`; API docs at `/api/docs`; `LLM_BACKEND=fake` works without a model or key

## Layout

- `src/megatron/` — the package (src layout): `settings.py` (.env), `departments.py` (config loader), `ticket.py` (ticket schema: the model returns ranked `candidates`, routing adds `department`), `routing.py` (weighted score over the candidates), `prompt.py`, `inputs.py` (request files: .txt or .jsonl with `text`/`expected`), `llm.py` (`Extractor`: schema-constrained output + retry; `OllamaExtractor`, `OpenAIExtractor`, picked by `LLM_BACKEND`), `__main__.py` (CLI, `--file`), `testset.py` + `testset_cli.py` (test sets: cleaning, leak stripping, dev/test split, gold drafts), `evaluation.py` + `eval_cli.py` (metrics, baselines, report).
- `web/` — the Django service (iteration 2), not packaged: `megatron_web/` (settings from `megatron.settings.Settings`; `settings_test.py` = SQLite for pytest), `support/` (the app: `models.py` User/Department/RoutingSettings/Request/Ticket/TicketEvent/ApiToken — a request has 1..n tickets; `services.py` `create_ticket`, `departments_config` with load from open tickets, `extract` (no saving), `visible_tickets` (what each role sees), YAML import/export; `api.py` — the JSON API (Django Ninja, token or session auth); `management/commands/`; `views.py` + `forms.py` + `templates/support/` — the open request form and the status page by secret link), `locale/ru/` (translations; commit the compiled `.mo`). The database is the source of truth for departments; YAML only seeds and exports. Tests in `tests/test_services.py`, `tests/test_views.py`, `tests/test_api.py` (pytest-django; views and the API use `FakeExtractor` via `support.services.default_extractor`).
- `config/departments.yaml` — departments and routing weights; the ticket's `candidates` enum is built from it.
- `config/queues_en.yaml` — queues of the public dataset Tobi-Bueck (English test set).
- `data/` — demo requests; `data/local/` — real requests and datasets, never committed (git-ignored + pre-commit hook).
- `docs/results.md` — models × metrics table, choice of model (gpt-5.4-mini, prompt v3) and target values; update it after every new evaluation run (aggregate numbers only).
- `tests/` — pytest, no network calls; `tests/data/queues.yaml` — dataset-style config (en/de, no load).
- `.github/workflows/ci.yml` — GitHub Actions: ruff, ty, deptry, pytest (3.12, 3.13), Docker build. `pr-title.yml` — PR title into `develop` must be a Conventional Commit.
- `compose.yaml`, `Dockerfile` — containers. Ollama is the `ollama` compose service on CPU with `qwen3:1.7b` (qwen3:8b does not fit the Docker VM); `ollama-pull` downloads the model. Another Ollama: `OLLAMA_BASE_URL_DOCKER` + `--no-deps`.

## Rules

- Git: every change goes through a PR into `develop` (squash; the user merges). Never merge locally or push to `develop`/`main`. Full procedure: the `git-workflow` skill.
- Never add `Co-Authored-By: Claude` or "Generated with Claude Code" to commits or PRs.
- Ask before pushing, opening PRs, or changing GitHub issues.
- Python conventions: `.claude/rules/python.md`.
