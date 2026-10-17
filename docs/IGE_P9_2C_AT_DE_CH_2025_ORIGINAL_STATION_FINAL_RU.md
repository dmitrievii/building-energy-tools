# IGE P9.2C — итоговый исходный AT/DE/CH 2025 audit

**18 октября 2026. Финальный GitHub Actions [#39076913550](https://github.com/dmitrievii/building-energy-tools/actions/runs/39076913550) — 3/3 jobs SUCCESS; 38/38 тестов PASS** (9 new C, 16 B, 13 A). Первый run #39076847999 завершился частично из-за отсутствия `numpy` в окружении MeteoSwiss reader, затем установлена зависимость и повторён тот же frozen cohort. Source evidence: [2025 station observations aggregate #12117720879](https://github.com/dmitrievii/building-energy-tools/actions/runs/39076913550/artifacts/12117720879); [28 original NASA CanESM5 development days #12116813549](https://github.com/dmitrievii/building-energy-tools/actions/runs/39076913550/artifacts/12116813549).

## Original-source, заранее замороженные 3 страны и 2025 год

AT GeoSphere Graz station ID30 `tl/rf` и нативные `tl_flag/rf_flag`; DE DWD Oberstdorf station ID03730 `TT_TU/RF_TU`, нативный **QN9=3 автоматический QC, не финальный QN10**; CH MeteoSwiss SwissMetNet Davos DAV `tre200h0/ure200h0` OGD original published hourly without equivalent per-sample native QC certification. Exactly 10–16 Jan and 10–16 July 2025, per site/season 168 original sensor hours. **1008 site-hours, 2016 hourly matched T and RH variable pairs**, all 12 predeclared site × season × variable cells scored; no missing or skipped generated days. All 12 source SHA/QC and original measured metric sets available in original Actions artifact. Swiss end-of-previous-hour timestamp is a time support caveat; original artifact also contains a prospectively requested one-hour-shift sensitivity, which cannot be used to choose a favorable aligner after results.

Control B0 = original ERA5 full *hourly* 2025 data, A = P9.2A 2019/20 analog 24h blocks, C = P9.2C physically screened 2019/20 joint donors, constrained only by **ERA5 2025 DAILY AGGREGATES**, not station observations. One frozen seed 7313, no observed residual tuning. **B0 has much richer hourly 2025 information than C**: do not call this a fair independent weather forecast skill comparison; it is a strictly legitimate downscaling information-loss / hourly reconstruction diagnostic against independent measured station weather. 2025 LW field required internally by P9.2B was an explicitly unqualified surrogate because original P9.1A ERA5 source has no genuine native downwelling LW hourly field. No solar/rain/cloud/LW measurement accuracy is claimed.

## Original station T2m MAE, °C

| Country | Period | N | ERA5 B0 | P9.2A | P9.2C | Δ C−B0 |
|---|---|---:|---:|---:|---:|---:|
| AT | January | 168 | 1.039 | 3.005 | 1.601 | +0.561 |
| AT | July | 168 | 1.288 | 3.043 | 1.696 | +0.408 |
| DE | January | 168 | 1.665 | 4.446 | 2.102 | +0.437 |
| DE | July | 168 | 1.826 | 3.747 | 1.999 | +0.173 |
| CH | January | 168 | 2.754 | 3.268 | 3.054 | +0.299 |
| CH | July | 168 | 1.929 | 3.232 | 2.071 | +0.142 |

Six-cell T macro-MAE: ERA5 **1.750 °C**, A **3.457 °C**, C **2.087 °C**. **C improves A 6/6**, but **C worsens B0 6/6**.

## Original station RH MAE, percentage points

| Country | Period | N | ERA5 B0 | P9.2A | P9.2C | Δ C−B0 |
|---|---|---:|---:|---:|---:|---:|
| AT | January | 168 | 6.815 | 16.083 | 10.784 | +3.969 |
| AT | July | 168 | 7.952 | 12.155 | 9.637 | +1.684 |
| DE | January | 168 | 9.893 | 15.470 | 12.310 | +2.417 |
| DE | July | 168 | 7.750 | 9.054 | 10.540 | +2.790 |
| CH | January | 168 | 9.585 | 11.676 | 12.133 | +2.548 |
| CH | July | 168 | 5.842 | 9.089 | 9.105 | +3.263 |

Six-cell RH macro-MAE: ERA5 **7.973 pp**, A **12.254 pp**, C **10.751 pp**. **C worsens B0 in 6/6**, and worsens even A in **3/6**. Davos separate sensitivity: C Jan T MAE 3.054 °C nominal vs 3.159 °C one-hour-shift; July 2.071 nominal vs 1.976 shifted. Do not choose whichever is lower after reading results. Native QC qualifications and source-time mismatch prevent treating all six comparisons as equivalently calibrated independent station benchmarks.

## Genuine registered CanESM5 source development-only replay

Original NASA NEX-GDDP-CMIP6 v2 CanESM5 single-member 2013 historical and 2050 SSP245 Jan/Jul, already studied in P9.2B: **28/28 original days preserve all eight native hard daily CMIP6 constraints** after physically eligible original ERA5 donor preselection, compared to 27/28 B. P9.2C joint **huss and hurs both closed 17/28 days** (2013 Jan 5/7, 2013 Jul 1/7, SSP245 Jan 4/7, SSP245 July 7/7); the other 11 days preserve huss but do not guarantee native daily RH. Original daily temperature mean/min/max, precipitation, GHI, LW, wind, specific humidity unchanged; no clamping supersaturation. This is **development reproducibility only, NOT a new independent future-climate holdout**. In the ERA5-2025 retrospective internal diagnostic, 41/42 weather-generator days also attained both daily q and RH targets, but there is no genuine original CMIP6 daily target there.

## Decision and no-global-validation policy

**P9.2C physically admissible donor algorithm: PASS on finite physical source criteria. P9.2C independent original station 2025 T/RH check: COMPLETED WITH NEGATIVE HOURLY ACCURACY VS FULL ERA5 (12/12 cases).** Source variables T/RH only independently scored; no independent AT/DE/CH original QC clouds/precipitation/radiation/LW convergence or annual 8760 EPW qualification. Not justified to substitute generated hours for original full-hourly ERA5, or to release synthetic EPW as qualified engineering inputs. Observed accuracy vs less-information daily-only comparator remains a distinct question: this limited test cannot prove forecasting skill.

Keep `joint_weather_generator_qualified=false`, `production_epw_ready=false`. Prior P8.5/P8.6 original EPW byte/solar-humidity/weather coupling and EnergyPlus release gates remain outstanding. Do not tune hyperparameters to revealed 2025 station errors, expand beyond AT/DE/CH, launch global tests before publication or merge `main`. CI workflow manual only after final run.
