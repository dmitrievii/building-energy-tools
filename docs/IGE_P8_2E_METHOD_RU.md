# IGE P8.2E — Cross-Year Generalization, Humidity Extremes & EPW Time Alignment

## Research scope / frozen protocol

**Source branch:** `research/ige-p8-meteonorm8-batch-automation-20261012`.

**Hypothesis:** The frozen 2019 P8.2D full-multidonor log-vapour shape reconstructs hourly moisture more accurately than constant monthly vapour pressure in independent calendar years **2018 and 2020**, without compromising physical bounds. Separately, measure the frequency and duration of extreme RH regimes; do not assume the lower mean MAE implies correct extremes.

### Independent-source chronology

- MeteoSwiss SwissMetNet actual UTC hourly reference timestamp is **the END of the measurement interval** (`h`, not the beginning). Official documentation: https://opendatadocs.meteoswiss.ch/general/download.
- 2018: 8,760 native hourly slots; 2020 leap year: **8,784 native hourly slots**. All are preserved and scored in the scientific holdout.
- EPW fixed Swiss local **standard time CET = UTC+1** without switching to CEST/DST. The timestamp `01.01.2018 00:00 UTC` denotes the hour ending 01:00 CET, hence EPW **1 January hour 1**. The UTC hour ending 23:00 maps to local 24:00 = **EPW hour 24 of that same date**. Directly pairing UTC index to EPW 1..24 is correct here *because SwissMetNet stamps are end-of-interval* — not a generic rule for every provider.
- For an explicitly synthetic **8760-hour EPW weather year**, 29 February 2020 is removed only in a separate mapping view; original 8,784 observed/predicted hours are **not removed from validation**. This is **not an assertion that removing leap day is appropriate for EnergyPlus actual-weather RunPeriods**. EnergyPlus leap day is retained when actual weather and simulation require it; the weather-file type and calendar must be explicit.

### Data and leakage

- **Test sites**: ABO, BER, PAY; **test years**: 2018 and 2020, fixed before examining results.
- **Frozen calibration**: original GeoSphere Austria 1991–2010 temperatures and pressure-of-vapour altitude regressions; no Swiss or 2011–2020 target meteorology used to fit coefficients.
- **Donors**: other Swiss stations from frozen P8.2D candidate set. Same-time observed donor T/P/e and donor monthly e are permitted. The target station T/P/RH/e/Td and monthly means are *never* predictor inputs; they are read only in the separated evaluation routine.
- Four unchanged P8.2D variants: `constant`, `nearest_shape`, `half_multidonor_shape`, `full_multidonor_shape`. No outcome-dependent choice of method, stations or hyperparameters.

### Error statistics and event scoring

For T, P, vapour pressure e, RH, dew point Td: MAE, RMSE and signed bias on **exactly matching observation timestamps**. For high moisture RH ≥ 90% and very dry air RH < 30%: predicted vs observed event frequency, frequency bias in pp, TP/FP/FN, precision, recall, F1, critical-success-index. Also count events and consecutive runs ≥6 h and ≥12 h and maximum continuous run length. Missing observation hours **split**, never merge, periods.

This is exploratory and limited to 3 Alpine stations and 2 independent years. Inference with 3 location clusters is not globally statistically reliable. Do not select post-hoc thresholds from the results. The P8.2D year 2019 remains a comparison reference, not new training data.

### Physical and EPW gates

1. Exact native source-year UTC hourly axis with no duplicate/gap. At least two independent donor stations per predicted hour; fail closed otherwise.
2. Reconstructed e > 0, RH 0–100%, e < station pressure, dewpoint ≤ T; exact source-month reconstructed e mean for each UTC month. Fail if physically infeasible; never repair with target values.
3. 8760-hour EPW mapping with no DST, no duplicated hour, 1–24 EPW interval-end semantics. For 2020 all original 8784 hours remain in scientific annual scores; no fake interpolation at 29 February.
4. A humidity-column payload (T/Td/RH/P) may be patched **only** into a independently verified 35-field EPW at matching lat/lon/elevation/timezone. Preserve all other fields verbatim. Without complete validated wind/solar/precipitation EPW, the study does **not** claim to have produced a full EPW.

### Interpretation

Local synthetic tests must pass *before* original observed validation. GitHub green workflow indicates computational completion, not necessarily successful humidity extremes. The P8.2E research stage can close with either positive or negative model skill. **Do not designate full-multidonor algorithm as globally production-ready** without independent climate-region and additional-year generalization.

Original Swiss hourly source files remain outside repo and artifact. Publish aggregate station-year skill, monthly scores, extreme-event diagnostics, source digests and provenance only.