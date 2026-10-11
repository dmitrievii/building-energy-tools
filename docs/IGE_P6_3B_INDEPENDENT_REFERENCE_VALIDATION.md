# IGE P6.3B — Independent historic multivariate references and future M3 case studies

**Scope:** two specific >0.10 P6.3A correlation-change anomalies;
research-only. NO production Climate Analyzer/EPW integration.

## Specific cases, independently reproduced from immutable NASA P6.1

| Model | Period | Season | Dependency | P6.3A M3 change-signal distortion |
|---|---|---|---|---|
| CanESM5 | SSP5-8.5, 2080–2099 | JJA | Mean air temperature ↔ GHI | +0.1009038369 Pearson |
| IPSL-CM6A-LR | SSP5-8.5, 2080–2099 | JJA | Downward longwave ↔ GHI | +0.1391316137 Pearson |

These are NOT anomalous observational future weather records. The
source is a future GCM ensemble product; no observations from 2080–2099
exist. Independently verify these P6.3A figures from original daily NASA
data and re-applied original M0/M1/M2/M3 algorithms. Fail if results
change by >1e-8 due to reproducibility failure; do not fit parameters
to these two anomaly magnitudes.

## External historic references, 2005–2014 only

1. **GeoSphere Austria station #30, Graz Universität:** observed
   daily temperature \`tl_mittel\` (°C), observed relative humidity
   \`rf_mittel\` (%), observed precipitation \`rr\` (mm), observed wind
   \`vv_mittel\` (m/s), with explicit q21 quality flags; combined
   with *previously independently verified* station
   calibrated daily solar \`cglo_j\` J/cm² from P6.2B (all 7305
   historical records trusted and annual/monthly energy closed).
   Reject individual unflagged/unchecked/missing reference variables;
   keep their immutable raw values and flags. No infilling, no
   reclassification of q21=0 as acceptable.
   Station humidity and temperature are observed products but not
   necessarily based on the same averaging/integration windows as GHI.
2. **NASA POWER daily original satellite/reanalysis-gridded product**
   at requested NEX-GDDP cell center 46.875°N/15.375°E (underlying
   NASA POWER grid and interpolations may differ from 0.25° NASA cell).
   Request 2005–2014, explicit UTC, six original variables:
   \`T2M\`, \`RH2M\`, \`PRECTOTCORR\`, \`WS2M\`,
   \`ALLSKY_SFC_SW_DWN\`, \`ALLSKY_SFC_LW_DWN\`.
   Provider daily radiation unit must be *verified from metadata*
   then converted, if needed, to kWh/m²/day.
   **This is NOT a direct ground-based longwave observation** and
   may share upstream reanalyses with other evaluated archives.

All original provider response JSON and SHA-256s are archived.
Reject source unit drift, unexpected provider/station ID or incomplete
native chronology. Record missing POWER days rather than synthesize
weather.

### Daily time-window caveat

GeoSphere daily \`cglo_j\` irradiance covers 00–24 MOZ
(23:00 previous UTC day to 23:00 nominal UTC day).
GeoSphere daily \`rr\` and temperatures are based on DIFFERENT
integration/observation intervals. Station date-label pairing of
temperature↔solar and precipitation↔solar produces an
**approximate diagnostic** of day-scale dependence, not precisely
synchronized hourly fluxes. The original model and observed
station/POWER daily dates must **NEVER** be paired as if a GCM were
a weather forecast of 2005–2014.

## Metrics and protocol

- Comparison: historical JJA 2005–2014 **within-source Pearson and
  Spearman correlations** of air temperature ↔ GHI for CanESM5;
  downward LW ↔ GHI for IPSL-CM6A-LR. Each source is scored
  as an *unpaired distributional dependence statistic*.
- For station/POWER 2005–2014, independently estimate confidence
  variation with 500 deterministic 10-year *year-block bootstrap*
  repetitions (resample whole JJA yearly blocks, NOT individual
  days). Do not interpret these percentile intervals as covering
  sampling bias, underlying input-source bias, time-integration
  boundary error or GCM structural model uncertainty.
- Replicate native model historical 1995–2014 / future SSP585
  2080–2099 joint-weather correlations for all four solar methods.
  Report the actual P6.3A future-minus-historical correlation-change
  distortion under M3.
- For each problematic future/historical GCM, stratify JJA days
  by decile of the ORIGINAL unmodified model temperature or LW
  variable; quantify the M3 solar decrement, physical clipping
  and original-model GHI. This is **distributional mechanism
  evidence, not causal attribution**.
- The observed source may have sparse months or missing values;
  report **INSUFFICIENT_QC_SAMPLE** if JJA sample <150
  for station or <300 for NASA POWER; do not silently fill gaps.
- No claim that reproducing the raw GCM correlations implies a
  physical improvement: station/POWER references may have different
  climate and topography.
- No claim of full psychrometric/radiative-energy closure, because
  station \`rlds\` and verified matched-hour pressure/cloud/longwave
  budget are unavailable.
- The original NEX-GDDP climate GHI was **already corrected by
  BCSD**; all local M1/M2/M3 changes are experimental.

## Code and resource references

- GeoSphere Austria official daily resource \`klima-v2-1d\`:
  https://dataset.api.hub.geosphere.at/app/frontend/station/historical/klima-v2-1d
- GeoSphere API resource documentation:
  https://dataset.api.hub.geosphere.at/v1/docs/user-guide/resource.html
- NASA POWER daily data API:
  https://power.larc.nasa.gov/docs/services/api/temporal/daily/
- NASA POWER original product documentation:
  https://power.larc.nasa.gov/docs/tutorials/parameters/

Acceptance for this stage is **source provenance verified +
observational dependence metrics computed or explicitly marked
insufficient + both original M3 anomalies reproduced**.
No pathway to production from P6.3B alone.
