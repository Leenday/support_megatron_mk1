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

## Departments from the database (#19)

On 2026-11-11 the evaluation was rerun on configs exported from the service database (`export_departments`): RU department accuracy 0.93 (0.87–0.99), the same as with the YAML; EN 0.27 (0.18–0.35) against 0.28; the fields move within their ranges. Details: [testing-iteration2.md](testing-iteration2.md).

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
| "where" F1 | ≥ 0.75 | 0.64 | open: #34 |
| Triage time, request → ticket in work (business goal) | −30 % | — | measured in #43 |
| Local model as an alternative (story 30) | ≥ 0.85 accuracy, ≤ 10 s | 0.29, ~3 min (qwen3:1.7b, CPU) | open: #44 |
