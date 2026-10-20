# IGE P9.3B2D — Preregistered German source-only pressure availability census

Date: 2026-10-20. Parent P9.3B2C `b793d2f0846a1efcfc3b621e36cc02127a41bfa0`.
**Pre-registered before reading any of the new German 2023 pressure values or running pressure-error comparisons.**
Only AT/DE/CH relevant; German candidate selection independent of model residuals.

## Source qualification before freezing an independent measurement holdout

Official DWD CDC historical hourly pressure original archive:
`https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/`.
Original per-station `stundenwerte_P0_<id>_<start>_<end>_hist.zip`, CSV
`produkt_p0_stunde_*`, field `P` measured absolute station-level pressure (hPa).
`P0` sea-level reduced pressure is prohibited as a substitute; no pressure may be
reverse-solved from RH, ERA5, or model estimates.
Check the original DWD station metadata and selected archive's field structure, true
finite P counts, source QN_8 (=10 final; =3 automatic); record listing/ZIP SHA and
rows per 168-hour window **only**. Never emit raw hourly P or any model error during census.

Fixed January 10–16 and July 10–16 **2023 UTC** windows, exactly 168 hours each,
and same-year source-original historical station coordinates/elevation.
Preset candidates, in immutable order within geographical strata:
- LOWLAND: `01420` Frankfurt/Main, fallback `03015` Lindenberg.
- SOUTHWEST: `01443` Freiburg, fallback `05440` Weißenburg-Emetzheim.
- ALPINE_APPROACH: `02559` Kempten, fallback `01550` Garmisch-Partenkirchen.

This rank is **based on prior known station metadata and spatial coverage only**.
Do not inspect past or current P-model station errors to select a candidate.
One first eligible station per stratum, max 3 total. Threshold: at least 144 unique
valid true-P UTC hours in **each** seven-day window (from QN_8=10 or QN_8=3).
QC10 and QC3 are always reported separately; if QC10 insufficient, QC3 may qualify
only with explicit AUTOMATIC_ONLY label, never described as final quality.
Never merge QC3 into QC10 in the analysis. Report rejected/absent alternatives too.
If a stratum lacks eligible candidate, report SOURCE_BLOCKED instead of inventing values.
Potsdam 03987 and Oberstdorf 03730 are *excluded*: their original 2023/2024
station P sources already produced missing-only negative results.
All original source metadata/ZIP SHA, UTC support, missingness and row count must be pinned.

**Holdout definition is to be frozen in a separate later commit** immediately after
source-only census outputs, before loading any actual German P values into a scoring
procedure. Then evaluate predeclared B0 vs B4 (ARCO surface geopotential height and
hypsometric correction), and B3 provider-height sensitivity; use original
ERA5 hour, grid, and original site altitude with no residual-based fitting.

Existing AT GeoSphere Graz, CH SwissMetNet Davos 2024 values are already-seen
retrospective comparisons ONLY. German 2023 is the sole newly held-out pressure
skill cohort. Nonstation CanESM5 future pressure skill remains unresolved.
Production EPW remains blocked independently of this pressure-source audit.
