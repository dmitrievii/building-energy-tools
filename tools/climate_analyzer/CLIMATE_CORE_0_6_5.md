# Climate Analyzer 0.6.5 — Canonical Hourly Analysis Pipeline

Status: implementation branch / draft PR #62

## Goal

Normalize sub-hourly source observations once to a canonical hourly analysis dataset, while retaining the native-resolution source dataset for provenance and source-quality diagnostics.

## Analysis contract

- Ordinary scientific downstream analysis uses the canonical hourly dataset.
- Native source data remain available and are never overwritten.
- Quantity-aware aggregation applies by canonical variable semantics:
  - state/intensive variables: arithmetic mean;
  - extensive interval quantities: sum;
  - circular quantities: circular mean.
- Hourly completeness is strict by default. For a 10-minute source, six physical source timestamps are required for an hourly timeline slot; six valid source values are required for a valid hourly value of that canonical variable.
- Missing source intervals are never silently converted to zero.
- A missing physical source timestamp removes the incomplete hour from the hourly analysis timeline; variable-local missing values mask only that hourly variable.
- Derived psychrometric quantities are calculated downstream from hourly primary variables rather than averaged from sub-hourly derived values.
- EPW native hourly data use a no-resampling fast path.
- The hourly primary frame is cached once per active canonical dataset object.

## Native Data Quality contract

`Data Quality` is an explicit exception to the hourly analysis route:

- it uses the provider-native source frame (GeoSphere: 10-minute observations);
- source timestamps, provider-record counts, native gaps and per-variable native missingness are evaluated before hourly normalization;
- the source frame is calendar-enriched for diagnostics without mutating `dataset.data`;
- the native diagnostic frame is identity-cached independently of the hourly analysis frame;
- the global analysis Data filter is intentionally not applied to Data Quality, so user-excluded months/hours cannot be misclassified as missing provider observations;
- UI provenance states both `Source cadence` and `Canonical analysis cadence` and identifies the active frame role.

Ordinary historical pages continue to use:

`provider-native observations -> canonical hourly normalization -> global Data filter -> analysis / charts`

Data Quality uses:

`provider-native observations -> native source diagnostics`

The historical Overview separates coverage context from filtered analysis: coverage indicators describe the complete loaded canonical hourly frame, while climate metrics and charts respect the active global Data filter.

## Precipitation / snow cadence wording

Ordinary GeoSphere precipitation and snow analysis runs on the canonical hourly frame. Therefore UI wording no longer calls those hourly rows provider `source records`:

- `Precipitation-interval occurrence` counts analysis intervals meeting the selected threshold;
- it remains explicitly distinct from exact rainfall duration;
- snow-cover duration integrates the active hourly analysis cadence;
- native 10-minute gaps and missing observations remain a Data Quality responsibility.

## Temporal heat-map calendar-axis contract

Temporal heat maps use explicit numeric calendar coordinates rather than date-like strings:

- Day: leap-neutral calendar slot 1...366 on a fixed leap reference year. Feb 29 is slot 60 and Mar 1 is slot 61 in every source year.
- Week: ISO week number 1...53. `Week × Year` uses ISO week-year at calendar-year boundaries.
- Month: 1...12.
- Hour of day: 0...23.

For `Compare across = Hour of day`, equivalent calendar slots from all selected years are aligned instead of expanding chronological multi-year data into thousands of absolute-date columns. For `Compare across = Year`, real years remain the comparison dimension.

For multi-year interval-extensive `Total` heat maps, each source year's calendar cell is totaled independently and equivalent cells are then averaged, so the displayed value does not scale merely with the number of loaded years.

## Performance policy

The canonical hourly pipeline is the primary multi-year performance measure. No chart-specific Plotly downsampling, pre-binning, WebGL rewrite or other rendering approximation is introduced by default.

Additional Plotly optimization will be considered only if the final multi-year benchmark identifies a specific residual bottleneck after hourly normalization. Scientific calculations remain full-resolution at the canonical hourly analysis resolution.

## Validation

Focused regressions cover:

- mean/sum/circular 10 min -> hourly reduction;
- precipitation and irradiation conservation;
- missing timestamps and variable-local missingness;
- EPW/hourly no-op behavior;
- psychrometric derivation after hourly normalization;
- one-time hourly cache reuse;
- preservation and independent caching of native diagnostic observations;
- explicit native-vs-hourly frame roles and cadence provenance;
- Data Quality isolation from analysis filtering;
- precipitation interval-occurrence wording;
- all six `Day / Week / Month × Hour of day / Year` temporal heat-map configurations;
- full 24-row `Day × Hour of day` rendering;
- leap-day stability and ISO week-year boundaries.

## Remaining before merge

1. Run the clean full Climate Analyzer CI after native Data Quality / provenance integration.
2. Benchmark multi-year GeoSphere before/after hourly normalization (at least 1, 5 and 10 years where practical).
3. Decide from measured benchmark results whether any chart-specific optimization is required; current default decision is **no**.
