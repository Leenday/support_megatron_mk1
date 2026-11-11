# Iteration 2 testing (#19)

Checked on 2026-11-11 on the `develop` branch after #15, #17, #42, #18 and #35, before the admin panel (#16, PR #52). The check is rerun after #52 is merged and before the v0.2.0 release.

How:

- **User stories:** [e2e/acceptance.py](../e2e/acceptance.py) in Chrome against the service in Docker with Postgres (`LLM_BACKEND=fake`, so the routed departments are predictable). It acts as a requester, two specialists and the admin, and the admin creates the specialists in the admin panel. Rerun: README "Acceptance check".
- **Time to ticket with the real model:** 5 synthetic requests through the form with gpt-5.4-mini.
- **Regression:** each test set's department config imported into the database, exported again (`export_departments`), and the evaluation rerun with gpt-5.4-mini v3 on the exported config.
- **Unit tests:** 211 (`uv run pytest`), no network.

## User stories

✅ works · 🟡 works with a limit (see the note) · ⏳ waits for the admin panel (#16)

| Story | | Result | Note |
|---|---|---|---|
| 1 | Free-text web form | ✅ | Two fields, text and contact; no login |
| 2 | Russian or English | ✅ | An English request gets an English page and is routed |
| 3 | Ticket in ≤ 10 s | ✅ | gpt-5.4-mini: 1.2–1.9 s from "Send" to the status page (5 requests, all routed correctly) |
| 5 | Confirmation with the ticket number | ✅ | "Заявка №N принята и направлена в отдел «…»" |
| 6 | Department shown | ✅ | In the confirmation and on the status page, in the interface language |
| 7 | Status check | ✅ | By the status link, not by the bare number: numbers are consecutive, so the link carries a secret code; a wrong code gives 404 (a deliberate change, #17) |
| 11 | Original message | ✅ | On the ticket page, with the contact |
| 14 | Routing by profile and load | ✅ | Load = open tickets / capacity, counted live; a full best fit losing to a free second candidate is covered by `tests/test_routing.py` and `tests/test_services.py` (the fake backend gives one candidate) |
| 15 | Return a misrouted ticket | ✅ | One form with a reason; goes to the best untried candidate, then the fallback |
| 16 | Department queue | ✅ | New tickets of the department, oldest first |
| 17 | Take a ticket | ✅ | One click; a second specialist taking the same ticket is refused |
| 18 | Statuses | ✅ | New → In progress → Done; the requester's status page follows |
| 19 | My tickets | ✅ | |
| 20 | Edit own tickets | ✅ | The history keeps old and new values |
| 21 | Filters | ✅ | Status, tag, date range |
| 22 | Users with a role and a department | ✅ | Created in the admin panel; they log in to the dashboard. Deleting is possible in the plain admin; #16 replaces it with deactivation |
| 23 | Departments with descriptions | ✅ | Added, edited, deactivated (never deleted: tickets refer to them) |
| 24 | Department capacity | ✅ | Used by the load at once (`/api/departments`) |
| 25 | Department language | 🟡 | Set and saved; translating tickets into it is #23 (iteration 3, as planned) |
| 26 | Routing weights | ✅ | Changed in the admin panel and used by the next request |
| 27 | All tickets with status and assignee | ⏳ | All tickets are listed, without status and assignee columns |
| 28 | Edit or reassign any ticket | ⏳ | Works (after the fix below), but the reassignment is not recorded as an event |
| 29 | Open tickets per department | ⏳ | In `GET /api/departments`; not yet in the admin panel |
| 33 | Log of requests and answers | ✅ | Every request with its text, model, prompt version, attempts, time, dropped identifiers and error |

20 of 24 stories work, 1 works with a planned limit (25), 3 wait for #16 (27–29).

## Bugs found and fixed

1. **The admin could not save a ticket without identifiers or tags** (stories 23, 28). An empty JSON list counted as a missing value, so most tickets could not be reassigned in the admin panel, and a department without tags could not be saved. Fixed: `blank=True` on `Ticket.identifiers`, `Ticket.tags`, `Department.tags`, `Request.dropped_identifiers` (migration 0005), test `test_admin_saves_a_ticket_without_identifiers`.
2. **A misconfigured model backend lost the request** (story 31). With `LLM_BACKEND=openai` and no key, the form answered 500 and nothing was saved. Fixed: a missing key is a `BackendError` like a wrong one, `create_ticket` saves the request with the error, the API answers 502, the CLIs print the error instead of a traceback. Tests `test_unconfigured_backend_keeps_the_request`, `test_cli_reports_an_unconfigured_backend`.

## Regression: departments from the database

The database is now the source of truth for departments, so the evaluation was rerun on a config that went YAML → database → `export_departments`. The RU export is identical to the YAML; the EN one has the same departments in another order (the database sorts by id), which changes the order in the prompt.

| gpt-5.4-mini v3 | Department accuracy | who | where | when | what | identifiers |
|---|---|---|---|---|---|---|
| RU, iteration 1 (YAML) | 0.93 (0.87–0.99) | 0.95 | 0.64 | 0.87 | 0.97 | 0.92 |
| RU, departments from the database | 0.93 (0.87–0.99) | 0.95 | 0.64 | 0.90 | 0.93 | 0.91 |
| EN, iteration 1 (YAML) | 0.28 (0.19–0.37) | 0.69 | 0.89 | — | 0.63 | — |
| EN, departments from the database | 0.27 (0.18–0.35) | 0.74 | 0.88 | — | 0.70 | — |

No regression: every difference is inside the 95 % ranges, the variation of the model's answers between runs. All 179 answers are valid on the first try.

## Open

- Stories 27–29 → #16 (PR #52); rerun the check after it is merged.
- Release v0.2.0 after #16.
