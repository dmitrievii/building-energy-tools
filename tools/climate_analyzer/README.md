# EPW Climate Analyzer

Local browser application for interactive EPW climate analysis for architecture and HVAC decision support.

## Main features

- Local EPW upload.
- Climate.OneBuilding station catalog builder.
- OpenStreetMap station-selection page with clustered station markers.
- Purple station points at close zoom levels and cluster counts at low zoom levels.
- One-click station selection and automatic EPW ZIP download/extraction.
- Cached global station catalog stored in the user profile folder.
- Hourly, daily, weekly, monthly and seasonal aggregation.
- Temperature, humidity, psychrometric, solar, wind, sky/daylight, natural-ventilation, HVAC/passive-design and data-quality dashboards.
- Automatic interpretation below the main charts.

## Run on Windows

Double-click:

```bat
run_app.bat
```

The launcher creates a local virtual environment, installs dependencies and starts Streamlit.

Default local address:

```text
http://localhost:8501
```

## Climate-file source page

The first page is `Climate File Source`.

It supports two workflows:

1. `Local EPW upload` — choose an EPW file from your computer.
2. `Climate.OneBuilding station map` — build or load the Climate.OneBuilding station catalog, select a station on the clustered OSM map and download its EPW archive.

Direct manual URL input has intentionally been removed from the user interface.

## Climate.OneBuilding catalog workflow

Climate.OneBuilding publishes public WMO-region pages with KML map files and XLSX station spreadsheets. This app reads those catalogs, extracts station coordinates and ZIP/EPW download URLs, and stores a normalized CSV cache locally.

Default cache path:

```text
%USERPROFILE%\.epw_climate_analyzer\onebuilding_station_catalog.csv
```

Use the `Build / refresh Climate.OneBuilding station catalog` button on the first page to rebuild the cache.

## Map behavior

- At low zoom levels, nearby station markers are clustered and displayed as count bubbles.
- After zooming in, individual stations appear as purple points.
- Click a purple station point to load its metadata in the right panel.
- Click `Select and download this station EPW` to make it the active climate file for all analysis pages.

## Bundled fallback catalog

A small fallback CSV is still included so the app can open before the global online catalog has been built:

```text
epw_climate_analyzer/data/station_catalog.csv
```

The global online cache is preferred whenever it exists.

## Notes

- Online catalog building and EPW download require an internet connection on the local machine.
- The first global catalog build may take time because multiple regional KML/XLSX catalogs are read.
- The app uses SI units internally.

## Calculated EPW Statistics

The `Overview` page includes a `Calculated EPW statistics` section. It uses only the active EPW hourly data table and EPW-derived columns. It does not parse companion package files. The statistics include:

- dataset coverage and missing-value diagnostics;
- temperature percentiles, extremes, daily amplitude, frost hours and tropical-night proxy;
- humidity, humidity ratio, wet-bulb temperature, dew point and moist-air enthalpy indicators;
- annual GHI/DNI/DHI, diffuse share, peak GHI, daylight availability and high-solar hours;
- wind-speed percentiles, calm/strong-wind hours and dominant wind-direction sector;
- sky-cover, precipitation and snow indicators from EPW fields;
- HDD18, CDD26 and default passive/HVAC decision indicators;
- monthly, seasonal and extreme-day summary tables with CSV export.

## Multi-climate comparison

The application includes a `Compare Climates` page for comparing two or more EPW files. The comparison mode uses only EPW hourly data and EPW-derived variables. It does not parse companion files such as CLM, WEA, PVSyst, DDY, RAIN or STAT.

Supported comparison workflows:

- Add the currently active climate to the comparison basket.
- Add multiple local EPW files.
- Add Climate.OneBuilding stations from the cached station catalog.
- Rename and remove comparison climates.
- Select one reference climate.
- Use automatic, overlay, small-multiple, ranked-summary and difference-to-reference display modes.

Implemented comparison chart groups:

- Summary metrics and ranked indicators.
- Monthly temperature profiles, temperature duration curves, monthly boxplots, temperature heatmaps, temperature-difference heatmaps, HDD/CDD comparison, heating/cooling season timelines and extreme-temperature rankings.
- Humidity-ratio profiles, humidity-ratio duration curves, outdoor-air enthalpy duration curves, psychrometric T-d/i-d density comparisons and latent-load rankings.
- Monthly GHI/DNI/DHI comparisons, radiation duration curves, sun-path comparisons, façade-radiation comparison, tilt-sensitivity comparison, orientation-tilt heatmaps and solar/shading rankings.
- Wind-speed profiles, wind-speed duration curves, small-multiple wind roses and wind rankings.
- Natural-ventilation monthly hours, natural-ventilation heatmaps, difference heatmaps, night-flushing monthly hours and ventilation/comfort rankings.
- Passive/HVAC stacked strategy bars, passive-strategy calendars and HVAC indicator rankings.
- Generic difference-to-reference charts for temperature, humidity, enthalpy, radiation, wind and relative humidity.
- Data-quality comparison matrices.

Every chart is followed by an automatic interpretation based on the selected climates and the current comparison filters.

## Update: performance and chart audit fixes

This version keeps the existing UI structure and visual style, but adds the following fixes:

- Faster Windows startup: dependencies are installed only on first launch unless `.venv\.deps_installed` is removed.
- Streamlit toolbar is forced to viewer mode to avoid accidental developer-cache shortcuts while copying text.
- Climate.OneBuilding catalog refresh can be limited to selected WMO regions; Europe is the default.
- The station map renders a capped number of markers and asks the user to filter before showing very large catalogs.
- All Plotly charts are rendered with unique Streamlit keys to avoid duplicate element ID errors.
- Generic variable charts now use a separate `Chart type` and `Aggregation` control. Heat maps have their own day/week/month aggregation selector.
- Aggregated profiles use readable period labels and unified hover so min, central and max values are visible together.
- Plot axes now use physical lower/upper limits where appropriate while retaining Plotly zooming.
- Heat maps use period on the x-axis and hour of day on the y-axis.
- Temperature heat maps use a blue-green-red colour model with the green band tied to heating/cooling thresholds.
- Solar/radiation heat maps use a violet-orange-yellow colour model and generic radiation profiles show mean intensity; energy sums remain in the dedicated solar component charts.
- Psychrometric charts now use grey dashed RH/grid layers, month-coloured climate points, explicit axis-limit controls and a tile-occupancy mode based on 1 °C × 5 %RH bins.
