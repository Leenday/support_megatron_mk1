---
name: git-workflow
description: Branching, commit and merge procedure for Megatron-mk1 (simplified git-flow). Use before creating a branch, committing, merging, tagging a release or opening a PR in this repository.
---

# Git workflow for Megatron-mk1

Simplified git-flow, based on "A successful Git branching model" by V. Driessen
(Russian translation: https://habr.com/ru/articles/106912/). Release branches are dropped
because each iteration is a single release.

## Branches

| Branch | From | Merges into | Purpose |
|---|---|---|---|
| `main` | — | — | Released code only. Every merge into `main` is tagged. |
| `develop` | `main` | `main` (at iteration end) | Integration branch; always passes tests. |
| `feature/<issue>-<slug>` | `develop` | `develop` | One GitHub issue, one branch. Example: `feature/6-ticket-schema`. |
| `hotfix/<version>` | `main` | `main` and `develop` | Only for an urgent fix of a released version, e.g. `hotfix/0.1.1`. |

Rules:
- Never commit directly to `main` or `develop` (the `no-commit-to-branch` pre-commit hook enforces this).
- `<slug>` is lowercase English, words separated by `-`, 2–4 words.
- Delete a feature branch after it is merged.

## Commits

Conventional Commits 1.0.0 (https://www.conventionalcommits.org/en/v1.0.0/), in English:

```
<type>(<scope>): <imperative summary, ≤ 72 chars>

<optional body: what and why>

Refs #<issue>
```

- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `ci`, `chore`.
- Scopes (optional): `schema`, `config`, `llm`, `routing`, `cli`, `eval`, `docker`, `web`.
- **No attribution of AI tools.** Never add `Co-Authored-By: Claude …` or "Generated with Claude Code"
  to commits or PR descriptions. `.claude/settings.json` disables it and the `commit-msg` hook rejects it.
- One logical change per commit; run `uv run pytest` and `uv run pre-commit run --all-files` first.

## Procedure

Start a feature:
```bash
git switch develop && git pull --ff-only
git switch -c feature/<issue>-<slug>
```

Finish a feature (tests green):
```bash
git switch develop
git merge --no-ff feature/<issue>-<slug> -m "Merge branch 'feature/<issue>-<slug>' into develop"
git branch -d feature/<issue>-<slug>
```
On GitHub the same is done by a PR into `develop` with "Create a merge commit"; put `Closes #<issue>` in the PR body.

Release at the end of an iteration (v0.1.0 = console MVP, v0.2.0 = Django service):
```bash
git switch main
git merge --no-ff develop -m "Release v0.X.0"
git tag -a v0.X.0 -m "Iteration X"
```
Bump `version` in `pyproject.toml` on `develop` before the release merge.

Pushing, opening PRs and tagging on the remote are outward-facing: ask the user first.
