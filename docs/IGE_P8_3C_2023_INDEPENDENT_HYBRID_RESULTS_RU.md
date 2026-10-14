# IGE P8.3C — Independent 2023 six-site wind hybrid: verified numerical decision

**Date:** 2026-10-14. **Status:** `COMPUTATION_PASS / HYBRID_NOT_ACCEPTED`. The 2023 test was pre-registered on targets DAV, GVE, LUG, SIO, SMA, WYN, and no parameter was re-tuned to those observations.

## Original execution and evidence

- Original [GitHub Actions #38635314231](https://github.com/dmitrievii/building-energy-tools/actions/runs/38635314231), source SHA `194dcd83ec148e5378500e5c5ff8a3cbcd70009c`, **2/2 jobs SUCCESS**: frozen scientific contracts **16 P8.3A + 16 P8.3B + 22 P8.3C = 54/54 PASS**, independent original SwissMetNet 2023 run PASS.
- Original artifact `11926919396`, ZIP SHA-256 `4fbc38b1163c530054f09eec09a01677d05d129a2ad0ac9e46abfb18ac134638`. Downloaded; ZIP CRC PASS; 8 files (CSV aggregates, provider availability/QC visibility, wind rose, gap spells, original source SHA provenance). No provider original hourly measurements redistributed.
- Original source metadata = 159 Swiss stations; 115 station candidates screened, 107 passed numerical wind coverage eligibility; 114 CSVs had no individual record-level `fkl010h0`/`dkl010h0` QC flag columns, one failed to fetch (MLJ). Therefore historical observations are **not per-record quality certified**.
- 6 targets × 8,760 scored = **52,560 station-hours**; **47,826 observed noncalm** target-hours. All six target station observations excluded from their own donor prediction; same-hour independent neighboring donors are used. This is **retrospective spatial hindcast, not an independently generated future-weather file or region-blocked validation**. Prior phase donor involvement limits complete external independence.

## Coverage and accuracy for fixed 2023 target noncalm hours

| Method | Resolved / 47,826 | Coverage | Emitted-only circular MAE | Sensitivity mean with 90° loss for missing |
|---|---:|---:|---:|---:|
| Nearest observed donor | 45,169 | 94.44% | 56.49° | 58.36° |
| Velocity-vector IDW (P8.3A) | 44,939 | 93.96% | 56.17° | 58.21° |
| Unit-direction circular IDW (P8.3B) | 45,968 | 96.12% | **53.46°** | **54.88°** |
| Frozen vector-first / unit-fallback hybrid (P8.3C) | **47,335** | **98.97%** | 57.46° | 57.79° |

The 90° penalty is a diagnostic utility function, not a measured error for undefined azimuth. The hybrid improves that penalty very slightly versus vector (58.21°→57.79°), but remains much worse than standalone unit-circle 54.88°.

Strict **42,138 all-four-method common hours**: nearest MAE **54.88°**, vector **54.60°**, unit-circle **51.71°**, hybrid = vector **54.60°**. Crucially, the standalone **unit-circle method was better than vector by 2.89°** in this new 2023 six-site experiment — the opposite of earlier 2021/2022 three-site evidence; method ranking does **not** generalize.

## New directions recovered by hybrid, previously vector missing

Total **2,396 new azimuths**; hybrid still unresolved **491 observed noncalm hours**. Mean circular MAE on recovered hours = **81.64°** (only about 8.36° below the 90° expected for unrelated uniformly distributed azimuths, so weak standalone directional information). Only **28.84%** within 45°, **57.39%** within 90°. A fair paired comparison with nearest on the **1,419** fallback hours where both were available gives hybrid MAE **80.72°** vs nearest **86.12°**: hybrid is modestly better here, but neither is accurate enough for a general-purpose wind-direction claim.

### Per-site recovery and primary directional errors

| New target | vector coverage → hybrid coverage | New recovered | Fallback MAE | Vector emitted MAE | Hybrid emitted MAE | Scalar speed MAE |
|---|---|---:|---:|---:|---:|---:|
| DAV | 99.92% → 100% | 6 | 129.00° | 70.05° | 70.10° | 2.981 m/s |
| GVE | 97.94% → 99.85% | 164 | 51.33° | 53.75° | 53.70° | 2.319 m/s |
| LUG | 95.30% → 99.32% | 326 | 92.33° | 71.95° | 72.78° | 1.370 m/s |
| SIO | 96.13% → 98.48% | 194 | 72.13° | 78.41° | 78.26° | 2.353 m/s |
| SMA | 87.55% → 99.14% | 942 | 95.04° | 24.74° | 32.95° | 0.655 m/s |
| WYN | 85.91% → 96.76% | 764 | 69.12° | 29.48° | 33.92° | 0.774 m/s |

### Weak wind and donor-vector cancellation

**2,210 / 2,396 = 92.24%** of fallback hours occur at target 0.5–<2 m/s, fallback MAE **82.46°**. Other groups: 2–<5 m/s, n=161, MAE **73.53°**; ≥5 m/s, n=25, MAE **61.19°**. In 2023, low vector agreement 0–<0.3 had 828 recovered hours with fallback MAE **86.22°**. This is precisely where an emitted azimuth is least reliable.

Hybrid mismatch may be larger than the unchanged vector on its emitted subset simply because recovered hours are harder — comparisons must use same hours or fixed-denominator penalties, and explicitly assess recovery error.

## 2023 speed-side generalization warning

P8.3A scalar speed has **pooled MAE 1.742 m/s**, positive bias **+1.218 m/s** (versus 0.640 m/s MAE on prior three sites in 2021); new sites DAV MAE **2.981 m/s** / bias +2.516, GVE MAE **2.319 m/s** / bias +2.142, SIO MAE **2.353 m/s** / bias +1.181. The speed algorithm was NOT changed, so this exposes **serious previously unseen spatial/topographic/instrument-exposure limitations** that require separate diagnostic investigation; do not mask by adjusting direction alone.

Donors illustrate exposure/elevation mismatch: DAV uses WFJ (2,691 m) 3.623 km from target; LUG uses GEN (1,600 m) 9.612 km from lowland Lugano; SIO uses two >2,700m donors. Geographic nearest is NOT automatically wind-climatically representative.

## Scientific decision

**P8.3C passes computational gates but FAILS general hybrid method acceptance.** A 98.97% azimuth coverage is not sufficient when newly recovered directions average 81.64° error and overall emitted MAE worsens.

1. **DO NOT make this frozen hybrid the production or generic IGE wind-direction model.** Retain P8.3A vector and P8.3B unit-circle as unpromoted research alternatives. On 2023 unseen targets the unit-circle method is more promising than vector, so revisit geographic generalization rather than re-fit the 2023 thresholds.
2. **Do not apply any post-hoc site-specific fix on the heldout 2023 sample.** Treat this as evaluation evidence. A new model must be developed on separate training locations/years and tested prospectively on new untouched stations/years; stratify by wind exposure, altitude, valley/ridge and calm behavior, check original observation height and QC.
3. Prioritize investigation of **wind-station donor representativeness and exposure** and 2023 speed bias separately, before integrating wind into automatic EPW. 16-sector wind-rose distributions are available in original artifacts but not a substitute for accurate hourly sequences.
4. No main branch or accepted P8.2F physical solver modifications are warranted by the finished check.

**Status tags:** `COMPUTATIONAL_VALIDATION_SUCCESS`; `EXTERNAL_GENERALIZATION_REVIEW_REQUIRED`; `HYBRID_NOT_ACCEPTED`; `PRODUCTION_EPW_READY_FALSE`.
