# IGE P7B.3D — Cross-Year and Cross-Site Conditional Solar Generalization

**2026-10-11. Research protocol. No production EPW; no change to `main`.**

## Research question

Does the **frozen** P7B.3C observed-day cloud analogue generator M2 improve independently evaluated hourly GHI climatological variability when tested on distinct years and nearby independent GeoSphere stations, **without** refitting its parameters or using any held-out hourly radiometry to synthesize the target hours?

### Scope and honest baseline

This stage isolates the **daily-GHI → hourly-GHI disaggregation** problem. Each target test day is supplied with its **actual QC-approved observed daily energy**, formed from the same day's 24 complete observed hours. The generator is *not* provided the target hourly distribution. Consequently it is legitimate to compare distributions and temporal statistics conditional on known daily total, but **not** to claim full synthetic CanESM5 future-weather forecasting skill or a blind solar daily energy forecast. The deterministic comparator **M0-clear** is a normalized hourly Haurwitz curve with the same daily energy and physical caps, **not** the original 2013 CanESM5 P7B.2 entire hourly profile. Results cannot be directly subtracted from P7B.3C's full-model M0 metrics as though the inputs were identical.

No hourly meteorological events from a GCM synthetic date are paired with actual events. Here, by construction, an *observed-day given its measured daily integral* is the reconstruction target; comparison against that day's held-out hourly observations measures conditional reconstruction diagnostics, not meteorological forecasting accuracy.

## Pre-registered source, train/selection/test partitions

- Source: GeoSphere Austria [Stationsdaten-v2, 10-minute historical API](https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min), observed `cglo` original calibrated mean W/m² plus `cglo_flag` QC; provider [dataset DOI 10.60669/8fya-7x87](https://doi.org/10.60669/8fya-7x87), CC BY 4.0.
- Training: Graz #30 **2007–2008**, original frozen P6.3F 10-minute six-of-six quality-approved hourly data; `chim` never used.
- Parameter selection: Graz #30 **2009**, **already frozen P7B.3C** `alpha=0.75`. P7B.3D never re-estimates alpha or the training analogues.
- Temporal evaluation: individually **2012**, **2013**, **2014**, with strict 24/24 originally accepted hours per observation day. Years 2010–11 excluded due unresolved provider daily-vs-10-minute disagreements.
- Geographic evaluation: pre-registered independent stations **Laßnitzhöhe #53** (47.07361°, 15.59222°, 530 m), **St. Radegund #94** (47.18211°, 15.48978°, 726.3 m), **Gleisdorf #200** (47.11556°, 15.70806°, 377.3 m). Station #16412 is an alias/child of Graz #30 and **not a second validation site**. Original metadata confirms radiation parameter availability; **actual original 2012–2014 10-minute QC coverage must be checked live independently** before any transfer claim.
- GeoSphere original `record_start` / `record_end` timestamp interpretations remain separate hypotheses. Fixed CET +01 is used, without Austrian DST. No clock hypothesis is chosen by accuracy.
- The 2012–14 Graz dataset was examined in earlier phases. These are predesignated held-out **for the P7B.3D fitting procedure**, not historically virgin holdouts for the project. Cross-site hourly observations have not yet been used to tune M2, although earlier P6.3C inspected *daily* nearby-site climate characteristics.

## Physical and statistical design

1. Check original official provider metadata for each registered station; retrieve each site-year complete 10-minute UTC time axis, GHI values and QC. A usable hour must contain **exactly six distinct ten-minute samples**, all with provider accepted q21 flags in `{10,11,12,20,21,22}`. No q21=0, missing/null, negative readings or interpolated gaps.
2. Require a **complete local 24-hour observation day**. Daily measured source energy `E_d` is sum of these 24 hours. Strict QC missing days are excluded and counted; an explicit physical cap incompatibility is excluded and counted rather than silently reducing original observed daily energy.
3. Calculate approximate NOAA geometry at 5-minute substeps across each local hour, extraterrestrial horizontal energy from 1361 W/m² nominal solar constant and eccentricity, and Haurwitz reference `1098*cos(z)*exp[-0.059/cos(z)] W/m²`. The registered near-horizon engineering cap is `min(TOA,max(1.25*Haurwitz,0.65*TOA))` from P7B.3C; **not** a validated clear-sky physical law.
4. Baseline **M0-clear**: physically bounded projection of the Haurwitz hourly profile onto original **observed** daily `E_d`.
5. M2: frozen Graz 2007–2008 seasonal and day-clearness nearest-15 cloud analogues, frozen `alpha=0.75`, deterministic `seed` and model-day hash. Apply the same physical cap and exact daily-energy-preserving projection. An ensemble of **20 distinct seeds** is pre-registered.
6. Independently compare season-specific 95th percentiles of absolute changes in *consecutive* daylight hours, monthly-by-hour climatological MAE, and persistence of cloudy periods using `observed_GHI/Haurwitz<0.5` when hourly clear-sky ≥0.1 kWh/m². Missing hours break sequences; overnight cloud persistence is never fabricated.
7. Report per **site and year** both clock hypotheses, exact QC coverage, missing full days, cap exclusions, ensemble ranges, source SHA, and explicit flags when observations are insufficient. Threshold: ≥240 complete usable days **per site-year**, and ≥2 distinct independent external stations over ≥2 calendar years with at least 4 successful external station-year groups for the *data-availability gate*. This gate demonstrates benchmark coverage **not** algorithm transfer success.

No score is used to tune M2 on 2012–14 or any external station. The benchmark is fail-closed if external original-source coverage is inadequate; passing CI is not proof M2 universally generalizes.

## Initial independent-local original-data cross-year numerical preflight

Source: user's immutable P6.3F 10-minute GeoSphere original audit ZIP, extracted original 137,553,136-byte CSV with SHA-256 `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`. Source is **one station Graz only**. M2 20 seeds, time hypothesis `record_start`:

| Graz #30 QC 2012–14 | Full observation days | M0-clear month-hour MAE | M2 month-hour MAE | M0 mean seasonal p95 relative error | M2 mean seasonal p95 relative error |
|---|---:|---:|---:|---:|---:|
| 2012 | 365 | 0.020061 | 0.017008 | 0.362815 | 0.133255 |
| 2013 | 362 | 0.022539 | 0.016200 | 0.373922 | 0.128700 |
| 2014 | 365 | 0.018796 | 0.016666 | 0.396006 | 0.160993 |

Hour-profile MAE values are **kWh/m²/hour**, relative seasonal p95 errors dimensionless. This measures hourly disaggregation given **known daily observed energy**, and has different baseline and conditioning than the original P7B.3C synthetic-year comparison. Other site results are **PENDING until original-source GitHub Actions measurement**; do not manufacture any scores.

## Open conditions (non-production)

- A small set of geographically nearby sites does not prove nationwide or global interpolation.
- Live provider metadata and QC can evolve; SHA-pin every retrieved source and avoid publishing provider raw records in public GitHub without an explicit licence review.
- Fully independent validation should later test a physically verified clear-sky model and sensitivity to the 0.65 TOA horizon floor; observations at sunrise/sunset and potential instrument effects remain unresolved.
- Historical station cross-year data do not establish transfer across eight GCMs or to future SSPs.
- No sensor-grade independent DHI/DNI, no coupled-temperature/humidity cloud relationships, and no building simulation loads have been tested. Complete new EPW remains **not approved**.