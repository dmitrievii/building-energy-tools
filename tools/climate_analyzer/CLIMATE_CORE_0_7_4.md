# Climate Analyzer 0.7.4 / 0.7.4.1 — Temporal, source-neutral and psychrometric remediation

Status: 0.7.4.1 remediation on PR #69. Parent production baseline: Climate 0.7.4 (`main` merge `c0728c0771239fd8a77aa60bd2fdc55c254ae1e4`).

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

Implemented in the current branch:

- Ground Temperature is nested inside **Temperature and extremes** while retaining dedicated `T(z,t)` views.
- The standalone Ground Temperature navigation page is removed.
- EPW and GeoSphere use the same capability-gated wind renderer.
- Mean wind and maximum gust share the variable explorer, direction distribution and wind-rose architecture; gust direction remains paired with the governing gust.

## C — UX cleanup

Implemented and qualified in C1/C2/C3:

- Ground-temperature profile and animation views use one stable 12-month temperature domain and a wider fixed-height presentation.
- Chronological multi-year ground calculations preserve real years through an explicit year selector; Calendar profile fits one clearly labelled climatological annual harmonic across represented years.
- The selected-depth annual curve uses the same annual temperature range so seasonal damping with depth is visually comparable.
- Liquid-precipitation heat maps are anchored at 0 mm with white for dry intervals and progressively stronger blue toward the observed maximum.
- Precipitation duration/histogram/box/violin distributions default to **Wet intervals only**, with an explicit **All intervals including dry periods** option.
- Every Time Series and Overlay series has independent line colour, style, width and opacity while retaining the existing common time axis, resolution semantics and two-unit-family limit.
- Sky & Daylight uses one capability-gated quantity explorer for daylight, measured sunshine, relative sunshine, sky cover and illuminance; quantity-specific aggregation remains physical (duration sums versus state/intensity statistics).
- Overview no longer repeats the monthly temperature profile already available under Temperature.
- Humidity remains the canonical home for humidity-control threshold and enthalpy analyses; HVAC no longer duplicates those routes or the Temperature degree-metric route.
- Natural Ventilation removes the redundant Month × hour route because the canonical heat map already provides Month × Hour of day, and it follows the shared Chronological/Calendar-profile temporal contract.
- Passive-strategy annual and monthly views are consolidated under one HVAC analysis with a view selector.

## D — Psychrometric redesign — superseded by 0.7.4.1

The selected-cell 0.7.4 implementation is no longer the release contract. 0.7.4.1 replaces it with a continuous climate-zone representation:

- **Climate zone** is the default representation for single-climate and Compare Climates psychrometrics.
- The zone is calculated from a duration-weighted two-dimensional density field in the actual displayed `T–d` or `i–d` coordinates, smoothed deterministically with NumPy.
- The outer contour is an iso-density region containing at least the requested share of represented physical duration. Coverage is user-selectable from 50–99%, default 90%.
- The former 1 °C × 5 %RH selected-cell mosaic and its square-cell geometry are removed from the runtime contract.
- Zone interior can be shown as **Density gradient**, **Sparse points**, **Solid fill** or **Contour only**; an optional 50% core contour is available.
- Chronological multi-year analysis exposes **All years combined**, **Single year** and **Compare selected years**. Real source years remain explicit.
- Compare Climates uses one fixed shared axis domain for all selected climates.
- Climate-state coordinates retain each source's own pressure-derived psychrometric properties. **Reference psychrometric grid pressure** is a separate visual setting and cannot move the climate zones.
- If measured/station pressure is completely unavailable, EPW and GeoSphere fall back to standard-atmosphere pressure derived from that climate location's own elevation, not an unrelated global 101325 Pa default.
- A permanent **Climate Analyzer Psychrometric Integration** workflow guards the density-zone, year, shared-axis and pressure-separation contracts.

## E — Original 0.7.4 audit closure

0.7.4.1 re-audits the full original remediation scope rather than treating psychrometrics as an isolated hotfix. The retained closure contract is:

- A — chronological/calendar heat-map semantics, safe temperature colour domains, plain-language P05/P95 terminology, real-year degree-metric labels, 20 °C default KGT cooling limit, explicit frost/nighttime-hour terminology and interannual interpretations remain regression-protected.
- B — Ground Temperature remains nested under Temperature with stable annual axes and explicit chronological-year semantics; EPW and GeoSphere retain one capability-gated wind architecture.
- C — Overview temperature duplication remains removed; precipitation zero/wet-interval semantics, per-series Time Series styling, Sky & Daylight consolidation, Natural Ventilation route consolidation and HVAC/Humidity de-duplication remain regression-protected.
- **Wet-bulb temperature has one generic variable home: Temperature.** It remains available to psychrometric calculations/relationships but is no longer duplicated in the generic Humidity variable explorer.
- **Passive-strategy annual totals preserve real years.** In Chronological multi-year mode, `By year` is the default; `Selected-period summary` is an explicit opt-in pooled view.
- Compare Climates uses the 0.7.4.1 continuous climate-zone contract described above.

The release candidate must pass the full Climate Analyzer CI and the dedicated psychrometric integration gate on the same final head before PR #69 is marked Ready.
