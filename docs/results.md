# Results: models × metrics (iteration 1)

Measured on 2026-11-05 with `megatron-eval` (see README "Evaluation"). The test sets are not in the repository: the Russian one is real anonymized requests, the English one is built from a public data set with `megatron-testset`.

| Set | Requests (dev / test) | Departments | Gold subset (fields checked by hand) |
|---|---|---|---|
| RU | 30 / 69 | 2 support lines (real requests, anonymized) | 30 test requests |
| EN | 40 / 110 | 10 queues of the public Tobi-Bueck data set (`config/queues_en.yaml`) | 30 test requests |

Systems: two baselines trained on the dev part (majority class; TF-IDF character n-grams + logistic regression), OpenAI gpt-5.4-mini and gpt-5.4-nano with prompt v1 / v3 (`PROMPT_VERSION`), and the local qwen3:1.7b via Ollama in Docker on a CPU. Ranges are 95 % bootstrap intervals (1000 resamples).

## Department (test part)

| RU | Requests | Accuracy | Macro-F1 | Expected in candidates | Valid | s/request, median · p90 |
|---|---|---|---|---|---|---|
| majority class | 69 | 0.71 (0.61–0.81) | 0.42 (0.38–0.45) | — | — | — |
| TF-IDF + logistic regression | 69 | 0.91 (0.84–0.97) | 0.89 (0.80–0.96) | — | — | — |
| gpt-5.4-mini, prompt v1 | 69 | 0.91 (0.84–0.97) | 0.90 (0.81–0.97) | 0.91 | 1.00 | 1.5 · 1.7 |
| **gpt-5.4-mini, prompt v3** | 69 | **0.93 (0.87–0.99)** | **0.91 (0.83–0.98)** | 0.93 | 1.00 | 1.6 · 1.9 |
| gpt-5.4-nano, prompt v3 | 69 | 0.86 (0.77–0.93) | 0.83 (0.73–0.92) | 0.86 | 1.00 | 1.7 · 2.0 |
| qwen3:1.7b, prompt v1 (partial) | 17 | 0.29 (0.12–0.53) | 0.23 (0.11–0.35) | 0.29 | 1.00 | 175.8 · 338.0 |

| EN | Requests | Accuracy | Macro-F1 | Expected in candidates | Valid | s/request, median · p90 |
|---|---|---|---|---|---|---|
| majority class | 110 | 0.10 (0.05–0.16) | 0.02 (0.01–0.03) | — | — | — |
| TF-IDF + logistic regression | 110 | 0.22 (0.15–0.29) | 0.22 (0.14–0.28) | — | — | — |
| gpt-5.4-mini, prompt v1 | 110 | 0.25 (0.17–0.35) | 0.22 (0.15–0.28) | 0.36 | 1.00 | 1.4 · 1.7 |
| gpt-5.4-mini, prompt v3 | 110 | 0.28 (0.19–0.37) | 0.23 (0.16–0.28) | 0.39 | 1.00 | 1.6 · 1.9 |
| gpt-5.4-nano, prompt v3 | 110 | 0.28 (0.20–0.37) | 0.24 (0.17–0.29) | 0.40 | 1.00 | 1.3 · 1.5 |

The EN queue labels often do not follow from the text (for example a data breach labelled as customer service), so every system stays low there; the EN set is used for the fields and for reproducibility.

## Fields (gold subset): F1 (range)

| RU | who | where | when | what | identifiers |
|---|---|---|---|---|---|
| gpt-5.4-mini, prompt v1 | 0.83 (0.69–0.95) | 0.61 (0.43–0.78) | 0.90 (0.71–1.00) | 0.87 (0.73–0.97) | 0.93 (0.83–0.98) |
| **gpt-5.4-mini, prompt v3** | **0.95 (0.86–1.00)** | **0.64 (0.47–0.81)** | 0.87 (0.69–1.00) | **0.97 (0.90–1.00)** | 0.92 (0.80–0.97) |
| gpt-5.4-nano, prompt v3 | 0.80 (0.65–0.91) | 0.39 (0.21–0.57) | 0.75 (0.52–0.91) | 0.83 (0.70–0.93) | 0.91 (0.81–0.97) |
| qwen3:1.7b, prompt v1 (7 gold) | 0.18 | 0.43 | 0.00 | 0.43 | 0.60 |

