# Climate Analyzer

Climate analysis for building design and building performance.

Climate Analyzer is an interactive Streamlit application for exploring EnergyPlus Weather (EPW) files. It is intended for building-physics, architectural and early HVAC/passive-design analysis.

## Release identity

Current candidate:

```text
Climate Analyzer 0.1.0-beta.1
channel: public-beta-candidate
status: BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

The beta candidate is an **independent personal research and teaching tool** by Ivan Dmitriev. Academic affiliation with the Institute of Buildings and Energy, Graz University of Technology is biographical context only; Climate Analyzer is not an official TU Graz website, service or product.

The public publication gate is tracked in `../../website/PUBLICATION_CHECKLIST.md`.

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

## Methodology and limitations

The calculation/decision-support scope, assumptions and known limits are documented in [METHODOLOGY.md](METHODOLOGY.md).

Climate Analyzer is not a regulatory energy-performance calculator, certification engine, full building thermal simulation or CFD/pressure-network ventilation model. Climate-derived passive/HVAC outputs should be interpreted as screening or decision support unless a documented calculation explicitly states otherwise.

Canonical engineering disclaimer:

> Climate Analyzer is a research and teaching aid for climate-data exploration and early design support. Outputs are not a substitute for project-specific engineering judgement, regulatory verification, certification or professional design responsibility.

## Climate data and provenance

The public application does not rebuild upstream station catalogs during user sessions. It reads a reviewed, versioned catalog snapshot from:

```text
epw_climate_analyzer/data/station_catalog.csv
epw_climate_analyzer/data/station_catalog.meta.json
```

The catalog CSV is verified against its manifest SHA-256 and record count before use. The current bootstrap snapshot is intentionally limited to Austria and selected nearby Central European stations; it is not presented as global coverage.

Climate.OneBuilding EPW files are **not bundled in this repository**. A selected file is downloaded from the provider on demand. Local uploads and provider downloads are processed through the input/download security boundaries before parsing.

See [DATA_SOURCES.md](DATA_SOURCES.md) for the provenance and catalog-maintenance model and [ATTRIBUTION.md](ATTRIBUTION.md) for third-party attribution requirements.

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

## Privacy / deployment boundary

The application code does not add advertising, Google Analytics or tracking pixels. The intended beta host, Streamlit Community Cloud, still has its own platform logging/analytics/privacy behavior, and the station map can cause browser requests to external map infrastructure.

The current deployment-aware privacy draft is `../../website/content/privacy.md`. It is intentionally not marked final until public controller/contact fields and actual browser/network behavior are verified.

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

## Licensing status

No repository-wide software licence has been selected yet. Public source availability must not be described as unrestricted permission to copy, modify or redistribute the code. Third-party libraries, map data and climate datasets retain their own terms.

## Project status

`WEB-0.7` is the current identity / methodology / publication-policy candidate. Scientific and runtime behavior remain governed by the previously validated calculation, security and provenance gates; publication clearance is a separate explicit gate.
