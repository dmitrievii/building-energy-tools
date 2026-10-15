# IGE P8.3F2 — preregistered physically conditioned ERA5 and 2025 wind benchmark

**Frozen before executing P8.3F2 source-backed 2025 holdout.** Research-only. Child of verified P8.3F1 research head `535ced052dd412a03930a3337820f06754190a4d`. No source or solver modifications in main.

## Research question

Does *physically constrained* interpolation of prior-year ERA5 residuals (station altitude and measured station-text exposure categories), with conservative shrinkage and low-wind taper, improve 2025 independent-station wind accuracy against uncorrected ERA5, legacy P8.3F1 corrections, the same-input-set F1 station IDW4 baseline, and the **frozen P8.3D altitude-selected donor sets**?

The name does NOT imply validated orographic flow, z0/roughness measurement, CFD, WMO exposure class or neutral log-profile corrections. Avoid post-hoc hyperparameter tuning on 2025.

## Completely declared inputs

- **Calibration:** donor stations ABO, BER, PAY, DAV, LUG, GVE, SIO, SMA, WYN, ZER, measured + explicit Open-Meteo ERA5 10m wind 2023 (calendar month scalar and wind-TO u/v residuals). Qualified donor has >=400 jointly valid original hours per training month.
- **Validation:** six withheld independent target station identities BAS, CHD, GRA, MUB, STG, VIS; **calendar 2025** (8760 UTC hours). None of the six sites enters residual calibration, even if they appear as contemporaneous baseline donors for another target. Same nominal GMT hour (known metadata time-integration uncertainty). No optimized time shifts.
- **ERA5 source:** `archive-api.open-meteo.com`, explicitly `models=era5`; units m/s, directions meteorological wind FROM degrees, `timezone=GMT`. Fetch annual original hourly JSON, SHA-256, require strictly complete aligned annual timestamps and >=95% finite pairs. No undocumented substitution of another reanalysis.
- **Station sources:** original MeteoSwiss 2020–2029 hourly CSV; do not export raw original observations or hourly predictions.
- **Exposure:** `station_exposition_en` (de/fr/it fallback), recognize exact text *plain*, *slope*, *height (30-100 m above valley)*, otherwise *unclassified*. Use solely as an uncertain, declared categorical proxy. Station elevation is masl, NOT mast mounting height. Actual mast height and z0 remain unavailable: **no wind profile correction authorized**.

## Frozen candidate predictions

1. `era5`: no adjustments.
2. `f1_residual`: P8.3F1, four nearest distance-only qualified calibration donors, 1/d² residual interpolation, unshrunk monthly scalar and u/v corrections.
3. `f2_altitude_shrunk`: same qualified 2023 calibration pool; choose four sites minimizing `sqrt(d_km²+(0.04*delta_elevation_m)²)` (frozen P8.3D selector), combine their monthly residuals with `1/max(d,.25)^2 * exp(-abs(delta_elevation_m)/500)`, renormalized. Multiply scalar and u/v residuals by `0.5*min(1, v_ERA5/2)`; wind=0 has no adjustment. These numbers are *preregistered heuristics* inspired by reduced representativeness with altitude mismatch, not universal physical constants.
4. `f2_exposure_shrunk`: as above, but residual interpolation weights for donors with a declared nonmatching exposure text class are multiplied by 0.5; unknown exposure is neutral. Same 0.5 shrink/taper.
5. `f1_distance_idw4`: 2025 same-hour original P8.3A scalar/vector interpolator, donor pool limited to 10 F1 candidates, 4 distance-nearest 2023-calibration-qualified stations. Strong contemporaneous observational information advantage.
6. `p8d_frozen_altitude_idw4`: original P8.3D 2024 four donor identities for each site (altitude_idw4, exactly from artifact `11930026508`, `p8_3d_wind_selected_donors.csv`), **frozen** for out-of-year 2025 verification. Original P8.3A scalar/vector weights 1/d² on actual 2025 same-hour measurements. The 2024 selection relied on earlier source coverage and pre-2025 metadata; no 2025 target-dependent selector tuning. It is not a fully refitted 2025 P8.3D candidate census. No 2025 reference target measurements may enter prediction for that target.

FROZEN 2024 P8.3D altitude donor IDs: BAS MOE/RUE/DEM/GOE; CHD CDM/MAS/ORO/BOL; GRA MAS/PAY/PLF/MUB; MUB BER/CRM/NEU/GRE; STG BIZ/ARH/OBR/GUT; VIS FRU/BLA/SIM/ABO. Previously reviewed 2024 selections were generated **before** this 2025 test; site-selection metadata independent of 2025 observations. For GRA, MUB contemporaneous measurements are allowed only as an externally observed donor to the GRA target (but GRA itself cannot appear in its own donors).

## Strict validation

Each site: compare all six methods on intersection of original target observations, valid ERA5 and predictions from both IDW baselines. If <80% of 8760 physical hours, fail closed; reveal missing fraction, never silently forward-fill. Compare on identical hours; noncalm target `v>=0.5 m/s`, unresolved direction penalized 90° with fixed denominator. Report speed MAE, RMSE, bias, direction conditional circular MAE, fixed-90 penalty and resolution, all four seasons, per-site as well as micro/macro pooled averages. **Primary criterion: improvement in speed MAE over both raw ERA5 and F1 without large reversals by site.** A speed/direction trade-off must be explicit; it is not sufficient to win on pooled mean alone.

Additionally use a deterministic **moving 7-day block bootstrap** of per-hour paired absolute-error difference, sampling within each site, to estimate 95% uncertainty for candidate-minus-ERA5 MAE; 300 replicates, fixed seed. The bootstrap is descriptive due to residual serial/circulation dependence and limited six-site independence; not a formal population-generalization proof.

No hyperparameter tuning after inspecting 2025, no production acceptance without additional geographical/temporal verification and a more physically defensible exposure dataset. The 2025 time period has been used elsewhere in IGE (e.g. P8.3H), so this is a frozen F2-specific temporal/target holdout, NOT globally virgin evidence. Small six-site Swiss geography does not prove broad climate generalization.

## Data policy and reproducibility

Produce aggregate JSON with source SHA-256, declared inputs, metrics and site-level donor selections only. Do not publish raw MeteoSwiss hourly data, raw ERA5 grids, DEM rasters, or derived hourly sequences. Tests use synthetic fixtures; source-backed CI runs independently. Runtime can fail due to external provider accessibility; do not treat timeout as scientifically negative skill.

**Release:** `production_epw_ready=false`, never auto-merge to `main`.
