# IGE P9.1D — Native ERA5 Grid Orography, Independent DEM, Physically Conditioned Spatial Adaptation

**Preregistered before reading P9.1D original grid geopotential, independent DEM elevations or target station observations.** Date 2026-10-17. Parent frozen P9.1A–C head `b9f0ab4a347b66ba021b961cafde251c43b59f80`. Do not edit P9.1A–C data or `main`.

## Scientific question

Is the very high nearest ERA5 source-grid temperature MAE at valley and mountain stations in P9.1B/C due to **resolved grid-surface height difference**, and does any **physically constrained, non-target-fitted** elevation correction improve truly withheld 2022/2024 hourly station scores **without harming cold-air inversions or mountain-top exposure**?

**Native ERA5** is strictly distinct from **Open-Meteo processed ERA5 0.25° historical API** and Google **ARCO ERA5 0.25° regular-grid interpolated product**. Source priority:
- Original ERA5 `geopotential` (z, m² s⁻²), from Google Research ARCO ERA5 **cloud-optimized ERA5 native reduced Gaussian N320** at `gs://gcp-public-data-arco-era5/co/single-level-reanalysis.zarr-v2`; verify exact field, units, grid metadata, original retrieval SHA (selected values), and source coordinates. The Google ARCO conversion of ECMWF ERA5 files is traceable but **not original CDS GRIB bytes**. Its N320 native reduced Gaussian grid **is not the same** as Open-Meteo selected regular 0.25° cell; do not conflate their heights. For confirmation, compare with independent `ARCO ERA5 0.25° geopotential_at_surface` if accessible; do not call a native-grid station height the literal Open-Meteo model-grid elevation without a formally verified regridding/interpolation relationship.
- Independent ground elevation **Copernicus DEM GLO-90 Public** (DSM ~90 m) from original AWS COG tiles *where accessible*, supplemented independently by **SRTM v3** served by OpenTopoData (explicit dataset provenance / limitations). Independent DEM is not station metadata and **not a ground truth at building height**; vegetation/building DSM offsets and vertical datum differences must be recorded. Station source elevations obtained from original GeoSphere metadata **not treated as DEM readings**.
- If ARCO native Zarr cannot be accessed or geocodes cannot be verified: mark **`NATIVE_GRID_OROGRAPHY_NOT_VERIFIED`**. Never substitute Open-Meteo `elevation=nan` return value (reported zero in Alpine example).

## Frozen holdouts and methods

**Discovery** at three original GeoSphere Austria stations: Graz Universität/Heinrichstraße (ID 30), Innsbruck Universität (ID 39), Patscherkofel (ID 196). Additional neighboring valley/mountain stations may be used only to study spatial regime after preregistered station status. No station target temperature used to select model cell.

**Primary score period:** 2022-01-10…16 and 2022-07-10…16, **336 available hours per station** before QC. 2022 is distinct from both P9.1B 2023 and P9.1C 2024. Original `klima-v2-1h` `tl` + `tl_flag`, pre-existing `GOOD_FLAGS={10,11,12,20,21,22}`, >=120 matched QC hours per station-season; no target observation leakage. These are **same three sites**, hence temporal holdout but **NOT new spatial holdouts**.

**Candidate models, fixed BEFORE seeing 2022 scores:**
- L0 `ERA5_GRID`: Open-Meteo `models=era5,elevation=nan,cell_selection=nearest`, no height correction.
- P0 `OPEN_METEO_HEIGHT`: same ERA5+nearest cell, explicit `elevation=<station genuine altitude>` (provider black-box diagnostic, *not* independently physical).
- L1 `PHYSICAL_LAPSE_0065`: L0 plus `−0.0065°C/m × Δz`, where Δz is **native ERA5 reduced Gaussian N320 grid surface geopotential at the same lat/lon nearest native cell** and actual observation site station altitude. This estimate is a **screened proxy** unless native-to-regular height representativeness can be demonstrated; do not call it a calibrated 0.25 grid lapse.
- L2 `BOUNDED_LAPSE`: identical L1 but correction bounded to ±3°C. No extra parameters.
- L3 `NIGHT_COLD_AIR_GUARD`: L2 suppressed (zero correction) for **winter night in UTC**, hours 22…05 and **lower-elevation valley candidate** `site_height < native_model_height−150m`. This is merely a conservative proxy for cold-air/inversion susceptibility; not a validated inversion model. The guard may backfire, count separately. No forecast/observation feature leakage.
- Eligibility blocker: if native N320 source grid is invalid, native-to-regular representativeness cannot be estimated or DEM absent, candidates L1–L3 must remain `NOT_QUALIFIED`; diagnostics may be shown but cannot be production-released.

**Primary metrics:** same exact paired hourly sample per station-season across methods; MAE, RMSE, bias, daytime/nighttime errors, number of site-season improvements vs L0; grouped site macro-mean; worst degradation at Patscherkofel and all 6 station×season pairs. Do not select an optimum candidate on test data. Include 2022+2023/2024 only as follow-up external robustness, never tune using 2022.

**Source quality**: no published full original station time series; only source hashes, grid cell coords, verified z/g and independent DEM sample, summary holdout MAE. No height-derived corrections on cloud/rain/radiation in P9.1D. Solar and event coupling remains P9.2.

**Acceptance decisions:**
1. **Source qualification** requires a real N320 original ERA5 geopotential sample with verified units, coordinates, finite geopotential, SHA, provenance + independent original DEM sample with datum/type explicitly recorded.
2. **Methods scientific gate** passes if true originals are paired, *all frozen methods scored on identical holds*, meaningful variation reported, and no silent tuning. A negative result is scientifically valid.
3. **Global production/site adaptation remains BLOCKED** until full global independent geographic holdouts, validated native↔0.25 grid mapping, elevation distribution/vertical-datum QA, inversion/terrain exposure physics, and stable nondegrading regional error budgets.

Reference provenance: https://github.com/google-research/arco-era5 ; https://registry.opendata.aws/copernicus-dem/ ; https://www.opentopodata.org/datasets/srtm/ ; https://github.com/open-meteo/open-meteo/issues/1155 .
