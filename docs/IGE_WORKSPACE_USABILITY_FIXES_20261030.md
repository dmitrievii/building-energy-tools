# Climate workspace corrections — 30 October 2026

Base: main `b4647b232439faf8c04c86cadfde14962d2cb62f` (PR #121).
Scope: the existing Streamlit application, H1 → S1 → F1. No new fitting,
station-accuracy qualification, protected target observations or global validation.

## User-visible corrections

| Reported issue | Result and remaining scope |
| --- | --- |
| Automatic elevation with override | One bounded terrain metadata lookup per selected point. Copernicus DEM GLO-90 (2021), 90 m, via Open-Meteo. The original Graz response returned 363 m and is retained with URL, time and SHA256. Manual input overrides it; moving the point invalidates the previous height. A failed request remains missing and is not replaced by zero. A restore button retries explicitly. |
| Vertical-datum text field | Removed. Automatic/manual provenance is recorded internally. Neither a DEM height nor a manual entry establishes sensor-height or datum equivalence. |
| Explore opens a separate simplified viewer | Corrected in the public router. Generated years use the existing Overview, Temperature, Humidity/Psychrometrics, Solar, Wind, Sky, Precipitation, Time Series, Natural Ventilation, HVAC and Data Quality panels. The old experimental viewer is retained for historical reproducibility, with no public router call. |
| Invisible interpolation sources | Uploaded EPW headers have a candidate preview; GeoSphere station locations can be loaded without weather acquisition. Completed admission supplies actual donor coordinates, names, IDs, eligibility and selection. Violet markers and connecting lines identify selected sources; grey identifies other candidates. Annual eligibility still requires the existing full-year checks. |
| Unclear grid source | The map identifies the point actually returned by Open-Meteo. The source section explains ERA5-derived data, approximate 0.25° delivery grid, provider height, absence of local height correction and the separate NASA POWER longwave chain. No native-cell boundary is invented. |
| Different future location interface | The same OSM/Leaflet map, 620 px height and 2:1 map/selection layout are used. The future map follows the selected base and retains its station/grid provenance. For B0 the requested NASA-signal point and the returned EPW grid point remain distinct. A future base cannot be relocated by editing its label. |
| Two SSPs only | The software allowlist now permits the four NEX Tier-1 pathways SSP126, SSP245, SSP370 and SSP585 for the existing CanESM5 member. Labels and help explain emissions pathways and approximate 2100 forcing, not temperature or probability. Every original response must still pass the same location, version, unit, calendar, variable-operator and complete-census checks. The retained complete original-source replay is SSP245; it does not qualify the other scenarios. SSP119 and other GCMs remain outside this contract. |
| Raw F1 saturation error | Known B0 0.1 K source-quantisation contradictions have a bounded, journalled admission described below. Unknown/large contradictions still block export with a readable explanation. The exact user's failed packet was not supplied, so its cause is not claimed as verified. |
| Unclear Historical year | Explicitly a real calendar year of ERA5 reanalysis delivered by Open-Meteo, with NASA POWER downwelling longwave. This is neither a measured station year nor a TMY. The 2002–2025 range is a source-request policy; missing required data block export. |
| Different Find-climate template | The source routes share the existing Leaflet/OSM, map-left / selection-right visual pattern and station-marker colours. Source semantics remain distinct: a catalog selects a file, historical selection requests a point, future selection chooses an admitted base. |

## Canonical panels without changing humidity definitions

Re-importing generated EPW bytes through the typical-year parser would change
calendar handling and implicitly apply the legacy ASHRAE water/ice convention.
The new display adapter instead validates the original engine dataset, retains
all source values and timestamps, and adds calendar helpers and engineering
derived columns for the existing panels. Optional snow, illuminance, opaque
cloud and wet-bulb fields stay missing.

The established psychrometric chart builders receive a context-local water
convention. Points, RH construction curves, RH-bin geometry, Givoni boundaries
and contour masks therefore use compatible definitions. Original EPW/GeoSphere
charts keep their existing ASHRAE default. Context is restored after each chart;
no shared mutable process-wide water setting is introduced.

For each source point:

\[
e_h=e(q_h,p_h),\qquad w_h=\frac{q_h}{1-q_h},\qquad
h_h=1.006T_h+w_h(2501+1.86T_h).
\]

Guides and RH-bin coordinates use the year's median pressure, while points keep
their original hourly moisture and pressure. For source-water contours, the
physical envelope uses the minimum source pressure, preventing valid hourly
states at lower pressure from being rejected by a median-pressure boundary.
Wet-bulb guides are withheld for these source-water contracts. Display changes
do not modify exported EPWs or qualify pressure accuracy.

## Bounded B0 quantisation admission

The existing historical bounds screen admits independently quantised T/Td/RH
when their rounding intervals are compatible. F1 previously imposed strict
`Td <= T` on their rounded centre values. This can reject a centre-value
dew-point excess despite the historical source having passed admission.

The additional policy is restricted to the known B0 background/reference route,
dew-point vapour authority and the existing Murphy–Koop liquid-water transfer.
It requires T and Td on the documented 0.1 K lattice and
`0 < Td - T <= 0.100001 K`. At unchanged source T and pressure:

\[
e^*=\arg\min_{0\leq e\leq e_s(T)}(e-e_{\rm source})^2
   =\min(e_{\rm source},e_s(T)).
\]

This is a conditional derived-vapour projection, not recovery of the unknown
unrounded observation. Original T, Td, RH and EPW bytes are retained. Each
affected UTC hour records original T/Td/RH, original/admitted vapour and its
change. Reference-year logs are included in diagnostics.reference.years; base
logs in base.source_rounding_admission. Future output displays correction counts.
The policy is not offered as a general repair for uploaded EPWs, station
observations, larger excesses or non-quantised inconsistencies. Existing monthly
q targets, closure checks, NASA definitions and no-fabricated-year guards remain.

The disclosed original Graz reference years 2002–2014 had zero `Td > T` hours.
Thus this is not claimed as a reproduction of the user's unspecified failure.
Positive and negative synthetic controls exercise the formerly failing branch;
the original annual files remain regression examples, not fitting targets.

## Verification and reproducibility

- Pinned Python 3.12 dependencies from requirements.txt; no dependency upgrades.
- New tests cover terrain failure/override/point changes, source geometry,
  source immutability, bounded projection and negative cases, all four SSP
  request identities, the public Explore route and the three psychrometric
  representations. Existing scientific/temporal regression controls remain.
- The local browser runs the actual app, actual S1/F1 solvers and original
  source admissions, replacing only source acquisition with retained original
  packets. Terrain replay uses the original Graz API response. It checks
  desktop/mobile controls and ten real HTTP downloads.
- Download verification checks complete 8760-hour S1/F1 EPWs, every F1 ZIP
  member hash, CSV state closure, unchanged original research inputs and H1's
  correct refusal of its incomplete original year.
- Local map raster tiles do not load in the isolated software-test renderer.
  Those screenshots establish layout/widget behaviour, not map-tile acceptance.
  Actual map rendering requires the separate public-browser observation.

```bash
PYTHONPATH=tools/climate_analyzer:research/ige_cmip6:tools/climate_analyzer/tests \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python -m unittest discover -s tools/climate_analyzer/tests -p 'test_*.py' -v

python deployment/run_ige_workspace_browser_acceptance.py \
  --out /absolute/path/to/evidence --chrome-path /absolute/path/to/chromium
```

The release uses a new source-hash manifest. The previous F1 manifest and
research results are preserved. CI success, conditional physical admissibility,
independent accuracy and production readiness remain separate. No new
independent accuracy or production qualification is asserted by this revision.

Final local acceptance: **772/772 regression tests PASS** in 324.357 s; nine final map-state checks PASS; ten actual browser downloads verified. S1 EPW SHA256 `855515517eb22601f5f4e6025a32ff463fc81b8055aa08168ff48442565138d2` and F1 EPW SHA256 `3c49a8dabb7c2d0f49f784aa417113e5c9f83b9b4e5b68ed3073f08d275bac2a` are unchanged. The candidate is prepared for review; public deployment has not been changed by this acceptance.
