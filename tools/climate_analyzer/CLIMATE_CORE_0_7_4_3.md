# Climate Analyzer 0.7.4.3 — Psychrometric representation restoration

## Purpose

This hotfix restores the original psychrometric distribution-grid representation as a peer visualization instead of replacing it with the new smooth climate-contour representation.

## Representation contract

The Psychrometric Diagram exposes three independent representations:

1. **Points** — individual source observations.
2. **Distribution grid** — the pre-existing 1 °C × 5 %RH cell representation, using the original tile-occupancy renderer.
3. **Climate contour** — smooth duration-weighted joint-density contours.

The contour representation is additive; it does not replace Points or Distribution grid.

## Contour coverage contract

- The outer contour coverage remains user-selectable.
- Additional nested contour levels are optional and user-selectable at 1 percentage-point resolution below the outer coverage.
- No 50 % contour is mandatory or implicitly special. The UI starts with no additional nested contour selected; users may select 50 %, 70 %, both, or other valid levels.

## Physical-domain contract

Gaussian smoothing is performed numerically on a rectangular grid, but the resulting density is clipped to the physically valid psychrometric domain before coverage thresholds are evaluated. Density outside `0 <= RH <= 100 %` is removed and the remaining physical density is renormalized to represented duration.

For Plotly rendering, physically impossible cells are represented as `NaN` rather than zero. This prevents contour interpolation from crossing beyond the 100 % RH saturation boundary.

## Compare Climates reference-pressure contract

A comparison psychrometric diagram must use one coordinate system. The selected **Reference psychrometric pressure** therefore applies to all display geometry:

- RH construction curves, including the 100 % saturation curve;
- Points;
- Distribution-grid cells;
- Climate contours.

Source climate data and their station pressures are not modified. For display only, dry-bulb temperature and relative humidity are retained and humidity ratio / moist-air enthalpy are recomputed at the selected common reference pressure. This prevents physically inconsistent overlays when climates originate at different elevations or station pressures.

## Validation

The focused 0.7.4.3 workflow validates:

- restored Distribution grid routing;
- arbitrary simultaneous nested contour levels;
- zero numerical density outside the saturation domain;
- `NaN` rendering outside the saturation boundary;
- identical T/RH states from different source pressures overlaying at one common display pressure;
- preservation of the original source humidity-ratio series;
- compatibility with the existing psychrometric runtime guard and prior psychrometric regression suite.

Focused workflow run `35433064501` completed successfully before this qualification commit. Full repository CI must also pass before the hotfix is considered merge-ready.
