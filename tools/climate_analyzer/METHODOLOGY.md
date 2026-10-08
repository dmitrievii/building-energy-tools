# Climate Analyzer methodology and limitations

## Purpose

Climate Analyzer is a research and teaching application for exploring EnergyPlus Weather (EPW) files in building-physics, architectural and early building-performance workflows.

It is designed to make climate data inspectable and to support questions such as:

- What are the annual and seasonal temperature/moisture conditions?
- How are solar radiation and wind distributed?
- How do two or more climate files differ?
- When do simple passive-design or outdoor-air criteria appear favorable?
- Which periods deserve closer project-specific simulation or design review?

It is **not** a building-energy compliance calculator, a certification engine or a substitute for project-specific simulation and engineering judgement.

## Input model

Primary input is an EPW weather file.

Two source paths are supported:

1. a user-provided EPW upload; or
2. an EPW selected through the reviewed Climate.OneBuilding station catalog and downloaded on demand.

Source handling, catalog versioning and provenance are documented in `DATA_SOURCES.md`.

## EPW time semantics

The parser normalizes EPW time fields into the application's plotting/aggregation model. Reference tests explicitly protect:

- EPW hour 1/24 mapping to plotting hours 0/23;
- typical-year calendar behavior independent of source-year labels; and
- fractional EPW UTC offsets used in solar-position calculations.

These details are important because apparently small timestamp shifts can alter solar position, hourly profiles and comparison plots.

## Psychrometrics

Psychrometric properties are calculated from EPW dry-bulb temperature, relative humidity and the selected pressure model.

The public default is normal pressure:

```text
101325 Pa
```

Advanced modes allow:

- EPW station pressure with fallback median;
- standard-atmosphere pressure derived from site elevation; or
- a custom constant pressure.

The current direct scientific dependency baseline includes:

```text
PsychroLib 2.5.0
```

Reference tests compare vectorized application results against independent ASHRAE/PsychroLib-equivalent reference calculations and documented anchor values.

### Post-materialization psychrometric physical-closure check

Historical hourly and native-derived humidity outputs are validated a second
time, after psychrometric computation, against the original measured dry-bulb
temperature, relative humidity and atmospheric pressure. The check requires
cross-field closure among humidity ratio (kg/kg and g/kg), vapour pressure,
moist-air enthalpy, specific volume, moist-air density and degree of saturation.
ASHRAE/PsychroLib saturated vapour pressure is independently checked against
the Magnus water/ice reference in ordinary weather temperature ranges.

If a running process has generated internally inconsistent *derived* columns,
the application recalculates those derived columns algebraically from the
physically valid source inputs, preserves all original observations and records
how many rows were reconciled. A visible warning identifies a corrected
historical view; corresponding corrected values are used by both the chart
and filtered CSV export. The foundational saturation vapour pressure is
evaluated vectorially with the ASHRAE water/ice equations rather than through
mutable PsychroLib saturation runtime state; any inconsistent materialized
saturation pressure is independently reconstructed from measured temperature.
Impossible source temperatures or vapour pressure at/above total pressure
still fail closed rather than inventing finite humidity.

This gate addresses the observed **33,045-hour** versus **32,709-hour** GeoSphere
humidity anomaly. The proximity to **32,768 = 2¹⁵** is diagnostic evidence for
a size-dependent runtime/materialization issue, but not proof of a specific
pandas, NumPy, PsychroLib or Streamlit defect. The independent-closure guard
is a protective layer, not an assertion that the underlying trigger is proven.

## Solar calculations

Solar-position and plane-of-array calculations use the EPW location/time information and the validated application solar layer. The current direct dependency baseline includes:

```text
pvlib 0.15.2
```

Reference gates include horizontal plane-of-array consistency and a vertical south-facing isotropic-decomposition case, plus fractional time-zone handling.

Solar and radiation plots must be interpreted according to whether they display instantaneous/intensity-type quantities or energy sums. Dedicated regression tests protect monthly/annual radiation aggregation and energy conservation for the deterministic annual reference climate.

### Ground reflectance for tilted surfaces

The **design ground-reflectance assumption** is separate from the **source EPW albedo**.
Climate Analyzer preserves the source `albedo` column unchanged, and offers three
explicit scenarios for plane-of-array (POA) radiation calculations:

1. **Standard ground (default):** `albedo = 0.20` at every timestamp. This is a
   practical building-design reference scenario, not a measurement of the site's
   ground conditions.
2. **Source EPW/provider albedo:** user opt-in to the source series, record by
   record. Genuinely missing entries fall back to 0.20 and the UI discloses
   their count. Any numeric observation outside the physical 0–1 range fails
   instead of being silently clipped.
