# Climate Analyzer 0.7.2 — EPW ↔ GeoSphere parity and provider-data audit

Status: audit in progress; no new analysis feature stage may start until the findings below are dispositioned.

## Purpose

This stage answers two separate questions:

1. Which user-facing analyses available for EPW are also available for a fully populated GeoSphere `klima-v2-10min` interval?
2. Which live GeoSphere parameters are currently consumed by the adapter, and which useful provider measurements are being left unused?

The audit deliberately distinguishes **scientific impossibility/source mismatch** from **implementation gap**. GeoSphere historical observations must not be forced to imitate EPW where the provider does not measure the required quantity.

## Current page-level parity

EPW exposes 13 navigation pages. With all currently mapped GeoSphere variables present, historical mode exposes 9 pages including the source page. The current gap is four pages.

| EPW page | GeoSphere current status | Audit classification |
|---|---|---|
| Climate File Source | Available | parity |
| Overview | Available | parity |
| Temperature | Available when `tl` has numeric observations | parity |
| Humidity and Psychrometrics | Available when `tl + rf` are present; psychrometrics derived after hourly normalization | parity |
| Solar and Radiation | **Partial** | source/data gap: GeoSphere maps measured GHI/DHI but no measured DNI; EPW façade/POA and DNI-dependent routes are therefore intentionally unavailable |
| Wind and Ventilation | **Partial** | implementation gap: measured wind analyses exist, but the EPW `Wind during natural-ventilation hours` route is not exposed in historical mode |
| Sky and Daylight | Unavailable | source + adapter gap: current GeoSphere adapter maps neither EPW sky-cover/illuminance equivalents nor provider sunshine duration `so` |
| Precipitation and Snow | Available and richer for measured historical data | parity / GeoSphere-specific enhancement |
| Time Series and Overlay | Available | parity |
| Natural Ventilation | **Unavailable** | **implementation gap**: current mapped `tl + rf` are sufficient for the base psychrometric suitability calculation and `ffam` can optionally provide wind limits |
| HVAC and Passive Design | **Unavailable** | **implementation gap with capability gating required**: most routes can use `tl + rf + p`; solar-dependent routes must be conditional on measured GHI |
| Compare Climates | Unavailable | architecture gap: the comparison basket and `ClimateDataset` loader are explicitly EPW-payload based |
| Data Quality | Available, but incomplete | provider-data gap: provider `*_flag` quality information is not consumed |

Therefore **EPW↔GeoSphere parity is not currently complete**. The next remediation should close the implementation gaps that are scientifically supported, while keeping source-specific routes unavailable where the underlying measurement does not exist.

## Current GeoSphere adapter boundary

The production `klima-v2-10min` adapter currently consumes these physical provider fields:

- `tl` — 2 m air temperature;
- `rf` — relative humidity;
- `p` — station pressure;
- `ffam` — arithmetic-mean 10 m wind speed;
- `dd` — wind direction;
- `rr` — precipitation depth;
- `rrm` — independently measured/calculated precipitation duration;
- `sh` — snow depth;
- `cglo` — global horizontal radiation;
- `chim` — diffuse horizontal radiation.

This is not the complete physical parameter set published by the resource.

## User-relevant live provider fields currently omitted

### Priority A — should be integrated before a new feature stage

- `ffx` — maximum wind speed / gust: directly useful for façade, comfort and extreme-wind analysis;
- `ddx` — wind direction associated with the maximum gust;
- `so` — sunshine duration: directly useful for solar/daylight/climate characterization and is explicitly exposed as station metadata by GeoSphere;
- `tlmin` / `tlmax` — true source-interval minimum/maximum 2 m air temperatures: useful for measured extremes and avoids deriving sub-hour extrema from hourly means;
- quality flags (`*_flag`) for loaded quantities: required to expose the provider's own quality status instead of reporting only timestamp/value coverage.

### Priority B — building-relevant, but can be a separate source-extension increment

- `tb10`, `tb20`, `tb50` — soil temperature at 10/20/50 cm depth;
- `ts`, `tsmin`, `tsmax` — 5 cm air-temperature state/extrema;
- `zeitx` — time of maximum gust within the reported interval.

These are meaningful for ground/frost/microclimate/extreme analysis, but they have no direct EPW page equivalent today. They should not block restoring EPW feature parity, but should be explicitly retained on the provider roadmap rather than silently ignored.

### Lower priority / redundant for current calculations

- `ff` — vector-mean wind speed; the application already uses `ffam` as scalar wind-speed magnitude;
- `pred` — sea-level-reduced pressure; building psychrometrics correctly use measured station pressure `p`, not reduced sea-level pressure.

## Quality flags

GeoSphere v2 publishes parameter-specific quality flags and code lists. The current adapter does not request or retain these flags. That means `Data Quality` currently reports structural coverage and missingness, but cannot distinguish provider statuses such as automatically/manually checked, original or changed observations.

This is a real data-utilization gap and belongs in the parity-closure stage.

## Required closure before 0.8

The audit recommends the following order:

1. expose Natural Ventilation for historical GeoSphere when its actual required observations are present;
2. expose HVAC/Passive routes with per-analysis capability gating rather than an all-or-nothing page;
3. restore the missing natural-ventilation-conditioned wind route;
4. integrate Priority-A provider fields (`ffx`, `ddx`, `so`, `tlmin`, `tlmax`) with quantity-correct canonical/native semantics;
5. retain and display GeoSphere quality flags in Data Quality without treating flags as physical analysis quantities;
6. decide separately whether Compare Climates should become source-neutral (EPW + historical datasets) or remain intentionally EPW-only;
7. keep DNI/plane-of-array and EPW sky/illuminance routes unavailable unless a scientifically explicit derivation/source is added; do not fabricate measured fields.

Only after these items are resolved should the project move to new analysis families such as historical extremes/design climate.

## Live census

`deployment/geosphere_capability_census.py` reads the current official GeoSphere metadata at workflow time and writes a JSON/Markdown census. The workflow is isolated from core deterministic CI and runs on relevant changes, manually and weekly so provider metadata drift is visible.
