# P9.3B1: original CanESM5 pressure source recovery & cross-variable consistency — frozen source protocol

**18 October 2026, before reading source-native CanESM5 pressure data.** Separate research branch from P9.3A closure `dce88aea`. Purpose is **data provenance and physical interpretation**, not an EPW-generation repair. Region Austria / Graz only, no future-world validation.

**Exact identification:** `activity_id=CMIP`, `institution_id=CCCma`, `source_id=CanESM5`, `experiment_id=historical`, `member_id=r1i1p1f1`, `table_id=day`, `variable_id=ps`, `grid_label=gn`, original calendar and units. Validate underlying asset's own CMIP attributes (not catalog row alone), UTC/CF time bounds, original units Pa, model coordinates, grid cell distance, native land elevation/grid-cell fraction where explicitly available, and original source storage URL. Prefer Pangeo mirror of original CMIP6-ESGF `gn` source Zarr, not ISIMIP/WorldClim bias-adjusted surface pressure. Pangeo mirror is an **original-model data replica**, not an original-provider pressure measurement. Second path via actual ESGF metadata if Pangeo lacks original `ps/day`; never infer existence from analogous other variables.

**Correct scientific distinctions:**
- Native global coarse-resolution model `ps` is pressure at **CanESM5 native atmospheric surface**, not pressure at Graz (~47.07°N 15.44°E) or NASA NEX-GDDP 0.25° (46.875°N 15.375°E) after bias correction and elevation adjustments.
- NEX-GDDP-CMIP6 daily `tas/tasmin/tasmax/huss/hurs` were independently bias-corrected/downscaled; adding *unadjusted* coarse CanESM5 `ps` may reduce pressure-source inconsistency but **does not prove a jointly physically consistent daily or hourly state**.
- Compare native-ps daily source original 2013 and 2014 (previously evaluated development years) to NEX GCM original `tas/huss/hurs` at registered grid. They are **not a new independent holdout**. Do not use these comparisons to select pressure offsets or modify the 15 failures.
- Source-native `ps` can diagnose pressure biases and physical achievable-RH differences; native surface elevation and local pressure-reference transformations require later P9.3B2 independent DEM/orography validation; no `p←huss/RH` inverse.
- Predefined saturation tests at native grid raw ps nearest/cell: target native `huss` vs `q_sat(tas,ps)`; target native `hurs` vs thermodynamic RH derived from native `tas,huss,ps` (distinct variables, daily aggregate `tas` and `huss` not identical to daymean RH). Also more permissive chord envelope given native daily Tmin/Tmax and mean. Report all 365 days in 2013, 365 in 2014, standard errors and how many exceed q saturation capacity. **Not** an hourly consistency proof or proof original GCM invalidity.
- Preserve all original source SHA and coordinate/temporal metadata, native calendar and link, q_saturation relation over liquid/ice flagged, no source substitution if `ps` missing. Source data JSON aggregate only (no raw 730-day original PS provided as 'measured observations').
- Frozen outcomes: `SOURCE_VERIFIED` only after original mirrored original ps day read; `SOURCE_NOT_FOUND` or `SOURCE_UNAVAILABLE` explicitly if not; `PRESSURE_GRID_NATIVE_COARSE` always, `NEX_GDDP_PRESSURE_AT_FINE_GRID_NOT_DIRECTLY_AVAILABLE` always; `scientific_EPWCET_production_qualified=false` always.

**Source references:**
- Pangeo CMIP6 catalogue https://storage.googleapis.com/cmip6/pangeo-cmip6.json and https://storage.googleapis.com/cmip6/pangeo-cmip6.csv
- ESGF CMIP6 controlled-vocabulary archive. Original model model development Swart et al (2019).
- NEX-GDDP-CMIP6 documentation https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf
