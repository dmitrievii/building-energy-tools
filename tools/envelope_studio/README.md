# Building Envelope Studio

Browser-first U-value and interstitial-condensation tool for Building Energy Tools.

## Target calculation modes

1. **Monthly normative mode** — monthly boundary conditions, steady heat transfer and vapour diffusion, period-by-period condensate accumulation/drying. The final normative policy will be locked against the Austrian reference method before release.
2. **Quasi-hourly EPW mode** — EPW outdoor temperature/RH evaluated hour by hour with a user-selected indoor-climate model. This is a sequence of steady states with condensate mass carried between hours; it is explicitly **not** a transient hygrothermal EN 15026/WUFI-type simulation.

## Calculation-core status

Implemented in the initial branch:

- saturation vapour pressure / vapour pressure;
- layer thermal resistance and U-value;
- temperature/interface states;
- stateful Glaser solver using a convex-minorant pressure profile;
- condensate carry-over and drying between periods;
- EPW parser and monthly aggregation;
- regression tests based on the current `Glaser_AT.xlsx` reference wall.

The existing spreadsheet is treated as a validation oracle, not copied blindly: its current moisture model is explicitly a single-condensation-plane teaching model and its annual sheet reuses one critical plane. The web engine is being generalized so the active condensation plane(s) can change between periods.

## Material library

The supplied `built-in-material-library.json` is the seed catalogue. Current inventory: 341 records across 26 categories. Thermal properties are complete; vapour-diffusion data are incomplete for a substantial subset, so moisture calculations must fail closed or require an explicit user value when no `mu`/`sd` value is available.

The application will keep calculation provenance internally. Third-party databases may be used as UX/validation references, but proprietary datasets are not copied wholesale or relabelled as original data.

## Release path

The intended public path is:

`/building-energy-tools/tools/building-envelope-studio/`

The GitHub Pages workflow will be extended only after the static UI, material runtime catalogue and browser tests are present.
