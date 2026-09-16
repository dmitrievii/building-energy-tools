# Climate Analyzer 0.6.5 — Canonical Hourly Analysis Pipeline

Status: implementation branch

## Goal

Normalize sub-hourly source observations once to a canonical hourly analysis dataset, while retaining the native-resolution source dataset for export and explicitly native analyses.

## Contract

- Scientific downstream analysis uses the canonical hourly dataset.
- Native source data remain available and are never overwritten.
- Quantity-aware aggregation applies by canonical variable semantics:
  - state/intensive variables: arithmetic mean;
  - extensive interval quantities: sum;
  - circular quantities: circular mean.
- Hourly completeness is strict by default. For a 10-minute source, six valid source records are required for a valid hourly value of a canonical variable.
- Missing source intervals are never silently converted to zero.
- Derived psychrometric quantities are calculated downstream from hourly primary variables rather than averaged from sub-hourly derived values.
- EPW native hourly data use a no-op fast path.

## Initial implementation scope

1. Reusable canonical hourly normalizer.
2. Per-variable coverage tracking and strict completeness semantics.
3. GeoSphere 10-minute -> hourly integration point.
4. Regression tests for mean/sum/circular aggregation, missing intervals, and EPW no-op behavior.
5. Application rewire after the scientific core is qualified.
