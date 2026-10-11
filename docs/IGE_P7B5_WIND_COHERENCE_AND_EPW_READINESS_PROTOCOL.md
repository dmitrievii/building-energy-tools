# IGE P7B.5 — Multivariate Weather Coherence and EPW Readiness

**Date** 2026-10-11. **Stage** controlled research; not a production EPW or validated future climate. **Source branch:** independently branched from P7B.4 `3e42db6a484dc916c9d858519efe531090a35c3e`; `main` immutable.

## Purpose

P7B.4 correctly carries all 8760 hours of 2013 CanESM5 historic pilot weather, with new conditional stochastic GHI but **all 8760 EPW wind directions = missing sentinel 999**. A meteorologically meaningful direction cannot be derived uniquely from wind speed. P7B.5 therefore attempts a **new original-observation-informed conditional wind-direction generator**, while preserving every existing EPW field except wind direction. If trustworthy training data or withheld QC reference are absent, fail closed, keep original EPW, and explicitly report no wind generation.

## Original sources and pre-registered splits

- Original P7B.4 accepted EPW SHA-256: `2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012`, GitHub Actions #38171672579, unmodified source.
- GeoSphere Austria original `klima-v2-1h` hourly data (CC BY 4.0), station #30 Graz; source URL: `https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h`. Required original fields `dd` (°), `dd_flag`, `ff` (m/s), `ff_flag`, plus `tl`,`rf`,`rr` and their original QC flags. Historical readings are not substitutes for synthetic 2013 event timing.
- Train Graz **2007–2008** only. **2009** reserved for model-selection diagnostics (not used to fit or select the frozen algorithm here). Validate observations **2012–2014** only, no adaptation after seeing outcomes. Previous project work on these years means they are not globally pristine holdouts, but the exact original hourly direction records have not been used in the P7B.3 phases.
- Two source clock hypotheses `record_start` and `record_end` must be retained and evaluated independently. One is not selected by fit. The first hypothesis is used solely for one marked candidate research EPW; the official hourly original instrument averaging-window convention remains unresolved.
- Provider-accepted q21 codes `{10,11,12,20,21,22}` only. Null/missing/unverified q=0 and nonphysical values are excluded without imputation; calm speed `<0.5 m/s` does not require an actual direction. Complete 24h days are required. Preserve the original metadata and year-file byte SHA-256 in audit, exclude raw provider records from public outputs.

## Independent hourly wind methodology

A day-level original measured direction-sequence *analogue* is drawn deterministically from the 20 closest QC-qualified days **of the same meteorological season**, ranked by (1) source/model daily mean wind speed, (2) average temperature, (3) RH, and (4) wet/dry classification when original hourly precipitation qualifies. Use seeded `SHA256('P7B5:WIND:' + seed + ':' + model_date)` for reproducible donor selection. This conditions direction on existing weather but does **not** alter source-model wind speeds or pretend measured wind on model calendar dates. For calm model hours set EPW direction to `0°`; for a non-calm target hour whose donor was calm, use the nearest available originally QC-approved donor direction within that donor day, count fallback incidence. No uniform random or North-as-default fabrication. No machine-learned source code or Meteonorm proprietary algorithms.

## Science and EPW gates

- Verify input 8760-hour EPW exact SHA, 8 headers, 35 columns, fixed-CET 2013 1–24 timestamps, missing wind direction *before* any mutation. All other 34 EPW fields are exactly identical, no source solar, air temperature, humidity, pressure, rain, or wind speed changes.
- Validate paired independent original hourly wind direction and speed quality, complete days at least **30/season in training**, at least **180 full days in 2009**, and at least **600 complete days in 2012–2014** for both clock hypotheses. Fail closed if inadequate.
- Compare generated direction **wind-rose distributions**, calm filtering, mean circular turning angle and sector total variation, using withheld 2012–2014 **observed speed-only conditioning** and *observed held-out direction only as reference*. No calendar-day forecast skill claim; no tuning after holdout.
- Enumerate EPW missing scientific fields (all 8760 P7B.4 source hours lack wind direction, total/opaque sky cover, visibility and precipitable water; a new wind direction candidate does not make other fields observed or validated). Pressure is elevation proxy, solar components DHI/DNI Erbs estimates lack observed instrument QC, RH temporal correlation not validated, no actual EnergyPlus building simulation performed.
- Research status is always `production_epw_ready: false`; no production-level wind/airflow/energy-load predictions, urban canopy adjustment, international transfer, or SSP future climate certification.

## Provider and format references

- GeoSphere hourly provider and original parameter-specific flags: https://data.hub.geosphere.at/dataset/klima-v2-1h
- Official GeoSphere metadata: https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata
- EnergyPlus EPW field semantics (wind-direction 999 missing, 0–360° observed or generated): https://bigladdersoftware.com/epx/docs/9-2/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html

## Further research gates

1. Determine original hourly wind time-interval convention, compare circular/speed-binned sector climatology and duration/autocorrelation across multiple independent sites, elevations and climates.
2. Test large-scale wind-flow consistency, especially geostrophic direction and terrain effects. Source CanESM5 daily `sfcWind` magnitude alone does not encode a physically unique wind direction; original gridded `uas/vas` or pressure circulation patterns would materially improve inference.
3. Replace proxy pressure and unspecified sky-cover/water-vapor data with source-registered variables and confidence flags, not unconditional fillers. Validate instruments for DHI/DNI.
4. Independently open EPW with EnergyPlus and execute matched natural-ventilation / HVAC simulations before approving use in building design.