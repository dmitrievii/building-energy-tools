# IGE P9.1A — Global Historical Source Backbone (registered pilot protocol)

**Date**: 2026-10-17. Parent: `3c5a8478bf3ff19f39630486cc44fce73f73197c`. Phase P9.1A = **source retrieval, provenance, hourly semantic and spatial-cell qualification pilot**, not yet the entire global historical-weather engine and not source-independent verification against worldwide observations. Never merge to main without authorization.

## Chosen baseline data source and provenance

A single **explicit ERA5** historical-reanalysis model via **Open-Meteo Historical Weather API** `https://archive-api.open-meteo.com/v1/archive`, request `models=era5` — **not** its default `best_match`, `era5_seamless` or automatic mix. Use `elevation=nan` to disable Open-Meteo statistical DEM-based downscaling and `cell_selection=nearest`, so this phase inspects the model's selected grid-scale representative data rather than silently moving to the most suitable terrain cell. GMT/UTC hourly points, `wind_speed_unit=ms`, source provider units asserted. URL, raw payload SHA256, returned nearest grid-center lat/lon, distance from requested coordinate, provider reported elevation *unverified* and missing/quality counts stored in report. **Do not claim the provider reanalysis JSON is byte-authentic native ERA5 CDS GRIB.**

- Open-Meteo official historic API: https://open-meteo.com/en/docs/historical-weather-api ; implementation details: https://github.com/open-meteo/open-meteo/blob/main/openapi/historical-weather.yml .
- ECMWF source family and limitations: https://www.ecmwf.int/en/forecasts/datasets/era5-land-hourly-data-1950-present and https://confluence.ecmwf.int/pages/viewpage.action?pageId=627854121 .
- **Important**: publicly reported issue https://github.com/open-meteo/open-meteo/issues/1155 warns that the API elevation field with `elevation=nan` can show `0` rather than true grid elevation. Do not use the response elevation as a verified native model geopotential height. Independent DEM + ECMWF/orography verification is P9.1B.

## Strict 12-field original hourly source contract

Temperature T2m °C, dewpoint Td2m °C, RH2m %, surface pressure hPa, precipitation preceding-hour mm, total cloud cover instant %, global shortwave GHI (preceding-hour mean W/m²), direct-horizontal radiation (preceding-hour mean W/m²), diffuse-horizontal DHI (preceding-hour mean W/m²), direct-normal DNI (preceding-hour mean W/m²), 10m wind speed m/s and meteorological FROM direction deg.

All fields must use **one common UTC sequence** with exactly every Gregorian hour, including leap days in 2024, no missing/duplicate/shifted timestamps, and no silent numeric imputation. Do not convert UTC back to EPW standard-time solar labels in P9.1A. Geographic response location may differ from user coordinates. Record cell-distance discrepancy; fail if >150km (sanity), flag errors on much smaller distances for locality. A finite, coherent ERA5 model cell DOES NOT prove site-scale representativeness.

Hard physics source checks: finite quantities, reasonable absolute limits, Td ≤ T+0.5°C, RH 0–100%, surface pressure hPa in plausible range, nonnegative rain/shortwave/wind, cloud 0–100%, FROM angle 0–360°, DHI≤GHI within 5W/m², direct-horizontal≤DNI within 8W/m². GHI vs direct_horizontal+DHI tolerance is **warning** (provider regridding/averages may differ); discrepancies and RH vs dewpoint Buck are tabulated without auto correction. **No daily weather generator and no GHI/DNI morphological closure claimed**.

Conditional scientific diagnostics: same-month same-UTC-hour wet/dry cloud and RH differences and diffuse fraction, wet-hour counts, solar sums, annual temperature/wind means. Source statistical associations are descriptive. Must not copy Meteonorm conditional distributions as acceptance thresholds.

## Registered source-spatial/time probes

All **full source years** to permit matching rain/dry same month/hour; **2023** (8760 hours) at:
1. Graz, Austria: (47.0707, 15.4395), inland Central European control.
2. Singapore: (1.3521, 103.8198), equatorial humid coastal island.
3. La Paz, Bolivia: (-16.5000, -68.1500), Andes high terrain — must flag that terrain elevation correction is NOT qualified.
4. Reykjavik, Iceland: (64.1466, -21.9426), northern maritime/subpolar.
5. Riyadh, Saudi Arabia: (24.7136, 46.6753), arid hot-climate stress test.
Additionally Graz **2024** (8784 hours), leap-year UTC source validation/temporal generality.

**Source API availability can vary; networking failures are NOT independent climate-skill failures.** Retry only transient transport failures conservatively; never switch sources automatically on failure. No future SSP morphing or full EPW output is included in this phase.

## Acceptance and unresolved science

`P9_1A_SOURCE_BACKBONE_PILOT_PASS`: six original-source requests return matching 12 variable units and exact 8760/8784 hours, expected coordinates and source SHA recorded, critical original-source variable QC for each is green, all aggregate JSON files produced and replay tests pass.

`P9_1_FULL_GLOBAL_AND_SITE_SCALE_QUALIFIED` **must remain false** regardless of how many source-origin requests pass: no independently held-out measured station benchmarking yet, no independently verified native grid orography/DEM, no scientifically tested lapse correction, no global land/coastal/ocean domain gate, no source mixing, no new seeded synoptic episodes or future scenario, no EPW time conversion/export validated.

**Next P9.1B** — independently verify spatial selection and true DEM/grid altitude with native ERA5 or ERA5-Land and source station holdouts 2019/2024 across landscape classes; quantify altitude, distance to reference stations, exposure, land/sea mask and biases before allowing model-to-site downscaling. Avoid unverified globally fixed lapse correction for all regimes.
