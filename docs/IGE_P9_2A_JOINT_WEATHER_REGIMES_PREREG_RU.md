# IGE P9.2 — Joint Hourly Weather Regime Generator, preregistration of P9.2A

**17 October 2026. Prospective P9.2A protocol, before new real-source pilot.**
Research branch `research/ige-p9-2-joint-hourly-regimes-20261017` from final regional P9.1H HEAD `5c37eeb3`, NOT `main`. No impact on released Climate Analyzer/EPW generators.

## 1. What was learned before P9.2

P8.6O authentic earlier experimental EPWs showed precipitation, humidity, solar and LW coupling significantly weaker than Meteonorm research comparator; weather-hour cloud cover absent from six early original IGE EPWs, prior precipitation occurrence hours repeated unchanged across six EPWs. Source years and models differ, so comparison is **diagnostic**, not proof of station-prediction skill. P9.1H3/H4 ERA5 + generic −1.25 °C night terrain correction **not** qualified at nine AT DE CH source sites; do not carry that correction into P9.2 without a new independent evidence gate. EPW research pipeline P8.5 production remains blocked; do not publish generated annual outputs as qualified.

## 2. Scientific task and explicit A/B separation

**P9.2A:** represent hourly **joint** meteorological weather states using original, internally coherent hourly source vectors (T2m, Td, RH, pressure, rain, total cloud cover, GHI, direct horizontal, diffuse, DNI, 10m wind speed and direction). Frozen regimes: `wet` if original rain >0 mm/h, otherwise `cloudy_dry` if cloud ≥70%, `clear_dry` if ≤30%, else `mixed_dry`. These rules classify actual source cloud and precipitation, **never** invent cloud from RH or GHI.

**Joint-donor method:** seed-fixed, 24-hour **whole-day** donor blocks selected from same calendar month, weighted to reduce unphysical inter-day seam discontinuity of T/Td/pressure/RH/cloud/wind and wet-state jump. Every 12-variable hourly vector, wet spell, sky partition and within-day temporal structure remains untouched. The smoothing penalty at one seam is phenomenological, not validated model physics. The source weather date year is strictly forbidden to coincide with the reference year; no observation residual used in donor choice. No substitution of missing input with clear sky, no silent interpolation, no independent randomization of weather variables.

**Comparison:** matched **iid hourly joint-vector** donor sampling by calendar month and hour, with the same original training vectors and seed. This is a stronger temporal control than a field-independent randomizer: even the baseline retains original within-hour correlations, but breaks synoptic duration and persistence. Comparing field independence would introduce known unphysical output and would not be a meaningful scientific null.

## 3. One minimal authentic source pilot, frozen before reading 2022 coupling

| Region | Source coordinate (WGS84) | Training | Evaluation |
|---|---|---|---|
| AT | Graz (47.0707 N, 15.4395 E) | 2019 and 2020 | 2022 |
| DE | Oberstdorf (47.408 N, 10.280 E) | 2019 and 2020 | 2022 |
| CH | Davos (46.801 N, 9.830 E) | 2019 and 2020 | 2022 |

In each region-year, exactly **10–16 January and 10–16 July**, inclusive, UTC (168 h per month/region/year). Therefore 14 training days per month/region and exactly seven heldout 2022 days. All original hours retrieved from explicit `models=era5`, `elevation=nan`, `cell_selection=nearest`, `timezone=GMT`, same frozen P9.1A backend, **Open-Meteo ERA5-derived source** (not authenticated ECMWF native CDS GRIB). All 12 fields compulsory. One frozen random seed: `7313`. No search for best seed, no new country or dates, no donor residual correction and no CMIP6 future forcing.

2022 previously examined for P9.1H **temperature only**; this is **not** a fully untouched global holdout. Also the reference is **ERA5-derived weather**, not genuinely independent station measurements. Thus these data can establish a pipeline feasibility and *within-source* multivariable dependence diagnostic, NOT independent ground truth of climatological regimes, future weather, country-level generalization, or production qualification.

## 4. Predeclared diagnostics and stop gates

For original reference, 24h blocks and iid hourly controls: fraction of wet hours, P(wet at t+1 | wet at t), wet-spell mean duration, wet-minus-dry RH, cloud, daytime (09–15 UTC) GHI, and mean day-seam absolute T jump. Six named metrics compared by **absolute deviation** from 2022 original-year values; report all improvements and degradations, plus unavailable metrics (e.g. no wet hours), separately. Also report count of named original storm/dry regimes/transitions, SHA256 source HTTP and canonical multivariable series, UTC and physical closure without modifying the source values. Solar GHI at fixed UTC hour is a limited seasonal diagnostic, not an independent solar-geometry normalized clearness-index validation.

A pass of structural tests or a more realistic day-block persistence does NOT qualify stochastic generator. If no source clouds, correct humidity or radiative fields, **BLOCK** cell rather than substitute weather. One source pilot only; exact failure recorded. Do not use any proprietary Meteonorm individual hourly rows in CI; no original source hourly values in CI artifacts.

## 5. Planned next steps (not claimed complete)

- **P9.2B** jointly condition seeded donor **weather regimes** on independent original CMIP6 daily input, enforce daily temperature mean/min/max, total GHI, precipitation amount, wind and humidity, use constrained multivariate adjustment with source-water-mass/radiation closure; validate native daily totals. No simple copying daily observed weather as climate future.
- **P9.2C** new independent 2m station/solar/precipitation/multivariable holdouts in AT/DE/CH, ideally source-qualified measured cloud and longwave; daily/onset/duration/spell extreme error and mean seasonality, with real heldout year. No worldwide validation until publication.
- **P9.2D** explicit annual 8760 EPW mapping, local standard time/calendar, field completeness and inter-field physical checks, independent EnergyPlus tests, release only if existing P8.5/P8.6 unresolved P0 gates pass.

Production flags: `joint_weather_generator_qualified=false`, `global_arbitrary_point_weather_qualified=false`, `production_epw_ready=false`. Do not merge to main without user instruction.
