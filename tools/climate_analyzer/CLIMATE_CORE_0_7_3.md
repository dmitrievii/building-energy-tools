# Climate Analyzer 0.7.3 — GeoSphere parity closure

Status: implementation complete on Draft PR #67, retargeted to `main` after PR #66 was merged. Functional and provider-backed qualification is green on the current implementation baseline; the PR remains Draft while the final handoff/documentation and any remaining presentation-layer work are completed.

## Goal

Close scientifically supportable EPW ↔ GeoSphere functional gaps and consume the useful provider-native observations identified by the 0.7.2 live metadata census without pretending that unlike sources are identical.

A route is exposed only when its physical inputs exist or can be derived explicitly. Missing measured DNI, EPW sky-cover fields and EPW illuminance equivalents are never fabricated.

## Increment A — functional parity

Implemented and qualified:

- historical `Natural Ventilation` is exposed when measured temperature and relative humidity support psychrometrics;
- historical psychrometric properties are derived after canonical hourly normalization;
- historical heating/cooling degree metrics are available;
- `HVAC and Passive Design` is exposed for historical data with capability gates;
- solar-shading rows are shown only when usable measured GHI exists;
- design-day screening no longer assumes GHI;
- Natural Ventilation wind limits fail closed when wind is unavailable;
- `Wind during natural-ventilation hours` is available for historical measured wind.

## Increment B — Priority-A GeoSphere measurements

Implemented and provider-validated:

- `ffx` → `wind_gust_speed_m_s`: hourly maximum of complete 10-minute source intervals;
- `ddx` → `wind_gust_direction_deg`: direction paired with the governing `ffx`, never independently circular-averaged;
- `so` → `sunshine_duration_s`: measured source-interval sunshine duration, conserved by summation;
- `tlmin` → `dry_bulb_temperature_min_c`: true source extrema preserved by minimum;
- `tlmax` → `dry_bulb_temperature_max_c`: true source extrema preserved by maximum;
- exact matching live GeoSphere `<parameter>_flag` fields are requested and retained as native diagnostics.

Provider quality flags remain diagnostic metadata under `quality_flag__<provider_parameter>` and are excluded from physical canonical-hourly analysis variables. Climate Analyzer reports observed provider code distributions without inventing undocumented accept/reject semantics.

### Priority-A quantity semantics

- temperature minima: `min`;
- temperature maxima: `max`;
- sunshine duration: `sum`;
- gust speed: `max`;
- gust direction: direction paired with governing gust speed;
- equal gust maxima: deterministic earliest-source-timestamp tie break;
- incomplete native hours remain fail-closed under the canonical-hourly completeness policy.

## Increment D — Sky and Daylight closure

`Sky and Daylight` is source-capability based rather than EPW-only.

Shared/calculated analyses:

- astronomical daylight duration from date and latitude;
- monthly daylight summary.

GeoSphere-specific measured analyses when `so` exists:

- measured sunshine duration;
- relative sunshine duration = measured sunshine / calculated astronomical daylight, using only fully observed calendar days.

EPW-only sky/illuminance analyses remain available when their native EPW quantities exist. GeoSphere sunshine duration is **not** converted into sky cover, illuminance or DNI.

`so` is no longer classified as a solar-radiation quantity for navigation: it opens `Sky and Daylight`, while `Solar and Radiation` remains tied to actual radiation observations.

## Increment E — Ground Temperature

A new source-neutral `Ground Temperature` page is implemented.

### GeoSphere observations

The provider fields are mapped as measured ground temperatures:

- `tb10` → `ground_temperature_0_10m_c` at 0.10 m;
- `tb20` → `ground_temperature_0_20m_c` at 0.20 m;
- `tb50` → `ground_temperature_0_50m_c` at 0.50 m.

Their exact matching quality flags are retained as native diagnostics. Canonical hourly ground temperatures use arithmetic means over complete six-record 10-minute hours.

### Calculated profile

For EPW, and optionally alongside GeoSphere observations, Climate Analyzer calculates a deep periodic profile from outdoor dry-bulb temperature using the one-dimensional periodic semi-infinite-ground solution.

The annual air-temperature harmonic is fitted as mean + first sine/cosine harmonic. The ground model applies depth attenuation and phase shift and analytically integrates monthly mean temperature over each calendar month.

The calculated route requires at least 300 represented calendar days to avoid fitting an annual harmonic to a short seasonal window.

