# IGE P6.3D — Original hourly solar QC and independent satellite/reanalysis reference

**Research-only pilot. Not a production hourly EPW weather generator.**

## Exact research decisions (frozen before data retrieval)

### 1. Authoritative GeoSphere q21 semantics

The **original** GeoSphere \`klima-v2-1d\` metadata archived in P6.3B
contains \`code_lists.q21\` with:

- \`0 = ungeprüfte Daten\` (**unchecked / not quality certified**);
- \`10,11,12 = automatisch geprüft\` (automatically checked);
- \`20,21,22 = manuell geprüft\` (manually checked).

See the GeoSphere Austria official Dataset API changelog:
https://dataset.api.hub.geosphere.at/v1/docs/changelog.html

Original immutable IGE P6.3C analysis verified **all 87,648** station #30
hourly \`cglo\` observations 2005–2014 are **not q21 accepted**.
Exactly **zero** hours qualify as independent certified hourly GHI.
They may be numerically plausible and may aggregate close to accepted
daily \`cglo_j\`, but arithmetic agreement cannot substitute for the
provider's missing source QC certification.

Station \`cglo_j\` daily sums (J/cm² converted to kWh/m² via ÷360)
have independent formal \`q21=20\` provider quality and remain an
accepted **DAILY reference** only.

### 2. Independent hourly gridded reference: NASA POWER

NASA POWER official hourly API:
https://power.larc.nasa.gov/docs/services/api/temporal/hourly/

NASA POWER time-standard documentation:
https://power.larc.nasa.gov/docs/faqs/other/

The POWER original hourly microservice is available from 2001 onward.
It defaults to local solar time unless \`time-standard=UTC\` is
included. Its timestamp marks the START of the hour (official FAQ).
Historical 2005–2014 is available. Hourly solar parameter:
\`ALLSKY_SFC_SW_DWN\`; companion diagnostic air temperature \`T2M\`.

**Important:** NASA POWER is a satellite/reanalysis gridded product,
NOT independent QC ground-station hourly radiometry. It may share
upstream data with other NASA/CMIP6 products. Its native spatial
footprint is different from the 0.25° NEX-GDDP model cell and the
point instrument at Graz. Even a favorable result is not proof
of observed hourly physical truth.

Two declared coordinates, **before viewing results**:

| Source point | Latitude | Longitude | Meaning |
|---|---:|---:|---|
| Graz Universität vicinity | 47.080 | 15.450 | Station comparison |
| NEX-GDDP-CMIP6 local model cell | 46.875 | 15.375 | Spatial representativeness |

NASA POWER data use explicit UTC, original provider unit,
and original hourly keys \`YYYYMMDDHH\`; no implicit timezone
conversion, climate-model day pairing, or synthetic fill.

Five original two-year source blocks per location cover
2004-12-31 through 2014-12-31 inclusive with source SHA-256
and overlap duplicates checked. Extra 2004-12-31 is needed to
reconstruct the first GeoSphere 2005-01-01 23–23 UTC day.

### 3. Check TWO temporal aggregation windows without optimizing on fit

Observed GeoSphere accepted **daily \`cglo_j\`** integrates:
\`[23:00 UTC previous date, 23:00 UTC labelled date)\`.

NASA POWER's hourly time stamps denote beginning of the hour.
Compute from original hourly POWER flux two alternatives:

- \`geosphere_23_23UTC\`: [previous 23:00, same-day 23:00),
  primary physically aligned comparison.
- \`utc_midnight_00_24UTC\`: [00:00, following 00:00),
  diagnostic of day boundary mismatch.

Do not replace daily station observations by satellite values.
Do not infer GeoSphere's own hourly timestamp convention from the
NASA POWER convention.

Verify NASA POWER original response \`parameters\` units:
for an **hourly** interval, W/m² or Wh/m² converts to kWh/m²
via ÷1000, kWh/m² hourly converts as-is. Reject unrecognized
units, daily units, negative/nonfinite solar energy, physically
impossible >1.5 kWh/m² per hour and inconsistent UTC day keys.
Missing external hours remain missing and invalidate the day's
24-hour sum.

For each site × window × ANNUAL/DJF/MAM/JJA/SON report:
- complete 24-hour daily coverage and flags;
- daily mean bias and mean absolute error kWh/m²/day against
  the observed **matched UTC window**;
- daily Pearson correlation and sums;
- model-to-observed energy ratio on **paired complete days**
  (not the sum across a missing-day source and complete observed
  record); any data gaps flagged \`INSUFFICIENT_PROVIDER_COVERAGE\`.

All source bytes and their SHA-256 digests are retained.

### 4. What a green workflow can and cannot establish

Green CI certifies original source hash/unit/time/coverage validation
and numerical comparison computation. Green CI does **NOT** certify
independent hourly GeoSphere GHI or weather suitable for simulation.

\`production_epw_ready=false\` is unconditional in this phase.

Before future hourly EPW scientific acceptance require:
1. An independently quality-controlled ground hourly GHI time series
   relevant to Graz, OR formal original GeoSphere source hourly
   QC certification — not assumptions based on daily closeness.
2. Solar sun-altitude, direct/diffuse, nighttime bounds and measured
   seasonal hour-level closure; external CERES product structural
   uncertainty and spatial representativeness quantified.
3. Temperature, humidity, wind, precipitation and radiation coherent
   source-hourly chronology; native hourly heat-balance closure and
   pressure/psychrometric checks with appropriate measurement data.
4. Proven precipitation \`rr=-1\` and \`rr=0\` handling from P6.3C,
   native calendars, unbiased daily/monthly energy conservation,
   future scenario-change signal preservation and validation in
   other cities and climates.

No approach can verify observations from future SSP2050/2100.
Use scenario diagnostics, not claimed future accuracy.
