# IGE P8.2F — Accepted Research Baseline / Decision Freeze

**Decision date:** 2026-10-14  
**Decision:** ACCEPTED FOR RESEARCH CONTINUATION — no further T/e/RH tuning in the current IGE milestone.  
**Status exclusions:** NOT production-validated; NOT a new blind temporal/geographic holdout; NOT an independently generated future-climate file or fully validated EPW.

## Accepted scope

- **Model:** frozen P8.2E `annual_predict()`: same hourly T, P, vapour pressure `e`, RH, dew point, IDW `1/d²`, lapse-rate and monthly reconciliation; no empirical RH threshold fixes or ML.
- **Donor selector:** P8.2F `p8_2f_station_selection.py`; source station metadata ranked geographically, among candidates closest 20 per target plus original control pool; select the **four nearest eligible** stations only AFTER strictly qualifying all native annual hourly T/P/e/RH and all 12 monthly e values. Never use target meteorology in donor selection, fit or reconstruction.
- **Coverage semantics:** exact annual 8760/8784 hour screening in the research pilot; missing-value rows are NOT treated as observations; fail closed on insufficient complete donors. This conservative screening is not yet an online-production missing-data strategy.
- **Comparison:** ABO, BER, PAY × 2018–2020; 78,912 station-hours; 2020 includes all 8,784 real hours per target. Original source contemporaneous donor weather is used. This is spatial retrospective reconstruction, not future weather prediction.

## Measured acceptance metrics (pooled; exact same station-hours)

| Metric | Original 12-station pool | Expanded strict donor selection |
|---|---:|---:|
| MAE T (°C) | 1.226 | **1.093** |
| MAE e (hPa) | 0.661 | **0.554** |
| MAE RH (percentage points) | 7.649 | **6.636** |
| RH≥90% recall | 0.488 | **0.686** |
| RH≥90% precision | **0.740** | 0.714 |
| RH≥90% F1 | 0.588 | **0.700** |
| RH≥90% frequency bias (percentage points) | -9.06 | **-1.04** |
| RH≥90% TP / FP / FN | 10222 / 3583 / 10734 | **14382 / 5755 / 6574** |

Improved T/e/RH MAE with no change of physics. **Trade-off:** more false humid events (3,583 → 5,755). At ABO in 2019, e MAE worsens while RH improves. These limitations must not be hidden. The years 2018–2020 were studied before; no untouched holdout claim.

## Immutable baseline anchors

- Accepted source/control GitHub Actions: [#38612389803](https://github.com/dmitrievii/building-energy-tools/actions/runs/38612389803), head `24a25261a0548ead4ac2c17ba5bead36a58f9ba7`, 4/4 successful jobs; 15/15 tests PASS (12 new + 3 existing).
- Frozen physical solver `research/ige_cmip6/p8_2e_crossyear.py`, GitHub content blob SHA `099357c4e9ba85bf397356457818fe3bd6df861f` (verified unchanged at closeout).
- Accepted selector `research/ige_cmip6/p8_2f_station_selection.py`, content blob SHA `d0107b04f81ecc1bc1e0392b3660bf44cc271e61`.
- Annual evidence artifacts: 2018 `11917912868`, SHA256 `ce5730f2c8925522878a69c069728c8feb093acf74e04ded8dfc9d5d87673dbb`; 2019 `11917798058`, SHA256 `761437db7996502d9e1ce0badb0b4d02d725b97aee7fae6401d1631441e75158`; 2020 `11917863301`, SHA256 `874b5a3028e5488d4e0f0f6b8c76a092eb9fe6d8e4801c93db040c4d8cf15025`.
- Portable **derived-data-only** scientific audit `IGE_P8_2F_CROSSYEAR_DONOR_SELECTION_COMPLETE_20261014.zip`, 18 members, SHA256 `749744931ef9b8ea0a57af88d947e01ddd99a75da2a9e33333bdf3c90bfda13c`, CRC PASS; this local ZIP is not asserted as a permanent institutional deposit.
- Details: [method](IGE_P8_2F_CROSSYEAR_METHOD_RU.md) and [numerical results](IGE_P8_2F_CROSSYEAR_RESULTS_RU.md).

## Decision and subsequent research

1. **Stop tuning moisture.** Do not introduce RH-dependent corrections or reselect donor count/weights based on these previously seen years.
2. Preserve the frozen solver and source/evidence references. Keep selection as **accepted research baseline**, not deployable production code.
3. Progress to **P8.3A — independent spatial wind-vector source/physics readiness** using documented original hourly wind speed/direction measurements, independent target sites/years, careful circular statistics, calm treatment and fail-closed missing observations. The existing P7B.5 wind-generation research stays a separate lineage. Do not conflate observed contemporaneous wind donor reconstruction with synthetic future wind.
4. Defer full 35-field EPW approval, EnergyPlus impact and production promotion to later cross-field/independent validation gates.
5. Only a new predeclared temporal/geographical holdout may justify future P8.2F *production* promotion, not retrospective improvements on already inspected stations.

**Repository isolation:** research only. No merge or modification of `main` authorized.
