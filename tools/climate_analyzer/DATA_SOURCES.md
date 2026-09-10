# Climate data sources and provenance

Climate Analyzer accepts two runtime source classes:

1. a user-provided local EPW file, processed transiently in the active Streamlit session; and
2. an EPW selected from the bundled, versioned Climate.OneBuilding station catalog and downloaded on demand from `https://climate.onebuilding.org/`.

## Climate.OneBuilding runtime model

The public application does **not** crawl or rebuild upstream station catalogs during a user session. It reads the reviewed repository asset:

- `epw_climate_analyzer/data/station_catalog.csv`
- `epw_climate_analyzer/data/station_catalog.meta.json`

At runtime the CSV is rejected if its SHA-256 or normalized station count differs from the manifest. Every loaded station row receives the active catalog version, manifest date, provider identity and CSV hash.

The current `onebuilding-bootstrap-2026-09-10` snapshot is deliberately small: Austria plus selected nearby Central European stations. It must not be described as a global catalog.

## EPW distribution policy

This repository does not bundle Climate.OneBuilding EPW files. The catalog stores normalized station metadata and provider download URLs. A selected EPW is fetched from the provider only when the user requests it and is validated by the existing download/input security boundaries before parsing.

Climate.OneBuilding aggregates and produces weather files from multiple source datasets. Building Energy Tools therefore does not assert one blanket redistribution licence for all upstream climate files. Dataset-specific source, citation and usage information should be checked at the provider/source-dataset level.

Provider references used by the manifest:

- Climate.OneBuilding home: `https://climate.onebuilding.org/`
- Weather Data Sources: `https://climate.onebuilding.org/sources/default.html`
- News / current dataset updates: `https://climate.onebuilding.org/news/default.html`
- Provider-requested website citation at the time of this snapshot: Lawrie, Linda K.; Crawley, Drury B. 2026. *Development of Global Typical Meteorological Years (TMYx).* Climate.OneBuilding.Org (paper in progress).

## Catalog maintenance

Catalog crawling is a maintenance operation:

```bash
cd tools/climate_analyzer
python scripts/update_station_catalog.py --regions Europe
```

Or, for all configured WMO regions:

```bash
python scripts/update_station_catalog.py --regions all
```

By default, any failed upstream catalog causes the command to fail closed. `--allow-partial` exists only for explicit diagnostic/partial-candidate work and should not be used for routine promotion.

A generated candidate receives a content-derived catalog version and a manifest binding its exact CSV SHA-256, station count, regions and source-catalog build evidence.

The GitHub workflow `.github/workflows/update-climate-catalog.yml` runs the same maintenance path manually and uploads the candidate CSV + manifest as an artifact. It does not modify `main` automatically. Promotion is always review-first through a normal pull request.
