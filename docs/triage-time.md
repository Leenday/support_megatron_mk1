# Triage time: by hand vs the service (#43)

The business goal is **30 % less time from a request to a ticket taken into work**. Without real specialists we measure the part the system changes, triage: reading a request, choosing the department and writing the ticket. Waiting in the queue is not measured; it depends on staffing, not on the system.

## Method

- **Requests:** 30 requests of the Russian test set that are not in the gold subset (the gold ones were read while labelling), in the support lines' proportions (26 general helpdesk, 4 CRM widgets line). The texts stay in `data/local/` and `out/` and are never committed; only aggregate numbers are reported.
- **Two modes, each request once.** The requests are split into halves A and B with the labels balanced. Participant 1 triages A by hand and checks B in the service mode; a second participant would swap (`--swap`), so nobody sees a request twice.
  - **By hand:** the page shows the request; the person chooses the department and writes who / where / when / what.
  - **Service:** the same form, already filled with the service's ticket (gpt-5.4-mini, prompt v4, the department after routing); the person checks it and fixes what is wrong. The model's own time from the run log (median 1.5 s) is added to the person's time.
- **Order:** blocks of 5 requests, by hand and checking in turn, so getting faster with practice does not favour one mode.
- **Timing:** in the browser, from showing the request to "Done". Pauses between requests do not count.
- **Result:** median and p90 per mode, the reduction of the median time with a 95 % bootstrap range (each mode resampled separately), the share of right departments per mode, and how often the person kept the service's department or changed nothing.

## Limits

- One participant, who knows the departments well (the project author), so the manual baseline is faster than a new operator's; the reduction is rather understated. A second participant would run `serve --participant p2 --swap` and complete the crossover.
- The service tickets were made in advance by the same pipeline the service uses (`megatron-eval --run`), not live through the form; the model's time comes from that run.
- With 15 requests per mode the range is wide.

## How to run

```bash
uv run megatron-triage plan data/local/ru --results out/eval/ru/gpt-5.4-mini-v4.jsonl
DEPARTMENTS_PATH=data/local/ru/departments.yaml uv run megatron-triage serve data/local/ru --participant p1
# open http://127.0.0.1:8743/ and triage all 30 requests (about 40 minutes; pauses are fine)
uv run megatron-triage report data/local/ru     # → out/triage/ru/report.md
```

## Results

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
