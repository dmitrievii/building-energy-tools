# IGE P8.4C — Future Wind Baseline, preregistered qualification

**Frozen 2026-10-17 before calculating original-source wind baselines and 384 model signals.** Based on immutable [Wind Closure](IGE_WIND_CLOSURE_P8_3_TO_P8_4B_20261017.md) and already source-audited P7C.3/P7C.4 future EPW research code.

## Scientific question

Are existing `P7C.1/P7C.4` monthly **scalar** daily NASA NEX-GDDP-CMIP6 v2 `sfcWind` change ratios well-defined, numerically realized and transparently bounded when applied to an hourly historical wind pattern? What changes (calm hour count, speed-conditioned wind rose, low/high tail, threshold persistence) and what cannot be projected (future vector direction, date-matched events, local terrain/roughness)?

## Original reference and immutable multi-GCM design

- Frozen published research signal file: `research/ige_cmip6/results/p7c3_384_monthly_model_signals.csv` in parent git commit `8d8821605107a4aebd960cdb9ae9159cfec28d73`. Exactly **eight** registered model IDs of `p7c3_ensemble.MODELS` × **four** SSP/time windows of `p7c3_ensemble.WINDOWS` × **12** Gregorian months, no duplicates/NaNs/negative/zero `wind_ratio`. Respect existing P7C1 frozen permissible ratio `[0.3,2.7]`. Preserve exact model/window identities and compute SHA256. **This validates the frozen previously independently audited monthly signals**, but does NOT re-fetch/rederive 40 original daily GCM ZIPs. P7C.4 original 28 EPWs and IPSL 4 missing-humidity block remain distinct.
- Original public instrument reference: **GeoSphere Austria station 30, year 2013**, `klima-v2-1h` parameters `ff` and `dd`, code `q21` original QC/metadata verification using previously audited P7B.5 decoder. Acquire exactly 8760 UTC timestamps; retain actual original measured value, direction, QC and original response+metadata SHA. This is a **source-backed wind-shape physics reference**, NOT the user's licensed Meteonorm baseline EPW and NOT a new proof of independent absolute future climate validity. Station UTC-hour support different from EPW local standard-time hours; do not shift timestamps to reduce errors.
- Evaluate 8×4=**32** wind-only changes on original 2013 source hourly reference (QC-valid paired rows only); IPSL wind-only is allowed as scientific scalar source, **never** mark its four EPWs production-ready because historical/future native `huss` absent. Run independent synthetic strict **8760h EPW** unit-vector/clock preservation tests, including invalid/sentinel/ambiguous calm crossing. No original station hourly time series or proprietary EPWs committed/uploaded.
- Plain monthly operation for valid source speed: `future_speed_h = round(source_speed_h * R_{gcm,window,calendar_month}, 3)`; direction original numeric FROM angle **unchanged** where defined; missing remains missing; nonfinite / negative / 360 wrap must follow source policy. This verifies numerical baseline already present in P7C1/4, not a new invented future wind direction.
- Historical EPW does **not** equal original hourly station QC: qualified 2013 source wind reference is merely the measurable public reference for transformations. Monthly future ratio reproduces monthly source mean speed to 0.001 m/s serialization tolerance; absolute model climatological value is NOT forced to match the station climatology.

## Fixed metric gates and information content

For all 32 scenarios and 12 months, on the same source-valid hours:
1. ratio min/max and source SHA provenance, 384/384 valid model signals; ratios strictly positive within P7C1 frozen model bounds.
2. scalar speed `>=0`, finite, 0.001m/s serialized, correct month-balance tolerance **<=0.001 m/s**; no original direction alteration or invented angle. Report `n_missing_noncalm_input_direction`; outputs with speed>=0.5 and source missing direction are **wind-direction unsuitable for EPW** (even if reference hour was calm). Do not silently make up north or prevailing.
3. ORIGINAL UTC year has exactly 8760 contiguous rows (fail missing clock data), QC missing hours recorded without interpolation. Minimum 85% QC-valid speed+direction-eligible hours, else block source analysis. All output metrics normalized to identical qualified reference hours per model (monthly denominators are not allowed to drift).
4. report monthly / season and yearly `mean_speed`, `p05,p50,p95`, 0.5m/s calm incidence, >=2 and >=5 m/s event incidence, 16-sector FROM wind rose for **non-calm** hours, circular source/derived angular parity on common defined-hours (must be 0°), wind-rose L1 change due to speed-threshold crossing, noncalm-direction coverage, 3h/6h wind-speed threshold persistence. Do **not** claim wind rose unchanged when calm threshold crossing changes the denominator.
5. report seasonality and cross-variable non-identifiability as explicit limitations: monthly speed factor cannot model a shift of prevailing wind direction, real 10min gusts, true future diurnal covariance with temperature/humidity, altered synoptic sequencing or future natural ventilation / infiltration loads.
6. examine primary **high-wind >=5m/s** and calm 0.5m/s frequency sensitivity across ALL GCMs/windows and explicit range/ensemble min, max, medians; do not assign probabilities to 8-member ensemble.
7. publish aggregated record-level provenance per original source, GCM ratio series and 32 scenario metrics only. No source hourly observation arrays; no proprietary Meteonorm EPW.

## Acceptance and scope

`P8_4C_RESEARCH_BASELINE_PASS` if all 384 ratios/source rows valid, 32 resulting scalar time-series are structurally/physically coherent, monthly factor accurately applied and original directions unchanged. **Missing direction newly noncalm is a separate strict EPW readiness blocker** and MUST be counted. This baseline can PASS scientific algebra and still be **unqualified for future direction or site wind**.

`P8_4C_FUTURE_DIRECTION_PROVEN=false`, `P8_4C_NATIVE_CMIP6_UV_AVAILABLE=false`, `P8_4C_INDEPENDENT_HOURLY_FUTURE_WIND_PROVEN=false`, `P8_4D_FULL_EPW_READY=false`, `production_epw_ready=false`. Avoid adapting station wind source for user EPW without provenance/license agreement.

Next P8.4D must check actual 8760×35 licensed EPWs, noleap/DST, scalar vector valid, direction missing/flag propagation, aerosol/balance of temperature/humidity/wind speed, and simulation sensitivity to infiltration & natural ventilation on qualified source/uncertainty cases.
