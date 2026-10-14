# IGE P8.3B — Swiss original wind-source QC and wind-direction robustness: 2021–2022

**Recorded:** 2026-10-14. **Scientific status:** RESEARCH PILOT COMPLETE; NOT production wind-direction or future-climate EPW approval.

## Provenance and execution

- [Original GitHub Actions #38631857812](https://github.com/dmitrievii/building-energy-tools/actions/runs/38631857812): 3/3 jobs SUCCESS, commit `a9fdc7e56cb447cf84f399074a9e882f099507a6`. Synthetic contracts: **32/32 PASS** (16 P8.3A physics + 16 P8.3B source-QC/circular comparisons).
- Held-out target stations: ABO (Adelboden), BER (Bern), PAY (Payerne). Same contemporaneous donor observations for each original SwissMetNet 2021 and 2022 UTC hour; **6 station-years, 52,560 scored station-hours**, 49,652 observed noncalm target-hours. Donors and predictor do not read the target observations; those are used strictly for scoring.
- The P8.3A scalar-speed method and IDW vector direction are **unchanged**; new alternative is IDW mean of directional unit vectors among donors with speed ≥0.5 m/s, with predeclared resultant threshold R≥0.20 and at least two usable directional donors.
- Official source metadata screened 53 candidate stations. For **each year**, 52 source files had the expected wind fields and no `fkl010h0`/`dkl010h0` per-hour quality-flag columns; 1 source unavailable. 50/53 candidates satisfy original numerical wind-coverage eligibility. Historical-provider review does not constitute an independently verified per-observation QC pass. `qc_flag_certified=false`.
- Results package 2021: artifact `11925669863`, ZIP SHA-256 `736c515fd88c3c00f75e9d21b865010153fd2183f8de40fa900941565ab5a3eb`. 2022: artifact `11926471691`, ZIP SHA-256 `c08d46db74d111e51848b24495ca0f2a3e9b771ecd184242536fb535fbb9b579`. Both downloaded and ZIP CRC verified. Only aggregate CSV and SHA/provenance are exported; no source hourly series redistributed.

## Same-hour directional error (MAE in degrees, circular shortest distance)

**Three-way complete-case comparison:** all nearest/vector/unit methods simultaneously report a direction in the same target noncalm hour. If a method emits no direction, the hour cannot enter this MAE and its missingness is reported separately. These comparisons should NOT be confused with three separate single-method MAEs on different hours.

| Year | Observed noncalm target hours | Matched three-method hours | Nearest MAE | Vector IDW MAE | Unit-circle IDW MAE |
|---|---:|---:|---:|---:|---:|
| 2021 | 25,084 | 17,518 | 47.73° | **40.67°** | 42.47° |
| 2022 | 24,568 | 16,494 | 48.12° | **41.13°** | 43.41° |
| **Combined** | **49,652** | **34,012** | 47.92° | **40.89°** | 42.93° |

The vector method beats the unit-direction circular method on matched hours by 1.80° (2021), 2.28° (2022) and 2.03° (combined). Unit-circle improvement in **coverage** is NOT evidence of a lower error on its additionally resolved hours; that separate paired-vs-newly-recovered skill remains unmeasured in this report.

## Coverage as fraction of observed noncalm target hours

| Year | Nearest | Vector IDW | Unit-circle IDW |
|---|---:|---:|---:|
| 2021 | 90.49% (22,699) | 74.17% (18,604) | **94.55% (23,718)** |
| 2022 | 88.47% (21,736) | 72.24% (17,749) | **93.83% (23,052)** |
| **Combined** | 89.49% (44,435) | 73.22% (36,353) | **94.20% (46,770)** |

Coverage improves by approximately **20.98 percentage points**, but the circular unit estimator yields one azimuth under some weak/competing-direction conditions. The 0.20 resultant is a predeclared research screen, not an externally validated uncertainty threshold.

**Independent 2022 site breakdown on strictly matched hours:**

| Target | Three-way matched hours | Nearest MAE | Vector MAE | Unit MAE | Vector coverage | Unit coverage |
|---|---:|---:|---:|---:|---:|---:|
| ABO | 5,081 | 53.12° | **49.89°** | 52.05° | 60.51% | **91.29%** |
| BER | 5,183 | 62.46° | **42.47°** | 47.16° | 75.02% | **92.63%** |
| PAY | 6,230 | **32.11°** | 32.88° | 33.24° | 82.26% | **97.79%** |

At PAY the nearest donor is slightly more accurate on the matched 2022 hours, illustrating the geographic heterogeneity and the need not to claim a universal vector-method advantage.

## Why direction is difficult

**2022 speed-bin paired MAE (vector vs unit):**

| Observed target wind speed | Matched hours | Vector circular MAE | Unit circular MAE | Vector coverage | Unit coverage |
|---|---:|---:|---:|---:|---:|
| 0.5–<2 m/s | 8,017 | **55.25°** | 56.19° | 59.0% | 92.0% |
| 2–<5 m/s | 7,424 | **28.02°** | 31.12° | 93.5% | 96.5% |
| ≥5 m/s | 1,053 | **26.11°** | 32.81° | 96.2% | 98.5% |

Weak winds dominate the azimuth disagreement, especially in complex Alpine terrain. At low unit-vector agreement R<0.3, the matched-angle errors of both approaches are particularly high; more emitted direction values is not automatically better physical skill.

## Scientific decision

1. **P8.3B COMPUTATION PASS, METHOD NOT PRODUCTION-ACCEPTED.** The 2022 temporal check corroborates P8.3A vector-direction superiority on common hours; the unit-circle method has substantially greater coverage and could be evaluated as **fallback only**.
2. **Keep P8.3A scalar wind speed frozen.** Separate `Wind Speed` from angle averaging; vector magnitude is NOT a substitute for observed scalar hourly mean wind speed.
3. **Do not silently fill missing wind direction.** Any hybrid vector-first/unit-second fallback must be frozen before a new independent test and separately scored on previously unresolved wind hours; require coverage/quality tradeoff, wind rose, directional persistence and low-speed stratification.
4. No provider-certified per-record QC is available in the downloaded CSV files; investigate official metadata or alternative authoritative QC interfaces if instrument-grade certification is required. Mark records `HISTORICAL_REVIEWED_QC_NOT_INDIVIDUALLY_VERIFIED`, not `QC_PASS`.
5. Current investigation is retrospective on actual 2021–2022 Swiss station observations, **not** prospective future wind or independent SSP EPW validation. Need fresh spatial and temporal holdouts and source wind QC documentation before any production promotion.
6. **Do not tune thresholds on 2021 or 2022.** Cross-year consistency does not remove selection bias from using three previously named targets.

Research-only branch; `main`, P8.2F, and P8.3A original solver unmodified.
