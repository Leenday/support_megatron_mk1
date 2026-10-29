# Megatron-mk1 — intelligent technical support system

[![CI](https://github.com/Leenday/support_megatron_mk1/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/Leenday/support_megatron_mk1/actions/workflows/ci.yml)

Megatron-mk1 turns a user's free-text request into a structured support ticket and assigns it to the most suitable and least busy support department.

- **Input:** a request in Russian or English (text; voice later).
- **Output:** a JSON ticket — who, where, when, what, summary, tags, department — always valid against the ticket schema.
- **Interface:** a Django web app — request form, specialist dashboard (take tickets, statuses), built-in admin panel.
- **How:** an LLM with schema-constrained output (local Qwen3-8B via Ollama; GigaChat API as backup) + a weighted routing score (profile match and current load).

**Team (group 2, SPbPU, Higher School of Cyber-Physical Systems Control):** Daniil, Roman, Denis.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 itself) and Docker Desktop.

```bash
git clone git@github.com:Leenday/support_megatron_mk1.git && cd support_megatron_mk1
uv sync                                  # .venv with the package and dev tools
uv run pre-commit install                # pre-commit and commit-msg hooks
cp .env.example .env                     # then edit: backend, Ollama URL, GigaChat key
uv run pytest                            # tests
uv run megatron --version
```

**Run (Docker).** Ollama runs as a compose service with the small `qwen3:1.7b` model (1.4 GB, fits CPU-only Docker on a Mac).

```bash
docker compose run --rm demo                 # requests from data/demo_requests.txt -> JSON tickets
docker compose run --rm megatron "текст"     # one request
docker compose run --rm megatron "текст" -o out/ticket.json   # save the ticket to ./out
docker compose run --rm demo -o out/demo.jsonl               # save all results (JSON Lines)
docker compose run --rm tests                # pytest in a container
```

The first run starts Ollama and downloads the model. Docker on macOS has no GPU access, so each request takes tens of seconds to a minute on CPU. For a faster model server (native Ollama or a remote one) set `OLLAMA_BASE_URL_DOCKER` in `.env` and add `--no-deps`. Locally without Docker: `uv run megatron "текст"` with `OLLAMA_BASE_URL`.

**CI.** GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs ruff, the ty type checker, deptry (unused and missing dependencies), pytest on Python 3.12 and 3.13, and a Docker build on every push and pull request; [pr-title.yml](.github/workflows/pr-title.yml) checks that a PR title into `develop` is a Conventional Commit. The same checks run locally in the pre-commit hooks. New PRs are announced in the project topic of the team's Telegram group ([.github/workflows/pr-telegram.yml](.github/workflows/pr-telegram.yml)).

**Workflow.** `develop` is the default branch. Each change: issue → branch `feature/<issue>-<slug>` from `develop` → PR into `develop` (template: `Closes #N`, demo recording) → *Squash and merge* after CI is green. `develop` and `main` are protected (PR + CI required). At the end of an iteration a `Release v0.X.0` PR merges `develop` into `main` with a merge commit and is tagged. Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Details: [.claude/skills/git-workflow/SKILL.md](.claude/skills/git-workflow/SKILL.md).

## Calendar plan

Waterfall plan by stage. Critical points are highlighted. Tasks are tracked as [issues](https://github.com/Leenday/support_megatron_mk1/issues), stages as [milestones](https://github.com/Leenday/support_megatron_mk1/milestones).

```mermaid
gantt
    title Megatron-mk1 — calendar plan (waterfall)
    dateFormat YYYY-MM-DD
    axisFormat %d.%m
    todayMarker on
    section 0 · Initiation and methods review
    Project idea and first presentation [1] :done, t1, 2026-09-25, 2026-10-02
    Methods review and choice of methods [2] :done, crit, t2, 2026-10-03, 2026-10-16
    Impact map and user stories (Miro) [3] :done, t3, 2026-10-09, 2026-10-14
    Calendar plan (waterfall Gantt chart) [4] :done, t4, 2026-10-14, 2026-10-16
    Initiation and methods review done :milestone, m0, 2026-10-16, 0d
    section 1 · Console MVP
    Repository skeleton and dev setup [5] :done, t5, 2026-10-17, 2026-10-20
    Ticket schema and department config [6] :done, t6, 2026-10-17, 2026-10-22
    Test set 50-100 requests in Russian and English [7] :t7, 2026-10-17, 2026-10-29
    LLM adapter local Qwen3 (Ollama) + GigaChat backup [8] :t8, 2026-10-20, 2026-10-29
    Prompt with department descriptions [9] :t9, 2026-10-22, 2026-10-29
    Routing weighted score [10] :t10, 2026-10-23, 2026-10-31
    Validation and retry [11] :t11, 2026-10-27, 2026-10-31
    Evaluation script and TF-IDF baseline [12] :t12, 2026-10-27, 2026-11-04
    CLI text in, JSON ticket out [13] :t13, 2026-10-29, 2026-11-02
    Model comparison and results table [14] :crit, t14, 2026-11-02, 2026-11-06
    Quality gates type checking, dependency check, PR title check [28] :t28, 2026-10-28, 2026-10-30
    Console MVP done :milestone, m1, 2026-11-06, 0d
    section 2 · Service
    Django project, data models and load-aware routing [15] :t15, 2026-11-07, 2026-11-13
    Django admin users, roles, departments, all tickets [16] :t16, 2026-11-13, 2026-11-19
    Request form connected to the pipeline [17] :t17, 2026-11-07, 2026-11-14
    Specialist dashboard take tickets and change statuses [18] :t18, 2026-11-12, 2026-11-24
    Translation RU ↔ EN (if time allows) [23] :t23, 2026-11-16, 2026-11-24
    Iteration 2 testing [19] :t19, 2026-11-23, 2026-11-27
    Service done :milestone, m2, 2026-11-27, 0d
    section 3 · Final
    Voice input with Whisper (optional) [20] :t20, 2026-11-28, 2026-12-05
    Final metrics and report [21] :t21, 2026-11-28, 2026-12-10
    Final presentation [22] :crit, t22, 2026-12-07, 2026-12-14
    Final done :milestone, m3, 2026-12-14, 0d
```

| Issue | Task | Start | Due | Owner | Done |
|---|---|---|---|---|---|
| [#1](https://github.com/Leenday/support_megatron_mk1/issues/1) | Project idea and first presentation | 2026-09-25 | 2026-10-02 | All | ✅ |
| [#2](https://github.com/Leenday/support_megatron_mk1/issues/2) | Methods review and choice of methods | 2026-10-03 | 2026-10-16 | Denis | ✅ |
| [#3](https://github.com/Leenday/support_megatron_mk1/issues/3) | Impact map and user stories (Miro) | 2026-10-09 | 2026-10-14 | Denis | ✅ |
| [#4](https://github.com/Leenday/support_megatron_mk1/issues/4) | Calendar plan (waterfall Gantt chart) | 2026-10-14 | 2026-10-16 | Denis | ✅ |
| [#5](https://github.com/Leenday/support_megatron_mk1/issues/5) | Repository skeleton and dev setup | 2026-10-17 | 2026-10-20 | Denis | ✅ |
| [#6](https://github.com/Leenday/support_megatron_mk1/issues/6) | Ticket schema and department config | 2026-10-17 | 2026-10-22 | Roman | ✅ |
| [#7](https://github.com/Leenday/support_megatron_mk1/issues/7) | Test set: 50-100 requests in Russian and English | 2026-10-17 | 2026-10-29 | Daniil |  |
| [#8](https://github.com/Leenday/support_megatron_mk1/issues/8) | LLM adapter: local Qwen3 (Ollama) + GigaChat backup | 2026-10-20 | 2026-10-29 | Denis |  |
| [#9](https://github.com/Leenday/support_megatron_mk1/issues/9) | Prompt with department descriptions | 2026-10-22 | 2026-10-29 | Denis |  |
| [#10](https://github.com/Leenday/support_megatron_mk1/issues/10) | Routing: weighted score | 2026-10-23 | 2026-10-31 | Roman |  |
| [#11](https://github.com/Leenday/support_megatron_mk1/issues/11) | Validation and retry | 2026-10-27 | 2026-10-31 | Roman |  |
| [#12](https://github.com/Leenday/support_megatron_mk1/issues/12) | Evaluation script and TF-IDF baseline | 2026-10-27 | 2026-11-04 | Daniil |  |
| [#13](https://github.com/Leenday/support_megatron_mk1/issues/13) | CLI: text in, JSON ticket out | 2026-10-29 | 2026-11-02 | Denis |  |
| [#14](https://github.com/Leenday/support_megatron_mk1/issues/14) | Model comparison and results table | 2026-11-02 | 2026-11-06 | Denis |  |
| [#28](https://github.com/Leenday/support_megatron_mk1/issues/28) | Quality gates: type checking, dependency check, PR title check | 2026-10-28 | 2026-10-30 | Denis |  |
| [#15](https://github.com/Leenday/support_megatron_mk1/issues/15) | Django project, data models and load-aware routing | 2026-11-07 | 2026-11-13 | Roman |  |
| [#16](https://github.com/Leenday/support_megatron_mk1/issues/16) | Django admin: users, roles, departments, all tickets | 2026-11-13 | 2026-11-19 | Roman |  |
| [#17](https://github.com/Leenday/support_megatron_mk1/issues/17) | Request form connected to the pipeline | 2026-11-07 | 2026-11-14 | Denis |  |
| [#18](https://github.com/Leenday/support_megatron_mk1/issues/18) | Specialist dashboard: take tickets and change statuses | 2026-11-12 | 2026-11-24 | Daniil |  |
| [#23](https://github.com/Leenday/support_megatron_mk1/issues/23) | Translation RU <-> EN (if time allows) | 2026-11-16 | 2026-11-24 | Denis |  |
| [#19](https://github.com/Leenday/support_megatron_mk1/issues/19) | Iteration 2 testing | 2026-11-23 | 2026-11-27 | All |  |
| [#20](https://github.com/Leenday/support_megatron_mk1/issues/20) | Voice input with Whisper (optional) | 2026-11-28 | 2026-12-05 | Denis |  |
| [#21](https://github.com/Leenday/support_megatron_mk1/issues/21) | Final metrics and report | 2026-11-28 | 2026-12-10 | All |  |
| [#22](https://github.com/Leenday/support_megatron_mk1/issues/22) | Final presentation | 2026-12-07 | 2026-12-14 | All |  |

## Stages

| Stage | Due | Result |
|---|---|---|
| 0 · Initiation and methods review | 2026-10-16 | Idea, first presentation, methods review, impact map, calendar plan. |
| 1 · Console MVP | 2026-11-06 | Iteration 1: console app, text in -> JSON ticket out; test set and model comparison. |
| 2 · Service | 2026-11-27 | Iteration 2: Django service: request form, specialist dashboard with statuses, Django admin, load-aware routing, RU/EN translation if time allows. |
| 3 · Final | 2026-12-14 | Optional voice input, final metrics, report and final presentation. The programme ends in mid-December; exact date to be confirmed. |

*Dates after 2026-10-16 are planned and may shift; the final date depends on the programme schedule (mid-December).*
