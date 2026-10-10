# P6.2D-C — Solar sensitivity and future climate-change signal

## Purpose and status

Research-only experiment extending successfully independently tested
P6.2D-A/B M0–M3 GHI. No production Climate Analyzer, automated EPW
generation, main merge, claims of future truth, or new calibration
against future observations.

The experiment answers two distinct scientific questions:

1. **Sensitivity:** How much does M3 historical holdout quality change
   if we alter the *assumed* NASA cell altitude (200 / 366 / 600 m),
   provisional FAO-56 clear-sky allowance (1.05 / 1.10 / 1.15), or
   historical calibration block (1995–2001, 1998–2004, or 1995–2004)?
2. **Climate-change signal:** How do M1 monthly scaling, M2 monthly
   multiplicative QDM and M3 daily clear-sky-index additive QDM change
   the original model's historical-to-future GHI change ratios in
   2040–2059 and 2080–2099 under SSP2-4.5 and SSP5-8.5?

Retained original sources are SHA-provenance-checked NASA
NEX-GDDP-CMIP6 v2 model daily \`rsds\` flux and \`model_monthly\` summaries
for **eight GCMs × five original windows = 40 model-window products**.
GeoSphere Graz station 30 complete daily \`cglo_j\`, q21 checked
1995–2014, is used exclusively for historical training/assessment.
CMIP6 model days and station days are *not* paired weather predictions.

## Experimental design

Baseline training (1995–2004) is separated from untouched observed
historical holdout (2005–2014). Original baseline M3 equals
P6.2D-B, with model \`Rso\` approximated at 366 m and k<=1.10.
The grid altitude is still NOT known. All 200/366/600 m trial values are
**proxy** elevations, not a claim about actual NASA-cell terrain.

The nine altitude/cap combinations use 1995–2004 calibration. Two
additional calibration blocks run at 366 m/1.10, using 1995–2001 and
1998–2004 while holding 2005–2014 entirely unused in fitting.
The experiment is 11 sensitivity runs/GCM, **88 source-validated
variant scores**, with identical model and station observations.

M3 normalization uses daily solar extraterrestrial \`Ra\` and
FAO-56 \`Rso = (0.75 + 2e-5 * altitude) * Ra\`.
Each calendar month has an independently trained pair of empirical
observed/simulated clear-sky-index distributions. Target-model
distribution rank is computed independently per target window.
The additive quantile-delta mapping of \`k=GHI/Rso\` is limited to
\`0 <= GHI <= min(Ra, cap * Rso)\` with diagnostic clipping/exceedance
counts. No observed holdout values enter the mapping.

For future application, fit model-specific M1/M2/M3 on historical
**1995–2004 only**, then apply identically to the model's complete
1995–2014 historical baseline and to each of four original 20-year
future windows. This distinguishes historical station-calibration
parameters from entirely independent model-generated future
distributions.

For each GCM × future window × method M0/M1/M2/M3, compare the mean
20-year GHI ratio (future/historical) for annual and DJF, MAM, JJA, SON
climatological seasons. This yields **8×4×4×5 = 640** change-signal
scores. DJF is a climatological composite of Dec/Jan/Feb months,
*not* synchronized winter-year weather.

Difference of the corrected GHI percentage change from raw model
NEX-GDDP percent change is a quantitative *signal distortion* metric.
Flag >5 percentage points and >10 percentage points separately for
screening. These thresholds are explicit research screens, NOT
confidence bounds or automatic acceptability criteria.

## Source and validity gates

- Four scenario windows \`ssp245-2040-2059\`,
  \`ssp585-2040-2059\`, \`ssp245-2080-2099\`,
  \`ssp585-2080-2099\`.
- Source/archive provenance and per-file SHA checks must validate all
  40 accepted historical + future original P6.1 products;
  repaired archival sources are selected exactly where required.
- Every native Gregorian/noleap daily record conserves original
  provider model monthly GHI to 1e-6 kWh/m².
- Corrected future GHI cannot be negative or exceed the declared
  FAO-56 extraterrestrial and 1.10×clear-sky bounds.
- Compare historical baseline M3 366 m, cap 1.10 holdout to the
  independently accepted previous P6.2D-B result (e.g. 8 GCM M3
  year GHI bias figures); flag drift.
- Preserve all source SHA, month/season and future daily outputs in
  downloadable GitHub Actions artifacts.
- **Workflow PASS means only that provenance, completed coverage and
  solar physical checks passed.** Distortion screen results may
  require REVIEW; this is not a production gate.

## Decisions after review

1. Compare M3 historical skill across the 11 variants; identify the
   sensitivity to elevation, cap and nonstationary calibration.
2. Summarize distortions of model annual and seasonal climate-change
   signals under each scenario.
3. Do not accept M3 as scientifically superior solely on lower
   monthly climatology MAE; M1/M2 may remain preferable.
4. Independently establish NASA grid-cell elevation and/or DEM source,
   then examine a physically more detailed clear-sky envelope such as
   pvlib Ineichen with atmospheric turbidity and geometry.
5. Multi-site replication, daily multivariate physical coherence,
   solar diffuse/direct separation, future hourly decomposition and
   EPW scientific verification remain later P6 gates.
