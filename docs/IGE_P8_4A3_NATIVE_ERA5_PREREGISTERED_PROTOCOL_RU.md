# IGE P8.4A3 — ERA5 10m vector validity, gateway transformation and temporal-support audit

**PREREGISTERED 2026-10-17; commit BEFORE independent 2024 native-value and gateway evaluation.** Parent P8.4A2 report `0a8ac77080dd86f2ef9fec09d91796c2ec7d5f4d`. Research-only, never update main/production EPW.

## Fundamental distinctions

1. ECMWF ERA5 10m u/v components (`10u`, `10v`; eastward / northward, m/s) are **instantaneous reanalysis valid-time values**, not hourly mean observed scalar wind. Construct scalar magnitude `sqrt(u²+v²)` and meteorological FROM direction `atan2(-u,-v)` normalized to [0,360); direction undefined under <0.5 m/s.
2. The Google ARCO ERA5 0.25° store is **an independent regridded archival copy of actual ERA5 component fields**, not the model's un-regridded T639/native horizontal grid. When this audit says `native_components`, it means actual reanalysis u/v rather than Open-Meteo derived speed/angle, **NOT native model-grid geometry**.
3. Open-Meteo `models=era5` returns instantaneous model speed/azimuth from its historical gateway; by default it uses elevation and land cell selection. `cell_selection=nearest,elevation=nan` is the preregistered *unadjusted gateway control* but provider-reported `elevation` is NOT independently verified grid geopotential and may be zero. It is NOT scientifically sufficient to call it raw ECMWF data.
4. Historical MeteoSwiss `fkl010h0` is scalar hourly mean (post-2018 hour stamp END of preceding six 10-min end samples), while GeoSphere `ff` 1h is vectorial mean magnitude, as confirmed by P8.4A2 original 2024 six-to-one reconstruction.

References: ECMWF ERA5 https://www.ecmwf.int/en/forecasts/datasets/era5-hourly-data-single-levels-1940-present ; ARCO public https://github.com/google-research/arco-era5 ; Open-Meteo historical https://open-meteo.com/en/docs/historical-weather-api ; official MeteoSwiss https://opendatadocs.meteoswiss.ch/general/download . See especially Open-Meteo documented `elevation=nan` and `cell_selection=nearest` semantics.

## Frozen source pilot

- Geographic original SwissMetNet target sites **BAS, GRA, MUB**, **January 2024**. Site parameters frozen prior to comparison. No model is fit/tuned.
- Retrieve original 744 UTC hours of station `fkl010h0`/`dkl010h0` and two `models=era5` gateway modes at same requested WGS84 point: 
  **default** (provider elevation/land-cell selection), and **`cell_selection=nearest,elevation=nan`** (no downscaling, provider nearest cell). Exact same time axis, `GMT`, `wind_speed_unit=ms`; retain actual gateway returned cell-center coordinates and elevation reported but do not trust the latter as DEM truth.
- Compare station published hourly scalar wind speed against both gateway modes on exactly identical 744 hours; report MAE, RMSE, bias, angular conditional MAE and direction coverage on identical target noncalm hours. Values are **observational representativeness scores**, not equivalence evidence. Do not choose best mode after inspecting its 2024 error.
- Predeclared endpoint-only hourly `trap_scalar=(s[t-1]+s[t])/2` and `trap_vector=hypot((u[t-1]+u[t])/2,(v[t-1]+v[t])/2)`; these are explicitly **TWO-POINT QUADRATURE PROXIES**, not subhourly reconstructed hourly mean, and not a replacement for native ERA5 subhour sampling. Score those two proxies on the same 743 complete interior hours, without artificial clock optimization. Report original instantaneous and both proxy methods on the same interior hours.
- Independently query public Google ARCO ERA5 `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3` using anonymous `gcsfs/xarray`, variable names `10m_u_component_of_wind`, `10m_v_component_of_wind`. **Only 4 frozen original January samples**: 2024-01-15 at `00:00,06:00,12:00,18:00 UTC`, all three stations. This deliberately bounded spot check (12 site-times) limits remote reads of enormous global time chunks; it is not a full-month archived-native skill benchmark. Check native `m s**-1` unit, exact valid-time indices, ARCO attributes `valid_time_start/stop` and returned true ERA5 0.25° grid cell centers, and vector conversion.
- Compare the independent 12 original component values against the **gateway nearest/unadjusted mode** at the same stamps, only IF ARCO-selected cell center coincides (numerical tolerance <0.025° latitude and longitude) with the actual gateway-returned cell center; otherwise **block cross-source numeric equality as spatially confounded** and preserve that evidence. Do not silently interpolate native ERA5 or choose cells based on forecast error. Calculate paired u/v RMSE and speed/angular differences, with missing direction explicitly reported. Only derived aggregate differences and original source/metadata identifiers can be published.
- ARCO 0.25° **regular regridded resolution** is not equivalent to native model T639 grid. If bucket is inaccessible, grid units incompatible, or wall-time limits reached: **`INDEPENDENT_ARCO_NATIVE_SPOTCHECK_BLOCKED`** with explicit source blocker, not a silent fall back to Open-Meteo or a false CI success. Keep gateway science independently auditable.

## Mathematical and physics gates

- `u=-speed*sin(dirFROM)`, `v=-speed*cos(dirFROM)`; 0/360 canonical to 0°, calm azimuth unresolved. Unit tests for N/E/S/W, domain, inverse roundtrip, zero, near 360.
- For any two endpoint speeds `trap_vector<=trap_scalar`; do not claim `mean(abs(v(t)))` from 1h endpoint samples.
- Explicit 744 sequential GMT hours and actual matched timestamps; original station height measured AGL/roughness `z0` unknown. Never apply log-law vertical correction.
- No uncorrected ERA5/gateway, ARCO reanalysis values or observations are adapted/calibrated to test-year reference; no forecast event-date claims. No original hourly, native gridded arrays or gateway JSON data redistributed.
- Holdout year/site generalization still required for any method promotion; Jan 2024 was previously examined. This is a **physical source semantics** experiment only.

**P8.4A3 PASS condition:** gateway original-source pilot and 4-point ARCO provenance resolved (or explicit independent-source blockage published). **`full_source_equivalence_proven=false`** until independently matched native-grid/temporal support, other seasons/sites and instrument metadata are verified. `production_epw_ready=false` irrespective of CI.
