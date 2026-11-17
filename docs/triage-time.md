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

- One participant so far, and he knows the departments well, so the manual baseline is faster than a new operator's; the reduction is rather understated.
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

Pending: the measurement session.
