# IGE Independent Climate Engine — P6.1 full-period daily research (ACCESS-CM2)

**Status:** computation requested, not certified until GitHub Actions closeout succeeds. **Date:** 2026-10-10. Production Climate Analyzer remains unchanged.

## Objective and scope

Expand successful 2014/2050 nine-variable pilot to one consistent GCM: NASA NEX-GDDP-CMIP6 v2.0 ACCESS-CM2, member r1i1p1f1, Graz reference point 46.983 N 15.450 E; sampled grid cell 46.875 N 15.375 E. The raw historical/future daily meteorological data are **not observed weather** and are **not locally calibrated**.

Five independently collected, 20-year windows:
- historical 1995–2014;
- SSP2-4.5 2040–2059;
- SSP2-4.5 2080–2099;
- SSP5-8.5 2040–2059;
- SSP5-8.5 2080–2099.

**Total planned:** 100 model-years × nine synchronized variables = 900 annual NASA NetCDF subset requests. Expected daily observations: 36,525 for Gregorian calendars; may differ for CF noleap/360-day calendars. P6.1 preserves source calendars; calendar regridding is NOT part of this stage.

## Scientific method

Nine raw variables: tas, tasmin, tasmax, hurs, huss, pr, rsds, rlds, sfcWind. Each annual source includes URL, downloaded NetCDF SHA-256, CF time calendar, units, grid coordinates, day count, member and scenario. Annual joins require exact matching time axes; all years and windows must share one grid and CF calendar. Unit and value guards fail closed. No filling of missing days, synthetic wind direction, pseudo-observations, DNI/DHI, atmospheric pressure, or hourly weather generation.

The full-period extraction calculates raw daily data, month-year sums/averages, annual values, and 20-year month-of-year means, **keeping all source daily records**. Values are computed from raw model radiation; they are NOT the GeoSphere-adjusted future GHI reported in P5.

## Numerical regression against P5

An immutable ACCESS-CM2 P5 source-only reference was extracted from the P5 v0.4.0 closeout CSV at results/multimodel_solar/model_monthly_ghi.csv: 12 historical months + four scenario-period combinations ×12 = 60 values.

For each 20-year window, the 12 raw NASA radiation monthly climatological means must agree with P5 to within 0.0001 kWh/m²/month. Differences beyond that threshold are recorded as failures, never silently reconciled. A matching P5 monthly GHI does not independently validate future temperature, humidity, wind or precipitation.

## GitHub execution and closing criteria

Matrix runs each of the five windows independently (up to two concurrent jobs, up to three NASA requests per job) and saves four CSVs plus two QA/provenance JSONs. Each job must PASS 20 distinct years, 180 distinct source-variable/year pairs, exact CF dates, one grid/calendar, correct raw values and 12 P5 reference months.

A follow-on audit downloads all five artifacts and requires all 900 source hashes, 100 model-years, 60 P5 GHI regression checks, unique daily source records, CSV SHA-256 verification, and consistent spatial/calendar metadata. The closeout report is written only after all matrix jobs succeed. This is **research-source closure, not engineering/EPW validation**.

## Next stage

After full ACCESS-CM2 audit, expand to the seven additional P5 GCMs, *then* P6.2 bias correction / multivariate coherence diagnostics and P6.3 hour-by-hour EPW research generation. Historical validation needs independent GeoSphere daily station measurements; daily relative humidity and specific humidity coherence must account for missing local pressure and nonlinear time averaging.
