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

Implemented in the current branch; qualification runs from this documented head:

- Ground Temperature is nested inside **Temperature and extremes** while retaining dedicated `T(z,t)` views.
- The standalone Ground Temperature navigation page is removed.
- EPW and GeoSphere use the same capability-gated wind renderer.
- Mean wind and maximum gust share the variable explorer, direction distribution and wind-rose architecture; gust direction remains paired with the governing gust.

## C — UX cleanup

Implemented in C1/C2:

- Ground-temperature profile and animation views use one stable 12-month temperature domain and a wider fixed-height presentation.
- Chronological multi-year ground calculations preserve real years through an explicit year selector; Calendar profile fits one clearly labelled climatological annual harmonic across represented years.
- The selected-depth annual curve uses the same annual temperature range so seasonal damping with depth is visually comparable.
- Liquid-precipitation heat maps are anchored at 0 mm with white for dry intervals and progressively stronger blue toward the observed maximum.
- Precipitation duration/histogram/box/violin distributions default to **Wet intervals only**, with an explicit **All intervals including dry periods** option.
- Every Time Series and Overlay series has independent line colour, style, width and opacity while retaining the existing common time axis, resolution semantics and two-unit-family limit.

Still planned for C:

- Sky & Daylight consolidation and removal of duplicated analysis routes.
- Overview, humidity and natural-ventilation/HVAC duplicated-analysis cleanup.

## D — Psychrometric redesign

Planned:

- Chronological multi-year yearly climate envelopes.
- Frequency palette: low frequency pale blue, high frequency saturated blue.
- One common psychrometric comparison chart for all selected climates.
- Envelope extent selector: **All observations** or **Middle 90%**.
