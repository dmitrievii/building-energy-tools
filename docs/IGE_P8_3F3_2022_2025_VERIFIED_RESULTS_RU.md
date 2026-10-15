# IGE P8.3F3 — independent 2022/2025 factor-ablation research closure (2026-10-15)

**Verdict:** `CI_PASS / ORIGINAL_SOURCES_PASS / FACTOR_ABLATION_NEGATIVE_FOR_GENERAL_CORRECTION / PRODUCTION_REJECTED`. Original run [#38730707530](https://github.com/dmitrievii/building-energy-tools/actions/runs/38730707530) on commit `13f5f0e1ac5e18a1b58a6a0f40902c7b5d42a94a`: **3/3 jobs successful**, all **85/85 contracts passed** (18 F3 + 15 F2 + 13 E1/F1 + 20 D + 19 E–H). Two original-source artifacts and JSON decoded and checked; ZIP CRC PASS.

- **2022** artifact `11970747509` (name `ige-p8-3f3-2022-original-source-factorial-aggregates`), ZIP SHA-256 `51e28a152fe26727f2075827076305c3b2876dd07378a80cee40b28c4e675496`, JSON SHA-256 `6d468e73874f2e5cfe74a501e2efc76df99fae9eb045bc62fe138497b40bfd49`.
- **2025** artifact `11971266109`, ZIP SHA-256 `03d0d88ecdcfc9f04c60b189b1df21e4addab37428ef4670bb190ad848fbec79`, JSON SHA-256 `db5eefcbfeabe6dc582619606f2ad40b3e5989c8359674700cc0f44fb9542b24`.
- Source station metadata SHA-256 identical both years: `b0025fb9909f28d536e90983337525697c27b75a607d1724f2d411ef3477ab59`; all **10/10** prespecified 2023 training donors qualified; no donor download failures.
- New F3 targets `MOE/MAS/NEU/GUT/FRU/BOL`, target meteorology excluded from training. Tested 2022 (52,535 paired hours) and 2025 (52,553 paired hours), **105,088 site-hours** in total; incomplete original hours not imputed. 2022 site-hours: MOE 8760, MAS 8742, NEU 8753, GUT 8760, FRU 8760, BOL 8760; 2025: MOE 8760, MAS 8753, NEU/GUT/FRU/BOL 8760 each.

## Primary equal-site mean MAE of hourly scalar wind speed (m/s)

| Predeclared method | 2022 | 2025 |
|---|---:|---:|
| **Raw ERA5** | **1.106393** | **1.091668** |
| F1 residual `S0_W0_H0_T0_E0` | 1.148646 | 1.139171 |
| F2 altitude `S1_W1_H1_T1_E0` | 1.112424 | 1.100125 |
| F2 altitude + exposure `S1_W1_H1_T1_E1` | 1.109304 | 1.097822 |
| **Best retrospective variant among 32** | 1.109304 (S0_W1_H1_T1_E1) | 1.097498 (S0_W0_H1_T1_E1) |
| Observed contemporary distance IDW4 | **0.951389** | **0.958094** |
| Observed contemporary altitude IDW4 (restricted 10-donor pool) | **0.951389** | **0.958094** |

The best of the 32 is selected **after** inspecting the evaluation year, so that row is *exploratory ranking*, not independent model selection evidence. **None** of the 32 beats raw ERA5 in the six-site mean in **either** year. Raw ERA5 is preferable to unconditional F1/F2 residual methods on this external F3 panel. The independently observed same-year station donors have a different, richer input information set, and are retrospective spatial interpolation comparators, NOT ERA5-only future-climate forecasts.

## Frozen F2-altitude case by site: change in speed MAE vs raw ERA5 (m/s)

Negative = improvement; positive = worse.

| Site | 2022 | 2025 | Behaviour |
|---|---:|---:|---|
| MOE | −0.0011 | +0.0017 | negligible/mixed |
| MAS | −0.0167 | −0.0193 | consistent gain |
| NEU | −0.0210 | −0.0097 | consistent gain |
| GUT | −0.0075 | −0.0106 | consistent gain |
| FRU | **+0.0739** | **+0.0689** | persistent material deterioration |
| BOL | +0.0086 | +0.0197 | consistent deterioration |

For FRU, seven-day-block paired 95% bootstrap intervals for F2-altitude minus ERA5 are strictly positive: **2022 +0.0485…+0.0932 m/s** and **2025 +0.0424…+0.0919 m/s**. For MAS/NEU/GUT they are generally negative, but site-specific intervals cannot prove population-level improvement.

## Factor ablation: balanced marginal effects on MAE, averaged across the six targets (m/s)

Each effect is **level 1 minus level 0** while averaging over all 16 combinations of the other factors; negative is beneficial to the 32-variant correction family. It does NOT imply superiority vs raw ERA5.

| Factor | 2022 | 2025 |
|---|---:|---:|
| S: altitude-aware station *selection* | **0.00000** | **0.00000** |
| W: elevation-distance residual weighting | −0.00240 | +0.00104 |
| H: shrink amplitude from 1.0 to 0.5 | **−0.02544** | **−0.03086** |
| T: calm-wind taper | −0.00701 | −0.00935 |
| E: text exposure category weight | −0.00423 | −0.00240 |

Primary conclusion: **shrinkage** makes an otherwise overactive residual correction less harmful, particularly at FRU/BOL; weak-wind taper is also beneficial to the adjusted family. This is a **damage-limitation** result, not proof that corrections should be applied: all 32 aggregate adjusted models still lose to the raw ERA5.

Altitude weight marginal effect changes sign across years; exposure has small mixed effects by individual sites; no generalized physical/topographic gain demonstrated. Predefined H×T interaction is +0.01410 m/s (2022), +0.01705 m/s (2025). W×E interaction is very small (−0.00014/−0.00051 m/s).

## Critical structural finding: the 'selection' experiment has zero identifiable signal

For **every one of six targets** in **both 2022 and 2025**, the altitude selector and distance selector choose the *same four donor identities*. MAS changes ordering, not set membership. Original distance weights then normalize in the same way, so each pair differing only by factor S predicts identically. Hence the 32 named variants represent only **16 distinct predicted variants per station/year at most** (due solely to S aliasing). **This is not a software failure**; it is a lack of discriminatory donor candidates in the restricted 10-donor pool. More variants in the factorial table do not make selection physically identifiable.

The two observed IDW4 baselines are also identical on the same stations and hours: they have the same donor sets. This experiment **does not** reproduce the 2024 full-census P8.3D altitude benefit and should not be used to reject that separate finding.

## Direction and coverage (do not collapse into speed)

Equal-station mean `direction_fixed90_deg`, assigning unresolved noncalm target direction an arbitrary 90° penalty:

| Method | 2022 | 2025 |
|---|---:|---:|
| ERA5 | 61.934° | 61.575° |
| F1 residual | 60.910° | 61.261° |
| F2-altitude | 61.560° | 61.351° |
| F2-exposure | 61.715° | 61.479° |
| Observed distance IDW | 64.346° | 63.759° |

However, ERA5 resolves 100% of scored noncalm target directions (49,689 in 2022; 49,948 in 2025); F2-altitude resolves only **94.96%** and **93.22%**; F1 resolves 93.56% and 91.51%. Any small fixed90 score improvement may mask a **worse missing-direction rate**, and 90° is a conventional penalty not observed angular error. Do not select model on this alone. An additional paired resolved-hour angular comparison and wind-vector component evaluation are needed.

## Scientific and production decision

1. **Close F3 as completed original-source ablation research; reject broad unconditioned ERA5 monthly-residual wind corrections as a default wind generator.**
2. Shrink and taper were isolated and appear to reduce harm, but **do not establish scientific skill over zero adjustment**.
3. No verified sensor height, site z0, upwind exposure class, or fluid-dynamic valley correction; stop presenting 2023 monthly biases as physical terrain flow reconstruction.
4. Full-census P8.3D altitude-based donor selection must be evaluated independently: the 10-donor F3 restriction is incapable of identifying its selection benefit.
5. For future generalization consider: same-hour station-aided interpolation for **observed-era retrospective climate reconstruction**; raw reanalysis as first future-climate wind baseline; alternate physical vector-downscaling hypotheses tested on multiple countries/years, with same-input-set and direction-coverage-controlled comparisons. No adoption absent robust site-generalized benefits.
6. `production_epw_ready=false`, no changes to `main`, no Streamlit deployment changes, no merge.

**Design note:** 2022 predates the 2023 donor-calibration year, which is permissible for retrospective holdout *evaluation*, not for any chronological operational real-time forecast claim.
