# Climate Analyzer i18n foundation 0.1

## Scope

This stage introduces a presentation-layer internationalization boundary without changing Climate Analyzer calculations, canonical climate data, provider adapters, routing IDs, chart semantics or the visual shell.

Supported locale families are:

- English (`en`) — default and deterministic fallback
- German (`de`)
- Spanish (`es`)
- Russian (`ru`)

Region variants resolve to the base language in this stage, for example `de-AT -> de` and `es-ES -> es`.

## Non-negotiable architecture contract

The following identifiers remain locale-neutral and must not be translated:

- `NAVIGATION_PAGES` internal page IDs;
- Streamlit/session-state keys;
- canonical DataFrame columns and variable IDs;
- provider parameter names and source identifiers;
- scientific model inputs/outputs and units;
- validation/reference IDs;
- export schema field names.

Translation occurs only at the presentation boundary. This prevents a language change from changing calculation routing or invalidating persisted state.

## Runtime/performance contract

The i18n layer uses only Python dictionaries and string operations. It introduces no Babel/gettext runtime dependency and imports no pandas, NumPy, Plotly, Streamlit or provider libraries. This is intentional because Climate Analyzer is deployed under constrained Streamlit Community Cloud resources.

## Stage 0.1 integration

This first stage localizes the stable navigation label contract while keeping the existing English output exactly backward compatible. The application itself does not yet expose a language selector; `app.py` is unchanged.

A later UI integration stage may add a locale selector and progressively move headings, controls, explanatory text, chart labels and interpretations into translation catalogs. That stage must preserve the same internal identifiers and scientific regression surface.
