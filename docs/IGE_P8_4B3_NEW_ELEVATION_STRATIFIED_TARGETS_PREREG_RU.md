# IGE P8.4B3 — Independent Target Sites, Elevation-Stratified Holdout & 25 km Spatial Blocking

**Preregistered 17 October 2026, before checking any NEW held-out station forecast errors.** Parent B2 code head `30290fb07ee3179c9f6976bfe635f4ad32ed56c3`, including the protocol-restored geometry/directional/source-coherence weights `(.65,.25,.10)`. This is a **new external-target confirmatory stress test** of a FROZEN previous method, not model calibration.

## Source, target eligibility, sample selection

Source MeteoSwiss SwissMetNet original `2020-2029` hourly CSV full 159-station catalog; original `fkl010h0` scalar mean and `dkl010h0` meteorological FROM. Training uses **2023 donor hours at fixed 6-hour cadence**. New target evaluations are **full calendar 2024 (8784h) and 2025 (8760h)**.

Target eligibility is restricted ONLY by (a) source metadata altitude/coordinates/ID and (b) **original data availability**, NOT any wind forecast-error value: a source requires >=75% valid 2023 sampled training hours, >=90% usable 2024 source hours, >=90% usable 2025 hours. Both years' availability is prequalifying; therefore it is a **complete-records station conditional** independent-target evaluation, not an unconstrained operational station feed forecast. All included observation values are completely withheld from target model ranking and training. Source IDs that fail/have HTTP 403 are censused and not silently replaced post-score.

Known previously scored target IDs EXCLUDED (across P8.3/P8.4): `ABO,BER,PAY,BAS,CHD,GRA,MUB,STG,VIS,MOE,MAS,NEU,GUT,FRU,BOL,AIG,THU,INT,RAG,ZER,VIT,DIA,CDM,GRE,BIZ,SAE,CRM`; excluded by identity only, not by learned forecast performance.

**Deterministic metadata-only selection rule, frozen now:**
- Three elevation bins: low `z<600m`, mid `600<=z<1300m`, high `z>=1300m`.
- Exactly **six** source-eligible new target IDs in each bin (18 total); if not possible, **fail closed** instead of relabeling.
- For each bin sequentially, greedy maximin spatial dispersion from all already-selected target points (not past targets, which are identity-excluded only); first selection of a bin when no selection exists uses fixed SHA256 station-code priority `IGE-P8.4B3-20261017:<station_id>`. At all subsequent selections select the station whose minimum great-circle distance (km) to all previously selected sites is largest, tie deterministically by hash/ID. Minimum new-new geographical distance `15km`. Bin order low → mid → high. Selection never queries target wind value, meteorological skill, or validation error.
- All 18 new target stations are excluded globally from all donor pools, even when predicting another target. Also exclude the previously evaluated six B2 target IDs from all donor lists. No origin site appears as an own/different target donor.

## Strictly frozen predictors and tests

Three previous B2 selectors exactly as before: 4-nearest-distance IDW, 4-altitude-ranked IDW, and 10-candidate source-coherence subset (210 combinations) with original frozen objective **geometry .65 / donor direction disagreement .25 / source availability .10** (no target calibration). Original scalar speed IDW, vector azimuth, unit-circle azimuth, vector-then-unit deterministic fallback; calm <0.5 m/s and original thresholds unchanged. Training-year 2023 donor-only source coherence, no new hyperparameters.

Two comparisons *for every 18-site target and every 2024/2025 year*:
1. **Unbuffered independent targets:** predictors above using all metadata/source-qualified eligible donors.
2. **Spatially blocked:** remove ALL donors whose true physical distance from target is **<25km** before choosing the same four-donor predictors. This tests extrapolation away from immediate local measurement; do not mislabel as future weather or a clean holdout from previously used past-source donor patterns.

For each comparison use strictly **identical 2024/2025 UTC score hours across all three predictors**, minimum 80% full-year. Compute per site/year speed MAE/RMSE/bias, reference noncalm directional coverage and emitted/strict-three-method circular MAE, fixed90 missing-direction *diagnostic* (not true measured azimuth error), vector/union coverage. Preserve selected donor IDs and original hashes. Compute seven-calendar-day paired bootstrap CIs, 400 repetitions per site/year including leap-year 2024.

## Frozen *material spatial-generalization* acceptance criteria (EACH year SEPARATELY)

- Equal-site joint-minus-altitude speed MAE <= **−0.02 m/s**.
- At least **6/18** sites achieve MAE improvement >= **0.02 m/s**, so 18-site ties cannot trivially pass.
- At least **12/18** sites have nonworsening speed MAE (ties allowed).
- No site has speed MAE deterioration **>0.15 m/s**.
- Equal-site union direction coverage joint-minus-altitude >= **−2.0 percentage points**.
- No single site suffers union direction coverage loss **>10.0 percentage points**.
- Equal-site fixed90 missing-direction diagnostic joint-minus-altitude <=0°.
- All seven rules must pass **for BOTH years in each unbuffered and 25km blocked design** to justify the narrow research finding `broad_elevation_stratified_swiss_generalization_passed`. Otherwise reject this claim. No post-hoc changing site IDs, minimum sample counts, bin edges, weights, circle thresholds or missing-value penalties.
- Even if passing, no physical wind direction transfer to SSP future, no proven instrument height/roughness/true full-year ERA5 temporal equivalence; `production_epw_ready=false`, no main merge.

**Important:** The 18 sites are new evaluation target IDs, but nearby Swiss donor/target locations and previous P8.3 source exposure may be correlated; this is not completely independent country-scale geography. Exact conditional eligibility and known prior-target exclusions must be disclosed. All raw observations remain transient inside GitHub CI; **only aggregates, source hashes and donor IDs** are published.
