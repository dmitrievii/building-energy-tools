# IGE P7B.3A — Original observed-hour GHI benchmark

**2026-10-11. Research only; no merge to production main, no approved future EPW.**

## Primary evidence and source lineage

- Synthetic **CanESM5 2013 P7B.2**, 8,760 original-source hours, compared with its frozen pre-local-solar-correction **P7B** reference. Dates in model weather are **not the observed 2013 events**.
- **Original GeoSphere Graz #30**, 10-minute `cglo` radiation aggregated to complete QC-approved hours in **2012–2014**. Child site #16412 duplicates the same station observations and is never independently counted. Ignore unapproved `chim` and NASA POWER for ground GHI scoring.
- Observational six-of-six ten-minute interval QC original provider codes 10–22 required; missing hours are excluded without replacement. The 2012–2014 observational period was previously used to evaluate P7B.2's daily GHI climatological bias, so this hourly analysis is **a new diagnostic on an already-consulted holdout**, not a new virgin holdout.
- Local solar calibration uses **2005–2009**; conflicted **2010–2011** excluded. No model refitting on validation data.
- Retain **both** original `record_start` and `record_end` source timestamp conventions; add one fixed CET hour to observed UTC timestamps (no DST), compare monthly *hour-of-day* distributions only. Provider exact record labeling remains unresolved. No same-day event/weather verification, no declaration of one timestamp hypothesis being true based on higher match.

## Calculated measures

For each source timestamp hypothesis, derive 12 × 24 monthly-hour climatological GHI means, separately reporting all covered cells and cells with observed GHI ≥0.025 kWh/m²/hour. Each group averages the available model year and observed years independently. Also report season-specific daylight (08–18 fixed CET) hourly irradiance distributions, complete-24h observed daily energy distributions, absolute consecutive hour differences (08–18; gaps never joined), and unadjusted consecutive-day seasonal lag-one Pearson correlations (complete days only). Include all sample counts; percentile defined by sorted linear interpolation at `(n-1)*p`.

## Reproduced original-archive local pilot results, awaiting independent GitHub Actions replay

| Hypothesis | Pre-local-correction P7B daytime month-hour MAE (kWh/m²/hour) | P7B.2 corrected MAE | P7B.2 corrected RMSE |
|---|---:|---:|---:|
| `record_start` | 0.0988689 | **0.0326082** | 0.0411285 |
| `record_end` | 0.0986676 | **0.0337744** | 0.0422602 |

These means improve by approximately **67%**, but calendar-event weather skill cannot be inferred and one model year is not statistically exchangeable with three observed years.

**New variability warning:** JJA p95 of |ΔGHI| between adjacent daytime hours for `record_start`: **0.332333 kWh/m²** for original QC observations vs **0.118979 kWh/m²** for P7B.2. The synthetic daily GHI lag-one seasonal correlation is 0.7393 (observations 0.3912), but unadjusted correlations may include solar-season trends, unequal sample sizes and GCM sampling variability. Investigate the deterministic intra-day shape before any stochastic correction; no arbitrary smoothing or noise without observed conditional validation.

Ground source strict QC count for `record_start`: 2012 **8782**, 2013 **8750**, 2014 **8760**, total **26292** accepted hours, **1092** fully populated days; for `record_end` **26289** accepted hours, **1089** complete days. These are 2012–14 years including leap 2012, not 8,760-hour EPW observations.

## Science and software release gates

The P7B.3A Python script and 11 source semantics/unit contracts are reproducible without non-stdlib Python dependencies. GitHub Actions fetches the original **P6.3F #38134438339**, **P7B #38144426555**, **P7B.2 #38149471728** outputs; it publishes **derived tables and source SHA only**. All original-data archives remain user-controlled, not committed to public GitHub. Original artifact retention may expire.

`scientific_status=EXPLORATORY_SINGLE_GCM_SINGLE_SYNTHETIC_YEAR_NOT_VALIDATED_FOR_PRODUCTION`; `epw_production_ready=false`. No observationally verified independent DHI/DNI, no joint hourly temperature/moisture/wind/rain verification, no transfer to 8 GCM, no future SSP assertions.

Next: isolate cloud attenuation/clear-sky shape and compare multiple synthetic years against multiple observations with pre-registered independent temporal and geographical folds, avoiding further leakage into the previously consulted 2012–2014 solar holdout.
