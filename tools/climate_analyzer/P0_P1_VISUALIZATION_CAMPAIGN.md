# P0 + P1 — Presentation and Universal Climate Visualization

## Scope / admission
P0: shared Plotly presentation options (title, legend, native grid, line thickness, PNG/SVG, exact matching numeric axis range, compass polar rotation). Existing background remains global; compass rotation does not rotate the physical azimuth values. The underlying data are unchanged. SVG may contain embedded raster layers for WebGL. Native GIF retains the earlier binary transparency support; controls specifically involving Plotly axes/grid/export are not applied to that separately rendered GIF.

P1: Overview climograph / Walter–Lieth core diagram / temperature–precipitation loop; generic explorer typical daily profiles (overlay / small multiples, centre and variability band) and occurrence classes; duration curve frequency representation; daily temperature amplitude; ground heatmap; geometric sunrise/sunset envelope; observed sky condition distribution; measured sunshine month–hour heatmap; multi-panel meteogram for native and monthly sources.

## Scientific contracts
- Complete real calendar hours/days for hourly profiles and day classifications; gaps are never zero-filled. Days may have 23 or 25 physical hours in local civil time. Source duration weighting remains independent of gaps. Circular directions are excluded from linear profile/class analytics.
- Calendar month/hour profiles intentionally pool equivalent months and hours; chronological occurrence series keep year-months distinct. Calendar-profile occurrence series average individual year-month counts or percentages.
- Paired temperature–precipitation summary uses complete year-month intervals or valid published monthly totals, equally averaging corresponding complete year-months; no inference of unavailable precipitation. The core Walter–Lieth graphical scaling is 2 mm/°C through 100 mm and 20 mm/°C thereafter. The monthly dry condition P < 2T is empirical, not a water balance. Reference: https://search.r-project.org/CRAN/refmans/climatol/html/diagwl.html . Frost bars and station metadata of a full traditional atlas sheet are not included.
- Solar-time envelope uses the existing geometric daylight duration model. It is not a civil-clock sunrise/sunset prediction and does not account for terrain/refraction.
- Meteogram reuses the canonical overlay engine separately for every series; no new resampling policy.
- Native monthly source capability gates exclude hourly/daily classification rather than inventing samples.
- P2 and later packages are not included.

## Qualification
New regression tests exercise physical-hour sums, missing months, class closure, graphic equivalence, scale transformation and physically meaningful export, native monthly gating, and meteogram unit independence. Full CI, source and browser campaigns are mandatory before declaring production qualification.
