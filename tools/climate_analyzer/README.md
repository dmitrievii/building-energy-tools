# Climate Analyzer

Climate analysis for building design and building performance.

Climate Analyzer is an interactive Streamlit application for exploring EnergyPlus Weather (EPW) files. It is intended for building-physics, architectural and early HVAC/passive-design analysis.

## Start

The public workflow has two entry points:

1. **Upload EPW** — analyze a user-provided EPW file for the current session.
2. **Find climate** — select a station from the reviewed Climate.OneBuilding catalog and download the selected EPW on demand from the provider.

After a climate is selected, the application opens the Overview automatically.

## Analysis sections

- Overview
- Temperature
- Moisture and psychrometrics
- Solar radiation
- Wind
- Sky and daylight
- Natural ventilation
- Passive strategies and HVAC
- Multi-climate comparison
- Data quality and EPW metadata

The application supports hourly, daily, weekly, monthly and seasonal views where relevant, plus duration curves, heat maps, psychrometric diagrams, wind roses, solar-orientation analysis and climate-comparison views.

## Climate data and provenance

The public application does not rebuild upstream station catalogs during user sessions. It reads a reviewed, versioned catalog snapshot from:

```text
epw_climate_analyzer/data/station_catalog.csv
epw_climate_analyzer/data/station_catalog.meta.json
```

The catalog CSV is verified against its manifest SHA-256 and record count before use. The current bootstrap snapshot is intentionally limited to Austria and selected nearby Central European stations; it is not presented as global coverage.

Climate.OneBuilding EPW files are **not bundled in this repository**. A selected file is downloaded from the provider on demand. Local uploads and provider downloads are processed through the input/download security boundaries before parsing.

See [DATA_SOURCES.md](DATA_SOURCES.md) for the provenance and catalog-maintenance model.

## Scientific validation

Scientific behavior is protected by reference-point and deterministic annual regression tests. Current validation covers, among other things:

- psychrometric calculations against independent ASHRAE/PsychroLib-equivalent equations;
- solar plane-of-array reference cases;
- fractional EPW UTC-offset handling;
- EPW hour and typical-year semantics;
- degree-hour indicators;
- natural-ventilation and night-flushing logic;
- an 8,760-hour deterministic annual climate fingerprint;
- monthly/annual radiation conservation and passive-strategy results.

See `validation/SCIENTIFIC_VALIDATION.md` and `validation/scientific_reference_register.json`.

## Security boundaries

Public inputs are bounded and validated before processing. Climate.OneBuilding downloads are restricted to HTTPS on the approved provider host, redirect targets are revalidated, transfer sizes are bounded, and ZIP members are read without filesystem extraction.

See [SECURITY.md](SECURITY.md).

## Local development

Use Python 3.12.

```bash
cd tools/climate_analyzer
python -m venv .venv
```

Activate the environment, then install the pinned direct dependency baseline:

```bash
python -m pip install -r requirements.txt
```

Run the application:

```bash
streamlit run app.py
```

Run the validation suite:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Catalog maintenance

Catalog crawling is a maintenance task, not a public UI function. A candidate can be generated locally with:

```bash
python scripts/update_station_catalog.py --regions Europe
```

or via the manually triggered GitHub workflow **Build Climate Catalog Candidate**. The workflow creates a review artifact and does not modify `main` automatically.

## Project status

`WEB-0.6` is the current public-UX candidate for the Climate Analyzer public-beta preparation. Calculation outputs should be interpreted together with the documented assumptions, source provenance and validation scope.