Default generic-soil inputs reproduce the supplied `Klimate.xlsx` reference calculation and are editable:

- thermal conductivity λ = 2 W/(m·K);
- density ρ = 2000 kg/m³;
- specific heat c = 1000 J/(kg·K).

The UI always distinguishes calculated ground temperature from measured GeoSphere ground temperature.

### Ground Temperature views

- monthly profiles versus depth;
- temperature through the year at a selected depth;
- measured shallow ground temperature;
- measured vs calculated validation;
- interactive January → December looping profile animation with Play/Pause and month slider;
- generated infinitely looping 12-frame GIF preview and download, with fixed axes and optional measured GeoSphere points.

The GIF is a pure presentation layer over the already calculated monthly profile; it does not change or repeat the scientific calculation.

### Workbook regression contract

The analytical monthly integration is frozen against the supplied reference workbook with exact regression points, including:

- January at 0.00 m: `-0.5337866745508535 °C`;
- July at 0.25 m: `20.710435720735227 °C`;
- October at 15.00 m: `10.409625038969944 °C`.

## Remaining GeoSphere fields

The live resource exposes 24 physical parameters. After D/E, **18/24 physical parameters are mapped** and **18/24 matching quality flags are consumed**.

The remaining six physical provider fields are intentionally not mapped:

- `ts`, `tsmin`, `tsmax`: air temperature at 5 cm, physically distinct from canonical 2 m outdoor dry-bulb temperature;
- `zeitx`: intra-interval timestamp of the maximum gust, auxiliary event metadata rather than an independent hourly climate quantity;
- `ff`: vector-mean 10 m wind speed; the application already uses provider arithmetic-mean `ffam` for scalar wind speed;
- `pred`: sea-level-reduced pressure; measured station pressure `p` remains the correct psychrometric input.

Their matching quality flags remain unconsumed because the corresponding physical fields are not mapped.

## Final page-parity boundary

Navigation now contains **14 pages**, including the new `Ground Temperature` page.

With all currently mapped GeoSphere observations present, historical mode exposes **13/14 pages**. The only navigation-level source gap is:

- `Compare Climates` — intentionally EPW-only in 0.7.3 because the existing comparison engine assumes EPW/typical-year comparison semantics.

A future source-neutral comparison stage must define historical-vs-typical-year alignment, unequal-period normalization, coverage handling and per-chart capability intersections before GeoSphere comparison is enabled.

## Scientific invariants

- measured and calculated quantities are labelled separately;
- GeoSphere provider-native observations remain intact for native diagnostics;
- ordinary cross-source analyses use the quantity-aware canonical hourly frame;
- missing provider observations are never converted to zero;
- provider quality flags remain diagnostics, not physical analysis variables;
- gust direction stays paired with the governing gust maximum;
- 5 cm air temperature is not substituted for 2 m outdoor air temperature;
- shallow measured ground temperature is not presented as a measured deep profile;
- sea-level-reduced pressure is not substituted for measured station pressure;
- sunshine duration is not used to fabricate DNI, sky cover or illuminance.

## Validation

Qualification on implementation head `f54ab3d318117eeee2fb12f279ce11982f99fb36`:

- Climate Analyzer CI #313 — **PASS**;
- GeoSphere Capability Census #38 — **PASS**;
- GeoSphere Priority-A Live Smoke #24 — **PASS**;
- GeoSphere Ground Temperature Live Smoke #7 — **PASS**.

Live capability census:

- 48 provider parameters total;
- 24 physical parameters + 24 matching quality flags;
- **18/24 physical parameters mapped**;
- **18/24 matching quality flags consumed**;
- unsupported physical parameters: `ff`, `pred`, `ts`, `tsmax`, `tsmin`, `zeitx`;
- GeoSphere pages with all mapped observations: **13/14**;
- only missing navigation page: `Compare Climates`.

Ground-temperature live proof passed on **Wien Hohe Warte, station ID 105**, **2026-07-15 → 2026-07-17**:

- `tb10`, `tb20`, `tb50`: 432/432 native 10-minute observations each;
- matching `tb10_flag`, `tb20_flag`, `tb50_flag`: 432/432 each;
- canonical hourly ground temperatures: 72/72 records each;
- independent source-to-hourly check reproduced arithmetic means for all three sensor depths.

PR #67 remains Draft and targets `main`. It is not merged. The GIF presentation layer is included after the D/E provider qualification and must pass the subsequent CI requalification before final review.