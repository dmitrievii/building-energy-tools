# IGE P6.2D-B — clear-sky-aware daily GHI correction benchmark

**Research only. No production/main changes, EPW generation, future
scenario adjustment, or claim that 2025 Bailey et al. has been
reproduced exactly.**

## Question

Does explicit extraterrestrial/clear-sky solar geometry improve on:
- M0: accepted historical NASA NEX-GDDP-CMIP6 v2.0 (already BCSD-adjusted);
- M1: train-only model-specific calendar-month GHI scaling;
- M2: train-only model-specific multiplicative monthly GHI QDM?

M3 is **daily solar-geometry-normalized, additive quantile delta mapping**
with independently checked physical daily bounds.

## Source-validated data

- GeoSphere Austria Graz Universität/Heinrichstraße station **30**:
  **47.080000° N**, **15.448056° E**, **366.0 m** from provider station
  metadata. 1995–2014 calibrated 24-hour MOZ \`cglo_j\`, in J/cm²,
  J/cm² ÷360 => daily kWh/m²; every one of 7305 observed days has
  \`q21=20\` and has previously closed against an independent official
  monthly GeoSphere series. NO station target-day observations are used
  to fit the 2005–2014 holdout.
- Eight *immutable original P6.1 NASA artifacts*:
  ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR,
  MPI-ESM1-2-HR, MRI-ESM2-0, NorESM2-MM. Model grid center
  **46.875° N, 15.375° E**; native Gregorian or noleap calendars.
  \`rsds\` is a surface downward shortwave daily-mean flux W/m²,
  kWh/m²/day = W/m² ×0.024.
- NASA cell altitude is **not** available in P6.1 source metadata.
  M3 provisionally uses **366 m station altitude** as a *declared
  proxy*, NOT a terrain-derived model grid altitude. This is an
  outstanding uncertainty to address by a model-cell DEM altitude
  sensitivity analysis.

## Geometry (FAO-56 daily radiation, not TOA-for-GHI)

For latitude \`phi\` (radians), day of year \`J\`:
\`\`\`
dr    = 1 + 0.033*cos(2*pi*J/365)
delta = 0.409*sin(2*pi*J/365 - 1.39)
omega = acos(clamp(-tan(phi)*tan(delta), -1, 1))
Ra = 24*60/pi * 0.0820 * dr *
     (omega*sin(phi)*sin(delta) + cos(phi)*cos(delta)*sin(omega))
Rso = (0.75 + 2e-5*z) * Ra
\`\`\`
The equations return MJ/m²/day; divide by 3.6 to get kWh/m²/day.
\`Ra\` is extraterrestrial solar radiation on a horizontal plane;
\`Rso\` is an *approximate* clear-sky **surface** irradiance envelope.
**Neither replaces observed GHI**.

Observed GeoSphere data show 17/7305 days above nominal FAO \`Rso\`,
max \`GHI/Rso ~ 1.039\`. For a reasonable provisional cloud-edge
allowance, the M3 daily feasibility envelope is:

\`0 <= GHI_corrected <= min(Ra, 1.10 * Rso)\`.

The 1.10 factor is a declared **benchmark parameter**, not a universal
atmospheric upper bound. Its effect MUST be tested against factors
1.05, 1.10 and 1.15, and a more sophisticated clear-sky radiation
model (ineichen/pvlib, turbidity, aerosols, water vapour) must later
be compared before use in scientific or engineering production.

## M3 transformation

Training/calibration station and GCM: **1995–2004**.
Holdout station and GCM: **2005–2014**.
No station/GCM matched weather dates or paired-year RMSE.

For each source day:
\`k = clamp(GHI / Rso, 0, 1.10)\`.

For each calendar month independently, fit **unpaired sorted empirical
distributions** of observed and model \`k\` over all daily records of
training years. For the holdout GCM period, use the empirical rank
within the *holdout model target distribution only* to compute:

\`k_adj(q) = clamp(Q_obs_hist(q) + k_target(q) - Q_model_hist(q), 0, 1.10)\`

\`GHI_adj(day) = min(Ra(day), 1.10*Rso(day), k_adj(q)*Rso(day))\`.

This is *additive QDM in daily clear-sky-index space*; preserves an
additive shift in target index distribution as long as no hard bound
binds. Its use for future signals still needs rigorous quantitative
checks. This is not the same formula as M2 multiplicative monthly QDM,
nor a claim to replicate Bailey et al. exact implementation.

## Artifacts and acceptance criteria

- 8 GCM × four methods M0/M1/M2/M3 = **32 unpaired heldout scores**;
  **384 monthly-method diagnostic rows**.
- Model daily \`rsds\` must conserve each original NASA source monthly
  GHI to <1e-6 kWh/m² (same native model calendar). Freeze source
  checksums and original source in previous accepted GitHub Actions.
- M3 heldout daily output must always be >= 0, <= extraterrestrial
  \`Ra\` and <= 1.10 nominal clear-sky \`Rso\`, with observed/model
  source exceedances counted independently.
- Scores: month-of-year climatology MAE, annual climatological bias
  and annual distribution q10/q90 differences; **no daily weather
  RMSE from unpaired GCM and observed station realisations**.
- Explicitly record model grid altitude as proxy and the monthly
  10-year sample limitations of M2.
- Fail the run if original data hashes differ, monthly coverage fails,
  station q21 is unchecked, source daily units drift, or M3 correction
  breaks the physical envelope.
- Workflow success indicates only *research holdout physical closure*.
  It does NOT prove physical realism of hourly disaggregation or
  end-of-century scenarios, nor generalization to other locations.

## Literature

- FAO Irrigation and Drainage Paper 56, Chapter 3:
  https://www.fao.org/4/X0490E/x0490e07.htm
- Bailey et al. (2025), *Adapting quantile mapping to bias correct solar
  radiation data*, Solar Energy 288, 113220,
  https://doi.org/10.1016/j.solener.2024.113220
- Lange (2019), ISIMIP3BASD, Geoscientific Model Development,
  https://doi.org/10.5194/gmd-12-3055-2019

The appropriate next gate is **P6.2D-C**: sensitivity to altitude
assumption and clear-sky cap, blocked temporal resampling, larger
historical samples for daily/monthly nonstationarity, then application
to five original model scenario windows while preserving seasonal
climate-change signals. Never promote directly to \`main\`.
