# Climate Analyzer 0.7.3 — GeoSphere parity closure

Status: implementation in progress; stacked on the qualified 0.7.2 audit PR.

## Goal

Close scientifically supportable EPW ↔ GeoSphere functional gaps and consume the useful provider-native observations identified by the 0.7.2 live metadata census before starting a new analysis family.

0.7.3 does **not** force unlike sources to become identical. A route is exposed only when its physical inputs exist or can be derived explicitly from measured inputs. Missing measured DNI, EPW sky-cover fields and EPW illuminance fields are not fabricated.

## Increment A — functional parity

Implemented in the first 0.7.3 increment:

- historical `Natural Ventilation` is exposed when measured temperature and relative humidity are available;
- historical psychrometric properties are derived from the canonical hourly T/RH/pressure frame before natural-ventilation and HVAC calculations;
- historical hourly heating/cooling degree metrics are added after canonical hourly normalization;
- `HVAC and Passive Design` is exposed for historical data when T/RH support the required psychrometrics;
- passive-strategy solar shading is capability-gated: it is present only when usable measured GHI exists;
- design-day screening no longer assumes a GHI column;
- wind-speed limits on Natural Ventilation are disabled rather than failing when wind observations are unavailable;
- `Wind during natural-ventilation hours` is restored for historical measured wind when T/RH/wind inputs are present.

With a fully populated current GeoSphere adapter frame, the remaining page-level gaps after this increment are intentionally:

- `Sky and Daylight` — source/data gap under the current resource and canonical contract;
- `Compare Climates` — source-neutral comparison architecture is not yet implemented.

## Increment B — GeoSphere Priority-A measurements

Next within 0.7.3:

- `ffx` — native 10-minute maximum wind speed / gust;
- `ddx` — direction associated with the maximum gust;
- `so` — sunshine duration;
- `tlmin` / `tlmax` — true provider-native interval air-temperature extrema;
- relevant provider `*_flag` quality fields retained for native Data Quality.

These fields require quantity-correct semantics. In particular, gust direction must remain paired with the corresponding gust maximum; it must not be treated as an independent circular mean. Native extrema must not be replaced by extrema of hourly mean temperature.

## Increment C — secondary provider measurements and comparison decision

The audit also records `tb10`, `tb20`, `tb50`, `ts`, `tsmin`, `tsmax` and `zeitx` as building-relevant provider observations. They are retained on the 0.7.3 closure roadmap but do not block EPW feature parity.

`Compare Climates` requires a separate decision: either make the comparison basket source-neutral for EPW and canonical historical datasets, or keep the page explicitly EPW-only. This decision must be explicit before 0.7.3 closes.

## Scientific invariants

- GeoSphere provider-native observations remain intact for native diagnostics and true source extrema.
- Ordinary cross-source analyses use the canonical hourly analysis frame.
- Psychrometrics are derived after quantity-aware hourly normalization.
- Missing provider observations are never converted to zero.
- Source-specific quality flags are diagnostic metadata, not physical analysis variables.
- No measured DNI, sky-cover or illuminance value is invented from unavailable provider fields.

## Validation plan

0.7.3 must retain the complete Climate Analyzer CI, live GeoSphere capability census and provider-backed precipitation/snow smoke gates. Additional regression tests freeze historical page capability gating, psychrometric/degree-metric preparation and solar-strategy gating.
