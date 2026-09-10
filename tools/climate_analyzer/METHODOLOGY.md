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

## Solar calculations

Solar-position and plane-of-array calculations use the EPW location/time information and the validated application solar layer. The current direct dependency baseline includes:

```text
pvlib 0.15.2
```

Reference gates include horizontal plane-of-array consistency and a vertical south-facing isotropic-decomposition case, plus fractional time-zone handling.

Solar and radiation plots must be interpreted according to whether they display instantaneous/intensity-type quantities or energy sums. Dedicated regression tests protect monthly/annual radiation aggregation and energy conservation for the deterministic annual reference climate.

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
