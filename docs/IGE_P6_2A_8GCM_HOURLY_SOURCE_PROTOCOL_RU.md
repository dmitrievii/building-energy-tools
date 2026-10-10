# IGE Climate Engine — P6.2A: 8 GCM full diagnostics and hourly source-quality probe

Date: 2026-10-10. Status: **workflow submitted, NOT validated until GitHub Actions succeeds**.

## Scientific rationale

NASA NEX-GDDP-CMIP6 v2.0 has already undergone BCSD bias-correction/spatial disaggregation against a historical forcing reference. P6.2 is **not** an indiscriminate second bias correction. Phase P6.2A tests physical closure and residual station climatology differences using immutable P6.1 model-day values. References: NASA technical note https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf ; GeoSphere hourly https://data.hub.geosphere.at/dataset/klima-v2-1h .

## Input evidence

- Eight P5-selected CMIP6 models: ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR, MPI-ESM1-2-HR, MRI-ESM2-0 and NorESM2-MM.
- Five 20-year windows each: historical 1995–2014 and SSP2-4.5/SSP5-8.5 in 2040–2059 and 2080–2099; 800 model-years, 7100 original NetCDF source files and 292125 daily records (subject to file QA).
- ACCESS-CM2 from original P6.1 accepted run 38067931031. Seven remaining models via strictly validated combination of 28 successful original run 38072042977 artifacts + 7 repaired run 38077903914 artifacts.
- GeoSphere month-by-month reference from independently downloaded provider station 30 for 1995–2014 (240 records) from the previously accepted P6.2A pilot run 38081032571.

## Outputs of full 8-GCM diagnostic

- 40 model-period source-climate summaries, retaining model-native calendars.
- 32 historical-to-future paired changes (8 models × 4 future windows): annual temperature, precipitation and GHI changes, JJA T mean and daily Tmax p95, JJA wet-day frequency, within-season temperature/radiation and rain/radiation correlations.
- Model ensemble descriptive median, p10/p90, min/max for four future windows and eight metrics. These are **sampled-GCM descriptive spreads and NOT frequentist confidence intervals or complete structural/model uncertainty**.
- 96 station-vs-GCM monthly climatology comparison records for Graz station 30; per-model station annual precipitation differences and monthly temperature climatology MAE. These are site/metric residuals, **not validation error on individually aligned days**.
- Preserve sha256 for every imported source CSV, original quality/provenance audit, and all generated outputs; flag RH excursions and missing IPSL specific humidity.

## Independent one-week hourly feasibility

Separately request GeoSphere v2 hourly dataset for station 30, 2020-07-01 00:00 UTC through 2020-07-07 23:00 UTC, and parameters tl, rf, rr, cglo, ff and p. Verify live metadata units, station ID, explicit UTC timestamps, length, null counts, and available per-parameter quality-code fields. Store original source bytes/hash and metadata.

**Crucial:** GeoSphere's recorded hour may mean instant sample, trailing-hour mean, accumulation or extrema depending on parameter. Quality flags have meanings that must be parsed from source metadata before exclusion. Global solar radiation (cglo) unit is verified live; there is no implicit conversion in this feasibility probe. One week does not qualify as an independent 20-year validation.

## Next decisions

After success, acquire 1995–2014 source-quality station observations for agreed matching stations/variables and run correctly aggregated historical day/month distribution validation with spatial/altitude differences. Decide whether and how much additional local correction is supported by evidence. Do not use EPW or call any forecast validated before future temporal disaggregation, physical daily-hourly conservation and EnergyPlus parsing are tested.
