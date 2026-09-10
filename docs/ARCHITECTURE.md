# Architecture

## Product model

Building Energy Tools is an independent personal research and teaching platform maintained by Ivan Dmitriev.

The platform and scientific applications are separated deliberately:

- the **website** provides discovery, documentation, teaching and research context;
- each **tool** owns its scientific calculation code and interactive UI;
- deployment targets may differ while remaining in one repository.

## Initial deployment model

- Website: static deployment (initially a free hosting provider)
- Climate Analyzer: Streamlit Community Cloud for the beta stage
- Source: GitHub monorepo

## First tool

`tools/climate_analyzer/`

The scientific calculation layer must remain separable from the Streamlit presentation layer so that a future frontend migration does not require rewriting validated calculations.
