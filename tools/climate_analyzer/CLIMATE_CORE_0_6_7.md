# Climate Analyzer 0.6.7 — GeoSphere Load Progress UX

Status: implementation branch

## Goal

Make long GeoSphere historical downloads visibly progressive without changing the 0.6.5 transport or scientific semantics.

## UX contract

- The UI shows a determinate progress bar for the original bounded request plan (`0/N ... N/N`).
- Progress denominator is the number of planned root batches shown before the load starts.
- A transient retry remains inside the current root batch and updates the status text without falsely advancing progress.
- Adaptive split children also remain inside the current root batch; the denominator never jumps when a provider response is bisected.
- Root progress advances only after all successful child requests for that planned batch have been parsed.
- On failure, the bar remains at the number of fully completed planned batches and the existing fail-closed error is shown.
- Progress reporting is observational only: a callback/rendering failure must not alter provider requests, data values, retry policy or fail-closed behavior.

## Transport events

The GeoSphere adapter exposes an optional callback with these events:

- `batch_start`
- `retry`
- `split`
- `batch_complete`
- `load_complete`

Each event carries `completed_batches`, `total_batches`, `batch_number`, source time bounds and split depth; retry events also carry the retry attempt.

## Initial scope

0.6.7 starts with GeoSphere load progress only. It does not introduce Plotly downsampling or change the canonical hourly pipeline. Further 0.6.7 work should remain isolated behind separate regressions.
