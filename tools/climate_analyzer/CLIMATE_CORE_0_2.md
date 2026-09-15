# CLIMATE-CORE-0.2 — Canonical climate model

## Purpose

Climate Analyzer originally treats normalized EPW data as the application data model. That is sufficient for typical-year EPW analysis, but it is not sufficient for measured 10-minute observations, multi-year historical series, future provider adapters or comparisons between data sources with different calendars.

CLIMATE-CORE-0.2 introduces a provider-neutral boundary without changing the existing EPW calculations or public release status.

## Canonical contract

Every canonical climate dataset has five explicit parts:

1. **Identity** — stable climate ID and display name.
2. **Data** — a unique, monotonic `pandas.DatetimeIndex` plus canonical climate-variable columns.
3. **Location** — latitude, longitude, elevation and optional city/state/country/station ID.
4. **Temporal metadata** — native source interval, calendar mode, timezone and interval timestamp semantics.
5. **Provenance** — provider, dataset, source format, source name/reference and optional provider station ID/retrieval metadata.

The canonical layer does not interpolate or invent missing time steps.

## Calendar modes

- `typical_year` — synthetic plotting calendar such as the normalized EPW year. Original EPW source years remain separate metadata.
- `historical` — actual observed timestamps. Years are never rewritten to a typical-year calendar.
- `forecast` — future dated values from a forecast source.
- `climatology` — explicitly climatological/non-year-specific aggregates when a future adapter needs them.

This distinction is mandatory for later Detailed Year and Historical Comparison features.

## Native temporal resolution

The source cadence is metadata, not a display preference. A provider may explicitly declare a 10-minute native cadence even when individual observations are missing and the observed timestamp gaps are temporarily larger.

The time-series explorer may downsample a source according to quantity semantics, but it must not upsample it. Therefore:

- 10-minute source → 10 min, 30 min, hourly, daily, monthly, etc. are allowed;
- hourly EPW source → 10/30-minute displays remain blocked;
- gaps remain gaps unless a future feature explicitly defines a scientifically justified filling method.

## Canonical variables and aggregation semantics

`epw_climate_analyzer.climate_model.CANONICAL_VARIABLES` is the authoritative registry for source adapters and time-series aggregation.

Examples:

- temperature, pressure, humidity ratio, wind speed, snow depth → arithmetic mean when coarsened;
- interval irradiation and liquid precipitation depth → sum when coarsened;
- wind direction → circular mean.

Provider adapters must explicitly map provider field names onto registered canonical columns. Unknown canonical targets fail closed rather than silently extending the vocabulary.

## EPW adapter

`canonical_from_epw()` wraps the existing normalized EPW representation. It does **not** alter EPW parsing, psychrometrics, solar calculations or current UI behavior.

Important EPW semantics are retained:

- the parser's unified plotting year is marked as `calendar_mode="typical_year"`;
- original measured/source years remain in `source_years` / `epw_source_year`;
- EPW hour-ending fields are represented on the current interval-start plotting axis (`hour 1 -> 00:00`, `hour 24 -> 23:00`);
- source provenance remains attached to the canonical dataset.

## Future adapters

The next data-source stages should terminate at this boundary rather than imitate EPW files. A GeoSphere Austria measured-data adapter, for example, should:

1. retain real provider timestamps;
2. declare the provider-native cadence (e.g. 10 minutes where supported);
3. map provider fields to canonical variable names;
4. attach station/location metadata and provider provenance;
5. pass the resulting `CanonicalClimateDataset` to analysis/comparison layers.

This is the required foundation for station-map measured data, Detailed Year and Historical Comparison.
