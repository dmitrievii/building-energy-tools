# R2.18 semantic colour qualification

Physical variables use chart_theme.METRIC_COLORS and metric_colorscale. Named
categories use SKY_CONDITION_COLORS, PASSIVE_STRATEGY_COLORS, EXPOSURE_COLORS,
RAIN_DAY_COLORS and the previously established rejection-reason registry.
Climate and month identities remain independent of physical quantity. A
directional plot's radial magnitude and colour variable are independent;
the dedicated rain-exposure view encodes its existing sector sum in both
channels, whereas explicit wind-speed colour uses the wind palette.

No blanket post-render recolouring is performed. Palette qualification
inspects actual Plotly trace properties, shared colour axes and report clones.
The audit CSV distinguishes explicit matching signatures, missing assignments,
cross-surface/print differences, unavailable routes and rendering errors.
Trace names are included in the signature, so presentation-only differences
may require review. This is diagnostic evidence, not a claim that all cases
pass. Run with --require-complete for strict admission after discrepancies
have been adjudicated.

The dominant passive strategy calendar uses categorical modal selection
rather than averaging strategy codes. Missing and tied cells remain blank.
All original per-observation strategy thresholds and priorities are retained.
The sky-cover summary merges the separate zero class into Clear (0–2 tenths);
detailed occurrence charts retain their original individual classes.
