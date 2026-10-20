# IGE P9.3B2D — Frozen new German 2023 true station pressure holdout

Date 2026-10-20. **This registration precedes any new DWD Urban measured pressure model error calculations.**
Source-only independent census action:
https://github.com/dmitrievii/building-energy-tools/actions/runs/39474780059 .
No measured hourly pressure values or any model predictions/errors examined in census.

## Frozen source and comparisons

- One new authentic original DWD `climate_urban/10_minutes/pressure/historical/`
  station **00399**, original archive matching
  `10minutenwerte_P0_STADT_00399_20150701_20241231_hist.zip`.
- Genuine station-level pressure `P0_ST_10` (hPa), NEVER sea-level
  `PP_ST_10`. Original DWD Urban source field `QN` exists but is blank for
  **all 168/168** minute=00 observations in each preselected 2023 week.
  Quality tier therefore `DWD_URBAN_PUBLISHED_NO_PER_SAMPLE_QC`,
  **NOT DWD_QN10**; the study is a limited original-measurement source check.
- Frozen windows: **2023-01-10 00:00–2023-01-16 23:00 UTC** and
  **2023-07-10 00:00–2023-07-16 23:00 UTC**, each 168 exact HH:00 sensor
  samples, 336 station pressure values total; no frequency conversion or
  substitution of minute=10 etc.
- DWD original station coordinates and station elevation from original
  metadata; insist station original site identity `00399`.
  Reuse only the same station coordinate to retrieve an explicit
  `models=era5` + `elevation=nan` Open-Meteo hourly source at exact
  Gregorian UTC hours. Record response grid and original SHA, verify its
  original-source height with **ARCO ERA5 surface** `geopotential_at_surface/g0`,
  not nearby SRTM 90m pixel.
- Baseline `B0`: original source-grid ERA5 `surface_pressure` without
  altitude correction. Physically registered `B4`: hydrostatic
  `p_station = p_ERA5*exp(-g*(z_station-z_ARCO)/(Rd*T_virtual))`.
  Comparator `B3`: same unmodified hydrostatics with returned Open-Meteo
  grid reference height instead of authenticated ARCO `z/g0`.
  No source pressure calibration, station-P conditioning or selection of a
  favourable model after viewing results.
- Source UTC support caveat: DWD minute=00 sensor instant is compared with
  ERA5 source-reanalysis indicated-hour quantity. Even if identical
  timestamps, this is not proof identical temporal measurement support.
- Report **both seasons** MAE, RMSE, signed bias, exact-hour pair N and
  B4−B0, B4−B3 differences. Acceptance exploratory criterion:
  B4 MAE <= 2 hPa in BOTH frozen seasons AND B4 MAE < B0 in BOTH seasons;
  not a calibrated or publication-quality global benchmark.
- If a period has under 144 original station P values, missing native ERA5
  fields, incompatible source elevations or a source error, return
  SOURCE_BLOCKED; do not backfill.
- Retrospective prior AT Graz and CH Davos source values from P9.3B2/B2C
  are excluded from new independent skill claims. No new German 2023
  site/period after scores, no world sweep, no main merge.

**Important:** even if source model MAE criteria pass, full AT/DE/CH pressure
skill remains NOT QUALIFIED (single German urban source, no sample QC),
and future GCM-native high-frequency pressure remains unresolved.
This closure can qualify the source height model only with stated limitations,
not production EPW.
