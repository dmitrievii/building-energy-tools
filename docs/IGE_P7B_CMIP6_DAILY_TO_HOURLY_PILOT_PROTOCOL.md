# IGE P7B — Original CMIP6 daily-to-hourly 2013 historical synthetic pilot

**Stage:** P7B. **Research date:** 2026-10-11. **Branch:** \`research/ige-p7b-daily-cmip6-hourly-synthesis-pilot-20261011\`. No production or main merge.

## Why first historical P7A GHI used NASA POWER, and how to improve that

P7A's purpose was a **complete GHI+DNI+DHI hourly reference** with original NASA POWER direct/diffuse components, rather than a station-measured solar reference. However, **GHI 2013 from GeoSphere should be preferred for a station-first historical EPW** once the original ten-minute source timestamps have been resolved. The earlier audited Graz ten-minute \`cglo\` has 52,520 q21-accepted ten-minute records in 2013, i.e. **8,750 complete six-of-six QC-approved hours** under start-of-interval working hypothesis; this is a compelling primary measured-GHI baseline.

The original station \`chim\` is unavailable numerically for 2013 (only 2006–2009 q21-unchecked numeric observations). Station DNI is also absent in the open data. Therefore a **second historical EPW profile** should be generated later:
- GeoSphere observed GHI at complete quality-screened hours;
- a declared/validated diffuse partition model to estimate DNI/DHI, preserving \`GHI = DHI + DNI cos(zenith)\` at each hour;
- source-matched gaps filled from explicit alternative gridded/derived sources **with a per-hour lineage marker**, not a silently mixed NASA DHI/DNI with measured GHI;
- entire 8760-hour fixed-CET calendar, including cross-year UTC source boundary, original measurement interval support and 2010–11 source-product discrepancies if using other years.

**Do not silently replace P7A's existing immutable original file**. Treat the station-first EPW as a separate engineering branch/backlog after P7B's climate-generation proof. A 2013 station EPW alone is not future climate synthesis.

## What P7B actually implements

The first algorithm genuinely generates **new 8760-hour synthetic weather from original CanESM5 daily model data**. It does not simply reformat NASA POWER original hourly records. Pilot source is the frozen 20-year original-derived NEX-GDDP-CMIP6 CanESM5 \`historical-1995-2014\` daily archive, original successful GitHub source artifact \`ige-p6-CanESM5-historical-1995-2014\` (artifact 11677189364 from original source workflow 38072042977).

The pilot processes the daily 2013 subset (365 dates, native \`noleap\`). It verifies input raw daily source SHA against original \`quality_report.json\` and \`source_provenance.json\`. It preserves \`historical\` and member labels; NASA original NEX \`rsds\` was already BCSD-adjusted; NO P6 M1–M3 correction is silently injected.

**Physical/disaggregation methods, preregistered in code:**
- \`tas_c\`, \`tasmin_c\`, \`tasmax_c\`: 24-hour cosine with minimum at 03 and maximum 15 fixed local CET. In the actual CanESM5 original daily 2013 source \`tas_c ≈ (tasmin_c+tasmax_c)/2\` within <0.001 K, so full source daily mean/min/max can be conserved simultaneously. Explicit fail if that prerequisite fails. This is an initial parametrization, **not** a calibrated observed diurnal profile or nighttime cooling forecast.
- \`hurs\`: daily RH mean preserved using constant within-day relative humidity; hourly dewpoint computed from hourly T/RH. This is physically bounded but deliberately simplistic. Daily \`huss\` cannot in general also be conserved with fixed pressure; independent diagnostic stores source \`huss\`, derived mean-hourly q and mismatch. Full water-vapor closure is **NOT** achieved.
- \`sfcWind\`: seeded persistent random intraday positive factor with exact daily average conservation. No source-observed intraday persistence or measured wind direction; **EPW wind direction = 999 (missing)**. Seed makes replay deterministic.
- \`pr_mm_day\`: seeded hourly storm occurrence with exact daily mm conservation; event timing/distribution is **not** statistically validated.
- \`rsds_kwh_m2_day\`: native horizontal irradiance daily sum conserved exactly, using the approximate NOAA solar-position function and positive daytime hourly weighted distribution. **DHI and DNI are inferred by Erbs hourly diffuse-fraction partition**, physically closing \`GHI=DHI+DNI cos(zenith)\` exactly, with a declared DNI 1350 W/m² bound and review flags; these are **not** measured beam/diffuse irradiances.
- \`rlds_kwh_m2_day\`: constant daily mean diffuse sky LW flux, exact 24h total; meteorological cloud/emissivity dynamics not reconstructed.
- pressure: standard-atmosphere altitude 366 m **proxy** for missing CMIP6 daily local station pressure. This is **not** an independent on-site observation; do not treat as model daily \`ps\`. Wind direction, illuminance, visibility and cloud cover use EPW missing sentinels and may limit EnergyPlus simulation readiness.
- Weather year 2013 is **a synthetic model realization**: no calendar-day pairing to observations. Compare historical model vs historical actual observational distributions at monthly/seasonal levels only, not individual dates.

## Accepted goals for P7B pilot

Produce original-source-pinned, 8760x35 format-verifiable research EPW, synthetic original hourly CSV, per-day 8-variable conservation audit, monthly **unpaired** distribution reference comparison to P7A Graz 2013 EPW and physical-screen counts.

Conservation tolerance \`1e-7\` native source units for daily T mean/min/max, RH daily mean, wind mean, precipitation daily depth, GHI energy and LW energy; all 365 days.

**Explicit cannot-yet-claim list:**
- physically calibrated hourly joint T/RH/wind/cloud/precipitation;
- conservation of daily source \`huss\` or realistic hourly psychrometrics;
- 8 GCM, SSP245/585 2050/2100 generation or climate future uncertainty;
- daily model meteorology exactly follows observed events on dates;
- independently calibrated DNI/DHI, correct inferred solar diffuse fraction;
- full EnergyPlus run or energy-use accuracy;
- EPW production readiness.

## Work plan after P7B

- P7B.1: evaluate diurnal profile distributions and source original huss, calibrate against the real hourly historical GeoSphere and independent NASA POWER solar partition without leakage; reject unphysical cases and quantify seasonal error.
- P7B.2: refine time support, psychrometric q/RH/T/p consistency, autocorrelation and cross-variable daily stochastic/copula coupling; track daily input conservation and reference source selection. Wind direction, pressure and rainfall event statistics need explicit source or proxy methodology.
- P7C: scale one original daily-to-hourly method to all eight GCMs and four SSP future windows; assess physical performance and impact on independent EnergyPlus building simulation before user-facing Climate Analyzer integration.

**Scientific status** remains research only, \`production_epw_ready=false\`.
