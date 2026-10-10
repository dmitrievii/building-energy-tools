# IGE P6.2B — Solar radiation 30% discrepancy scientific root-cause analysis

Date 2026-10-10, research only. NEVER merge to main without explicit instruction.

## Historical evidence already confirmed (1995–2014)

- GeoSphere Graz Universität/Heinrichstraße station 30 \`cglo_j\` calibrated GHI:
  mean of 20 annual totals **1226.349861 kWh/m²/year**; all 7305 days verified
  with q21=20, 240/240 monthly official sums numerically identical.
- Eight NASA NEX-GDDP-CMIP6 v2.0 GCM historical mean annual \`rsds\`:
  1611.8–1637.6 kWh/m²/year across GCMs from the *same* sampled NASA
  grid-cell center (46.875°N, 15.375°E). Station position:
  47.080°N, 15.448056°E.
- The implied anomalous mean-downwelling-shortwave offset is
  +44–47 W/m². In ACCESS-CM2 monthly climatology NASA vs GeoSphere
  differences are ~26–45 kWh/m²/month. This is not a uniform multiplicative
  scale error: percentage differences are most pronounced in winter.
- Original P6.1 converters:
  \`rsds\` reported \`W m-2\`, daily-mean power converted to
  \`kWh m-2 day-1\` by multiplication by 0.024. GeoSphere \`cglo_j\` in
  J/cm² converted to kWh/m² by division by 360. Both are dimensionally sound.
- NASA v2 tech note (May 31 2025) identifies historical GMFD/PGF
  0.25° reference forcing for BCSD calibration across all GCMs in
  1960–2014. The shared-GMFD climatological reference, rather than eight
  unrelated independent GCM errors, is the prime *hypothesis*. This has
  not yet been confirmed by DIRECT extraction of the original GMFD rsds
  records, which is still required for scientific attribution.
  URL: https://www.nccs.nasa.gov/wp-content/uploads/2025/06/NEX-GDDP-CMIP6-v2-Tech_Note.pdf
- Published evaluations of older NCEP-NCAR surface radiation report
  approximately +46.6 W/m² all-sky excess over European reference
  irradiance in the analysed comparison. This magnitude is coincident
  with the IGE discrepancy but is NOT proof the NASA GMFD is affected in
  precisely the same way. Source:
  https://doi.org/10.1175/JCLI-D-20-0979.1

## Independent source validation (this CI)

For an exactly matched 2005–2014 historical sample, independently query:
1. PVGIS-ERA5 and PVGIS-SARAH3 monthly global horizontal radiation, no
   artificial local terrain horizon, at both source station and actual NASA
   grid cell, with raw JRC data and metadata preserved.
   PVGIS MRcalc variable \`H(h)_m\` is monthly global horizontal irradiation
   in kWh/m²/month; no PV-plane irradiation or PV output substituted.
2. NASA POWER all-sky surface shortwave, monthly mean daily kWh/m²/day
   multiplied by the actual historical days in each month, 2005–2014;
   exclusively CERES era (avoid the 2000→2001 SRB/CERES transition).
   Acquire for station and grid center; preserve header unit.
3. Historical \`model_monthly.csv\` of all eight accepted original NASA
   P6.1 GCM sources, source SHA verified, recomputed on 2005–2014 without
   comparing GCM simulated calendar days to specific station weather dates.
4. The q21=20 GeoSphere 2005–2014 calibrated daily sums, preserving native
   GeoSphere 00–24 MOZ timing.
5. Compare annual/monthly GHI and station-vs-grid shifts. A few-km
   grid change cannot simply be *assumed* negligible; quantify via two
   externally sourced grids. Never add solar correction to the product
   in this phase.

## Differential hypotheses

| Hypothesis | Test | Interpretation |
| --- | --- | --- |
| Station sensor or J/cm² conversion | GeoSphere 1d vs official 1m, two independently gridded irradiance datasets | Existing station-to-month closure strongly counters conversion error; two independent gridded checks strengthen confidence |
| NASA units error | Inspect native netCDF var unit, and source daily rates | Existing \`rsds\` W/m² → ×0.024 correct |
| Location mismatch explains >30% | Run the SAME PVGIS/POWER source twice: station and NASA-grid coordinates | Tests possible spatial/topographic climatology differences |
| All 8 GCMs coincidentally each biased >30% | Check NASA technical BCSD historical reference and between-model spread | Shared reference climatology is much more plausible |
| GMFD forcing itself has GHI excess | Obtain **original** GMFD/PGF 0.25° \`rsds\` from NASA reference at 46.875°N, 15.375°E | DIRECT test **NOT YET DONE**; required before claiming definitive attribution |
| NASA NCSS extraction/CF unit decode bug | Fresh source subset vs P6.1 original raw model records with metadata | Confirms source provenance; independent GHI sources alone cannot prove NetCDF parser is bug-free |

NO retrospective quantile correction, universal 0.76 multiplier, EPW
generation, or scientific claim that NASA authors made a programming error.
Even if the raw GMFD reference is high, the original underlying reason for
the GMFD error may include NCEP model radiation parameterization, aerosols,
cloud effects, gridded support, geography and/or solar reference periods.