| EN | who | where | when | what | identifiers |
|---|---|---|---|---|---|
| gpt-5.4-mini, prompt v1 | 0.42 (0.12–0.67) | 0.82 (0.67–0.93) | 1.00 | 0.43 (0.23–0.60) | — |
| **gpt-5.4-mini, prompt v3** | **0.69 (0.46–0.87)** | **0.89 (0.78–0.98)** | 0.67 | 0.63 (0.47–0.80) | — |
| gpt-5.4-nano, prompt v3 | 0.35 (0.00–0.63) | 0.75 (0.57–0.89) | 0.67 | 0.70 (0.53–0.87) | — |

"—": nothing to score (the EN gold has no identifiers). EN "when" rests on 1–2 gold requests, so its value is not meaningful.

## Rules for identifiers and dates (#35)

Measured on 2026-11-10 with `megatron-eval <set> --rules`: the rules only post-process an answer, so they are applied to the saved answers above, without new model calls. Two variants: the **shape filter** (an identifier without a digit that is not an e-mail, a placeholder or a login like `a.smirnova` is dropped) and the filter **plus additions** (codes the model missed, found by the patterns of `megatron-testset`, and an empty "when" filled from an explicit date). The gold drafts were made by the same patterns and then corrected by hand, so if anything the additions are favoured here.

| RU, identifiers | F1 (range) | Precision / recall | Changed |
|---|---|---|---|
| gpt-5.4-mini v3 | 0.92 (0.80–0.97) | 0.93 / 0.91 | — |
| **+ shape filter** | **0.92 (0.81–0.97)** | **0.94 / 0.91** | 5 dropped in 5 of 69 tickets |
| + shape filter + additions | 0.78 (0.59–0.94) | 0.64 / 0.99 | + 74 added |
| gpt-5.4-nano v3 | 0.91 (0.81–0.97) | 0.89 / 0.93 | — |
| **+ shape filter** | **0.92 (0.83–0.98)** | **0.91 / 0.93** | 5 dropped in 5 of 69 tickets |
| + shape filter + additions | 0.78 (0.59–0.93) | 0.64 / 0.99 | + 73 added |

- **Shape filter: kept.** It never dropped an identifier of the gold, and on EN, where the gold has none, it removed every identifier gpt-5.4-mini v3 had made up (2 tickets). It is what the iteration 1 review asked for (`asdfgh` from `asdfgh 12345`).
- **Additions: off.** The model already finds 0.91–0.93 of the identifiers, and the patterns also catch numbers that the gold does not count as identifiers (4–6-digit numbers, anonymisation placeholders, codes): on the gold subset 8 of 57 additions were right. "When" from a date never fired on RU, where the model fills it; on EN it filled 4–6 tickets and lowered the "when" F1 from 0.67 to 0.50 (one gold request, not meaningful). The additions stay in `megatron/rules.py` (`add=True`) to be measured again on new sets.
- Department accuracy and the other fields do not change: the rules touch only identifiers and "when".

## Systems vocabulary (#34)

Measured on 2026-11-12. The department config got a vocabulary of systems with their spellings; the ticket's `systems` is a list of its ids (an enum, like the departments), listed in prompt v4. A list rather than one system: in the RU gold "where" often names an integration of two systems ("CRM → messenger"). The RU vocabulary has 17 systems (the company's channels and integrations, built from the dev part and the department descriptions; it stays in `data/local`, like the RU set). The EN data set is synthetic and names a different product in most requests, so its vocabulary is 16 product categories (`config/queues_en.yaml`). The gold `systems` were drafted from the spellings and checked by hand (RU: 11 of 30 drafts corrected, EN: 8 of 30). A stricter instruction (v5: "not a guessed cause, the topic, the industry") was tried on dev and gave nothing beyond run-to-run noise, so v4 stays.

| gpt-5.4-mini, test gold | systems F1 (range) | Precision / recall | Exact set | "where" F1 | Department accuracy |
|---|---|---|---|---|---|
| RU, prompt v3 (no vocabulary) | — | — | 0.10 | 0.64 | 0.93 |
| **RU, prompt v4** | **0.91 (0.85–0.96)** | 0.89 / 0.94 | **0.73 (0.57–0.87)** | 0.64 | 0.93 |
| RU, spellings only (no model) | 0.88 | 0.84 / 0.92 | 0.63 | — | — |
| EN, prompt v3 (no vocabulary) | — | — | 0.30 | 0.89 | 0.28 |
| EN, prompt v4 | 0.73 (0.63–0.83) | 0.59 / 0.96 | 0.57 (0.40–0.73) | 0.84 | 0.27 |
| EN, spellings only (no model) | 0.76 | 0.68 / 0.88 | 0.73 | — | — |

