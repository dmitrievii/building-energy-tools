# IGE P9.1F1 — Physically Conditioned Terrain & Inversion Modelling: frozen 2019 holdout protocol

**Registered before ANY 2019 target-hourly station temperature or 2019 method scores are read. Date 2026-10-17.** Parent immutable P9.1E result `8d3907cf2545126892d8030f2226a708a19adbb8`. Research only, NO main merge and NO production generator release.

## Scientific hypothesis, not assumption

An ERA5 0.25° cell has spatially averaged model-surface height and cannot resolve nocturnal cold-air pools inside narrow Alpine valleys. A universal `−6.5K/km × (station−grid)` can strongly worsen winter valley estimates (Klagenfurt Flughafen P9.1E2 January 2020: 1.706 °C raw vs 4.547 °C physical-lapse MAE). Fixed night+clear+calm decision logic may help suppress **positive low-valley height correction** under stable radiative conditions. However the rule is only a **cold-pool susceptibility proxy**, not identification of an actual collocated temperature inversion; cloud/wind/terrain provide incomplete physical evidence. Guard can degrade, must test falsifiably.

Published motivators: Rauchöcker et al. (2024, QJRMS) `https://doi.org/10.1002/qj.4644` (stable cold-air pool disruption by wind); Rupp et al. (2020, JGR Atmospheres) `https://doi.org/10.1029/2020JD032686` (synoptic and local inversion controls). These studies do not calibrate our gate coefficients.

## Inputs and strict independence

- **6 baseline lowland/city stations from earlier P9.1E2 eligibility-only 2021 selection**: `105 Wien Hohe Warte, 56 Linz Stadt, 145 Salzburg Freisaal, 48 Klagenfurt Flughafen, 15 Bregenz, 22 Eisenstadt Nordost`. Three additional physically contrasting Alpine fixed stations (not spatially novel to earlier IGE): `39 Innsbruck Universität, 196 Patscherkofel, 14305 Galzig`. Nine total named stations fixed, no selection based on 2019 weather residuals.
- **Purely untouched 2019 periods** January 10–16, July 10–16, October 10–16: 3 × 7×24 original UTC weather hours per station, **27 registered station-season scores**, minimum 120 actual original GeoSphere `tl` + original QC `tl_flag` accepted classes (10,11,12,20,21,22) for each station-season. All source missing failures reported, never select the easy stations.
- Source weather: explicitly Open-Meteo `models=era5,elevation=nan,cell_selection=nearest,timezone=GMT`; `temperature_2m,wind_speed_10m,cloud_cover,shortwave_radiation` and all prior P9.1A 12 variables. Reanalysis source returned selected 0.25° grid center verified. Separate provider black-box `elevation=official_station_m` comparator; same UTC hours.
- **True grid geophysical source for `Δz`**: original Google ARCO regular 0.25° `geopotential_at_surface` at **the selected returned weather cell**, cross-checked against ARCO nearest native N320 (NEVER replace regular height with native height). Neither Google ARCO pipeline nor its internal terrain is guaranteed identical to Open-Meteo regridding. All results marked proxy.
- Independent SRTM v3 90m DEM via OpenTopoData at official station coordinates and **16 terrain points per station** (eight cardinal/diagonal bearings, nominal radii 5 and 12 km), distances geodesic adjusted by latitude. Record source JSON SHA and vertical/datum limitations. Terrain `p75` adjacent height minus DEM site height. Minimum 14 finite bearing points, otherwise terrain-dependent candidates blocked. Separate terrain/site classification from test temperature.
- No actual station 2019 hourly temperature used in predictor, terrain orophography, source variable choice, regime, coefficients or eligibility. 2019 source weather conditions can be used in prediction and are not 2019 target station observations.
- Temperature source sampling temporal semantics and station UTC time-support discrepancies still unresolved beyond common reported timestamp. No claim of exact forecast-skill universality.

## Five FIXED candidates (no hyperparameter sweep)

`L0_RAW`: original grid ERA5 2m temperature without corrections.

`P0_PROVIDER`: Open-Meteo site-elevation provider black-box (control).

`L1_REGULAR_LAPSE`: grid ERA5 raw `−0.0065°C/m × (official_station_altitude−regular_ERA5_model_height)`.

`L2_TERRAIN_NIGHT_GUARD`: L1 except **suppress** the full positive height adjustment in a potentially cold-pool valley when:
`station_alt < regular_grid_height−150m`, independent SRTM 12-km ring p75 elevation ≥ DEM site +120m; **Oct–Mar (UTC month 10..3)**; **source ERA5 GHI ≤10 W/m²**, **ERA5 wind10m <2.5 m/s**, **ERA5 total cloud <60%**. No cold-pool correction outside guard. This is **not** a measured inversion and does not apply if grid altitude ≤station altitude.
`L3_TERRAIN_NIGHT_COLDPOOL`: same as L2 but when guard active use **grid ERA5 raw minus 1°C** (a fixed, non-fitted physical sensitivity perturbation). Do not retrofit to best observed 2019 offset.

Pre-registered metrics all source-clean pairs equal within station-season: MAE, RMSE, bias, macro MAE by station-season, macro by winter/nonwinter, risk-activated subset MAE for all models (at least 30 original QC guarded hours to interpret), subset of source-valley/high summit, max harm per station-season, meteorology of guard (wind, cloud, solar). Confidence from independent station-year units, NOT assuming 168 highly autocorrelated hours independent. A negative L2/L3 result remains **valid scientific closure**, no retuning threshold after outcomes. No claims of global validation based on Austrian/Alpine nine stations.

**Pre-specified scientific gates:** (i) original independent DEM rings and 0.25 ARCO z read for all selected points; (ii) all 9 named stations ×3 periods accounted for; (iii) ≥18 original QC-qualified site-period comparisons among 27 and winter Klagenfurt must be evaluable; (iv) 5 model scores reproducible and original source SHA emitted; (v) only if L2 consistently better in macro *and* worst-regime harm reduced is it eligible for subsequent **new unseen spatial/temporal validation**, not deployment. `production_epw_ready=false` regardless.

After P9.1F1, independent confirmation requires new geography OUTSIDE AUSTRIA (e.g. MeteoSwiss, DWD, NOAA original station metadata+QC) with preregistered held-out regions, full-year periods and provider/DEM altitude datum checks. Other weather variables and future EPW generator remain independently blocked.
