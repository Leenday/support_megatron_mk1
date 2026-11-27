# Iteration 3 testing (#79)

Checked on 2026-11-27 on the `develop` branch at a7d0a86, before the v0.3.0 release. Since the last run (2026-11-19, [testing-iteration2.md](testing-iteration2.md)) `develop` got similar solved tickets as examples (#67), abstaining from routing (#73), department corrections reviewed by a Validator (#75) and the admin panel fixes (#77, PR #78).

How:

- **User stories:** [e2e/acceptance.py](../e2e/acceptance.py) in Chrome against the service in Docker with Postgres (`LLM_BACKEND=fake`), as a requester, two specialists and the admin. Rerun: README "Acceptance check".
- **Unit tests:** 288 (`uv run pytest`, no network), 246 on 2026-11-19.

## User stories

24 stories: 21 pass, 3 partial, 0 failed. Same result as on 2026-11-19. The three partial ones are limits known in advance, not regressions:

| Story | | Note |
|---|---|---|
| 7 | Status check | By the link with a secret code, not by the bare number: a deliberate change (#17) |
| 14 | Routing by profile and load | The fake backend gives one candidate, so the choice by load is covered by `tests/test_routing.py` and `tests/test_services.py` |
| 25 | Department language | Set and saved; translating tickets into it is #23, moved to the backlog |

## Iteration 3 functions

The acceptance script covers the iteration 2 user stories. The iteration 3 functions are covered by unit tests:

| Function | Issue | Tests |
|---|---|---|
| Systems vocabulary grown from closing answers, reviewed by a Validator | #57 | `tests/test_vocabulary.py` (17) |
| Similar solved tickets as examples for the model | #67 | `tests/test_examples.py` (8) |
| Abstaining when the model and the history classifier disagree | #73 | `tests/test_abstain.py` (10) |
| Department corrections at closing, reviewed by a Validator | #67, #75 | `tests/test_department_review.py` (5) |
| Extended admin panel, department names in the interface language | #16, #77 | `tests/test_admin_panel.py` (9) |
| Triage-time measurement | #43 | `tests/test_triage.py` (7) |

The quality numbers of these functions (department accuracy with examples, share of wrong routes with abstaining, local models) are in [results.md](results.md).

## Fixed since iteration 2

- The admin panel at a 1200 px window and Russian department names in the admin lists, the "Open" item of [testing-iteration2.md](testing-iteration2.md): fixed in #77 (PR #78).
