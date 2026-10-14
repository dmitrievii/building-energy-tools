# IGE P8.3E–H — original-source screening protocol (fixed before GitHub data runs)

**Date:** 2026-10-15. **Branch:** `research/ige-p8-3e-h-wind-screen-20261015`, forked from P8.3D. **Only research.**

Four independent CI jobs are intentionally source-scoped preflights; green CI does **not** imply final production qualification.

## E — Wind station height and exposure

Read the official MeteoSwiss station and parameter metadata. Do NOT equate station altitude above sea level with anemometer height above ground, surface roughness, displacement height or instrument exposure. A numerically valid neutral log wind law requires documented measurement height and roughness; until obtained, source-level normalization must remain BLOCKED. Report the missing inputs, not guessed defaults.

## F — ERA5 availability + 2024-01 comparison

Read original SwissMetNet wind and **explicit ERA5** 10 m wind via the Open-Meteo *archive* reanalysis gateway (`models=era5`, not Best Match). First geographic sites: BAS, GRA, MUB; 2024-01-01 to 2024-01-31. Validate 744 one-hour source timestamps and speed units m/s. Evaluate both nominal same-time and prior-hour clock hypotheses, avoiding post-hoc selection. This is **not** an ERA5 station-residual interpolation model; a new annual train/holdout protocol is still required before adopting it.

## G — DEM valley-axis diagnostic

At CHD, SIO, VIS and GRA use pre-existing Mapzen/Tilezen DEM sampler: 12 radials at 1500 m, opposite-pair mean-elevation minimum as a coarse valley-axis candidate. Compare the **axial (180°)** angle with double-angle mean of original noncalm Swiss 2024 wind, reporting axial resultant. This only probes terrain/wind orientation; does not reconstruct wind direction, solve CFD or adjust any EPW.

## H — First synthetic year, 2025 temporal holdout

At BAS, PAY, VIS draw complete 24-hour original observed wind blocks from **2021–2023 only** using seeded `20261015`, conditioned on calendar month. Compare independent **2025** observed monthly mean speed, annual speed bias, calm frequency and 16-sector wind-rose total variation. Never compare the synthetic day's value to the calendar-day observation as a forecast, and do not use 2025 for calibration. This is a **single-seed day-block bootstrap**, *not* a Meteonorm AR(1) clone, not multi-day physical stochastic closure and not SSP future wind.

## General controls

- Audit original Swiss source SHA-256; no hourly original source exported, no DEM tiles, no commercial Meteonorm files.
- Assert explicit time axis and physical speed/angle conventions, minimum data, no target leakage, seed determinism.
- Compute stage results independently (`fail-fast: false`); phase E's legitimate `height unverified` must not be mistaken for accepted normalization.
- Source quality: historical MeteoSwiss data files do not establish individual QC certification at each original hour.
- Research years and stations have been investigated in earlier phases; no global virgin geographic holdout. 2025 is the first stated temporal synthetic-year check, with previously examined sites.
- No changes to P8.2F moisture, P8.3A/B/C/D wind solvers, or repository `main`.

## Additional blocker: comparison to user's installed Meteonorm 8

This CI **does not have the licensed Meteonorm 8 program or a controlled export by Site / Situation / seed / model period**. We cannot truthfully run identical station-specific Meteonorm-8 comparisons until those user exports are provided. The scripts can be used as an open counterpart after receiving them.

Sources: https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations ; https://open-meteo.com/en/docs/historical-weather-api ; https://registry.opendata.aws/terrain-tiles/

**Not yet executed at protocol freeze:** original-source CI for stages E/F/G/H. Do not infer any numerical stage outcome from contracts alone.
