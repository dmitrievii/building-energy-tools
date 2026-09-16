# Climate Analyzer 0.6.5 — Canonical Hourly Analysis Pipeline

Status: implementation branch

## Goal

Normalize sub-hourly source observations once to a canonical hourly analysis dataset, while retaining the native-resolution source dataset for export, provenance and explicitly native diagnostics.

## Contract

- Scientific downstream analysis uses the canonical hourly dataset.
- Native source data remain available and are never overwritten.
- Quantity-aware aggregation applies by canonical variable semantics:
  - state/intensive variables: arithmetic mean;
  - extensive interval quantities: sum;
  - circular quantities: circular mean.
- Hourly completeness is strict by default. For a 10-minute source, six valid source records are required for a valid hourly value of a canonical variable.
- Missing source intervals are never silently converted to zero.
- A missing physical source timestamp removes the incomplete hour from the hourly analysis timeline; variable-local missing values mask only that hourly variable.
- Derived psychrometric quantities are calculated downstream from hourly primary variables rather than averaged from sub-hourly derived values.
- EPW native hourly data use a no-resampling fast path.
- The hourly primary frame is cached once per active canonical dataset object.

## Temporal heat-map calendar-axis contract

Temporal heat maps use explicit numeric calendar coordinates rather than date-like strings:

- Day: leap-neutral calendar slot 1...366 on a fixed leap reference year. Feb 29 is slot 60 and Mar 1 is slot 61 in every source year.
- Week: ISO week number 1...53. `Week × Year` uses ISO week-year at calendar-year boundaries.
- Month: 1...12.
- Hour of day: 0...23.

For `Compare across = Hour of day`, equivalent calendar slots from all selected years are aligned instead of expanding chronological multi-year data into thousands of absolute-date columns. For `Compare across = Year`, real years remain the comparison dimension.

For multi-year interval-extensive `Total` heat maps, each source year's calendar cell is totaled independently and equivalent cells are then averaged, so the displayed value does not scale merely with the number of loaded years.

## Validation

Focused regressions cover:

- mean/sum/circular 10 min -> hourly reduction;
- precipitation and irradiation conservation;
- missing timestamps and variable-local missingness;
- EPW/hourly no-op behavior;
- psychrometric derivation after hourly normalization;
- one-time hourly cache reuse;
- all six `Day / Week / Month × Hour of day / Year` temporal heat-map configurations;
- full 24-row `Day × Hour of day` rendering;
- leap-day stability and ISO week-year boundaries.

Latest Climate Analyzer CI after the temporal heat-map remediation: PASS, including compile, scientific/security regressions, module imports and Streamlit root-launch health.

## Remaining before merge

1. Keep Data Quality / source-coverage diagnostics explicitly native-resolution.
2. Update UI/provenance wording to distinguish source cadence from analysis cadence.
3. Review precipitation occurrence wording under hourly analysis.
4. Benchmark multi-year GeoSphere before/after hourly normalization.
