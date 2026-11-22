# Design note: splitting a request across departments (#45)

The idea comes from the supervisor's review of iteration 1 (30.10). One request can concern several departments ("the printer does not print, and the network folder does not open"). Each department should read only its own part. That means less to read, and a confidential part (a phishing click, a lost phone) does not reach everyone. The supervisor said it does not have to be implemented, only worked out. This note does that. Nothing here is implemented yet.

## Where the service stands

- **The model** returns one ticket per request: one `what`, `summary`, `tags` and `systems`, and a ranked list of 1–3 `candidates` ([src/megatron/ticket.py](../src/megatron/ticket.py)). Routing picks one of the candidates ([src/megatron/routing.py](../src/megatron/routing.py)). A second topic is lost or merged into the first ticket's `what`.
- **The database** already allows a request to have many tickets: `Ticket.request` is a foreign key with `related_name="tickets"` ([web/support/models.py](../web/support/models.py)). The API (`RequestOut.tickets`) and the requester's status page already list every ticket of a request. Only `create_ticket` ([web/support/services.py](../web/support/services.py)) creates exactly one.
- **The specialist's ticket page** shows the whole `Request.text` ([web/support/templates/support/desk_ticket.html](../web/support/templates/support/desk_ticket.html)). This is the one place where another department's part would leak. The API's `TicketOut` does not include the request text.

## Test set

[data/split_requests.jsonl](../data/split_requests.jsonl) has 15 synthetic requests (9 RU, 6 EN, no real data) for the departments of [config/departments.yaml](../config/departments.yaml):

- 12 multi-topic requests: 11 with two parts and one with three.
- 3 controls: one problem that mentions two departments' topics, and they must not be split. Examples: a VPN refusing an expired password is an account problem, not a network one; a laptop's broken Wi-Fi after a repair is hardware; a phishing e-mail also seen by colleagues is one incident.

The gold labels are given per sentence. Every sentence of the text is copied verbatim either into `shared` (greeting, signature, location: context every part needs) or into the `sentences` of one part with its department. A check confirms that the gold sentences cover each text exactly. This makes both part boundaries and departments measurable without fuzzy text matching.

## Options

The three options from the issue are not exclusive. (a) is how the model produces parts, (b) is how parts are stored and worked on, and (c) is what a specialist sees. Each one is described on its own first.

### (a) The model returns parts in the same structured call

**Schema.** The ticket becomes a request-level object: `who`, `language` and `parts: list[Part]` (1–4 parts). Each `Part` has the per-problem fields (`where`, `systems`, `when`, `what`, `identifiers`, `summary`, `tags`, `candidates`) plus the part's text. One part is exactly today's ticket, so single-topic requests do not change.

There are two ways to give the part's text:

- **a1, copied text** (`text: str`). The model may paraphrase, shorten or drop a sentence, and the only check is a fuzzy substring match.
- **a2, sentence numbers.** The request is split into numbered sentences before the call (a regex splitter on `.!?`, line breaks and list markers, RU and EN), and the model answers `sentences: list[int]` per part plus `shared: list[int]`. The validator then checks hard invariants: every sentence is used, numbers exist, no part is empty. On a violation it retries with the error, as `Extractor` already does for schema errors. A lost sentence becomes impossible by construction.

**Routing.** Each part is routed on its own `candidates` with the existing score. If two parts land in one department, they are merged into one ticket, so a department never gets two tickets for one request.

**Cost.** Still one model call, with a longer schema and prompt (prompt v5). The answer grows with the number of parts.

**Risks.** Over-splitting one problem into two (the controls above). The fallback `general` getting a "part" that is only a greeting. A sentence that mixes two topics ("the printer and the VPN do not work") can only go to one part, unless a sentence may belong to several parts. Small local models (qwen3:1.7b) already struggle with the current schema.

### (b) A parent request with a child ticket per part

**Schema.** No new tables: `Request` is the parent, and each part becomes a `Ticket`. `Ticket` gets `part_sentences` (JSON, sentence numbers) and `Request` gets `sentences` (the split text, so the numbers stay valid). Each child ticket has its own status, assignee, events and department load. The request is done when all its tickets are done.

**Routing and workflow.** Load counts each child ticket, as now. Returning a ticket re-routes only that part. Its `TicketEvent` records the part, so the admin can see which part was moved.

**What the requester sees.** One status link with a line per part ("Printer — in progress, Network folder — done"). The page already lists all tickets.

**Risks.** A part that cannot be solved without the other one (a computer that is not connected and the software install on it). The specialists then need to see that the request has sibling tickets, and possibly in which department. Without a split model (a) this option has nothing to store, so it needs either (a) or a person who splits by hand.

