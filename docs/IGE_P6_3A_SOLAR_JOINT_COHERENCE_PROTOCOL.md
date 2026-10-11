# IGE P6.3A — Joint physical/dependence impact of solar correction

**Research and source diagnostics only. Does not implement future EPW,
hourly diffuse/direct irradiance, or a full psychrometric closure.
Do NOT merge to main or silently change any original NASA provider data.**

## Scientific question

How does independently calibrated local downward solar radiation
(\`rsds\`, GHI) correction change its relationships with the other original
multivariable NASA NEX-GDDP-CMIP6 v2 daily climate variables?

The independent GeoSphere Graz #30 QC-confirmed solar reference
(1995–2014 daily \`cglo_j\`) trains ONLY the 1995–2004 solar
calibration parameters. All other joint-weather quantities remain
**original NASA GCM values**. This is a test of the **preservation of
model-internal relationships**, not measured multivariate station
skill. NASA historical years and GeoSphere station-year weather are
NOT synchronous. No paired daily-year weather performance scores.

## Exactly which sources and methods

- Original SHA-checked NASA P6.1 archive for **eight climate models
  × five 20-year windows = 40 independent model-window products**.
  Original native calendar is Gregorian or noleap, and original
  accepted \`rsds\` [W/m²] ×0.024 = [kWh/m²/day].
- \`M0\`: raw already-BCSD-adjusted original native NASA \`rsds\`.
- \`M1\`: per-model, per-calendar-month historical GHI mean-ratio
  calibration 1995–2004; corrected month from original P6.2D-C method,
  then multiply each native model day in that year-month by the
  **same target/month original solar energy ratio**.
- \`M2\`: monthly multiplicative QDM calibrated 1995–2004;
  apply each target model-month corrected/original ratio to the native
  individual model days within the same month. This **exactly
  conserves monthly M2 output**, but must **not** be falsely presented
  as fully calibrated daily QDM. It cannot repair submonthly weather
  relationships or intra-month GHI distribution shape on its own.
- \`M3\`: same P6.2D-C original FAO-56 daily clear-sky-index QDM,
  \(k = GHI/R_{so}\), cloud allowance 1.10 and NASA elevation proxy
  366m. All corrected days respect \`0 <= GHI <= min(Ra, 1.10*Rso)\`.
  This is a research variant, not an exact copy of a published method.

Historical training 1995–2004, historical structural assessment
1995–2014, and historical accuracy holdout previously closed using
2005–2014 only (P6.2D-A/B). Future periods are:
\`ssp245-2040-2059\`, \`ssp585-2040-2059\`,
\`ssp245-2080-2099\`, \`ssp585-2080-2099\`.

## Model variables and dependencies

All native daily \`tas\` (and \`tasmin/tasmax\`), \`hurs\`, \`pr\`,
\`rlds\`, \`sfcWind\` are unchanged. \`huss\` is original where the
P6.1 provider has it; no gap-filling for IPSL-CM6A-LR.

For every model/window/solar method and each season
ANNUAL, DJF, MAM, JJA, SON:

1. Compute daily Pearson and Spearman rank correlation for
   \`tas_c ↔ GHI\`, \`hurs ↔ GHI\`, \`pr_mm_day ↔ GHI\`,
   \`rlds_kwh_m2_day ↔ GHI\`, \`sfcWind ↔ GHI\`.
2. Estimate wet/dry solar contrast, where wet days have
   \`pr >= 1 mm/day\`; and mean GHI on days in the upper decile
   of daily mean model temperature. Model temperature and rain
   classifications use ORIGINAL source values.
3. Count original and adjusted GHI exceeding the FAO-56
   extraterrestrial \`Ra\` or provisional 1.10×clear-sky \`Rso\`,
   and any negative/invalid GHI values.
4. For each future window, quantify \`rho(future)-rho(historical)\`,
   then measure how much that **climate-change dependence signal**
   differs between each corrected M1/M2/M3 and raw M0.
5. Flag any Pearson or Spearman change-signal distortion
   **>0.10** (screen) and **>0.20** (severe). These are
   transparent, provisional effect-size screens; not
   statistically derived significance thresholds or normative
   confidence bounds. No screen is silently treated as approval.

## Acceptance and reproducibility

- Original full source archives and SHA-256 digests checked
  using same accepted P6.1 source validation; check original
  date/model/scenario identity across solar and native joint data.
- M1/M2 disaggregated daily sums conserve **every corrected target
  month** within 1e-6 kWh/m². The model's original native
  \`model_monthly.csv\` also matches daily \`rsds\` input.
- M3 never negative, never above extraterrestrial \`Ra\` or
  1.10×\`Rso\`; record raw and M1/M2 exceedance diagnostic
  without silently clipping them or changing monthly sums.
- All original non-solar daily variables preserved, not replaced
  with inferred station values or weather synthesis.
- Produce 40×4×5×5 = 4,000 relationship rows, 800 conditional
  solar/rain/heat diagnostics, 160 physics/source QA rows and
  32×4×5×5 = 3,200 climate-change-dependence diagnostics.
- Store all original input archive SHA and scientific warnings.
  CI PASS signifies computational source/QC and reported screen
  completion **only**, NOT observational validation.

## Critical scientific limitations

- \`hurs\` may naturally contain source overshoots above 100%
  (~0–5 percentage points), explicitly accepted as immutable
  provider data in P6.1. They are not changed here.
- Native pressure \`ps\` and observed hourly humidity pairing
  are unavailable; therefore no credible exact
  \`tas + hurs + huss + pressure\` psychrometric closure
  can be claimed. Relative humidity and specific humidity can
  also have temporal averaging inconsistency.
- Downward shortwave and downward longwave alone cannot prove
  energy balance closure: reflected shortwave, upward longwave,
  cloud/aerosol and albedo data would be required.
- Dependence preservation is **not proof that raw correlations
  correspond to physically observed relationships**. Further
  field measurements, additional cities and coherent multivariate
  bias-adjustment tests are necessary.
- Solar correction has effects on building energy (overheating,
  passive heat gains, cooling loads) not quantified in this phase.
  No model may be promoted for EPW from P6.3A alone.
