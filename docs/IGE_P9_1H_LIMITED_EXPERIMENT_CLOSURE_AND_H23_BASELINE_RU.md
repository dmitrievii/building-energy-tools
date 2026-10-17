# IGE P9.1H — Limited verification closure and H2/H3 baseline, 2026-10-17

**One frozen second-site source attempt; one transparent preliminary physical candidate. Main unchanged.**

## 1. P9.1H1 source verification scientific result

| Gate | Observation | Outcome |
|---|---|---|
| Hyytiälä original 2018 January + July tower temperatures at 4.2/67.2m | Original public SmartSMEAR source-minute responses and source SHA authenticated; 10,080 January and 10,052 July synchronous unfilled temperature pairs; native QC still unresolved | Research-only source provenance; not fully QA qualified |
| Cabauw KNMI manual LB1 v1.3, 2018 Jan/Jul | One attempt against official KNMI Open Data API with official published shared anonymous key, GitHub Actions [#39062235255](https://github.com/dmitrievii/building-energy-tools/actions/runs/39062235255) | HTTP 429 RATE LIMITED; **no original Cabauw meteorological bytes obtained; no independent Cabauw source qualification** |
| Unseen independent 2021 temporal holdout | Never read for Cabauw/Hyytiälä | BLIND, unchanged |
| Complete two-region H1 with original native QC | Not satisfied | **H1 SCIENTIFIC SOURCE GATE BLOCKED, not a successful H1 qualification** |

Provider access failure is distinct from failed climate model prediction; no temperature error was calculated for Cabauw. Historical G1 strict QN10 issue and all P9.1G limitations still stand. Do not retry KNMI continuously: shared API anonymous credentials are rate limited and provider explicitly prohibits excessive polling.

## 2. New P9.1H2/H3 frozen physically conditioned candidate

Implementation:
- [`p9_1h23_physical_inversion_candidate.py`](../research/ige_cmip6/p9_1h23_physical_inversion_candidate.py): deterministic UTC Sun geometry; ERA5 wind/cloud nighttime *radiative proxy*, SRTM independent cold-air-pool morphology, physically bounded negative correction **at most 1.25 K**; snow enters only after independent source verification. Daytime, nonvalley, or missing predictors return baseline unchanged. Existing B0 raw ERA5, B1 fixed 6.5 K/km regular grid height, B2 provider altitude adjusted preserved with individual source identities.
- [`p9_1h23_source_era5_dem_adapter.py`](../research/ige_cmip6/p9_1h23_source_era5_dem_adapter.py): uses already implemented **P9.1F original SRTM 12 km eight-ray morphology**, with previously frozen minimum relief **120m** and original site vs ERA5 regular grid elevation difference **-150m**, authenticated P9.1E ARCO regular surface geopotential. Normalized ramp factors (240m and 350m) are new frozen modeling assumptions, not fitted. Reject provenance discrepancies. The *adapter* expressly rejects 2021 holdout timestamps; development only 2018.
- Results are *not* a genuine coupled radiation or stable boundary layer energy balance; cloud is a cooling proxy, wind mixing is a parametric proxy, and no temperature residual fit has been performed. This is an explicit scientifically conservative first candidate, not an inversion law.
- An actual flat Cabauw site would generally have no valley cold-pooling modifier (candidate returns B1); it could validate the observed inversion feature but not alpine site-skill. Hyytiälä 4.2m forest tower must NOT be substituted for true 2m station temperature. Need independent instrument data for skill.

## 3. What was actually tested

Offline two-file physics and adapter tests: **10+7=17 PASS** in [GitHub Actions #39062673368](https://github.com/dmitrievii/building-energy-tools/actions/runs/39062673368), SUCCESS. These check fixed coefficients, 2018-only holdout protection, DEM provenance and percentile, monotonic radiation/wind/terrain response, UTC timestamps, sensible parameter units, missing source fallback, no fictitious provider regridding certainty. The prior 10 tests passed independently at [#39062518771](https://github.com/dmitrievii/building-energy-tools/actions/runs/39062518771).

**None** of these offline tests provides measured 2018/2021 model MAE. No EPW production claim. No 2021 experimental score. No model tuning.

## 4. Research decision and next narrowly scoped eligibility gate

1. **Do not mark H1 scientific qualification PASS.** Under finite study budget, mark H1B source verification attempt complete with external access blockage, and continue H2/H3 *as algorithmic development only*.
2. The path to actual comparative skill is either an officially accessible original manually checked 2018 KNMI Cabauw LB1 source with original SHA, or (if unavailable) stop H1 scientific qualification. No site/date substitution or bigger benchmark program.
3. If approved source becomes available, first pair native QC-qualified 2m Cabauw with real ERA5 B0/B1/B2 and frozen H candidate for January and July 2018, report source-counts, MAE, signed bias and worst-period degradation, do not change coefficients; then conduct **one** blind 2021 qualification. Forest Hyytiälä original measured inversion vertical gradients are separate from true 2m skill.
4. Both P9.1H CI workflows have **no push triggers** after last successful test; all future runs manual. No automatic KNMI retries.

Flags: `global_arbitrary_point_weather_qualified=false`; `near_surface_inversion_model_qualified=false`; `production_epw_ready=false`. No main merge. This is honest partial scientific completion, not falsely green experimental closure.
