# IGE Independent Climate Engine — P6.2B Solar Reference Closure

**Scope:** GeoSphere Graz Universität/Heinrichstraße (station 30) source-calibrated
solar radiation benchmark, 1995–2014, plus UNPAIRED NASA NEX-GDDP-CMIP6
historical monthly GHI climatology for eight selected models.

**Status:** Workflow must pass before source closure or model residual claims.
Branch is research only; do not merge into production main.

## Source-derived definitions

Official GeoSphere \`klima-v2-1d\` parameter \`cglo_j\`:
"Globalstrahlung, kalibrierte 24-Stundensumme aus den Stundenwerten 0-24 Uhr
MOZ (23 Vortag - 23 Tag UTC)" in **J/cm²**.
\`klima-v2-1m\` \`cglo_j\`: monthly sum from calibrated hourly values in J/cm².

Thus daily sum in kWh/m² = raw J/cm² / 360. Preserve raw original
JSON bytes, q21 \`cglo_j_flag\` and checksum. Accept only source QC
\`10,11,12,20,21,22\`; reject values with \`q21=0\` from reference averages
without modifying their source. Preserve source gaps, no imputation, and use a
month only when all days have checked source values. Record monthly official
source flag separately. Do not mask the difference between daily MOZ periods
and separate NASA/GCM daily calendars.

GeoSphere station metadata: Graz Universität/Heinrichstraße, 47.080000° N,
15.448056° E, 366 m. NASA sample grid center: 46.875° N, 15.375° E.
The two measurement supports are spatially different, and climate-model days
are not phase-aligned with station historical days.

## Reproducible workflow

1. Request 4 independent 5-year spans of GeoSphere original calibrated daily
   \`cglo_j,cglo_j_flag\` source: 1995–1999, 2000–2004, 2005–2009, 2010–2014.
   Check UTC labels, Gregorian leap days, exact day continuity, metadata units,
   q21 values, physical plausibility, and SHA-256.
2. Get official 240-month \`klima-v2-1m\` \`cglo_j,cglo_j_flag\` source from
   the live GeoSphere endpoint, with independent source hash. Compare each
   fully checked daily solar month to checked official monthly sums. **Do not
   force equality**: source day boundaries and source aggregation can differ.
   Report exact disagreement and count comparable months.
3. Download original accepted P6.1 NASA historical artifacts, checksums and
   provenance: ACCESS-CM2 from Actions run 38067931031; CanESM5/GFDL-ESM4/
   MRI-ESM2-0/NorESM2-MM from run 38072042977; EC-Earth3/IPSL-CM6A-LR/
   MPI-ESM1-2-HR from accepted repair run 38077903914. Never reuse failed
   original history artifacts.
4. Compute 12 **month-of-year, 20-year climatology** GHI comparisons for
   each of eight GCMs, preserving original NASA native model calendars.
   Use only complete checked observed months; require >=15 eligible observed
   years for a month-of-year to declare a reliable residual estimate.
   Report average/ratio and unpaired distribution p10/p90. DO NOT compute
   year-by-year/daily matching RMSE or train a local bias correction.
5. Report source availability separately from validity. Zero usable station
   months still permits an honest provenance report but *does not mean a
   validated local solar reference*.

## Non-goals

- No second NASA BCSD bias correction.
- No hourly or EPW synthetic weather, no global radiation reconstruction from
  sunshine hours and no implicit timezone equivalence.
- No assumption that station 30 and the 0.25-degree NASA source cell have
  identical topographic, cloud or aerosol exposure.
- No quantile mapping without independent holdout testing and multivariate
  physical closure.

## Official reference

GeoSphere Austria, Station Data-v2 (1d):
https://data.hub.geosphere.at/dataset/klima-v2-1d .
The official daily product describes historical quality flags with \`_flag\`
and some observation-day boundaries in MOZ/MEZ. Its 1d source metadata
defines the exact parameter-specific \`cglo_j\` MOZ interval.

NEX-GDDP-CMIP6 v2.0 is already BCSD-based; the residuals obtained here
must not be interpreted as an independent model daily forecast error.
