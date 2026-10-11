# IGE P7B.3C — Conditional Cloud Analogue M2: Protocol and Original-Source Pilot

**Date:** 2026-10-11. **Status:** experimental scientific comparison; production EPW blocked. No merge to `main`, no alteration of original P7B.2 EPW.

## Research question

Can season- and daily-clearness-conditioned empirical cloud patterns improve the temporal variability of synthetic hourly solar radiation compared with IGE P7B.2 (M0), while exactly conserving its corrected daily GHI and respecting top-of-atmosphere (TOA) irradiance limits? The reference TAG-informed approach M1 from P7B.3B increased variability excessively; M2 is an independently developed observed-day-analogue generator, **not Meteonorm code or its model**.

## Physics and source

Source CanESM5 synthetic model-weather year: historical 2013, 8760 fixed-CET hours. Original post-correction P7B.2 source GHI remains immutable. Original GeoSphere Austria Graz station #30 `cglo` ten-minute observation aggregated to one-hour values only where **six-of-six original samples received provider QC approval**. Repeated substation #16412 and NASA POWER cells are not counted as independent ground samples; unchecked `chim` DHI is excluded. Both unresolved source time conventions (`record_start`, `record_end`) are modeled and evaluated separately. Synthetic model dates do **not** identify actual weather events of the same Gregorian date.

Reference clear-sky: **Haurwitz**, `GHI_clear = 1098 cos(z) exp(-0.059/cos(z)) W/m²`, for sun above horizon; NOAA approximate (geometric, **not refraction-corrected apparent**) solar position for station observations. This requires no invented atmospheric turbidity inputs and differs from Meteonorm's full ESRA/Solis. Source 2013 uses its original solar cosine. Input solar energy is kWh/m² per hour.

Sunrise/sunset special case: Haurwitz tends to zero too quickly to serve as an inflexible energy cap. 274 original P7B.2 source hours exceed 1.25×Haurwitz, all at cos(zenith) < 0.08. The empirical reference is not a physically verified local horizon model. For M2, hourly cap `min(TOA, max(1.25*Haurwitz, 0.65*TOA))` avoids falsely deleting valid near-horizon source energy. The 0.65 coefficient is a **provisional fixed engineering safeguard**, not a validated transmissivity law. It must be subjected to an explicit sensitivity study before publication or production.

M2 fits complete-day measured hourly patterns (24 QC-approved hours) through ratios `observed_ghi / max(Haurwitz,0.025)`, with low-sun screening and ratio bound [0,1.6]. It classifies days by DJF/MAM/JJA/SON and ranks training analogues by difference in daily clearness ratio `Kt = E_day / sum(Haurwitz_hour)`. A reproducible seeded sampler selects uniformly among the nearest 15 candidate days in the same season. The new hourly pre-projection profile is `(1-alpha)*GHI_M0 + alpha*(Haurwitz_source*analogue_cloud_ratio_hour)`. A bounded monotonic projection conserves **each source-corrected daily GHI** to numerical precision, and verifies 0 ≤ hourly GHI ≤ cap ≤ TOA. The algorithm **does not currently re-partition DNI/DHI**; its new hourly GHI CSV is a research candidate, **not a valid complete EPW update**.

## Temporal independence and validation leakage controls

- **TRAIN:** GeoSphere 2007 and 2008 only, complete approved days.
- **SELECT:** 2009 only. Choose `alpha` among {0,0.25,0.5,0.75,1.0}, using 8 deterministic random realizations. Composite selection loss is `0.35*(monthly-hour daytime MAE / M0 MAE) + 0.65*mean_seasons(abs(p95_generated/p95_ground-1))`, averaged over two unresolved timestamp conventions. Formula and search values fixed independently of evaluation period.
- **EVALUATE:** 2012–2014, twenty distinct model-weather seeds, no parameter adjustment based on this evaluation. **This is NOT a pristine held-out period for the overall project**, as 2012–2014 had been inspected in P7B.2 / P7B.3A / P7B.3B; it is external to M2 parameter selection, not external to the entire research process.
- 2010–2011 are excluded due to unresolved daily versus 10-minute GHI source inconsistency; 2005–2006 have incomplete approved station-year coverage and are not used in model training.
- Only **one GCM-generated year**, CanESM5 2013, is evaluated as a stochastic ensemble. This is a climatological distribution comparison; it is not a synchronized measurement skill score or genuine interannual GCM validation.

## Locally reproduced original-source pilot (pre-CI, numbers to verify against GitHub)

Original source SHA-256:
- GeoSphere hourly original: `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`.
- P7B.2 2013 hourly original: `099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a`.

Selected `alpha = 0.75` on 2009 only. Complete training analogue days: **715** for `record_start` and **713** for `record_end`. Strict observed evaluation QC hours: **26,292** / **26,289** respectively.

| Metric, 2012–2014 climate distributions | GeoSphere | M0 P7B.2 | M2 mean of 20 seeds |
|---|---:|---:|---:|
| `record_start` daylight monthly-hour MAE, kWh/m²/h | reference | 0.032608 | **0.035088** |
| `record_end` daylight monthly-hour MAE, kWh/m²/h | reference | 0.033774 | **0.033834** |
| `record_start` mean relative seasonal p95 | reference | 0.47399 | **0.09151** |
| `record_end` mean relative seasonal p95 | reference | 0.46873 | **0.09438** |
| `record_start` summer JJA p95 hourly absolute change, kWh/m²/h | 0.33233 | 0.11898 | **0.30313** |
| `record_end` summer JJA p95 hourly absolute change, kWh/m²/h | 0.33050 | 0.11898 | **0.30168** |

Mean seasonal relative p95 error is the average of four season-wise absolute relative deviations, **not** an MAE of irradiance. For `record_start` M2 annualized daytime climatological MAE worsens ~7.6%; for `record_end` ~0.2% deterioration. Therefore M2 gives a promising variability improvement **at the cost of slightly worse mean hourly climatology**. It has **not achieved uniform dominance of M0**, and the 20 model-seed spread does not represent interannual or multisite uncertainty.

## Required next acceptance gates

Scientific release remains **REVIEW_REQUIRED**, regardless of successful CI. Before production or paper-level generalization: independent geographical site(s), multiple historical GCM years, benchmark on newer untouched years or sites, clear-sky physics sensitivity (Haurwitz vs turbidity-informed), observed sunrise/sunset clocks, cloud duration/autocorrelation and consecutive rainy/windy weather correlations, joint solar DHI/DNI reconstruction with sensor-grade validation, and building energy sensitivity (heating/cooling, solar gain). Do not claim observed weather day-to-day correspondence.