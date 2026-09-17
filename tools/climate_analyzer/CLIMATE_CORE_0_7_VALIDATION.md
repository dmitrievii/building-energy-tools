# Climate Analyzer 0.7 — Validation Matrix

This file records the release-facing validation contract for precipitation and snow analytics.

## Backend

- `rr` remains interval-extensive and sums through canonical hourly normalization.
- `rrm` maps to `precipitation_duration_min`, unit `min`, aggregation `sum`.
- `rrm` is never inferred from `rr`.
- strict hourly completeness is variable-local for both `rr` and `rrm`.
- true source-interval precipitation peaks remain native-resolution diagnostics.
- snow-cover duration integrates provider-native snow-depth state records.
- annual precipitation indices preserve missing-day semantics.
- snow seasons use July–June grouping.

## Capability and UI

- `rr`, `rrm`, or `sh` can independently enable the Precipitation and Snow page when they contain numeric observations.
- one global Data filter is rendered; its selection is replayed onto the native precipitation/snow frame.
- no second precipitation-specific date/month/hour filter is introduced.
- no page-specific KPI strip is introduced.
- precipitation totals are not plotted as a centre line against per-record min/max extrema.
- source-record occurrence remains explicitly distinct from physical rain duration.
- measured precipitation duration is displayed only when the independent provider duration field is available.

## Qualification gate

Before merge, the final clean branch head must pass the complete Climate Analyzer CI suite: compilation, scientific/security regressions, reference/provenance checks, imports, deployment contract and Streamlit root-launch health.
