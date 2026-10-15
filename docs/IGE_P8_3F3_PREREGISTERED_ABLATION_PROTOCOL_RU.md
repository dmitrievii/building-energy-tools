# IGE P8.3F3 — frozen factorial ablation and additional-year / additional-site generalization

**Protocol committed BEFORE executing any F3 original 2022/2025 data analysis.**
Branch: `research/ige-p8-3f3-wind-ablation-20261015`, parent fixed P8.3F2 research `f4ecdc8e120aa2d9d85c56eb9448bebb4724d199`.

## Aim and confirmation limits

Distinguish the effects of donor *selection*, altitude-weight attenuation, shrinkage, weak-wind taper, and text-category exposure match. Avoid explaining improvements with "physical terrain" unless a separate effect actually survives ablation and independent site/year evaluation. No tuning of frozen factors on validation targets.

- Donor training: original SwissMetNet station hourly wind + Open-Meteo **explicit `models=era5`** 10-m GMT wind, **2023**, donor IDs `ABO BER PAY DAV LUG GVE SIO SMA WYN ZER`, each with >=400 paired hours **in every calendar month**.
- New withheld target identities: **`MOE MAS NEU GUT FRU BOL`**, chosen from previously published P8.3D *donor* station IDs, before reading F3 target responses. None may occur in calibration. Targets have distinct geographical / topographic settings, but are not a representative randomized Swiss sample.
- Test years: **2022** (genuinely additional temporal validation compared with F1/F2, retrospectively *before* training) and **2025** (contemporaneous alternate target identities but 2025 previously examined in F2). Keep separate results per year; 2025 is not virgin temporally; those targets were donors in earlier studies, not unseen anywhere in IGE.
- Original source timestamps: UTC nominal same hour; station mean versus reanalysis time definition remains unresolved, and no test-year clock shift optimization is permitted.
- Require 80% of 8760 site-hours on strictly identical reference, ERA5, and donor-baseline predictions. Fail closed per target; separate site failures/source gaps from predictive error. Do not claim six-site closure unless all six qualify.
- Original 2023 donors are qualified before inspecting any 2022/2025 target outcomes; 2022 is not used to select 2025 models or vice versa.

## Frozen 2^5 factorial (=32 correction variants)

Each combination uses 2023 monthly scalar and wind-TO u/v residuals. Indices `S W H T E` indicate:

| Factor | Level 0 | Level 1 |
|---|---|---|
| S selection | closest 4 donors, distance | P8.3D frozen altitude-distance score `sqrt(d_km²+(0.04 Δz_m)²)` |
| W interpolation weight | `1/max(d_km,0.25)^2` | same multiplied by `exp(-abs(Δz_m)/500)` |
| H residual amplitude | full amplitude `1.0` | shrink `0.5` |
| T weak-wind taper | no taper | `min(1,v_ERA5/2)` |
| E exposure category | no category penalty | `0.5` weight multiplier for known, nonmatching categories |

All weights strictly normalized and nonnegative. Unclassified category is neutral. Text-only categories are `plain`, `slope`, `elevated_above_valley`, or `unclassified`; they are NOT surface roughness `z0`, mast elevation, WMO class or aerodynamic exposure. No 10-m vertical profile adjustment. The original F2-A model is **S1_W1_H1_T1_E0** and F2-B is **S1_W1_H1_T1_E1**, while F1 is **S0_W0_H0_T0_E0**.

Also compare:
- `era5` uncorrected (common-input primary physical benchmark);
- `observed_distance_idw4` and `observed_altitude_idw4_restricted_pool` with real contemporaneous 2022/2025 donor observations. **Both use extra measured same-year wind unavailable to ERA5-only modes.** The latter uses the original P8.3D altitude selector equation but only within the F1 2023-qualified 10-donor pool; it is not the original *full-census* P8.3D candidate model, and must be labelled accordingly.

## Performance and inferential control

Per target/year report speed MAE/RMSE/bias and fixed-denominator noncalm direction `90°` missing-angle penalty, resolution. Report all 32 variants, baseline and original-F2 outcomes on **identical measured hours**. Four independent seasonal strata. Per-year equal-site macro and matched-hour micro averages. No model selected by optimizing an individual target's error.

Predeclared primary factor contrasts: marginal **within-target** differences of speed MAE averaged over the other four factor levels, for S, W, H, T, E separately. Quantify factor interaction for H×T and W×E; the factorial does not imply orthogonal observed meteorology, just balanced evaluated variants.

For primary frozen F1 and F2-A/B relative to raw ERA5 report 95% deterministic 7-day contiguous-block bootstrap CI of paired hourly absolute-error difference, **300 repeats**, fixed seed. Use physically contiguous sampled blocks only; missing target readings must not be treated as adjacent in time. These per-site/year CIs describe uncertainty *conditional on that station/year*, not cross-region model generalization.

Scientific promotion criterion:
1) at least **two different year/site panels** with an explainable stable variant better than raw ERA5 in equal-site MAE;
2) no material adverse site-level tails (focus CHD analogue, ridge/valley classes);
3) direction and unresolved coverage do not materially deteriorate;
4) no post-hoc coefficient tuning and no leaked target observations;
5) eventual third geography/independent country and corrected measurement-time semantics required before production status.

## Resources, failure policy and license

Scripts run on an isolated research branch, upload **derived aggregate JSON only**, station/file SHA256 provenance and calibration coverage, never source hourly Swiss/ERA5 timeseries, derived hourly predictions or third-party DEM rasters. External provider failures are reported, not silently replaced with another provider. The entire main branch, production EPW and Streamlit are untouched.

Result status means `CI_PASS_RESEARCH` only; `production_epw_ready=false` until physical and scientific approval.
