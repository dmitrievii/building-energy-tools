# IGE P9.3B2D — FINAL: Original DWD Pressure Source Recovery, Semantics Erratum & Frozen Independent German Benchmark

**20 October 2026.** Branch `research/ige-p9-3b2d-pressure-closure-20261020`; parent P9.3B2C `b793d2f`. **SCIENCE AUDIT COMPLETED, PHYSICAL STATION-PRESSURE MODEL NOT QUALIFIED, PRODUCTION EPW FALSE.** No main merge or original measured hour-level time series released.

## A. Chronological source-only preselection (before model-skill observations)

1. Fixed six original DWD CDC hourly pressure station candidates over two unexamined Jan/Jul 2023 weeks: Frankfurt 01420, Lindenberg 03015, Freiburg 01443, Weißenburg 05440, Kempten 02559, Garmisch 01550. Source-only [Actions #39473786078](https://github.com/dmitrievii/building-energy-tools/actions/runs/39473786078), 6 × 2 × 168 = **2016 original time rows**. Both raw DWD fields `P` and `P0` empty in every row. **0 authentic station-pressure pairs**, the original preregistered source family FAILED-CLOSED. No model predictions/errors read. Historical six-station results cannot be called station-pressure accuracy.

2. Predeclared alternative-source amendment before any new values: [Amendment A](IGE_P9_3B2D_SOURCE_RECOVERY_AMENDMENT_A_20261020_RU.md). Original two DWD pressure-family source schema names identified in source-only Actions #39474460867:
   - urban 10-minute station **00399**: `P0_ST_10` station and `PP_ST_10` MSL, original native `QN`;
   - subdaily `PP_TER` site pressure (native `QN_4`), candidates 01420, 02559, 01550.
   No measured pressure or model error seen during this field mapping.

3. Fixed source-family mapping applied, source-only [Actions #39474780059](https://github.com/dmitrievii/building-energy-tools/actions/runs/39474780059):
   - DWD Urban Berlin-Alexanderplatz `00399`, January 2023: **168/168** exact HH:00 P0_ST_10; July **168/168**. ALL 336 native `QN` values blank: published sensor observations **not independently per-sample QC-certified**. One and only one alternate-family candidate passes the preregistered availability gate.
   - DWD Subdaily 01420, 02559, 01550: each only **21/168** exact-hour source values per week; all numeric, `QN_4=9`, none meets frozen min **35**. Not used in new model comparison.
   - Genuine pressure source semantics are now pinned in [DWD source erratum](IGE_P9_3B2D_DWD_PRESSURE_FIELD_SEMANTICS_ERRATUM_20261020_RU.md).
   - The old hourly DWD `P` has **sea-level** meaning; original hourly DWD `P0` is **station-level** (the opposite of all old P9.3B2 and P9.3B2C textual assertions). Official DWD v24.03 English dataset documentation page 2:
     https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/DESCRIPTION_obsgermany_climate_hourly_pressure_en.pdf
   - Strict canonical source-specific field guard and anti-MSL-fallback contracts implemented in `research/ige_cmip6/p9_3b2d_canonical_pressure_fields.py`.

## B. Frozen independent 2023 German station-pressure experiment

[Prospective frozen registered cohort](IGE_P9_3B2D_FROZEN_URBAN_2023_PRESSURE_HOLDOUT_PREREG_RU.md), committed as `8edda297` before any model score. One Berlin-Alexanderplatz DWD Urban station 00399, original station `z=36 m`, `52.5198°N 13.4057°E`, `P0_ST_10`. UTC 2023-01-10...16 and 2023-07-10...16 minute=00 exact-hour samples. **336/336 genuine station-pressure measurement/time matches**, but no native QN content.

Same-point explicit historical Open-Meteo derived ERA5 `surface_pressure`, `temperature_2m`, `dew_point_2m`, selected regular 0.25-degree grid `(52.5°N,13.5°E)`. Open-Meteo returned grid height **50 m**; original ARCO ERA5-derived source-surface `geopotential_at_surface/g0 = 50.2610553 m`. DWD original metadata and ZIP SHA pinned in [full Actions artifact #12289272356](https://github.com/dmitrievii/building-energy-tools/actions/runs/39475489913/artifacts/12289272356).

Original independent [Actions #39475489913](https://github.com/dmitrievii/building-energy-tools/actions/runs/39475489913): all code/format checks SUCCESS, but **preregistered pressure-model scientific acceptance FAIL**:

| Original source, MAE (hPa) | Jan 2023, N=168 | Jul 2023, N=168 |
|---|---:|---:|
| B0 raw source-grid ERA5 p (no altitude adaptation) | **4.096429** | **3.667857** |
| B3 same hypsometry with returned OM grid z=50m | 5.801341 | 5.288273 |
| B4 exact ARCO ERA5 source geopotential z=50.261m | **5.833160** | **5.318513** |
| B4 minus B0 (positive worsens) | **+1.736732** | **+1.650656** |
| B4 minus B3 (near-equal grid height) | +0.031819 | +0.030240 |

Source-level original obs minus modelling? Error convention is **prediction minus observed**. Derived mean biases (hPa) in original artifact:
- Jan: B0 **+4.096429**, B4 **+5.833160**.
- Jul: B0 **+3.667857**, B4 **+5.318513**.

In both weeks error retains a positive sign at all matched hours. The pressure-grid surface and the DWD station elevation differ by −14.261 m, hence the prescribed physical correction increases predicted station pressure; **it worsens this frozen observation case**. This is scientifically valid negative evidence, not a coding failure. Do not invert the hydrostatic correction, fit bias, change station or year, replace sensor altitude, use sea-level data, or select B0 after having optimized hyperparameters against this score.

**Not demonstrated:** why raw ERA5 p shows 3.7–4.1 hPa mean pressure bias versus this station. Possible systematic components (source/remapping, spatial representativity, sensor reference/barometer height, 10-min vs ERA5 hourly time semantics or source QC) are HYPOTHESES, not independently established causes. Native per-record urban source `QN` was blank; no final quality tier can be claimed.

## C. Locked scientific release decision

| Test | Status |
|---|---|
| Correct DWD hourly/urban/subdaily original station vs sea-level pressure field mapping | **PASS**, old reports require ERRATUM |
| DWD original six-station 2023 native hourly site pressure records | **SOURCE BLOCKED**, 0/2016 |
| Independent German original urban exact-hour pressure observed | **336/336 available**, QC unspecified |
| ERA5 ARCO original remapped 0.25° surface height validated at urban test grid | **PASS within verified ARCO/OM source semantics** |
| Preregistered B4 pressure MAE ≤2 hPa each season | **FAIL**, 5.833/5.319 hPa |
| Preregistered B4 beats B0 in both seasons | **FAIL**, B4 worse in 2/2 |
| Broad AT/DE/CH station-pressure generalization with uniform native per-sample QC | **NOT QUALIFIED** |
| Independent ERA5 native CDS spectral GRIB equivalence | **NOT VERIFIED** |
| Native high-frequency CanESM5 surface-pressure `ps` and GCM T/q/RH closure | **NOT RECOVERED / NOT QUALIFIED** |
| Production EPW and whole future climate engine | **BLOCKED** |

**Decision:** `P9_3B2D_RESEARCH_CLOSED_NEGATIVE=true` and `historical_pressure_site_model_qualified=false`. B4 cannot be promoted as universal station-pressure correction, and B0 cannot be called station-accurate (German urban observed bias >3.6 hPa even before correction). Historical pressure at the ERA5 grid itself is source-backed; extrapolating it to other elevations remains physically formulated but not successfully validated in this frozen German cohort. The already seen 2024 Austrian/Swiss metrics are not counted as new holdouts.

**Next P9.3B3:** use an explicit physically sourced historical pressure reference as a *provisional pressure input with uncertainty*, design source-consistent thermodynamic T–p–q–RH solver, and check a single new predeclared station-pressure source/year only if indispensable. Do NOT claim to have scientifically completed worldwide pressure prediction or solved future native CanESM5 daily ps. All P9.3B2D automated one-shot CI workflows should be left manual-only following verified closure. Main unchanged.
