# IGE P6.2D — solar correction method selection (research benchmark)

Status: initial 3-method **monthly** comparison only. NO changes to production
Climate Analyzer, no future EPW generation and no claim of a universal NASA
NEX-GDDP error correction.

## Historical scientific basis

- GeoSphere Graz Universität/Heinrichstraße station 30, 1995–2014:
  fully checked calibrated *daily* global horizontal irradiation \`cglo_j\`,
  7305 Gregorian days, \`q21=20\`. Daily J/cm² -> kWh/m² by division by 360.
  Monthly totals were checked against an independently queried official
  GeoSphere \`klima-v2-1m\` solar record, all 240 months matched.
- Eight NASA NEX-GDDP-CMIP6 v2.0 models at the same NASA 0.25° cell center,
  46.875 N, 15.375 E. \`rsds\` daily mean W/m² -> daily GHI by multiplying
  0.024, preserved as immutable accepted P6.1 artifacts with SHA checks.
  The station is geographically offset from the NASA cell.
- Independent matched 2005–2014 solar evidence (annual kWh/m²):
  station 1237.95; PVGIS ERA5 station 1242.62; PVGIS SARAH3 station
  1271.34; NASA POWER grid center 1259.41; eight NEX-GDDP models median
  1620.66. NASA POWER annual-index \`YYYY13\` records are NOT months.
  These values indicate a large discrepancy, but do NOT prove that the
  processed \`GMFD_for_GDDPv2\` contains the same bias.
- 2005 native NetCDF NASA \`rsds\` extraction independently matches
  historical P6.1 CSV; 2005 archived NCAR Princeton GMFD \`dswrf\`
  is nearer observed station values. BUT NCAR archive is not guaranteed
  byte-identical to NASA's specially processed historical GMFD v2 reference.

## Honest temporal split

- Calibration: **1995–2004** (10 observed + 10 independently simulated
  historical years per calendar month).
- Heldout evaluation: **2005–2014** (10 years per calendar month).
- Causal training: model-specific parameters must depend ONLY on
  model-calibration historical samples and observation-calibration samples.
  No station observations from 2005–2014 enter fitted corrections.
- **No paired weather-year scoring.** GCM internal variability does
  not track observed station years. Report month-of-year climatology errors,
  full annual climatology bias, annual p10/p90 differences and empirical
  monthly distribution p10/p90. Test different year orderings of
  observations to ensure invariant scores.

## Methods

| ID | Operation | Caveat |
| --- | --- | --- |
| M0 | Original already-BCSD NEX-GDDP historical \`rsds\` | Baseline, no correction |
| M1 | Per-month, per-model factor = observed-calibration mean divided by NEX-calibration mean; apply to heldout model months | Simple empirical climatology scaling, may distort futures |
| M2 | Multiplicative empirical **quantile delta mapping**: for each month of a target scenario/window, let q be rank among simulated target years; corrected(q) = observed historical quantile(q) * target simulated value(q)/model historical quantile(q) | Preserves the target-to-historical quantile *ratio* algebraically; can be noisy for 10-year monthly distributions; NO hourly clear-sky bound yet |

For M2, the target distribution (historical holdout model years)
determines q, but NONE of its observed reference values are used in
the transformation. Distinguish correction evaluation from future
application; this stage does not yet calculate future windows.

## Required evaluations / decisions

1. Eight individually checksum-verified GCM baseline histories, not an
   ensemble-mean model used as calibration target.
2. For each method, 8 × 12 × 10 heldout monthly predictions, total 2880;
   24 independent model-method scores and 288 month-of-year error rows.
3. Assess whether simple M1 competes with M2 on holdout seasonal
   climatology AND annual distribution spread.
4. Reject a method that creates nonphysical solar values or drifts badly
   on independent data. Do not select solely by calibration fit.
5. Later work: uncertainty of monthly quantiles, blocked temporal
   resampling and sensitivity to split; use longer time series if
   necessary. Test 2040–2059 and 2080–2099 on all eight GCMs and
   compare historical/future quantile change signals to ensure future
   warming/cloud-related solar variations are not erased.
6. Next-stage M3: physically limited clear-sky-aware GHI correction with
   extraterrestrial solar geometry, clear-sky envelope, daylength,
   physical cap and seasonal validation, then hourly generator.

## Literature

- Lange (2019), ISIMIP3BASD trend-preserving bias adjustment,
  Geosci. Model Dev. 12, 3055–3074,
  https://doi.org/10.5194/gmd-12-3055-2019
- Bailey et al. (2025), *Adapting quantile mapping to bias correct solar
  radiation data*, Solar Energy, 289, 113220,
  https://doi.org/10.1016/j.solener.2024.113220
- Lange (2018), *Bias correction of surface downwelling longwave and
  shortwave radiation for the EWEMBI dataset*,
  Earth System Dynamics 9, 627–645,
  https://doi.org/10.5194/esd-9-627-2018

Additional caution: NEX-GDDP-CMIP6 has already undergone statistical
bias correction (BCSD) to a particular historical forcing reference.
Second-stage local correction is NOT an automatic improvement outside
Graz. This benchmark cannot be promoted to a generally valid weather
generator without new locations, reference periods, external holdouts
and joint-physical validation.