### (c) Each department sees the whole text with the other parts masked

**What the specialist sees.** The request text with their own part highlighted, the shared sentences visible, and every other part replaced by a placeholder: «[часть для другого отдела]» or "[part for another department]". The department's name is not shown, because a name like "Information security" already reveals something. Admins and Validators see everything, as they do now (`visible_tickets`).

**Schema.** It needs the same sentence numbers as (a2), since masking works on sentences. Masking happens when the page is rendered. The database still stores the full text, so this is need-to-know in the interface, not encryption.

**Risks.** If the split is wrong, the specialist may not see a sentence they need. That is why the placeholder stays visible: it shows that something was hidden, and the specialist can return the ticket or ask an admin. The model's own fields can also leak: a part's `what` or `tags` may mention another part. The validator can check that a part's identifiers and systems occur in its own sentences or in the shared ones.

## Chosen approach

All three together, each where it is strongest:

1. **(a2) extraction with sentence numbers.** It is one call and its coverage is checked, not hoped for. Copied text (a1) is rejected: the only defence against a lost sentence would be fuzzy matching.
2. **(b) storage** in the existing `Request → Ticket` relation. There is no new model, and the API and the status page need almost no change.
3. **(c) masking** on the specialist's ticket page. This is what makes the split useful for confidentiality: without it every department still reads the whole text.

It is turned on by a setting (`SPLIT_REQUESTS`, off by default), so the measured single-ticket pipeline (prompt v4) stays the baseline. Splitting ships only if the measurement below shows it does not make single-topic requests worse.

## Effort estimate

| Step | Days |
|---|---|
| Sentence splitter (RU/EN, lists, abbreviations) + tests | 0.5 |
| Schema (`Part`, request-level ticket), prompt v5, validator invariants with retry | 1 |
| Routing per part, merging parts with the same department; CLI output with parts | 0.5 |
| Evaluation: split metrics in `megatron-eval`, scoring `split_requests.jsonl` | 1 |
| Django: migration (`Request.sentences`, `Ticket.part_sentences`), `create_ticket` for n parts, masking on the desk page, return of a single part, status page lines | 1.5–2 |
| Tests for the service and the acceptance check | 1 |
| **Total** | **≈ 5.5–6** |

This does not fit in what is left of iteration 3 (until 27.11). In the final iteration it competes with the final metrics and the report. If there is time, a CLI-only prototype (the first three rows plus the evaluation, about 3 days) is enough to measure the idea without touching the service.

## Measurement plan

On [data/split_requests.jsonl](../data/split_requests.jsonl) (15 requests, 32 sentences in parts):

- **Number of parts:** the share of requests with the gold number of parts, and separately the over-split rate on the 3 controls.
- **Sentence accuracy:** the share of non-shared sentences that go to a part of their gold department. It covers part boundaries and the department per part at once. Its complement is the **leak rate**, the share of sentences a wrong department would see unmasked. This is the confidentiality metric.
- **Boundaries alone:** pairwise F1 over sentence pairs ("in the same part or not"), independent of department labels. It separates "split in the wrong place" from "split right, routed wrong".
- **Department per part:** parts matched to gold parts by the largest sentence overlap, then accuracy of the routed department.
- **Shared sentences:** the share of gold `shared` sentences put in `shared`. Signatures put in a part are harmless; a problem sentence put in `shared` is a leak and counts against the leak rate too.
- **Lost sentences:** must be 0. The validator enforces it, and the evaluation reports it in case a retry gives up.

A regression check runs on the existing test sets (RU 69, EN 110 requests, almost all single-topic):

- the over-split rate on them: the share of requests answered with more than one part;
- department accuracy of the first part against prompt v4 in [docs/results.md](results.md), with bootstrap ranges. If the ranges overlap, the split costs nothing on ordinary requests.

Suggested targets: over-split ≤ 5 % on the single-topic sets, sentence accuracy ≥ 0.85 and leak rate ≤ 0.10 on the split set, and no drop in department accuracy beyond the bootstrap range. Fifteen requests give wide ranges. The set can be grown with the same format, for example from real multi-topic requests found in `data/local/ru`, which stay local.

## Open questions

- Should one sentence be allowed in several parts (for a sentence that mixes two topics)? It is simpler to forbid it first and count how often it happens.
- Should a specialist see that the request has sibling tickets, and in which departments? Seeing that they exist helps with dependent parts; seeing the departments leaks a little.
- A department outside IT (accounting, HR, as in the supervisor's example) would only need a new entry in the config. The approach does not depend on which departments exist.
