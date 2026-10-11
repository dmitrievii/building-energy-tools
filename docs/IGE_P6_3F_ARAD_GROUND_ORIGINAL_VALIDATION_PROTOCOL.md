# IGE P6.3F — Original ARAD Graz ground validation / access gate

**Date** 2026-10-11. **Status** \`GROUND_SOURCE_RESTRICTED_NOT_ACQUIRED\`.
Research-only, no synthetic "ground" series and no future EPW release.

## 1. Results of original-source discovery, independently verified

**ARAD network original archive access is restricted.** Austrian GCOS
2025 documents the original ARAD minute observations with strict BSRN-like
quality management, data access by request to \`klima@geosphere.at\`
and partner-specific terms (potential fees). National ARAD science
correspondents are \`marc.olefs@geosphere.at\`,
\`florian.geyer@geosphere.at\`; University of Graz local meteorological
station contact \`messung.physik@uni-graz.at\`.

Sources:
- GCOS Austria 2025 report:
  https://www.gcos.at/reports/Austrian_GCOS_Report_2025.pdf
- Olefs et al., 2016, Atmos. Meas. Tech. 9, 1513–1531:
  https://doi.org/10.5194/amt-9-1513-2016
- University of Graz original meteorological station:
  https://climatephysics.uni-graz.at/en/meteorological-station/
- GeoSphere Data Hub generic historical station API is NOT
  verified to expose original ARAD with ARAD-specific original
  quality flags: https://data.hub.geosphere.at/

**The original ground ARAD minute CSV has NOT been received, its
metadata/time convention/license are NOT yet established.** P6.3F
must therefore NOT report a numerical NASA vs ARAD independent skill
score. ARAD literature's station-level 2012–2014 quality percentages
GLO 93%, DIR 96%, DIF 96%, DLW 95%, four simultaneous 88% are
*published network QC statistics*, not 2012–14 source data.
The independent sensor may be near GeoSphere #30 but exact
instrument coordinates/site identity must be verified.

External open alternatives, e.g., CAMS hourly gridded solar or
a different later Graz measured dataset, may support sensitivity
checks but are **not** equivalent ARAD 2012–2014 original hourly
validated ground observations. No proxy substitute is allowed.

## 2. Source data request contract

Ask ARAD custodians for research access to:
- **Graz** original **1-minute observations 2012-01-01
  through 2014-12-31 inclusive**, noting if any part of the
  time series unavailable;
- irradiances **GLO/GHI horizontal, DIR/DNI direct normal,
  DIF/DHI diffuse horizontal, DLW downwelling longwave**,
  original units W/m²;
- per-minute **original flags** (1=good; 2=wrong; 3=dubious;
  255=missing) including manual/automatic overrides,
  station maintenance, calibration epochs, temporal gap flags;
- station WGS84 coordinates/elevation, horizon obstruction,
  instrument types and radiometer replacements,
  timestamps' time base **UTC vs CET/CEST**, and **start/end/
  center of minute** definition of original averaging;
- exact primary source/data version, original source files
  and SHA-256, use permission, publication of aggregate
  scientific metrics, any restriction on secondary distribution,
  any possible data supply or processing costs.

If a custodial source is not in the normalized input contract
below, maintain a separate immutable ORIGINAL source plus
a documented, versioned conversion/transcription adapter.
Never relabel a rewritten file as unmodified instrument-original.

## 3. Strict original-to-hourly independent QC protocol

Command-line module
\`research/ige_cmip6/p6_3f_arad_ground_qc_validation.py\`
has two explicit paths:

1. **Public/CI default** with \`--p6e-frozen\` and \`--out\`,
   **without** ARAD source: validates the exact frozen original
   P6.3E GHI/DNI/DHI hourly SHA-256, counts exactly 26,304
   NASA POWER hourly satellite/reanalysis records per site
   for 2012–2014, outputs \`BLOCKED_ARAD_SOURCE_ACCESS_NOT_YET_ACQUIRED\`
   and null observed skill (NEVER fabricated zeros).
2. **Locally only after custodial approval** add
   \`--arad-original-minute-csv\` and
   \`--arad-source-manifest-json\`.
   Both are mandatory together. **DO NOT run private provider
   data through public GitHub Actions.** The custodian manifest
   must specify explicit original CSV checksum, station,
   temporal convention, unit, variable mappings and permission
   to analyze. The schema is a prospective normalized
   scientific contract, **not** a claim about the as-yet-unknown
   provider's file headers.

Canonical normalized CSV columns:
\`\`\`csv
timestamp_utc,ghi_w_m2,ghi_w_m2_qc,dni_w_m2,dni_w_m2_qc,dhi_w_m2,dhi_w_m2_qc,lw_down_w_m2,lw_down_w_m2_qc
\`\`\`
One record per original minute, **explicit UTC ISO-8601 offset
+00:00 or Z, start-of-minute mean** *only after verified with
original custodians*. No assumptions about time zones. Original
provider QC 1 alone is accepted; provider QC 2/3/255 never
counts as a verified measurement. Reject unconfirmed flag codes,
timestamps, units, duplicate timestamps and original SHA mismatch.

One accepted hourly component requires **all 60 distinct,
chronological, original UTC minutes AND 60 per-component q=1
values**. Different components have independent QC gates;
joint four-component coverage requires 60 all-parameter good
minutes. No resampling gaps, extrapolation, artificial
daylight/night clipping or normalization from 59 valid minutes.

For hourly power in W/m², correct energy over exactly 60
minute means:
\[
E_{\mathrm{hour}}={\sum_{i=1}^{60}I_i\over 60\times1000}
\quad[\mathrm{kWh/m^2/h}\cdot h]
\]
(numerically kWh/m² per complete hour). Preserve signed
night instrument offsets as measured diagnostic data rather
than silently clipping to zero.

Evaluate both NASA POWER source grid points already fixed
in P6.3D/E:
- \`graz_station30\` at 47.08°N, 15.45°E;
- \`nasa_gcm_cell\` at 46.875°N, 15.375°E.

Do not select a point to minimize observed error without
pre-registration. Compare exact same UTC hours for 2012–2014,
per original ARAD q1 complete hour, for GHI/DNI/DHI. The
NASA original-source \`LW\` was not retrieved in P6.3E,
so **LW is ground-only QA until a proper independent
NASA downward LW source is acquired with units verified**.

Report by year, ANNUAL/DJF/MAM/JJA/SON:
bias, MAE, RMSE, Pearson, n valid paired hours, coverage,
and physical consistency diagnostics. Null scores when
no observed pair. Do not claim solar physical closures at
longwave or higher temporal resolution.

Use **2012–2013 for exploratory diagnostics and 2014
held out from any future fitting**. As no model parameters
are fitted in P6.3F, all reported scores are descriptive
and not post-calibration test performance.

## 4. Frozen-source reproduction and downstream boundary

Frozen upstream integrated research archive:
\`IGE_CLIMATE_RESEARCH_P1_TO_P6_3E_INTEGRATED_FREEZE_2026-10-11.zip\`.

P6.3E accepted source workflow:
https://github.com/dmitrievii/building-energy-tools/actions/runs/38129047139

P6.3E source artifact:
\`ige-p6-3e-ghi-dni-dhi-toa-arad-research-audit\`.
Published GitHub Actions artifacts expire in 30 days. The
offline P1–P6.3E integrated preservation is the scientific
custody baseline, not a public GitHub replacement.

**P6.3F preliminary completion definition:**
- access feasibility checked and documented;
- independent custodian path verified;
- original NASA source verified against frozen SHA;
- 60/60 original minute ingestor with genuine QC test coverage;
- CI PASS explicitly with \`GROUND_SOURCE_RESTRICTED_NOT_ACQUIRED\`;
- no ground score until actual measurements are provided.

**The full independent ground-validation objective remains
scientifically OPEN after this preflight** and production
\`EPW_READY=false\`.
