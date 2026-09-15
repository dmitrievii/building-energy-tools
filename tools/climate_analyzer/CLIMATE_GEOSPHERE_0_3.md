# CLIMATE-GEOSPHERE-0.3 — public historical station selection

## Scope

This stage connects the qualified `klima-v2-10min` GeoSphere Austria adapter to Climate Analyzer without converting measured observations to EPW.

The Start page now offers **GeoSphere Austria** as a third climate source. The user can search quality-checked stations, select a UTC historical date range, see the expected request size/batch count, and load up to 366 days. Long ranges use the bounded batching introduced in CLIMATE-GEOSPHERE-0.2.

## Canonical analysis path

Loaded GeoSphere data remain a `CanonicalClimateDataset` with real historical UTC timestamps and a declared 10-minute native interval. Existing source-agnostic renderers are reused for:

- Temperature and extremes;
- Humidity and psychrometrics;
- Time series and overlay;
- source/provenance diagnostics.

A provider-specific duplicate temperature/humidity plotting stack is deliberately not introduced.

## Cadence safety gate

Several legacy EPW routes label a Boolean record count as "hours" because EPW is hourly. Those routes are not valid for 10-minute observations without explicit duration weighting. Therefore, measured-data mode currently hides:

- temperature threshold-hours;
- moisture threshold-hours;
- wind/ventilation occurrence views;
- precipitation occurrence views;
- natural-ventilation/HVAC occurrence summaries;
- multi-climate comparison.

HGT/KGT degree-hours remain enabled because `degree_metric_table()` weights each source interval by the canonical native interval; degree-days remain based on daily mean outdoor temperature.

## Public request boundary

The UI permits at most 366 days per load. Every provider request stays below the conservative 200,000-datapoint local batch limit, and exact request URLs remain in provenance. Historical gaps and missing values are retained; no temporal interpolation is performed.

## Next stage

CLIMATE-GEOSPHERE-0.4 should make occurrence/count routes explicitly duration-aware so wind, precipitation, natural ventilation and related HVAC views can be enabled safely for 10-minute measured data. Historical comparison should then consume canonical datasets rather than reintroducing EPW-only assumptions.
