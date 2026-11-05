---
name: git-workflow
description: Branching, commit, pull request and release procedure for Megatron-mk1 (git-flow with PRs). Use before creating a branch, committing, pushing, opening a PR or preparing a release in this repository.
---

# Git workflow for Megatron-mk1

Git-flow ("A successful Git branching model", V. Driessen; Russian translation:
https://habr.com/ru/articles/106912/) with every change going through a GitHub pull request.
No release branches: each iteration is one release.

## Branches

| Branch | Lifetime | From | Merges into | How |
|---|---|---|---|---|
| `develop` | permanent, **default branch** | — | `main` at iteration end | release PR, merge commit |
| `main` | permanent | — | — | tagged releases only |
| `feature/<issue>-<slug>` | until merged | `develop` | `develop` | PR, **squash** |
| `hotfix/<version>` | until merged | `main` | `main`, then `develop` | PR into each |

`develop` and `main` are never recreated. GitHub rulesets on both: changes only through a PR,
CI (`lint`, `test (3.12)`, `test (3.13)`, `docker`, and `pr-title` on `develop`) must pass, no force pushes, no deletion.
Allowed merge method: squash into `develop`, merge commit into `main` (a squash there would
break the next release PR). Merged branches are deleted automatically.

## Rules

1. **Issue first.** Every PR belongs to a GitHub issue. No issue for the work (e.g. tooling)? Ask the user to agree on one and create it before the branch.
2. **One issue → one branch → one PR.** Branch `feature/<issue>-<slug>`, slug = 2–4 lowercase English words with `-`. A large issue may take several PRs (`Refs #N` on all but the last).
3. **Never merge locally, never push to `develop`/`main`.** Push the feature branch and open a PR.
4. **The user merges.** Claude creates the branch, commits, pushes and opens the PR (ask before pushing and before opening the PR); the user reviews, attaches the demo and presses *Squash and merge* after CI is green.

## Commits

Conventional Commits 1.0.0 (https://www.conventionalcommits.org/en/v1.0.0/), English, `Refs #N` footer.
Types: `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `ci`, `chore`.
Scopes: `schema`, `config`, `llm`, `routing`, `cli`, `eval`, `docker`, `web`.
Never add `Co-Authored-By: Claude …` or "Generated with Claude Code" (disabled in `.claude/settings.json`, rejected by the `commit-msg` hook). The `commit-msg` hook also rejects messages that are not Conventional Commits.
Run `uv run pytest` and `uv run pre-commit run --all-files` (ruff, ty, deptry) before committing.

## Pull requests

- Base `develop`. **Title = the squash commit title**, so it must be a Conventional Commit: `feat(llm): add Ollama adapter`. The `pr-title` check fails otherwise; after editing the title it reruns.
- Body follows `.github/pull_request_template.md`: What · Issues · How to check · Demo.
- Issues: `Closes #N` only if the PR meets the issue's "Done when"; otherwise `Refs #N`. One keyword per issue: `Closes #8, closes #13`. Keywords work because `develop` is the default branch.
- Demo for behaviour changes: the user records the screen (Cmd+Shift+5) running the command from "How to check" (e.g. a `docker compose run --rm ...` command) and drags the .mov/.mp4 (≤ 10 MB) into the PR. `gh` cannot upload attachments.

```bash
git switch develop && git pull --ff-only
git switch -c feature/<issue>-<slug>
# ... commits ...
git push -u origin feature/<issue>-<slug>
gh pr create --base develop --title "<type>(<scope>): <summary>" --body-file <body.md>
```

After the user merges: `git switch develop && git pull --ff-only` (the local feature branch can be deleted with `git branch -D`, since squash commits are not ancestors of it).

## Release (end of an iteration)

1. Feature PR on `develop` bumping `version` in `pyproject.toml` (e.g. `0.1.0`).
2. PR `develop` → `main` titled `Release v0.X.0`, merged with **Create a merge commit**.
3. Tag the merge commit: `git switch main && git pull && git tag -a v0.X.0 -m "Iteration X" && git push origin v0.X.0` (ask first).
