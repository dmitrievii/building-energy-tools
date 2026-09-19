# Climate Analyzer i18n foundation

## Scope

This work introduces a presentation-layer internationalization boundary without changing Climate Analyzer calculations, canonical climate data, provider adapters, routing IDs, chart semantics or scientific exports.

Supported locale families are:

- English (`en`) — default and deterministic fallback
- German (`de`)
- Spanish (`es`)
- Russian (`ru`)

Region variants resolve to the base language in this stage, for example `de-AT -> de` and `es-ES -> es`.

## Non-negotiable architecture contract

The following identifiers remain locale-neutral and must not be translated:

- `NAVIGATION_PAGES` internal page IDs;
- Streamlit routing/session-state identifiers other than the locale value itself;
- canonical DataFrame columns and variable IDs;
- provider parameter names and source identifiers;
- scientific model inputs/outputs and units;
- validation/reference IDs;
- export schema field names.

Translation occurs only at the presentation boundary. This prevents a language change from changing calculation routing or invalidating persisted scientific state.

## Runtime/performance contract

The i18n layer uses only Python dictionaries, string operations and the standard-library `ContextVar`. It introduces no Babel/gettext runtime dependency and imports no pandas, NumPy, Plotly, Streamlit or provider libraries. This is intentional because Climate Analyzer is deployed under constrained Streamlit Community Cloud resources.

## Stage 0.1 — translation foundation

- lightweight EN/DE/ES/RU catalog;
- region-tag normalization and deterministic English fallback;
- stable internal navigation IDs;
- localized navigation labels;
- exact backward-compatible English label contract;
- `app.py` unchanged.

## Stage 0.2 — shared language selector

The existing early `apply_queued_navigation` runtime hand-off now also binds one sidebar language selector. No Streamlit import is added to the i18n or UI-contract modules: the already-loaded app object is obtained only at the runtime boundary.

The selected locale is stored in Streamlit session state and copied into an execution-context `ContextVar`. This provides two important properties:

1. EPW and canonical/GeoSphere routes use the same locale automatically because both already call the same `navigation_label` formatter.
2. Concurrent user sessions do not share a mutable module-global language value.

`app.py` and the source-parity UI module remain unchanged in this stage. The visible effect is intentionally limited to the language selector and localized navigation labels. Headings, controls, explanations, chart labels and interpretation text will migrate progressively in later stages through the same presentation-only catalog.
