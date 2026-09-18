# Climate Analyzer 0.7.3 — GeoSphere parity closure

Status: implementation in progress; stacked on the qualified 0.7.2 audit PR.

## Goal

Close scientifically supportable EPW ↔ GeoSphere functional gaps and consume the useful provider-native observations identified by the 0.7.2 live metadata census before starting a new analysis family.

0.7.3 does **not** force unlike sources to become identical. A route is exposed only when its physical inputs exist or can be derived explicitly from measured inputs. Missing measured DNI, EPW sky-cover fields and EPW illuminance fields are not fabricated.

## Increment A — functional parity

Implemented and qualified:

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

Implemented on the 0.7.3 branch:

- `ffx` → `wind_gust_speed_m_s`: true provider 10-minute gust maximum; canonical hourly reduction uses the maximum of the six complete source intervals;
- `ddx` → `wind_gust_direction_deg`: direction remains paired with the source row containing the governing `ffx`; the hourly value is **not** an independent circular mean;
- `so` → `sunshine_duration_s`: measured source-interval sunshine duration; canonical hourly reduction conserves duration by summation;
- `tlmin` → `dry_bulb_temperature_min_c`: true source-interval 2 m minimum temperature; hourly reduction preserves the minimum;
- `tlmax` → `dry_bulb_temperature_max_c`: true source-interval 2 m maximum temperature; hourly reduction preserves the maximum;
- matching live GeoSphere `<parameter>_flag` fields are requested automatically when metadata exposes them with unit `code`.

Provider quality flags are retained only on the native diagnostic frame under `quality_flag__<provider_parameter>`. They are excluded from the canonical hourly physical-analysis frame and shown on Data Quality as raw provider-code distributions. No undocumented accept/reject meaning is assigned to a code.

The GeoSphere request estimator and batch planner include automatically requested quality flags, so long-range request size remains bounded using the actual number of provider fields transferred.

### Quantity semantics frozen by regression tests

- temperature minima: `min`;
- temperature maxima: `max`;
- sunshine duration: `sum`;
- gust speed: `max`;
- gust direction: direction paired with the governing gust-speed row;
- equal gust maxima: deterministic earliest-source-timestamp tie break;
- incomplete native hours remain fail-closed under the existing canonical-hourly completeness policy.

The historical UI now exposes true temperature extrema, gust speed/direction and sunshine duration when those measured fields are present. None of these additions fabricates DNI, sky cover or illuminance.

## Increment C — secondary provider measurements and comparison decision

Next within 0.7.3, disposition the remaining provider measurements from the live census:

- `tb10`, `tb20`, `tb50` — soil temperature at provider-defined depths;
- `ts`, `tsmin`, `tsmax` — ground/surface temperature family;
- `zeitx` — provider extreme-time auxiliary field;
- `ff` — vector-mean wind speed, to be retained only if it adds information beyond mapped arithmetic-mean `ffam`;
- `pred` — sea-level pressure, not a substitute for station pressure `p` in psychrometric calculations.

These fields do not block current EPW feature parity and must not be added merely to increase mapped-field count. Each requires an explicit use case, canonical semantics and UI destination.

`Compare Climates` also requires a separate decision: either make the comparison basket source-neutral for EPW and canonical historical datasets, or keep the page explicitly EPW-only. This decision must be explicit before 0.7.3 closes.

## Scientific invariants

- GeoSphere provider-native observations remain intact for native diagnostics and true source extrema.
- Ordinary cross-source analyses use the canonical hourly analysis frame.
- Psychrometrics are derived after quantity-aware hourly normalization.
- Missing provider observations are never converted to zero.
- Source-specific quality flags are diagnostic metadata, not physical analysis variables.
- Gust direction remains paired with its governing gust maximum.
- No measured DNI, sky-cover or illuminance value is invented from unavailable provider fields.

## Validation

Increment A passed the complete Climate Analyzer CI and live GeoSphere capability census on its qualified head.

Increment B focused qualification passes syntax plus regression tests for Priority-A mappings, quantity-aware hourly reduction, gust pairing, quality-flag retention, canonical-hourly behavior and the 0.7.2 parity audit. Full branch CI and the live metadata census are required again on the user-authored post-Increment-B head before Increment B is considered fully qualified.
