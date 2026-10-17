# IGE P9.1H — Near-Surface Inversion Physics & Cross-Regional Generalization: preregistration

**17 October 2026. Research only; new branch from P9.1G HEAD dff6050a, not main.**
Scientific gate at branch creation: **H1 SOURCE DISCOVERY ONLY**. No original multiheight sensor payloads, sensor flags or cross-region skill verified at this stage. All previous P9.1G negative findings remain negative; G1 QN=10 blocked and G2 QN=3 lower-tier.

## 1. Research question and causal distinction

Can observed **near-surface** vertical temperature structure (roughly 2–200 m AGL), local radiation, snow, wind and surface exposure improve the *independent* reconstruction of hourly **2-m** temperature at arbitrary coordinates compared with ERA5 raw, ERA5 fixed lapse at true grid height, and provider altitude adjustment, while avoiding catastrophic seasonal regressions?

ERA5 **925/850 hPa** lapse/stability (P9.1G) is **free-atmosphere or deep-column**, and cannot detect valley-floor inversion merely through positive dry potential-temperature gradient. An inversion is true **dT/dz>0**. Static stability is not an inversion and usually exists even under a negative temperature gradient. Profile observations measured in different land cover cannot automatically represent a town or a mountain valley. Training/model claims must be limited by these representativeness domains.

## 2. Authentic independent tower cohorts, fixed before data read

See `research/ige_cmip6/p9_1h_observation_source_registry.json`; **provider data remain unverified**, and this registry must not be interpreted as permission to claim observations were downloaded. Four possible sources:

- **KNMI Cabauw:** 2/10/20/40/80/140/200 m; 10-min NetCDF, manually validated LB1 (v1.3), *not* gapfilled LC1. Confirm actual files, levels, flags, station exposures, licensing, missingness, API-key access.
- **University of Helsinki SMEAR II Hyytiälä:** 4.2/8.4/16.8/33.6/50.4/67.2 m instrumented levels; 1-minute database; standard time UTC+2 without DST and sentinel -999; source QA may be weaker than manually validated. Below-/above-canopy vertical structure is not valley inversion physics.
- **DOE ARM SGP:** multi-level 25/60 m candidate from historic tower; actual availability, station semantics, coordinates and QC still unqualified.
- **DWD Lindenberg 99-m tower:** UHH/ICDC dataset has T=K, QC good flag 5 and 10-minute data 2013–2017. It is restricted/partly accessible and not suitable for registered years 2018/2021; keep as supplementary non-holdout source only.

Fixed **development** UTC calendar windows: 2018-01-10..16 and 2018-07-10..16 inclusive.
Fixed **untouched temporal holdout**: 2021-01-10..16 and 2021-07-10..16 inclusive. The latter are **not** to be read or scored until physical candidate definition, tuning budget and model freeze. Missing/permission-blocked observations produce a blocked cell, not a substitute date/station. Model-fit may only use preregistered training windows; if a candidate has no 2018 support, that source is unavailable for fitting. Mountain regions will require their **own new observed 2–200m mast or multiheight local validation** in H3/H4; German/Austrian P9.1F/G holdouts cannot be repurposed for tuning.

## 3. H1 source/provenance qualification gates

For each original file store: exact provider identifier, authoritative URL+version, query parameters, site coordinates, physical sensor elevations relative to ground (and calibration/site log), UTC interpretation and interval start/end semantics, quality flag mapping with documentation, original-response SHA256, number of original observed records by QC, 10-min/1-min completeness, gap distributions and time horizon. Retain provider raw files privately if permitted, not in CI artifacts; publish only QA aggregates and cryptographic provenance. Never accept an automatically gapfilled, reanalysis-assimilated or synthetic value as an *independent* temperature observation. Exact sensor-level QC flags must be accepted explicitly; unknown -> BLOCKED. Provider QC levels across datasets must never be equated just because their integer codes are equal.

Gate H1 (source-qualified) is **OPEN** until >=2 geographical regions expose authentic measured *simultaneous* T values on >=2 levels with confirmed QC and timing, an independent year and original SHA. Three regions are desired; broad/global skill is not inferred from two or three towers.

## 4. Physically defined observational targets

For two colocated and synchronized original sensor heights `z_low < z_high`, `ΔT=T_high-T_low` [K], `dT/dz=1000 ΔT/(z_high-z_low)` [K/km], `inversion=ΔT>0.10 K`; `neutral_band=|ΔT|<=0.10 K` to reduce rounding-related false positives. **Frozen detection tolerance 0.10 K**, *not optimized on holdout*. Sensitivity analysis at 0.0/0.2 K is diagnostic only and must not be used to select a new threshold. Always report Δz; do not compare raw ΔT distributions across 4.2–67.2 and 2–200m as equivalent physical layers.

If actual pressure is absent, dry static-stability estimate `dθ/dz≈dT/dz+9.8 K/km` is only a shallow-layer approximation, **not** direct observed θ or an inversion indicator. Never compare its single value with P9.1G genuine pressure-level θ gradient as though equal.

Hourly targets are formed from >=4 synchronous QC-qualified **10-minute** readings per hour, or >=45 synchronous **1-minute** readings per hour, with both levels and actual time stamps, and **no imputation**. Any cross-provider aggregated series must record the temporal support and uncertainty. The analysis must retain transition hours and extremes, not only hourly/annual mean MAE.

## 5. Baselines, physical candidate, and safeguards

- B0: ERA5 raw grid 2m temperature; B1: actual regular grid surface height corrected at fixed -6.5K/km; B2: provider altitude adjusted, explicitly black box. Never substitute another reanalysis product for ERA5 silently.
- H2: separate hypothesized radiation (nighttime cooling, solar), cloud/LW, wind shear, snow cover, terrain aspect and cold-air drainage diagnostics. Validate the predictor source availability before use. Observed profile data are **target labels only**; not an input available at arbitrary forecast points.
- H3: small, physically constrained regime model (positive inversion correction only when source-supported and safe) against B0/B1/B2; frozen training/validation; backoff to proven baseline if source missing or outside-support; register sign and monotonicity constraints.
- H4: untouched new site/year **and valley, plateau, urban, open, forest** exposure strata; no parameter modifications after looking at holdout; if failed, report failure and return to new training data rather than retuning holdout.

Metrics: site×season MAE, RMSE, signed bias; inversion positive-class precision/recall, balanced accuracy, Brier/reliability if probabilities are used, frequency and duration; conditional T error under inversion and non-inversion separately; worst-cell regression, daytime/nighttime and snow stratification; block-bootstrap by site-day (not treating adjacent hours as independent). Report sensor/QC/sample uncertainty separately from model uncertainty. Significant evidence needs effect magnitude + uncertainty and no unacceptable regional degradation; **green unit tests are not scientific verification**.

## 6. Stop conditions and EPW linkage

No universal spatial correction and no production 8760 EPW integration until H4 true observation and non-meteorological leakage checks pass; humidity/radiation/wind co-closure and actual TMY/future generation remain separate gates. `global_arbitrary_point_weather_qualified=false`, `near_surface_inversion_model_qualified=false`, `production_epw_ready=false`. No merges to main without separate approval.

**Registered before P9.1H experiments:** source inventory only, not an observed skill result. Leave negative cases and failed access gates intact in reports.
