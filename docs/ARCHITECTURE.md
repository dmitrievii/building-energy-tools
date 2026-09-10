# Architecture

## Product model

Building Energy Tools is an independent personal research and teaching platform maintained by Ivan Dmitriev.

The platform and scientific applications are separated deliberately:

- the **website** provides discovery, documentation, teaching and research context;
- each **tool** owns its scientific calculation code and interactive UI;
- deployment targets may differ while remaining in one repository.

## Website architecture — SITE-0.1

The website foundation is a zero-build static layer under:

```text
website/site/
```

The first implementation uses only HTML and CSS. It has:

- no runtime JavaScript dependency;
- no package-manager/build-tool dependency;
- no external fonts or CDN runtime assets;
- no project-added analytics;
- relative internal links so the site remains portable across static hosts;
- a separate machine-readable site contract and CI validation.

This choice is intentional. The public website is primarily an information/discovery layer and does not require an application framework at this stage. A framework may be introduced later only if a concrete content-management or interaction requirement justifies the added dependency and privacy surface.

## Deployment model

- Website: free static hosting target, not yet selected in SITE-0.1
- Climate Analyzer: Streamlit Community Cloud for the beta stage
- Source: GitHub monorepo

The static website links to Climate Analyzer as an external application rather than embedding it. This preserves a clean initial website network footprint and keeps the interactive scientific runtime independently deployable.

## Information architecture

Primary sections:

```text
Home
Tools
Teaching
Research
Documentation
About
```

Support/publication pages:

```text
Privacy
Accessibility
Legal / disclosure
```

## First tool

`tools/climate_analyzer/`

The scientific calculation layer must remain separable from the Streamlit presentation layer so that a future frontend migration does not require rewriting validated calculations.

## Publication boundary

The existence of a static website implementation does not change the fail-closed publication state. Owner/disclosure facts, hosting-specific privacy behavior and the remaining manual publication gates are managed separately from website implementation readiness.
