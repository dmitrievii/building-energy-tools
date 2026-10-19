# IGE P9.3B2 — Terrain-Aware Pressure Baseline and Independent Station Validation

**Prospective frozen protocol, 19 October 2026; commit before reading original 2024 hourly pressure observations.** Research branch separate from final P9.3B1 commit `699082e2`; geography exclusively Austria, Germany, Switzerland; no world sweep.

## One fixed observational cohort

Original source measured station-level **absolute** pressure, not sea-level reduced QFF/QNH:
- **AT Graz** GeoSphere historic klima-v2-1h station **30**, published station altitude and native pressure+quality flags, provided source metadata identifies a genuine station pressure parameter. Original `tl` T and `rf` RH optionally supply hypsometric virtual temperature. If station absolute pressure not available, set source status blocked; do NOT substitute sea-level reduced pressure.
- **DE Oberstdorf** DWD CDC hourly `pressure/historical`, ID **03730**, archive product P0, station level `P` versus sea-level `P0` must be disambiguated against original source description, original `QN_8` pressure QC. Same station original TU T/RH only where original timestamp and QC match. If pressure availability/QC changes 2024, report it.
- **CH Davos** MeteoSwiss SwissMetNet DAV native barometric `prestas0` or other exact published **QFE** station-pressure variable, hourly original OGD 2020–2029 only if field actually present. `pp0qffs0` and `pp0qnhs0` are sea-level values and MUST NOT be used as station pressure. Original Swiss OGD may contain published 1h T/RH but per-sample QC not demonstrably equivalent to DWD QN10 or GeoSphere. Explicitly classify hourly temporal semantics and QC.

**Exactly** two original-observation windows: **2024-01-10 00:00 through 2024-01-16 23:00 UTC** and **2024-07-10 through 2024-07-16**, 168 hours each ×3 sites=1008 maximum station-pressure observations, no other years or sites. Pre-selected as new pressure validation relative to prior P9.1/P9.2C station-year T/RH studies; does not constitute statistical generalization. No tuning parameters, seed or corrections based on inspected 2024 observations.

## Physical candidates, preregistered

**B0:** Open-Meteo original model=era5, elevation=nan, cell_selection=nearest, timezone=GMT original **surface_pressure** at unmodified ERA5 selected grid. This is Open-Meteo-derived, not native CDS ERA5 GRIB. Do not mistake `mean_sea_level_pressure` for source `surface_pressure`. Original 2024 temperatures and dew point used ONLY as model physical density inputs; observed station T/RH never optimize pressure.

**B1 (terrain-aware physical hypsometry):** For each matched UTC hour, fixed original grid `p_g`, `T_g`, `q_g` from original ERA5; independent original station metadata station height `z_s`. Independently externally requested terrain height `z_dem,g` from SRTM90 at the returned selected ERA5 grid center, **not true ERA5 effective model geopotential surface height**. If and only if the external DEM is available and original metadata station elevation is valid, evaluate
```
p_s = p_g * exp[- g * (z_s-z_dem,g) / (Rd * (T_g+273.15) * (1+0.61*q_g))]
```
using `g=9.80665 m s^-2`, `Rd=287.05 J kg^-1 K^-1`, observed-independent ERA5 virtual T. The column is isothermal / constant virtual T approximation; limitations of variable lapse rate/DEM-versus-ERA5 model orography are explicit. No fitting of mean source pressure, station observed p, GCM huss or pressure offset. Do not derive pressure backwards from huss/hurs. For initial diagnostic also report `z_s-z_dem,g`, sources, and 2024 station error for both B0 and B1 on identical native QC hours. **DEM at ERA5 grid center is only a geographic proxy**; direct perfect elevation correction cannot be scientifically claimed without verifying actual ERA5 model geopotential/orography.

**B2 physical sensitivity (not tuned):** fixed 0.0065 K/m environmental lapse profile integrated in the hydrostatic column, only for |delta z|<=2000m and positive virtual temperatures; identify with label `LAPSE_SENSITIVITY`. Formula `p_s = p_g (1 - gamma*(z_s-z_dem,g)/T_v,g)^(g/(Rd*gamma))`; one alternative, no selection by observed performance.

## Source and scientific qualification gates

1. Exact original API station parameter identities, units (Pa or hPa), UTC semantics, native QC; no missing source substitutions.
2. Original DEM real source URL, its source/response SHA, SRTM90 vertical datum uncertainty, returned heights and location. A DEM failure blocks terrain correction while B0 may still be scored.
3. Same 2024 original 168 UTC hours per site-season: MAE/RMSE/bias station-level pressure hPa for B0, B1, B2 on **common QC hours**; minimum **96 original pressure observations** per cell. Report improvement/loss without clipping/renormalization. In a site where source station pressure or DEM is missing, don't invent numerical results.
4. Independently assess `T_v` and hydrostatic dimensional invariants, zero-altitude identity, sign of correction, lapse convergence, pressure plausible 50–110 kPa.
5. One fixed 2024 year; no post-hoc year, site, provider, DEM, lapse choice, or source pressure field search conditioned on observed errors. New observations would require separate preregistration.
6. Historical 2024 T/p accuracy is **not** native CanESM5 climate-pressure consistency; original coarse monthly Amon ps remains a **monthly GCM climate signal**, NOT 2024 ERA5 fixed datum, not projected hourly future pressure and not direct source of P9.3A 2013/2014 closure.
7. No annual weather generation, no main merge. `production_epw_ready=false`. Next P9.3B3 only after pressure-source altitude/orography semantics and independent station scores assessed; global validation reserved for paper.
