# IGE P9.1E — Native-to-Regular Grid Orography Mapping & Spatial Generalization

**Frozen scientific protocol · 2026-10-17.** Baseline P9.1D verified: native N320 ERA5 geopotential, independent SRTM and 9 original Austrian station observations; nearest native N320 `z/g` is **NOT** the selected Open-Meteo regular 0.25° grid height. No changes to P9.1D results. No merge to main.

## Core scientific question

Does **original ERA5 geopotential field resampled to a regular 0.25° grid** (independently distributed by Google ARCO) correctly correspond geographically to the **exact selected Open-Meteo ERA5 0.25° cell**, and is this regular-grid height a better physically grounded input for site adjustment than the previously used nearest native N320 height?

Source of regular geopotential `geopotential_at_surface`, units `m2 s-2`: `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`. This is **Google ARCO regridded ERA5**, not ECMWF CDS original GRIB and not guaranteed to be **the exact regridding scheme** Open-Meteo used. Validate coordinates and values; do not conflate latitude/longitude agreement with guaranteed vertical terrain equivalence. The earlier native N320 Gaussian points `gs://gcp-public-data-arco-era5/co/single-level-reanalysis.zarr-v2` are a distinct original model representation.

**Original-ground cross-check**: SRTM v3 90m independent terrain values via OpenTopoData, native official GeoSphere station altitude. Neither station metadata nor DEM may substitute for ERA5 model geopotential. No unsupported claims of the same vertical datum; flag vertical datum mismatch if relevant.

## Geometric qualification gates

- Regular grid must have exact latitude spacing 0.25°, 721 rows latitude [90,-90], 1440 longitudes [0,359.75] or equivalent; longitude normalized before matching, no false cell from nearest target lat/lon. Source `z` units m²/s², physically bounded. Extract exact regular-grid geopotential at **Open-Meteo returned latitude/longitude** per station, not at the requested target if they differ.
- Same station: report N320 nearest height, regular-cell z/g, independent SRTM/site altitude, N320-to-regular height discrepancy, regular-cell-to-site difference, distance source-cell to target. Reject nonexistent/ambiguous grid or incomplete response.
- A match of regular cell lat/lon does **NOT** attest that Open-Meteo's temperature source and Google ARCO regular grid have identical internal interpolation, topographic offsets or land/sea masks. Preserve `open_meteo_exact_grid_height_proven=false` until tested against a corresponding Open-Meteo native source/processing implementation.

## Site generalization: genuinely new lowland/coastal/valley locations

Selection frozen **before** any P9.1E station temperatures: six WGS84 urban target points **Vienna (48.249,16.356), Linz (48.300,14.300), Salzburg (47.803,13.043), Klagenfurt (46.624,14.305), Bregenz (47.503,9.746), Eisenstadt (47.842,16.525)**. For each target select the **nearest GeoSphere Austria QC station within 25 km**, excluding previously used 9 IDs `{30,39,196,119,14305,28,17005,66,184}`; deterministic station ID ordering for ties, and **no target hourly data used for selecting**. If no station, retain BLOCKED target; do not substitute by choosing a station with better error. Station altitude is used as known independent location metadata only.

Time holdout: **2021-01-10..16 and 2021-07-10..16** (new year vs prior P9.1D 2022, P9.1B 2023, P9.1C 2024). Original GeoSphere `tl` and QC `tl_flag` accepted `{10,11,12,20,21,22}`, minimum 120/168 paired hours per station×season. Each target appears in the score accounting; report missing/blocked sites.

Freeze source models & candidates:
- `L0_RAW`: ERA5 0.25° nearest cell from fixed Open-Meteo, `elevation=nan`.
- `P0_PROVIDER`: same source plus explicit site altitude using Open-Meteo black-box, **not** independent height physics.
- `L1_NATIVE_N320_0065`: old P9.1D N320-proxy `−0.0065 (z_site−z_N320)`.
- `L2_REGULAR_0065`: newly geometrically correct **regular grid** `−0.0065 (z_site−z_regular)`.
- `L3_REGULAR_BOUNDED_3C`: L2 with correction clamped to ±3°C. No temperature-dependent calibration, no use of withheld observations.
- Do not optimize lapse rates or pick best method on holdouts; count harms as well as wins, compare bias, MAE, RMSE, worst case and station macro distribution with confidence intervals cautioned for only six stations.

**Separate global geometry-only probes:** reuse predeclared P9.1A WGS84 points Graz, Singapore, La Paz, Reykjavik, Riyadh. For each, request minimal real ERA5 weather for **2021-01-10** to obtain returned model-grid coordinates and compare native/regular z and independently sourced SRTM where available. These **5 points** prove only consistent source spatial metadata, **not real measurement skill** or coastal building microclimate.

Predeclared scientific acceptance: original regular z on model grid with source SHA, exact coordinate unit/shape audit, 5 global geometric probes and at least 4/6 independently selected Austrian new station sites with ≥120 QC observations per season. A valid **negative** result still closes the study; **global spatial calibration/ready remains FALSE** without true extra-European station observational site/year holdouts, native-to-regular regridding documentation, pressure/time support and weather-variable completeness.
