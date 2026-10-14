# IGE P8.2E — Donor-RH versus temperature residual: post-hoc audit

Date: 2026-10-14. Research branch: `research/ige-p8-meteonorm8-batch-automation-20261012`.
Original successful workflow: https://github.com/dmitrievii/building-energy-tools/actions/runs/38600566925 (SHA `7ad8f1771cd59b8ed8d985761fac221f9d199e3a`).
No production-code modification; `main` unaffected.

## Protocol
- SwissMetNet ABO, BER, PAY, 2018–2020, 78,912 station-hours.
- Frozen donor-only `full_multidonor_shape` predictor from P8.2E, historical Austrian 1991–2010 calibration.
- Donor RH is the inverse-distance-squared-weighted average RH of *the exact stations used at each hour by the frozen T predictor*.
- Held-out site hourly and monthly weather never enters predictor or donor RH features; observed site RH is used only for scoring.
- Error = predicted T minus observed T; positive = too warm. Events defined as observed RH >= 90%.
- All recorded metrics are aggregate station/season/month/daypart/bin statistics, not original MeteoSwiss hourly series.
- All years previously inspected: THIS IS EXPLORATORY, NOT A FRESH HELD-OUT TEST.

## Pooled RH-bin results, 2018–2020

| Donor RH | Hours | Mean T bias (°C) | Observed wet hours | Missed wet hours | Recall |
|---|---:|---:|---:|---:|---:|
| <60% | 16,056 | +0.579 | 97 | 97 | 0% |
| 60–<70% | 9,922 | +0.059 | 452 | 452 | 0% |
| 70–<80% | 15,454 | -0.177 | 1,819 | 1,819 | 0% |
| 80–<90% | 23,525 | -0.227 | 8,238 | 7,211 | 12.47% |
| 90–<95% | 11,263 | -0.146 | 7,928 | 1,114 | 85.95% |
| 95–105% | 2,692 | -0.082 | 2,422 | 41 | 98.31% |

Total observed wet hours = 20,956; missed = 10,734. 89.24% of misses occur with mean donor RH below 90%; 67.18% of misses in donor RH 80–90%.

## Consistency and confounding
- T bias below donor RH 60% is positive in every year (+0.660, +0.537, +0.544 °C for 2018, 2019, 2020); at donor RH 80–90% it is negative (-0.229, -0.196, -0.256 °C).
- Station-bin T bias (pooled) at donor RH 80–90%: ABO **-0.96 °C**, BER **+0.24 °C**, PAY **-0.04 °C**. At <60%: ABO +1.07 °C, BER +0.01 °C, PAY +0.51 °C. No universal station-independent correction.
- Winter (DJF) T bias at donor RH 90–95% is -0.62 °C; summer (JJA) +0.01 °C. Seasonality matters.
- In site-month stratification for comparisons with >=30 h in both <60% and >=90% bins, low-RH T bias exceeds high-RH T bias in 24 out of 34 site-months; sign is NOT universal.
- Wet-event recall rapidly increases with donor RH; this is not a fully independent predictor, because donor e/RH already determines the frozen model humidity. A high association does not prove that lowering T based on donor RH will help; it may damage bias and MAE.

## Scientific decision
**NO DEPLOYMENT OF A DONOR-RH CONDITIONAL TEMPERATURE OFFSET.** For most high-donor-RH bins average T is already too cold rather than too warm. Keep P8.2E T and e frozen. It is more plausible that the principal missed-wet mechanism is geographically localized target saturation not simultaneously present among donors, interacting with temperature and vapour-pressure errors. That is a working hypothesis rather than an established causal explanation.

If any correction is subsequently proposed: pre-register it using a development set distinct from a new geographically and temporally held-out confirmation set, evaluate RH event frequency/recall/spells AND T/e MAE without worsening monthly mass balance or saturation closure.

## Provenance
Aggregated original artifacts, workflow 38600566925:
- 2018 `11912798662`, SHA256 `f36304aff2f8a8489ca82c40b37f3b5c86e6c1384678b5f806bc4e6d7dc8d86b`
- 2019 `11913168526`, SHA256 `0d7fe8e4f1767a62b366362254beb53432b82c2de3ea6080ab7dc29001750b1e`
- 2020 `11912443698`, SHA256 `d923e1344cc37cef968c54a5191d0c9327da781310bb903e7088c215aa6bd379`
