# IGE P7B.2 — Physically bounded hourly climate synthesis, source-registered humidity tradeoffs and station-calibrated solar

**Research phase:** P7B.2, 2026-10-11. **Active branch:** \`research/ige-p7b2-moisture-solar-calibrated-hourly-20261011\`. Source code \`research/ige_cmip6/p7b2_hourly_physically_bounded_synthesis.py\`. This work starts from original, SHA-verified historical CanESM5 2013 synthetic hourly P7B EPW and original 1995–2014 NASA NEX daily data, plus independent original GeoSphere 2005–2014 observed ground daily GHI. Original P7B and integrated earlier science freezes remain immutable; no merge to \`main\`.

## Problem 1 — humidity source incompatibility and transparent physical hierarchy

The previous P7B kept original daily \`hurs\` through a flat RH profile, but source \`huss\` daily was not conserved, largest error ~3.57 g/kg. P7B.1 tested bounded smooth RH amplitude ≤25 pp and could close 109/365 days. A more general **bounded 24-hour RH redistribution** tested in P7B.2 removes that unnecessary narrow-amplitude constraint but respects **RH 1–100%, dewpoint ≤ dry bulb and fixed standard-atmosphere pressure**. It must not falsely claim all original \`hurs\` and \`huss\` are jointly feasible when source GCM lacks corresponding daily local air pressure.

Pre-registered source-priority process:
1. For each of 24 original immutable T hours and native daily mean \`hurs\`, try RH profiles with successively registered max-amplitude levels [10,20,30,40,60,80,100] percentage points. At each level redistribute RH preferentially toward cooler / warmer hours preserving original \`mean(RH)=hurs\` and physical bounds. Monotonic interpolation from flat RH to those extremal profiles searches for the original native \`mean[q(T,RH,p)] = huss\`, with exact 1e−9 kg/kg tolerance.
2. If native joint \`hurs+huss\` cannot be satisfied within this registered family, but source \`huss\` is reachable by an RH-constant profile at documented pressure, **conserve source \`huss\` and report explicit source \`hurs\` daily deviation**. The actual relative-humidity mean has changed and must NOT be misrepresented as conserving native RH. Dewpoint remains computed consistently with generated T/RH.
3. If native \`huss\` is beyond all-hour RH saturation at the fixed hydrostatic pressure, **use physically saturated RH=100%, retain source \`huss\` mismatch**. Neither supersaturation (RH>100%) nor an undocumented variable pressure shift is permitted.

Output original P7B source hourly remains unchanged. New P7B.2 has **per-day 365 source-conservation/tradeoff flags** including number of jointly closed days, number of days where native hurs is relaxed, number of days where source q is physically unachievable at the fixed pressure; report residuals in original units. This is an explicitly bounded *engineering candidate*, not statistically calibrated real-hour diurnal moisture dynamics or proof of physical incompatibility under arbitrary pressure.

## Additional P7B.2 source-only runtime discovery: RH discontinuities and fixed-width temporal regularization

The first original-source scientific run [#38148686542](https://github.com/dmitrievii/building-energy-tools/actions/runs/38148686542) **PASS** for source SHA, 8760x35 syntax and hourly 1–100% RH but additional independent inspection found **310 adjacent hourly differences above 30 RH percentage points, maximum nearly 99 pp**. That initial result is preserved in its immutable action artifact, but **must NOT be recommended as realistic hourly climate**. Individual bounded RH does not ensure temporally plausible humid-air evolution.

A revised **separate EPW file** now applies a fixed, deterministic **5-hour, centered, all-8760-hour rolling average** to generated RH **across every daily boundary**, not a discontinuous per-day treatment. For source RH between 1–100%, this simple averaging guarantees a mathematical ceiling below 20 RH percentage points difference between adjacent smoothed hours. Dewpoint is recalculated from **unchanged original model-hour dry-bulb temperature and final smoothed RH** to preserve state consistency.

**Scientific source trade-off:** RH smoothing can change both **original daily mean RH** and **original native daily huss**. Therefore after the filter, recompute and report BOTH daily source constraints from the FINAL 8760-hour EPW; original pre-filter closure classes 239/112/14 remain labelled as *pre-continuity*, not false final source conservation. The final hourly file must carry distinct name \`Graz_2013_CanESM5_P7B2_HISTORICAL_BIASCORRECTED_RH_CONTINUOUS_RESEARCH.epw\` and a new source SHA. The original first P7B.2 output remains archived unchanged.

The rolling filter is a **necessary plausibility screening correction**, not a calibrated meteorological model: it introduces 5-hour numerical correlation by construction, can dampen real changes and does not establish realistic diurnal humidity statistics against GeoSphere observations. Final original hurs/huss discrepancies are scientific metrics, NOT software errors to erase by undocumented values. The next model should seek physically grounded moisture pressure/time-series covariance, not merely wider arbitrary smoothing.

## Problem 2 — independent source-trained historical ground GHI correction with proper holdout

Earlier P7B.1 historical CanESM5 2005–2014 native model daily GHI climatology exceeded **actual quality-checked GeoSphere Graz station** by 29.96%, and NASA POWER gridded source by 36.98%. P6 also identified internal GeoSphere daily-vs-ten-minute solar disagreement in **2010–2011**, even for individually provider QC-accepted data, so these two years are quarantined from the calibration.

**Fixed before computing new EPW:**
- **TRAIN** original CanESM5 historical model daily \`rsds\` versus actual GeoSphere Graz original quality-approved daily GHI: **2005–2009 only** (five years).
- **EXCLUDE** **2010–2011** from local radiation calibration and holdout due to source-resolution disagreement.
- **HOLDOUT** **2012–2014** (three years). These three years do not influence the fitted factors. 2013 original observed ground GHI does **NOT** enter calibration of its synthetic 2013 weather.
- For each month independently, use ratio of station observed and original modeled **mean daily solar energy** over the training years: \`factor_m = mean(ground_GHI_m)/mean(CanESM5_GHI_m)\`. Fail closed if factor outside preregistered [.45,1.20]. No day-event matching of CMIP6 to real observed dates, training or holdout: climatological distribution only.
- NEX-GDDP original daily \`rsds\` is **already NASA BCSD-adjusted**; this is an explicitly documented *additional local correction*, and potential double-adjustment is a genuine scientific risk. Do not assume it will generalize to SSP/future model or a different site; evaluate the holdout.
- Generate 2013 corrected daily GHI = original daily CanESM5 \`rsds\` × pre-2010 monthly factor, then distribute hourly following the existing original P7B astronomy (NOAA approximate sun position) and Erbs DHI/DNI partition; preserve \`GHI = DNI*coszen+DHI\` by construction.
- **Critical source semantics:** original native daily **GHI is deliberately changed** by the explicit bias correction, and cannot be claimed conserved. The **corrected daily GHI target** is conserved exactly. Native daily T mean/min/max, wind-speed daily mean, precipitation daily total and longwave total are preserved from source original P7B.

Original station GeoSphere daily solar 23–23 UTC convention is used **for monthly climatic distributions only**. It is not directly compared day-by-day to GCM dates; leap Gregorian station years normalized to 365 days for annual comparisons. Neither in-sample climatological bias closure nor 3-year holdout alone establishes a generalizable method across eight GCMs.

## Research EPW and exact acceptance criteria

New separate \`Graz_2013_CanESM5_P7B2_HISTORICAL_BIASCORRECTED_SYNTHETIC_RESEARCH.epw\`:
- 8 EPW headers + 8760 2013 fixed-CET no-DST consecutive hours × 35 fields, source model location [46.875°, 15.375°] grid and proxy elevation 366 m;
- physically valid 1–100% RH, \`Tdew≤Tdry\`, positive pressure proxy, retained nonnegative wind and rainfall, original native temperature and non-radiative daily conservation;
- new solar-corrected daily GHI and synthetically derived beam/diffuse terms with detailed original/target delta and model provenance;
- explicit FINAL source daily hurs/huss and status classes after cross-day RH continuity, plus PRE-filter status classes; **no false claim both are conserved on incompatible days**;
- 12 original observed-GeoSphere training coefficients (2005–2009), 12 withheld monthly climatological evaluation records (2012–2014), exact SHA of source originals and derived EPW/CSV;
- scientific status **RESEARCH ONLY**, \`epw_production_ready=false\`, no actual EnergyPlus model simulated, no future SSP year generated, no user-facing Climate Analyzer integration.

**Next action after source CI:** inspect actual source mismatch counts, measured holdout skill for warm/cool seasons, and test longer-term/higher model-class across NASA NEX eight-GCM and SSP windows before any future EPW claims. For complete atmospheric physics, original GCM \`ps\` or a verified local barometric source and true hourly meteorological copula model remain scientifically important. The measured-GHI historical station-first EPW \`P7A-S\` is a separate line and remains valuable.
