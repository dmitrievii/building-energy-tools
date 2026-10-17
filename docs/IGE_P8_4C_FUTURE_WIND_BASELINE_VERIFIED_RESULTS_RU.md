# IGE P8.4C — Verified Future Wind Baseline Scientific Results (17 October 2026)

**SCIENCE DECISION: `P8.4C_RESEARCH_SCALAR_BASELINE_PASS`; `FUTURE_WIND_DIRECTION_UNPROVEN`; `FULL_EPW_NOT_QUALIFIED`; `PRODUCTION_EPW_READY=false`.**

See the frozen [P8.4C protocol](IGE_P8_4C_FUTURE_WIND_BASELINE_PREREGISTERED_PROTOCOL_RU.md) and prior [Wind Closure](IGE_WIND_CLOSURE_P8_3_TO_P8_4B_20261017.md). This is a bounded source-backed **climate-change-factor sensitivity analysis**, NOT verified future station winds and NOT an actual licensed EPW comparison.

## Reproducibility and original source

- Final **source calculation**: GitHub Actions [#39028791923](https://github.com/dmitrievii/building-energy-tools/actions/runs/39028791923), commit **`9126eccd0de5c752f69467b7638a332ce6004896`**, **2/2 jobs PASS**, **71/71 tests PASS** (23 P8.4C +17 P7C1 +15 P7C4 +16 P7B5). Additional conservative source-calm direction diagnostic was added as a physical safety check, not tuned for better forecast scores.
- Full original-source audit artifact: [#12099541493](https://github.com/dmitrievii/building-energy-tools/actions/runs/39028791923/artifacts/12099541493). ZIP SHA-256 `a181eabfad4bf169e7e7c6c1364b3622599673b4fa1c63b073f07e38e1bda2e6`. Aggregated JSON SHA-256 `6dd83692b299d3c977276fc703ab8768ecdaee6e973a53d0124476ce162b16f5`. ZIP CRC PASS. The original 8760 source values are **not** uploaded.
- Previous physics CI on commit `5309a255` failed **one synthetic rolling 3h-count expected value** (3 instead of mathematically correct 4). Only that test expectation was corrected. Later green original source tests run after correction. The subsequently added calm-promotion guard detects a source-calm numeric azimuth newly classified as noncalm and flags it as **physically unqualified regardless of numeric availability**; in the real-source 32-member analysis, zero promoted hours occurred.
- Real public 2013 reference: GeoSphere Austria station **#30 Graz Universität/Heinrichstraße**, original `klima-v2-1h` `ff` and `dd` source-QC, original all-parameters provenance SHA256 `095ff56133e8253e3491ce988a710fb940fec799d07804227a415e8bb092d4a6`, metadata SHA256 `7f48727609fd5391a4210d00ba6d57be6a9650b6ed8f5d9e155deb2e3722fc8b`. **8760/8760** original UTC source-hours usable (no DST changes or timestamp-fitting). Original station `ff` hour is **provider vectorially defined**, different from scalar **daily GCM `sfcWind`**. Therefore numerical propagation of their monthly *change factor* is a sensitivity experiment, not instrumental equivalence.
- Published registered 384 model-month factors: `research/ige_cmip6/results/p7c3_384_monthly_model_signals.csv`, SHA256 `3aa2d72060024d2702e306bf9707c54b6fa7836cb5f650aa402aabb6108a1369`. Existing P7C.4 research previously independently source-checked 40 daily-model archives, but those archives were NOT independently re-downloaded in P8.4C. Model membership: 8 original GCMs, four SSP/warming windows, 12 months. `IPSL-CM6A-LR` has wind-only ratios, **but full EPW for IPSL remains BLOCKED by unavailable native `huss`**.

## Registered scalar transformation and physics verification

`v_future,h = round(v_source,h × R_GCM,window,month(h), 3)`. These 384 `R` values span **0.772990–1.160113** and are all finite, positive and inside P7C.1 frozen [0.3,2.7] limits.

- **32/32** climate-state scalar transformations PASS, **384/384** actual original-source month balances PASS, largest monthly change-factor residual **0.000257903m/s** after EPW-style rounding.
- **32/32** hourly numerical original direction sequences unchanged, maximum difference **0°** for all recorded valid source angles.
- Original source 2013 annual speed mean **1.360879 m/s**, calm frequency (<0.5m/s) **11.27854%**, high wind (>=5m/s) frequency **1.65525%**, wind-speed p95 **3.600m/s**.
- Across all 32 morphed states, annual speed means **1.21918–1.42885m/s**, calm frequencies **11.6667–17.1347%**, high-wind frequency **0.9475–1.9749%**. These are **scenario sensitivity relative to one 2013 measured reference**, NOT forecast 2040–2099 station means.
- Existing time order, UTC stamps and original measured directions were never modified; however **34–513 hours per 32-state sample crossed the 0.5m/s calm threshold**. In this original source, every crossing was **noncalm → calm**, with **zero original calm → new noncalm promotions**. Consequently both `new_noncalm_missing_direction_hour_count` and stricter `noncalm_direction_physical_suitability_blocker_hours` were **zero** for the sampled station. THIS DOES NOT imply they will be zero for a different historical EPW.
- The 16-sector **conditional** wind rose is **not invariant** if marginal wind speeds change which hours are classified as noncalm. Original-to-morphed sectoral distribution L1 change varied **0.000–0.134** across source months/states despite identical raw angle values. Do not claim future directional climatology is physically simulated.
- Direction in actual future atmosphere can change even when this numerical source angle is held fixed. Original numeric angles during calm are not a defensible future prevailing direction, and a future amplifying ratio at a different EPW could expose this error. The added conservative physical-qualification guard will flag it.

### Eight-GCM wind-only scenario envelopes for the 2013 public reference

All columns show **min–max over eight independent model names**; these are empirical source-model ranges, not confidence/prediction intervals. SSP/time window is a 20-year climate **signal**, not a fixed single future year's daily weather.

| SSP / years | Mean annual speed m/s | Calm hours (%) | Hours >=5m/s (%) |
|---|---|---|---|
| SSP245 2040–2059 | 1.299–1.413 | 11.68–15.39 | 1.38–1.96 |
| SSP245 2080–2099 | 1.228–1.429 | 11.67–16.76 | 0.95–1.97 |
| SSP585 2040–2059 | 1.279–1.401 | 12.05–16.76 | 1.21–1.78 |
| SSP585 2080–2099 | 1.219–1.403 | 13.11–17.13 | 1.10–1.92 |

## What was demonstrated

- Original P7C.3 daily-source **scalar** `sfcWind` monthly ratio table is structurally complete (8×4×12), physically bounded and reproducibly applied to original Austrian hourly observed wind reference.
- Historical numerical direction and event order remain immutable **by design**; per-month scalar mean change-factor algebra is satisfied with 3-decimal serialization and no source missing-value fill.
- Speed-conditioned wind direction frequency, calm-frequency, threshold persistence, 16-sector rose, seasonal extremes and scalar distributions are all explicitly measurable from derived data, and can **change without a forecast of future direction**.
- No missing newly noncalm direction in the one complete 2013 observation reference; source-calm numeric azimuth safety guard tested synthetically.

## What remains scientifically unresolved / blocked

1. This result is **not** a P7C.4 actual licensed Meteonorm EPW audit: proprietary **`Graz-hour_contemporary_seed1.epw`** was not accessed here; full 28 existing EPW members were not re-created or parsed under P8.4C. The public reference is station #30 in **2013 UTC**, whereas actual user EPW baseline is Meteonorm typical-year with local standard time.
2. Source GCM `sfcWind` **does not provide `uas/vas` components** or future direction. No validated future wind rose, climate-change in circulation regimes, future wind-pressure dynamics, channeling or surface exposure changes are inferred.
3. Original station vectorial hourly speed and original GCM daily scalar `sfcWind` have different measurement/temporal support. This source backed phase proves bounded transformation algebra, NOT exact physical comparability or bias.
4. Monthly factors scale *every hour in the month equally*: within-month speed ranks and ordered synoptic episode sequence are inherited, not generated. Calm frequency/high-wind threshold statistics can change; independent future event sequences cannot be claimed.
5. Source/model spatial resolution mismatch, instrument height and terrain roughness, model emission/calendar uncertainty and additional regional/country holdouts remain unresolved. Natural ventilation, façade wind pressure and infiltration predictions are especially affected.
6. Even though 32 GCM wind-only signals PASS, the full P7C.4 EPW portfolio comprises **28** completed (seven GCMs × four windows), IPSL `huss` remains missing and blocked.
7. `P8.4D` must validate actual source-authorized EPW 8760×35 fields, time/calendar, direction/calm semantics, climate-source monthly mean parity, source QC/missing propagation, seasonal wind roses plus native EnergyPlus simulation wind-infiltration/natural-ventilation sensitivity. `production_epw_ready=false`.

### Stage closure

**P8.4C scalar future wind baseline RESEARCH PASS** for registered 384 ratios and 2013 source sensitivity. Do not promote it to a future direction generator, do not merge to production, do not claim locally accurate predicted 2050/2100 winds. Wind donor research P8.3/P8.4B remains **frozen** per Wind Closure. Next logical stage **P8.4D Integrated EPW Wind Qualification**.

Current branch only: `research/ige-p8-4c-future-wind-baseline-20261017`; `main` unchanged.
