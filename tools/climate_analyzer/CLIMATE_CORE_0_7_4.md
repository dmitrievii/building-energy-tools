# Climate Analyzer 0.7.4 — Temporal and source-neutral UX remediation

Status: Draft implementation branch. Parent production baseline: Climate 0.7.3 (`main` merge `88b0f0138e2942f37ff3432acf4508fe3e51c5e6`).

## Core architecture contract

Climate source determines **availability, provenance, cadence and quality metadata**, not the visualization architecture. When EPW and GeoSphere provide the same canonical physical quantity, Climate Analyzer should expose the same compatible analysis and visualization set.

## A — Temporal semantics

Implemented in the current branch:

- **Chronological** means real source time stays sequential across years. Heat maps therefore use real `YYYY-MM-DD`, `YYYY-Www` or `YYYY-MM` period coordinates instead of folding several source years into one calendar year.
- **Calendar profile** is the explicit climatological alignment mode. Equivalent calendar days/weeks/months may be combined across years there.
- Interannual heat-map comparison uses real integer year labels only.
- Temperature heat-map colour thresholds are valid for all-cold, all-neutral, all-hot and mixed domains; selecting Minimum/Maximum must never produce an invalid Plotly colorscale.
- `P05` and `P95` remain the machine/statistical identifiers, but user-facing terminology is plain language:
  - **Lower 5% boundary (P05):** only about 5% of contributing values are lower; about 95% are higher.
  - **Upper 5% boundary (P95):** only about 5% of contributing values are higher; about 95% are lower.
  - **Middle 90% range:** the interval between P05 and P95; roughly 5% of observations are below it and 5% above it.
- Chronological degree-metric labels preserve real years instead of collapsing repeated months/weeks/days onto one calendar label.
- Default Cooling limit for KGT is 20 °C.
- Temperature threshold terminology distinguishes frost hours from the existing nighttime-hour proxy.
- Automatic interpretation for chronological multi-year continuous variables reports interannual annual-mean evolution rather than presenting only one pooled statistic.

## B — Source-neutral UI consolidation

Planned next on this same Draft PR:

- Move Ground Temperature into **Temperature and extremes** while preserving its dedicated `T(z,t)` views rather than pretending it is an ordinary scalar variable.
- Remove source-specific visualization divergence for canonical variables.
- Consolidate mean wind and maximum gust around one wind-analysis architecture, including the existing direction/circular analyses and wind roses.

## C — UX cleanup

Planned:

- Ground-temperature layout/range improvements and explicit multi-year semantics.
- Precipitation zero-aware heat-map and distribution treatment.
- Per-series Time Series and Overlay styling.
- Sky & Daylight consolidation and removal of duplicated analysis routes.
- Natural-ventilation/HVAC duplicated-analysis cleanup.

## D — Psychrometric redesign

Planned:

- Chronological multi-year yearly climate envelopes.
- Frequency palette: low frequency pale blue, high frequency saturated blue.
- One common psychrometric comparison chart for all selected climates.
- Envelope extent selector: **All observations** or **Middle 90%**.