- **RU: the place of the problem is now measurable and filterable.** The model names the right set of systems in 0.73 of the gold requests and reaches F1 0.91, slightly above matching the spellings alone (0.88). That baseline is favoured here: the gold drafts came from it. Free-text "where" is unchanged (0.64): the vocabulary did not make the model word it more consistently.
- **"where" scored with the vocabulary.** Following the course (session 03: "Winder 3" / "WIN 3" / "winder #3" is a normalisation problem, measured on the canonical id; session 08: gold answers with aliases), "where (vocab)" counts a "where" as right when the words match, as before, **or** both texts name the same non-empty set of vocabulary systems ("амо → тг" = "amoCRM → Telegram"; one of two systems is still a miss). RU: **0.81 (0.67–0.93)** with prompt v4 and 0.78 with v3, against 0.64 by words alone, so the misses were spellings, not wrong places. EN does not change (0.84): its misses are not spellings. "where" values naming no system are counted (RU v4: 9 of 69 tickets) and listed in `out/eval/<set>/where-outside-vocabulary.tsv` as candidates for the vocabulary; it is extended from new requests, not from the test part. In iteration 3 (#57) it grows from the specialists' answers when they close tickets, approved by a Validator.
- **EN: the model adds categories.** Recall is 0.96, but precision 0.59: it also tags a guessed cause ("server overload") or the topic (security). Spelling matching is as good or better here; the EN labels are categories assigned by meaning, so they are less certain than the RU ones.
- Department accuracy and the other fields stay within their ranges (RU "what" 0.97 → 0.87 and "who" 0.95 → 0.98 move within the ranges of 30 requests).

## Departments from the database (#19)

On 2026-11-11 the evaluation was rerun on configs exported from the service database (`export_departments`): RU department accuracy 0.93 (0.87–0.99), the same as with the YAML; EN 0.27 (0.18–0.35) against 0.28; the fields move within their ranges. Details: [testing-iteration2.md](testing-iteration2.md).

## Triage time (#43)

On 2026-11-17 one participant triaged 30 RU test requests outside the gold subset: 15 by hand (department, who / where / when / what) and 15 by checking the service's ticket, in alternating blocks of 5, timed on a local page (`megatron-triage`). Median 31.2 s by hand against 9.7 s with the service (8.3 s check + 1.5 s model): **69 % shorter (95 % range 44–79 %)**, goal 30 %. Department right: 73 % by hand, 93 % with the service (ranges overlap). The participant kept every service department, including the one wrong, so checks need the Validator (#57). On 2026-11-23 a second participant, a team member, triaged 30 requests of the harder local `buckets` set (three buckets of another support team; the service right on 23 of 30) with the halves swapped: median 76.1 s by hand against 41.2 s with the service, **46 % shorter (95 % range −3–67 %)**, so not proven on this set; after the first block the gain is near 30 %. Department right: 47 % by hand, 73 % with the service; the person kept both service errors and changed two right departments to wrong ones. Method, checks and limits: [triage-time.md](triage-time.md).

## Department descriptions that say when to choose (#67, step 1)

On 2026-11-23 the EN queue descriptions were rewritten as "choose when … · not when … → X", from the labels of the dataset's 16 230 English tickets outside the test set. For example, 50 % of the questions about prices and plans are billing, and only 3 % of all tickets are sales, while prompt v4 sent 40 % of the dev requests to sales. gpt-5.4-mini, prompt v4, the same program:

| EN | Requests | Accuracy | Macro-F1 | Expected in candidates |
|---|---|---|---|---|
| dev: v4 descriptions | 40 | 0.20 (0.10–0.33) | 0.17 (0.07–0.25) | 0.40 |
| dev: "when to choose" | 40 | 0.23 (0.10–0.35) | 0.23 (0.10–0.32) | 0.30 |
| test: v4 descriptions | 110 | 0.27 (0.19–0.36) | 0.22 (0.15–0.27) | 0.44 |
| test: "when to choose" | 110 | 0.22 (0.15–0.29) | 0.18 (0.12–0.23) | 0.30 |

**No gain; the v4 descriptions stay.** The sales bias went (sales answers on test 35 → 1), but the answers moved to the dataset's large queues: technical and product support got 97 of the 110 answers, against 48 % of the pool. The test part is balanced, 11 requests per queue, so the answers that follow the dataset's proportions lose the sales hits and gain little elsewhere, because the text says little about the label. Descriptions alone cannot fix labels that do not follow from the text; step 2 below does better. The run is `out/eval/en/gpt-5.4-mini-v4-when.jsonl`; RU uses its own departments and is not affected.

## Similar solved tickets as examples (#67, step 2)

For each request the 5 most similar solved tickets go before it as data, each with its queue (`megatron-eval --examples`, `src/megatron/examples.py`). The pool is the dataset's 16 229 English tickets outside the test set. The synthetic set has near-duplicates: 65 % of the test requests have a ticket with cosine > 0.8 in the pool, which would hand the model the answer. So every number below leaves those out (`--skip-similar 0.8`). With them the neighbours' vote alone reaches 0.65, a leak, not a result. Retrieval is measured apart from the answer: the right queue is among the 5 neighbours for 0.65 of the test requests (0.70 on dev), which is the ceiling of what the examples can teach.

| EN test, 110 requests | Accuracy | Macro-F1 | Expected in candidates | Paired against v4 (95 % range) |
|---|---|---|---|---|
| gpt-5.4-mini, prompt v4 | 0.27 (0.19–0.36) | 0.22 | 0.44 | — |
| v4 + "when to choose" descriptions (step 1) | 0.22 (0.15–0.29) | 0.18 | 0.30 | −0.055 (−0.127 to +0.018) |
| **v4 + 5 similar solved tickets** | **0.35 (0.26–0.45)** | **0.32** | **0.55** | **+0.082 (+0.009 to +0.155)** |
| TF-IDF + logistic regression on the pool, no LLM | 0.40 | 0.40 | — | +0.127 (+0.009 to +0.245) |

On dev: v4 0.20, with examples 0.30, logistic regression 0.47.

- **The examples help**, and the paired comparison shows it: 13 requests gained, 4 lost. The model now sees how this dataset routes, which its descriptions could not tell it (step 1).
- **The simple baseline is not beaten** (session 06: "did the model earn its complexity?"). Logistic regression trained on the same pool is +0.045 above the examples, a difference the paired test cannot tell from noise (−0.073 to +0.155). It is well calibrated: at a probability ≥ 0.5 it covers 26 % of the test requests with 0.83 accuracy. A hybrid (the classifier when it is confident, else the model) was chosen on dev, and dev picked the classifier for every request, so the hybrid is not claimed: a better threshold seen only on test would be tuning on test.
- **What it means for the service.** Without a history (a new company) the model with department descriptions is the only option, and on our real RU set it gives 0.93. Once there are a few thousand tickets with a confirmed department, the history is worth more than the descriptions: as examples for the model, or as a classifier next to it. Either way it must be confirmed history, so a specialist's department correction goes to the Validator first (#67).
- RU is not affected: examples are off unless `--examples` is given, and the prompt without them is v4 unchanged.

## Choice of model

**gpt-5.4-mini with prompt v3** is the model for iteration 2.

- It is the best system on the Russian set in every column. gpt-5.4-nano is cheaper and as fast, but loses 0.07 department accuracy (0.86, the lower range end below the 0.85 target) and most of the field quality ("where" 0.39 vs 0.64, "who" 0.80 vs 0.95).
- TF-IDF matches it on the department with two lines (the ranges overlap), but needs labelled tickets and fills no fields, so it stays the baseline.
- qwen3:1.7b in Docker on a CPU is not usable (0.29 accuracy, about 3 minutes per request). Larger local models with GPU acceleration are moved to #44; story 30 ("requests do not leave the company") stays open until then.
- The backend stays switchable (`--backend`, `--model`, `LLM_BACKEND`), so the choice can change without code changes.

## Target values

| Metric | Target | Now (RU, gpt-5.4-mini v3) | Status |
|---|---|---|---|
| Department accuracy (story 13) | ≥ 0.85 | 0.93 (0.87–0.99) | met |
| Valid tickets (story 31) | 100 % | 100 % | met |
| Time to ticket (story 3) | ≤ 10 s | 1.6 s median, 1.9 s p90 | met |
| "who", "what" F1 (story 8) | ≥ 0.90 | 0.95, 0.97 | met |
| "when", identifiers F1 | ≥ 0.85 | 0.87, 0.92 (with the shape filter, #35) | met |
| "where" F1 | ≥ 0.75 | by words 0.64; with the vocabulary 0.81 (0.67–0.93); `systems` F1 0.91 (#34) | met with the vocabulary (lower range end 0.67); by words open |
| Triage time, request → ticket in work (business goal) | −30 % | triage −69 % (44–79 %) on `ru`: 31 s → 10 s, median; −46 % (−3–67 %) on `buckets`: 76 s → 41 s (#43) | met on `ru` (the author); on `buckets` (a second participant) met at the median, not proven; queue time not measured |
| Local model as an alternative (story 30) | ≥ 0.85 accuracy, ≤ 10 s | 0.29, ~3 min (qwen3:1.7b, CPU) | open: #44 |