3. **Custom constant:** user-defined reflectance within 0–1, applied to every
   timestamp.

The selected albedo model applies consistently to orientation charts, tilt
matrices, monthly façade irradiation and the individual-surface POA component
view. Component totals are reported as **direct**, **sky diffuse**, **ground
reflected**, and **total**; changing albedo affects only the ground-reflected
component.

For an unobstructed isotropically reflecting horizontal ground plane, the
ground-reflected energy on a surface tilted by `β` from horizontal is

`POA_ground = GHI × albedo × (1 − cos(β)) / 2`.

This does not model partial ground view, façade recesses, nearby buildings,
obstructions, snow-cover physics or detailed urban radiative exchange. A
persistently high EPW albedo is surfaced as a **plausibility warning**, not
silently corrected or presented as proof of bad source data. Albedo source
values can be physically plausible on snow or specialized light-colored ground.

The POA totals cover the **currently selected period** and must not be
interpreted as annual values when date/month/hour filters remove observations.
The current sky-diffuse treatment is the installed pvlib calculation mode; the
ground-albedo scenario does not independently change the direct or sky terms.

## Degree-hour and climate-severity indicators

Heating/cooling degree-hour indicators are climate-screening quantities based on declared application thresholds. Their threshold behavior is explicitly unit tested at and around the boundary values.

They are not a substitute for a dynamic building heat-balance calculation because they do not represent project geometry, thermal mass, gains, ventilation systems, controls or HVAC efficiencies.

## Natural ventilation and night flushing

Natural-ventilation and night-flushing outputs are **eligibility/potential indicators**, not airflow simulations.

The application combines selected climate thresholds/conditions to identify hours that appear suitable under the chosen assumptions. Regression tests protect boundary behavior, including overnight intervals and the relation of early-morning night-flushing hours to the previous hot day.

Actual natural ventilation performance depends on building geometry, opening areas, pressure coefficients, wind exposure, buoyancy, controls, occupancy, indoor contaminants, acoustics, security and other factors outside the EPW-only model.

## Passive-strategy and HVAC decision support

Passive/HVAC pages contain climate-derived screening indicators and simple load proxies. They are intended to help users identify climate opportunities or periods requiring further analysis.

These outputs are not normative sizing calculations. In particular, ventilation-load proxies do not replace a complete HVAC or building-energy simulation.

Whenever a chart or summary is based on a heuristic rule rather than a physical building model, the result should be read as **decision support**, not as a predicted building response.

## Multi-climate comparison

Comparison mode applies the same parsing, derived-variable and aggregation logic to multiple EPW files and presents overlays, ranked summaries, small multiples and difference-to-reference views.

A comparison is only as meaningful as the underlying weather datasets. Different TMY construction methods, source periods, station relocations, urbanization, measured/synthetic data treatment or climate-change assumptions can produce material differences that are not caused by the application.

## Data quality

The application reports EPW metadata and data-quality diagnostics, including missing/invalid fields and structural input checks.

Passing parser/data-quality gates does not prove that a weather file is climatologically representative or suitable for a particular study. Dataset selection remains a methodological decision.

## Scientific validation model

The validation strategy has three layers:

1. **reference-point tests** for equations/time semantics and decision boundaries;
2. **security/input boundary tests** for accepted data paths; and
3. **deterministic annual regression** using an 8,760-hour synthetic reference climate with frozen fingerprints and aggregation checks.

Current machine-readable evidence is maintained under:

```text
validation/scientific_reference_register.json
validation/SCIENTIFIC_VALIDATION.md
```

A passing regression suite means the tested behavior matches the declared reference baseline. It does not establish universal validation across all EPW datasets or all engineering use cases.

## Dependency baseline

The public beta candidate is tested on Python 3.12 with pinned direct dependencies in `requirements.txt`, including:

- Streamlit 1.63.0
- pandas 2.3.3
- NumPy 1.26.4
- Plotly 5.24.1
- PsychroLib 2.5.0
- pvlib 0.15.2

Major scientific dependency upgrades should be treated as validation events, not routine cosmetic maintenance.

## Known scope limits

Climate Analyzer currently does not claim to provide:

- regulatory energy-performance certification;
- code-compliance verification;
- building thermal simulation from geometry/constructions;
- CFD or pressure-network natural-ventilation simulation;
- future-weather morphing or climate-change scenario generation;
- uncertainty propagation for weather-source uncertainty;
- automatic suitability determination for a specific building project.

## Engineering responsibility

Canonical disclaimer:

> Climate Analyzer is a research and teaching aid for climate-data exploration and early design support. Outputs are not a substitute for project-specific engineering judgement, regulatory verification, certification or professional design responsibility.

Release identity and publication status are defined in `epw_climate_analyzer/release_info.py`.
