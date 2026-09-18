# Climate Analyzer 0.7.4.1 — Psychrometric Integration Remediation

## Purpose

This patch closes the psychrometric integration defects discovered after the 0.7.4 production merge. The previous selected-cell "Middle 90%" visualization is removed as a user-facing/statistical model for climate comparison.

## Climate-zone contract

- **Climate zones are continuous 2-D iso-density regions**, calculated in the actual displayed psychrometric coordinates (`T–d` or `i–d`).
- Observations are duration-weighted on a regular grid, smoothed deterministically with a NumPy Gaussian kernel, and the contour threshold is chosen by cumulative smooth density.
- `90%` therefore means: the smooth joint-density region containing at least 90% of represented physical duration.
- It is **not** an independent P05/P95 rectangle and **not** a union of selected 1 °C × 5% RH squares.
- Zone coverage is user-selectable from 50–99%.
- Default interior: **Density gradient** in the climate colour. Alternatives: Sparse points, Solid fill, Contour only.
- Optional dotted 50% core contour is available inside the main zone.

## Pressure contract

Psychrometric state coordinates retain the pressure used when that climate was derived. The common comparison RH grid has its own explicit **reference grid pressure** and is visual-only. Changing reference-grid pressure must not move climate observations or climate-zone density contours.

If an EPW station-pressure series is unavailable, that EPW falls back to pressure derived from **its own elevation**, never to the active/reference climate's pressure.

## Multi-year contract

Chronological multi-year psychrometric analysis exposes:

- All years combined
- Single year
- Compare selected years

Year comparisons use real source years on one fixed axis domain. Climate-zone representation is the default because it preserves distribution shape and temporal comparison without rendering tens of thousands of overlapping points.

## Compare Climates contract

The psychrometric comparison is one large shared diagram. Default representation is **Climate zones**, not small multiples, point clouds or square mosaics. Each climate has one colour, one outer contour and an optional density gradient/core contour. Axis limits are calculated once from all selected climates and remain fixed when switching representation.
