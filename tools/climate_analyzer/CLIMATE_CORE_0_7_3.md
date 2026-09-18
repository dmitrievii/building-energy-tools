# Climate Analyzer 0.7.3 — GeoSphere parity closure

Status: implementation and qualification complete in the current stacked scope; awaiting the explicit #66 → #67 merge/retarget sequence and requalification after retargeting.

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

## Increment B — GeoSphere Priority-A measurements

Implemented and provider-validated:

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

The historical UI exposes true temperature extrema, gust speed/direction and sunshine duration when those measured fields are present. None of these additions fabricates DNI, sky cover or illuminance.

### Live provider proof

A permanent provider-backed Priority-A smoke now uses the production GeoSphere adapter against live `klima-v2-10min` data. The first qualified run passed on station **Wien Hohe Warte (ID 105)** for **2026-07-15 → 2026-07-16**:

- 288/288 native records for `tlmin`, `tlmax` and `so`;
- 284 numeric native gust-speed records and 283 gust-direction records;
- all five matching quality flags present for all 288 native timestamps;
- strict hourly output retained 48 temperature-extrema/sunshine records, 47 gust-speed records and 46 paired gust-direction records;
- source-to-hourly checks independently reproduced `min`, `max`, `sum` and paired-gust-direction semantics.

The smoke is scheduled and also runs when its adapter/scientific contract changes.

## Increment C — explicit disposition of remaining source differences

The remaining live physical GeoSphere fields are deliberately **not mapped in 0.7.3** unless they have a current Climate Analyzer use case and a defensible cross-source semantic contract:

- `tb10`, `tb20`, `tb50` — soil temperatures at 10/20/50 cm depth. Useful for a future ground/soil analysis family, but not an EPW hourly-parity field and currently without a UI destination;
- `ts`, `tsmin`, `tsmax` — 5 cm air-temperature observations/extrema. They are physically distinct from the canonical 2 m outdoor air temperature and therefore must not be substituted for it;
- `zeitx` — time of the maximum gust inside the provider interval. It is auxiliary event metadata associated with `ffx`, not an independent hourly climate quantity; the current hourly route already preserves the governing gust and its `ddx` direction;
- `ff` — vector-mean 10 m wind speed. The application already maps the provider arithmetic 10-minute mean `ffam`; adding `ff` under the same generic wind-speed concept would create ambiguous duplicate semantics;
- `pred` — sea-level-reduced pressure. It is not substituted for measured station pressure `p`, which remains the pressure used for psychrometric calculations.

Their matching quality flags are likewise left unconsumed because the corresponding physical fields are not mapped. The live census therefore closes 0.7.3 at **15/24 mapped physical parameters and 15/24 consumed matching quality flags**, with the remaining 9/24 explicitly dispositioned rather than silently ignored.

### Sky and Daylight

`Sky and Daylight` remains unavailable for GeoSphere historical mode in 0.7.3. The live resource does not supply the EPW sky-cover or illuminance quantities used by that page. Measured sunshine duration `so` enriches the Solar route but is **not** converted into invented sky cover, illuminance or DNI.

### Compare Climates

`Compare Climates` remains **explicitly EPW-only in 0.7.3**. The existing comparison engine assumes comparable EPW hourly/typical-year datasets and exposes metrics that can depend on EPW-only solar fields. Treating an arbitrary multi-year historical GeoSphere interval as interchangeable with an EPW typical year would introduce ambiguous calendar weighting and capability semantics.

A future source-neutral comparison stage may compare canonical datasets, but it must first define:

- real historical period alignment versus typical-year alignment;
- variable-intersection/capability gating per comparison chart;
- extensive-quantity normalization for unequal periods;
- handling of missing physical hours and unequal coverage;
- source-specific metrics that have no defensible common basis.

Keeping this page EPW-only is therefore an explicit scientific/product boundary, not an unimplemented silent fallback.

## Final parity boundary

With every currently mapped GeoSphere observation present, Climate Analyzer exposes **11 of 13** EPW navigation pages. The two non-shared pages are intentionally explained source-contract differences:

1. `Sky and Daylight` — unavailable source quantities;
2. `Compare Climates` — intentionally EPW-only comparison semantics in 0.7.3.

All other previously identified implementation gaps are closed.

## Scientific invariants

- GeoSphere provider-native observations remain intact for native diagnostics and true source extrema.
- Ordinary cross-source analyses use the canonical hourly analysis frame.
- Psychrometrics are derived after quantity-aware hourly normalization.
- Missing provider observations are never converted to zero.
- Source-specific quality flags are diagnostic metadata, not physical analysis variables.
- Gust direction remains paired with its governing gust maximum.
- 5 cm or soil temperatures are not substituted for 2 m dry-bulb temperature.
- sea-level-reduced pressure is not substituted for measured station pressure.
- No measured DNI, sky-cover or illuminance value is invented from unavailable provider fields.

## Validation

0.7.3 qualification includes:

- complete Climate Analyzer CI: compilation, scientific reference register, station-catalog provenance, deployment contract, security/scientific regression suite, module import and Streamlit health;
- live GeoSphere capability census;
- provider-backed Priority-A live smoke;
- regression coverage for historical page gating, psychrometric/degree-metric preparation, GHI-dependent passive-strategy behavior, Priority-A mappings, quantity-aware hourly reduction, gust pairing, flag retention and explicit final source-parity boundaries.

The live census after Increment B reports:

- 48 provider parameters total;
- 24 physical parameters and 24 matching quality flags;
- 15/24 physical parameters mapped;
- 15/24 matching quality flags consumed for mapped parameters;
- zero remaining Priority-A unmapped fields;
- exactly two intentional page differences: `Sky and Daylight` and `Compare Climates`.

PR #67 remains Draft and stacked on the 0.7.2 audit until an explicit merge sequence is approved.
