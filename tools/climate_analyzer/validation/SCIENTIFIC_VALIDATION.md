# Climate Analyzer scientific validation

Stage: `WEB-0.4`

This stage establishes numerical reference and regression gates for the Climate Analyzer. It is deliberately separated from the runtime/security work completed in WEB-0.3.

## Validation layers

### 1. Psychrometric reference points

The application's vectorized humidity-ratio, vapour-pressure, enthalpy, specific-volume, density and degree-of-saturation calculations are compared against an independent implementation of the ASHRAE 2017 SI equations at cold, moderate and hot/humid reference states.

PsychroLib remains the production backend for saturation pressure and iterative wet-bulb calculations. A published PsychroLib example (`25 °C`, `80 % RH` -> dew point `21.309397163661785 °C`) is also pinned as a dependency/reference anchor.

Reference: <https://github.com/psychrometrics/psychrolib/blob/master/docs/overview.md>

Published example: <https://github.com/psychrometrics/psychrolib/blob/master/docs/examples.md>

### 2. Solar transposition reference points

The wrapper around `pvlib.irradiance.get_total_irradiance` is checked against manual isotropic-sky decomposition:

`POA total = beam + sky diffuse + ground reflected`.

The test covers both a horizontal plane (which must reproduce a physically consistent GHI input) and a vertical south-facing plane with a manually calculated angle of incidence and view factors.

Reference: <https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.get_total_irradiance.html>

### 3. EPW time semantics

The parser preserves the EPW convention that the Hour field is `1...24`, while the application's plotting index represents these hourly intervals as `00...23` on the corresponding calendar day. Source years from typical meteorological year assemblies do not control the plotting calendar.

Reference: <https://energyplus.readthedocs.io/en/v25.1.0/auxiliary-programs/auxiliary-programs.html>

### 4. Deterministic annual regression

`WEB-0.4-SYNTH-1` is a deterministic analytical 8760-hour climate. It is not a real weather station and is not presented as one. Its purpose is to provide a stable whole-year regression fingerprint covering:

- dry-bulb statistics;
- heating and cooling degree-hour proxies;
- annual and monthly GHI aggregation;
- humidity ratio and wind means;
- natural-ventilation hours;
- night-flushing hours;
- shading hours;
- simple comfort hours;
- economizer hours;
- humidification/dehumidification hours;
- duration-curve ordering;
- passive-strategy summary consistency.

Expected values live in `scientific_reference_register.json` rather than being regenerated from production functions during the tests.

## Validation-driven fixes in WEB-0.4

Two defects were found while constructing the reference suite.

### Fractional EPW UTC offsets

The previous solar helper rounded the EPW UTC offset to an integer before localization. This shifts solar time for valid half-hour and quarter-hour time zones. WEB-0.4 now uses an exact fixed-offset `datetime.timezone` resolved to the minute.

### Night-flushing hot-day reference

The previous implementation used the current calendar day's maximum temperature for every night hour. For `00:00...06:00` this uses temperatures occurring later in the future day. WEB-0.4 instead evaluates early-morning hours against the preceding calendar day and late-evening hours against the current day.

## What this stage does not claim

This stage does **not** claim climatological validation of a specific EPW provider, station or measured dataset. It also does not validate whether the simplified design-strategy thresholds are appropriate for every building or standard. Those thresholds remain transparent screening assumptions.

Real-location/weather-source provenance and catalog production handling remain separate from these deterministic scientific regression gates.
