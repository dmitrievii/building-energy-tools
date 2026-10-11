# IGE P6.3E — Hourly GHI/DNI/DHI solar closure and ARAD Graz ground-reference path

**Research-only. No new future EPW, hourly synthetic climate, or production merge.**

## 1. Scientific reason to go beyond good GHI agreement

P6.3D showed high daily agreement between NASA POWER and GeoSphere
Graz accepted daily GHI. However, the current NASA POWER
methodology explicitly reports that DHI (diffuse horizontal
irradiance) and DNI (direct normal irradiance) can exhibit
countervailing biases which partially cancel in GHI.
Thus GHI-only validity **cannot** certify direct/diffuse components.
Source: NASA POWER CERES SYN1deg methodology:
https://power.larc.nasa.gov/docs/methodology/energy-fluxes/syn1deg/

P6.3E retrieves original hourly all-sky DNI, DHI,
top-of-atmosphere horizontal solar and source clear-sky GHI
from the same source and compares those with **unchanged
source-original hourly GHI from P6.3D**. These are NOT
independent observational sources. No historic GCM day
is aligned to the calendar day of a station measurement.

## 2. Source-verified computation

NASA POWER official hourly source and documented UTC:
https://power.larc.nasa.gov/docs/services/api/temporal/hourly/

Parameters:
- \`ALLSKY_SFC_SW_DWN\`: immutable original GHI hourly [Wh/m²];
- \`ALLSKY_SFC_SW_DNI\`: all-sky direct normal hourly;
- \`ALLSKY_SFC_SW_DIFF\`: all-sky diffuse horizontal hourly;
- \`TOA_SW_DWN\`: top-of-atmosphere downward horizontal hourly;
- \`CLRSKY_SFC_SW_DWN\`: clear sky downward hourly.

All units are validated from **actual provider response metadata**;
never assume daily units equal hourly units. Source original UTC
\`YYYYMMDDHH\` denotes the START of the hour. A strict
two-site × five overlapping source-block 2004-12-31–2014-12-31
original provenance is retained. Analyze only 2005–2014,
87,648 hours per site. Each companion timestamp must match the
frozen P6.3D GHI timestamp exactly. Reject mixed source
coordinates, LST, missing calendar keys, overlaps with conflicting
original values and unexpected radiation units.

### Derived geometrical screens

Independently approximate UTC midpoint solar position using NOAA
fractional year, equation-of-time, solar declination and hour angle.
This is a **screening approximation**, not a high-precision
solar ephemeris or site-dependent shading/terrain-horizon calculation.
Sole use:
- Sun low/high classification: \`cos(z)>0.05\` for
  conservative daytime; \`cos(z)<-0.05\` plus
  \`TOA<0.001 kWh/m²/hour\` for deep night.
- Source internal energy relation:
  \(GHI \approx DHI + DNI\max(0,\cos z)\).
  Deviations need not be file corruption: model hourly
  means, source direct/diffuse bias corrections, spatial
  footprint and hour-average zenith matter.
- Flag \`night GHI >0.03 kWh/m²/hour\` on deep-night
  hours, \`DHI>GHI+0.03\`, \`GHI>TOA\` with modest
  margin in strong daylight, and \`GHI>source
  clear-sky+0.10\` kWh/m²/hour in strong daylight.
- Component closure report absolute residual and screen
  \(|GHI-DHI-DNI*cos z| > max(0.10,0.15*GHI)\`
  kWh/m²/hour in daylight.
- These are **explicit descriptive screening thresholds**,
  not physical laws or statistically validated normative
  acceptance limits. Do not silently clip original source
  irradiance or force DNI/DHI to close by construction.

The output includes source SHA for every original response,
hourly source-physical flags, full seasonal counts and
a report \`production_epw_ready=false\` by construction.

## 3. Independently measured ground reference discovered: ARAD Graz

This materially changes the science-validation path.
University of Graz Climate Physics states the Graz ARAD
precision radiometry station has operated **since September 2011**:
https://climatephysics.uni-graz.at/en/meteorological-station/

Official Austria GCOS 2025 reports six ARAD sites including
Graz and original **one-minute** observations of:
global shortwave, direct normal shortwave, diffuse horizontal
shortwave and downwelling longwave radiation. ARAD original
QC and equipment differ from the standard GeoSphere
\`klima-v2-1h cglo q21=0\` archive:
https://www.gcos.at/reports/Austrian_GCOS_Report_2025.pdf

Published independent ARAD network paper gives quality flag
rates averaged **2012–2014 in Graz**:
- \`good=1\`: GLO 93%, DIF 96%, DIR 96%, DLW 95%;
- simultaneous GLO+DIF+DIR+DLW good: 88%;
- \`wrong=2\`, \`dubious=3\`, \`missing=255\`
  must remain excluded as specified by the original protocol.
See Olefs et al. (2016), Atmospheric Measurement Techniques 9:
https://amt.copernicus.org/articles/9/1513/2016/

**Do not mistake published percentages for downloaded data coverage
or transfer ARAD good flags onto the \`q21=0\` station archive.**
The ARAD original dataset has not yet been obtained or independently
authenticated in this step. It must be requested with original
sampling/timestamp definition, all four radiation variables,
instrument/QC flags, calibration/site metadata, 2012–2014
availability, publication/use permissions and access conditions.

University of Graz Climate Physics publishes measurement contact:
\`messung.physik@uni-graz.at\`

Since ARAD Graz began in September 2011, it CANNOT serve as an
observational 2005–2010 ground reference. A separate historical
station/network or a shorter fixed calibration/holdout period
is needed; do not silently extend ARAD to earlier years.

## 4. Acceptance / next steps

- P6.3E technical acceptance: original independent source
  provenance verified, full GHI/DNI/DHI/TOA/clear-sky
  hourly statistics produced, UTC calendar matched and
  diagnostic flags reported.
- Scientific ground validation is **OPEN** until
  actual ARAD Graz data with its own QC and measurement
  chronology are acquired, checked and compared
  independently, without overlapping calibrated
  and evaluated periods.
- Additional validation must include cloud variability,
  direct/diffuse partitioning, physically conservative
  future-hour disaggregation, multivariate temperature,
  humidity, pressure, wind and precipitation consistency,
  and building-energy simulation impact.
- P6.3E does not modify the production Climate Analyzer.
