# Climate Analyzer 0.6.5 — Canonical Hourly Analysis Pipeline

Status: implementation complete / draft PR #62 awaiting merge decision

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
- Circular wind-direction aggregation uses the exact vector definition `atan2(mean(sin θ), mean(cos θ))` in a vectorized hourly implementation. Cancelling resultants remain undefined (`NaN`).

## Native Data Quality contract

`Data Quality` is an explicit exception to the hourly analysis route:

- it uses the provider-native source frame (GeoSphere: 10-minute observations);
- source timestamps, provider-record counts, native gaps and per-variable native missingness are evaluated before hourly normalization;
- the source frame is calendar-enriched for diagnostics without mutating `dataset.data`;
- the native diagnostic frame is identity-cached independently of the hourly analysis frame;
- the global analysis Data filter is intentionally not applied to Data Quality, so user-excluded months/hours cannot be misclassified as missing provider observations;
- UI provenance states both `Source cadence` and `Canonical analysis cadence` and identifies the active frame role.

Ordinary historical pages use:

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

## GeoSphere long-range transport

Long historical intervals are no longer treated as a small number of near-hard-cap requests.

- `MAX_REQUEST_DATAPOINTS = 200,000` remains the hard local safety boundary.
- Normal planning uses a conservative `DEFAULT_BATCH_DATAPOINTS = 100,000`.
- Timeout, connection failures, HTTP 408/425/429 and HTTP 5xx are treated as transient.
- A transient failure retries only the current batch once with backoff.
- If the same batch still fails, only that batch is bisected on the native 10-minute grid and the child requests are retried independently.
- Successful neighbouring batches are not downloaded again.
- Local response-size failures split directly rather than repeating the same oversized response.
- Permanent provider 4xx errors, redirects, malformed JSON and malformed provider payloads remain fail-closed.
- Adaptive children are non-overlapping and final duplicate timestamps are rejected.

For the reported ~33.8-year / 1,779,264-datapoint / one-variable case, initial planning therefore changes from about 9 near-200k batches to about 18 near-100k batches, with adaptive splitting only where the provider remains slow.

## Performance policy

The canonical hourly pipeline is the primary multi-year performance measure. No chart-specific Plotly downsampling, pre-binning, WebGL rewrite or other rendering approximation is introduced by default.

Additional Plotly optimization will be considered only if a future measured production bottleneck remains after hourly normalization. Scientific calculations remain full-resolution at the canonical hourly analysis resolution.

## Benchmark

A reproducible synthetic benchmark is provided at:

`scripts/benchmark_canonical_hourly_0_6_5.py`

It measures the Python-side normalization/data-preparation path only. It does **not** claim to measure GeoSphere network time, Streamlit rerun time or browser/Plotly rendering.

The deterministic reference run used 365-day-equivalent 10-minute grids:

| Period | Native rows | Hourly rows | Row reduction | Temperature-only normalization | 9-variable normalization |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 year | 52,560 | 8,760 | 6.0× | ~0.006 s | ~0.03 s |
| 5 years | 262,800 | 43,800 | 6.0× | ~0.012 s | ~0.09 s |
| 10 years | 525,600 | 87,600 | 6.0× | ~0.024 s | ~0.18 s |
| 30 years | 1,576,800 | 262,800 | 6.0× | ~0.13 s | ~0.64 s |

The 9-variable case includes temperature, RH, pressure, wind speed, circular wind direction, precipitation, snow depth, GHI and DHI. The vectorized circular mean removes the former Python-per-hour `Resampler.apply` bottleneck; the same 30-year synthetic path was approximately 25 s before that vectorization in the reference environment.

Representative temperature-only dataframe preparation at 30 years showed the expected benefit from operating on the hourly matrix rather than the native 10-minute matrix:

| Preparation operation | Native 10 min | Canonical hourly | Approx. speed-up |
| --- | ---: | ---: | ---: |
| Month-hour heat-map grouping | ~105 ms | ~17 ms | ~6.2× |
| Histogram preparation | ~11.6 ms | ~2.3 ms | ~5.1× |
| Duration-curve sorting | ~98 ms | ~13.7 ms | ~7.2× |
| Daily min/mean/max aggregation | ~47 ms | ~8.2 ms | ~5.8× |

These results support the decision **not to add chart-specific Plotly optimization in 0.6.5**. The primary remaining long-range cost is provider transport, which is addressed separately by conservative batching plus retry/split.

## Validation

Focused regressions cover:

- mean/sum/circular 10 min -> hourly reduction;
- vectorized circular-mean wraparound and cancelling-resultant semantics;
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
- leap-day stability and ISO week-year boundaries;
- conservative GeoSphere batch planning;
- timeout/connection/transient-HTTP retry;
- adaptive failed-batch splitting without overlap;
- permanent-error fail-closed behavior.

## Merge gate

Implementation scope is complete. Before merge, the final branch head must retain:

- Climate Analyzer compile PASS;
- full security/scientific regression suite PASS;
- scientific module import smoke PASS;
- Streamlit root-launch health PASS.

PR #62 remains draft until an explicit merge decision.
