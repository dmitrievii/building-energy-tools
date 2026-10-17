# IGE P8.4B2 — joint wind speed/direction and source-only donor suitability

**Registered 2026-10-17 BEFORE B2 test-source results; base is audited P8.4B report commit `9e1aa13112c232f8153b3e42a692386e5d4db770`.** Independent research branch, no main/EPW changes.

## Why B2 is genuinely different

P8.4B altitude donor selection improves 6-site equal MAE in 2022/2025 but only 3/6 sites improve; ZER has severe 2025 directional coverage loss. A new *joint* predictor cannot simply change thresholds based on ZER or evaluate only the same sites/year after selecting weights. Here use **six previously donor-only station sites as independent B2 evaluation targets**: `DIA, CDM, GRE, BIZ, SAE, CRM` (identities previously visible among P8.3D original *donors*, never evaluated as B1 original six target sites). Targets preselected by metadata presence, broad altitude/region, not B2 target wind errors. They might have contributed to prior exploratory donor experiments and are not independent countries. Freeze **training 2023** (source donors only) and **holdout 2024 and 2025** before calculations.

## Strict separation

- Full original SwissMetNet metadata station census (expected 159): attempt every one with 2020–2029 wind hourly CSV. Retain all original source SHA hashes, responses, failed IDs, numeric coverage; no original time series uploaded.
- `2023`: source-only frozen donor-characterization year; use original hours divisible by 6 (1460 training candidates), never any of the **six target station weather series** in any scoring/selection calculation. Require at least **90% donor-hour availability in each evaluation year**, and at least **75%** of 1460 prespecified 2023 sampled-hour valid wind readings for training directional characterization. Qualification is retrospective source availability, not real-time forecast access.
- `2024,2025`: independent evaluation years (same six target locations repeated across both). No fitted coefficient, change of target list, training/validation mixing, or post-hoc pick of best joint method; target measurements enter only scores. At least 80% same source UTC hours for all models; no synthetic filling. Global exclusion of all evaluation target IDs from EVERY donor pool.
- Official `fkl010h0` scalar hourly mean and `dkl010h0` meteorological FROM angle. Use original immutable P8.3A hour-matched scalar IDW4 speed and P8.3B unit-circle direction, with calm <0.5 m/s and conditional vector coverage. No fake anemometer height or roughness/CFD claims.

## Three competing selectors (frozen)

1. `distance_idw4`: original four geographically closest eligible donors, true distance 1/d² weights.
2. `altitude_idw4`: original P8.3D frozen ranking `sqrt(d_km² + (0.04 Δz_m)²)`, true distance 1/d² weights.
3. **`joint_source_coherence_idw4`**, new *research candidate*: consider the **ten** lowest `altitude_idw4` ranking candidates from ALL qualified eligible source stations. Evaluate all `C(10,4)=210` subsets (ties deterministic by station ID). Rank using a frozen source-only objective:

`objective = 0.65 × mean((altitude_geometric_distance_km)/(median_altitude_top10_distance_km)) + 0.25 × mean(pairwise_training_direction_disagreement/180°) + 0.10 × mean(1 − training_usable_hour_fraction)`.

The pairwise disagreement is computed over **identical 2023 sampled UTC noncalm donor hours** at which both wind directions are defined. If a pair has fewer than 120 such hours, assign conservative disagreement `1.0` (not `0`); no target weather referenced. Wind-direction coherence between donor stations is a *proxy for shared circulation*, not independently verified target exposure or aerodynamics, and may favor overly correlated homogeneous donors; a scientific rejection is an acceptable result.

For each of the three donor sets use the same original hourly IDW weights; only selection changes. `joint_source_coherence` coefficients and sample cadence are **engineering hypotheses**, frozen before target evaluation, not fitted physical laws. The whole 10-candidate set is discovered via full qualified catalog, **not** the original 10-donor pool of P8.3F3.

## Three directional outputs for EACH selector (identical processing)

- Original P8.3A weighted **vector** direction: undefined when mean resultant speed <0.5 m/s.
- Original P8.3B **unit-circle** direction: undefined when less than two donor directions or resultant <0.20.
- **New deterministic union/fallback**: vector angle if defined, otherwise unit-circle if defined; otherwise undefined. This is *not* an additional trained selector and is used equally for all three donor sets.

Pre-registered primary comparisons across the same UTC hours and same reference-noncalm denominator: `scalar_speed_MAE_mps`, `scalar_speed_bias_mps`, `direction_union_coverage_pct`, `direction_vector_coverage_pct`, and fixed-90 missing-penalty **diagnostic** `fixed90_joint_angle_deg` (not a measured angular error for missing records). Separate **strict three-selector paired** circular MAE on hours where all three predict direction; show per-target/site direction loss even if speed improves. 7-day paired calendar-block bootstrap of `joint − altitude` speed MAE per site/year, 400 samples (inherited frozen B1 algorithm); no post-hoc source tuning.

Pre-declared multi-objective research acceptance (on each year):
- equal-site speed MAE joint <= altitude baseline,
- equal-site union direction coverage joint >= altitude − 2.0 percentage points,
- equal-site fixed90 angular diagnostic joint <= altitude,
- no site loses >10 percentage points of union coverage; no site worsens speed MAE by >0.15 m/s,
- minimum 4/6 sites nonworsening speed under joint (tolerance 1e-8),
- both years must independently pass; other metrics (e.g. wind-rose, physical exposure, regions outside CH) still gate *production*. If any condition fails, reject the joint method; do not retune against that year's outcomes.

Year is 2024 (leap 8784 UTC hours) and 2025 (8760 UTC hours). P8.4B1's 7-day bootstrap supports 365 only; B2 will implement **366** calendar days in leap year and preserve actual matched site-hour counts.

## Integrity and provenance

Avoid accidentally scoring unequal directional subsets, target-as-donor leakage, misspecified metric (scalar vs vector speed), mistaking nominal source timestamps for physically equivalent instantaneous ERA5. Original station CSV typically omits individual hourly QC; report `source_per_record_qc_verified=false`. Sites are retrospective Swiss holdouts and **cannot establish forecast skill for future climate**; `production_epw_ready=false` regardless of CI.

P8.4B2 deliverables: code, source/method synthetic contracts, original 159 catalog source QC/availability census, two year/site aggregate scientific metrics, chosen donor IDs and training 2023 provenance, explicit PASS/REJECT against the frozen multi-criterion gate, never a silent production integration.
