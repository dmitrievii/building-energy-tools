# IGE P6.3C — precipitation sentinel closure, UTC time windows and cross-station verification

Research branch only; no production Climate Analyzer or EPW implementation.

## Confirmed authoritative finding, not an assumption

GeoSphere Austria \`klima-v2-1d\` original **daily** metadata, downloaded and hashed
within the successful P6.3B run, declares for station parameter \`rr\`:

> Niederschlag, 24-Stundensumme der Einminutenwerte von 06:01 UTC bis
> 06:00 UTC des Folgetags, -1=kein Niederschlag, 0=weniger als 1/10 mm

Thus:
- Official QC-accepted **\`rr=-1\` is exactly a recorded DRY day: 0 mm precipitation**.
- Official QC-accepted **\`rr=0\` is a TRACE / interval-censored amount from 0 to less than 0.1 mm**, not a confidently zero/dry day.
- Values >0 use original physical mm/day.
- Null or not approved q21=10/11/12/20/21/22 remain missing.
- Any other negative code fails closed.
- **Every original raw value and q21 is immutable** in output alongside
  cleaned amount and semantic class. Code MUST check metadata descriptions
  and units dynamically against archived authoritative source.
- In original station #30 2005–2014 archive 2,122 of 3,652 days have
  QC-approved original \`rr=-1\`; the prior P6.3B precipitation QC incorrectly
  left these out. This constitutes a scientific data-processing defect
  now explicitly corrected and documented, **not** an error at GeoSphere.

## Verified mismatch between daily labels and actual measurement windows

GeoSphere original metadata specifies:
- \`cglo_j\`: calibrated global solar daily energy, 0–24h MOZ,
  **23:00 UTC previous date to 23:00 UTC labelled date**.
- \`rr\`: 24h daily sum from **06:01 UTC labelled date to 06:00 UTC following date**.
- \`tl_mittel\`: daily air temperature defined from \`(tlmax+tlmin)/2\`;
  max/min use a separate period, **18:10 UTC previous day–18:00 UTC
  labelled day**, and are not exactly a synchronized mean with solar.
- \`rf_mittel\`: mean of observations at **06, 13, 18 UTC**.
- \`vv_mittel\`: mean of observations at **06, 13, 18 UTC**.

Therefore, same DATE label is not necessarily the same physical time window.

For station #30 and pre-selected independent station IDs #53 Laßnitzhöhe,
#94 St. Radegund, #200 Gleisdorf, calculate ANNUAL/DJF/MAM/JJA/SON
climatological Pearson and Spearman correlation for air temperature–GHI,
relative humidity–GHI, precipitation amount–GHI with explicit
independent weather-label shifts \`-2,-1,0,+1,+2\` days.

All corrections are diagnostic; DO NOT shift original source rows nor
pick the lag with the highest correlation as a scientifically verified
time correction. Rain \`rr=0\` trace days are excluded from numeric
precipitation-amount correlation and reported as their own GHI/precip
class; verified no-precipitation days \`rr=-1\` contribute clean 0 mm.
Donor stations are selected **before any empirical outcomes**; different
altitude/exposure/microclimate must be disclosed and no donor reference
substitutes directly for measurements at the NASA model-cell center.

All original donor GeoSphere responses are preserved and SHA256 hashed;
QC flags and provider parameter units verified. If source records lack
minimum coverage, report \`INSUFFICIENT_QC_SAMPLE\`, never fill gaps.

## Previously collected HOURLY GeoSphere station source

Reuse immutable original P6.2B annual station #30 artifacts 2005–2014
from GitHub Actions run #38082122721. For each year validate the archived
source SHA-256 \`hourly_raw_qc.csv.gz\`, metadata, native 8760/8784 UTC
hours and original station identity. For ten years there are **87,648
original UTC hourly records**.

The provider original hourly \`cglo\` is \`W/m²\`, explicitly a
**kalibrierter Stunden-Mittelwert**. It is a MEAN W/m² for each hour,
not a daily total; candidate daily sums divide by 1000 to obtain
kWh/m², using 24 consecutive hours.

Important: in the independently inspected 2010 annual source,
all 8,760 \`cglo\` measurements are **q21=0 unverified** while
hourly \`tl\` is QC-accepted. That finding does NOT establish that all
ten years have identical flags until they are audited.
Compare raw hourly solar to the independently QC-approved original
daily \`cglo_j\` for each day with two alternate hour timestamp-position
hypotheses:
1. start-stamped hours in [previous 23:00 UTC, current 23:00 UTC);
2. end-stamped hours in (previous 23:00 UTC, current 23:00 UTC].

Report both differences and gaps. Critically, hourly q21=0 data **must
never be promoted** as an independently verified GHI reference, even
if aggregations resemble the accepted daily GHI.

No estimated hourly data, no source clipping, no selection of the
more favorable timestamp assumption without documentary evidence.

## QA and scientific gates

- All 3,652 frozen daily station #30 originals are present; exact
  provider meta \`rr\` description and source digest checked.
- All 2,122 original \`rr=-1\` correctly reclassified as zero-mm
  dry days with original value retained; number of trace days reported.
- Provider GeoSphere donor station identity, solar availability,
  source code units and raw/q21 flags checked; all source downloads
  archived with SHA256. Do not assume 100% measured parameter coverage
  just because date timestamps are complete.
- Explicit lag/season/variable correlation matrices, separate solar
  response by dry, trace, light-rain and wet day class.
- Verify original P6.2B 87,648 UTC hourly entries, preserve hourly
  solar q21, two 24-hour timestamp conventions and comparison to
  accepted calibrated daily GHI.
- **Green CI certifies source verification and diagnostic completion,
  not physical validation of hourly radiation, synchronized subdaily
  temperature/rain/solar or any future EPW.**
- Later work: independently QC hourly radiation source, full hourly
  mixed-variable closure, spatial representativeness, and additional
  independent data products outside near-Graz station cluster.

## Scientific source references

- GeoSphere official station resource: https://data.hub.geosphere.at/dataset/klima-v2-1d
- Official metadata (actual source for precipitation sentinel and periods):
  https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d/metadata
- Official hourly station resource:
  https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata
- Archive source: IGE P6.3B GitHub Actions successful run #38124674795.
- Hourly original archive source: IGE P6.2B run #38082122721.
