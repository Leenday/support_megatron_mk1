# Triage time: by hand vs the service (#43)

The business goal is **30 % less time from a request to a ticket taken into work**. Without real specialists we measure the part the system changes, triage: reading a request, choosing the department and writing the ticket. Waiting in the queue is not measured; it depends on staffing, not on the system.

## Method

- **Requests:** 30 requests of the Russian test set that are not in the gold subset (the gold ones were read while labelling), in the support lines' proportions (26 general helpdesk, 4 CRM widgets line). The texts stay in `data/local/` and `out/` and are never committed; only aggregate numbers are reported.
- **Second set, `buckets` (20.11):** 30 test requests of a local sample of 150 real requests of another support team, which a person on the first or second line sorts into three buckets (product, service desk, integrations). The bucket descriptions were tuned on its dev part only (v3; gpt-5.4-mini test accuracy 0.82, TF-IDF 0.85). The service's department is right in 23 of the 30. It is harder than `ru`, and the participants did not write the descriptions.
- **Two modes, each request once.** The requests are split into halves A and B with the labels balanced. Participant 1 triages A by hand and checks B in the service mode; a second participant would swap (`--swap`), so nobody sees a request twice.
  - **By hand:** the page shows the request; the person chooses the department and writes who / where / when / what.
  - **Service:** the same form, already filled with the service's ticket (gpt-5.4-mini, prompt v4, the department after routing); the person checks it and fixes what is wrong. The model's own time from the run log (median 1.5 s) is added to the person's time.
- **Order:** blocks of 5 requests, by hand and checking in turn, so getting faster with practice does not favour one mode.
- **Timing:** in the browser, from showing the request to "Done". Pauses between requests do not count.
- **Result:** median and p90 per mode, the reduction of the median time with a 95 % bootstrap range (each mode resampled separately), the share of right departments per mode, and how often the person kept the service's department or changed nothing.

## Limits

- On `ru` one participant, who knows the departments well (the project author), so the manual baseline is faster than a new operator's; the reduction is rather understated.
- On `buckets` one other team member, with the swapped half (half B by hand, starting with checking). The crossover there is complete once a second participant triages half A by hand (`serve data/local/buckets --participant daniil`); the report then pools both.
- The service tickets were made in advance by the same pipeline the service uses (`megatron-eval --run`), not live through the form; the model's time comes from that run.
- With 15 requests per mode the range is wide.

## How to run

```bash
uv run megatron-triage plan data/local/ru --results out/eval/ru/gpt-5.4-mini-v4.jsonl
DEPARTMENTS_PATH=data/local/ru/departments.yaml uv run megatron-triage serve data/local/ru --participant p1
# open http://127.0.0.1:8743/ and triage all 30 requests (about 40 minutes; pauses are fine)
uv run megatron-triage report data/local/ru     # → out/triage/ru/report.md
# the second set: participants get plan.jsonl and departments.yaml, the first without, the second with --swap
DEPARTMENTS_PATH=data/local/buckets/departments.yaml uv run megatron-triage serve data/local/buckets --participant roman --swap
uv run megatron-triage report data/local/buckets   # → out/triage/buckets/report.md
```

## Results

### `ru`, participant p1 (17.11)

Measured on 2026-11-17, participant p1 (one person, 30 requests: 15 by hand, 15 checking the service). Seconds per request.

| Mode | Requests | Median | p90 | Mean | Department right |
|---|---|---|---|---|---|
| By hand | 15 | 31.2 | 48.2 | 39.3 | 73 % (47–93 %) |
| Service: model + the person's check | 15 | 9.7 | 17.3 | 11.4 | 93 % (80–100 %) |

**The median triage time is 69 % shorter with the service (95 % range 44–79 %), against the 30 % goal.** In the service mode the person's check took 8.3 s (median) and the model 1.5 s.

Checks of the result:

- **Practice.** Both modes got about twice as fast towards the end (by hand: median 42 s in the first half, 25 s in the second; checking: 14 s → 6 s). The alternating blocks keep the comparison fair: each pair of neighbouring blocks gives a reduction of 61 %, 67 % and 77 %. Even the least favourable comparison, the fastest manual block against the slowest service block, gives 31 %.
- **Departments.** All five wrong departments are general-helpdesk requests sent to the CRM widgets line, the fuzzy border between the two lines. By hand the person made 4 such mistakes, the service 1 (the support line that handled the request is the reference). With 15 requests per mode the ranges overlap, so the accuracy difference is a hint, not a proof.
- **Automation bias.** The person kept the service's department in all 15 tickets, including the one the service got wrong, and changed nothing in 14 of 15. The last checks took 3–4 s, too short to read a 400-character request: checking turns into skimming. This is why the iteration 3 Validator (#57) and the "Was the department right?" answer at closing matter: errors the specialist lets through have to be caught later.

What this does and does not show: triage, the step the system changes, is about three times faster with the service for this person on these requests. The time a ticket waits in the queue is not measured, so the reduction of the whole time "request → ticket taken into work" depends on how much of it is triage.

### Second set: `buckets`, participant roman (23.11)

| Mode | Requests | Median | p90 | Mean | Department right |
|---|---|---|---|---|---|
| By hand | 15 | 76.1 | 116.7 | 89.2 | 47 % (20–73 %) |
| Service: model + the person's check | 15 | 41.2 | 83.1 | 49.7 | 73 % (47–93 %) |

**The median triage time is 46 % shorter with the service, but the 95 % range is −3 % to 67 %**: on this set, with one participant, the reduction is likely but not proven. The person's check took 39.8 s (median) and the model 1.6 s.

Checks of the result:

- **Practice.** By hand the person got much faster after the first block (median 117 s, then 54 s and 69 s); checking did not (41, 37, 51 s). The neighbouring pairs of blocks give 65 %, 68 %, 31 %, 4 % and 26 %. So the 46 % rests largely on the slow first manual block; after the warm-up the reduction is near the 30 % goal rather than clearly above it.
- **Departments.** By hand 7 of 15 right; 7 of the 8 mistakes sent requests to the integrations bucket, so the person did not know where that team draws the border. The service was right on 13 of the 15 it showed. With the service the person ended at 11 of 15: both wrong service departments were kept, and two right ones were changed to wrong ones. The person's corrections lowered the accuracy.
- **Automation bias, differently.** No skimming here: the checks took 21–90 s. Still, both service errors passed. Together with `ru`: a check by the specialist does not catch the service's mistakes reliably, whether it is fast or slow, which is what the closing question and the Validator (#57) are for.

### Both sets

Triage is faster with the service for both participants: −69 % on `ru` (the author, range 44–79 %) and −46 % on `buckets` (a team member who did not build the descriptions, range −3–67 %). The goal of 30 % is met on `ru`; on `buckets` it is met at the median but not proven, and after practice the gain is close to the goal. The times of the two sets are not pooled: the requests, departments and participants differ.
