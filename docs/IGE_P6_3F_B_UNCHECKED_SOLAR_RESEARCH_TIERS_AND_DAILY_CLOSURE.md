# P6.3F-B — Unchecked radiation is not erroneous: scientific two-tier source analysis

**Research-only**. 2026-10-11. The prior GeoSphere ten-minute Graz GHI source audit remains immutable.

## Scientific interpretation corrected

Original GeoSphere official \`q21\` quality list:
- \`0 = ungeprüfte Daten\`: not verified by provider QC. It is NOT a code meaning physically incorrect.
- \`10,11,12,20,21,22\`: provider QC-processed / accepted categories.
- null / missing values are not data and must not be filled.
- Other explicitly non-approved quality statuses cannot be silently included.

**A measured value's existence, scientific usability, and formal QC status are different properties.** Hence an unchecked measurement may be useful for exploratory methodology, sensitivity analysis, physics screens and comparison with independent products, if source uncertainty is propagated and not disguised as independently certified truth.

**Primary historic GHI** Graz \`cglo\` 10-min: 73,393 complete 6-of-6 QC-approved hourly values over 2005–2014. Historic original 10-min \`chim\` (Himmelsstrahlung) is physically observed and non-null in **2006–2009 only**, always \`q21=0\`; data DO NOT vanish because a QC approval was not recorded. Observed source counts: 2006 52,439, 2007 51,995, 2008 52,267, 2009 37,139 original non-null 10-min \`chim\` measurements at station #30 (source original archived P6.3F). 2005 and 2010–2014 have no reported numeric \`chim\` values and cannot be reconstructed from q0 flags.

The \`chim\` parameter's shortwave diffuse-horizontal interpretation is physically plausible based on measurement magnitudes and relation to GHI, but **exact instrument and source semantics remain to be confirmed**. Never use as atmospheric LW, and never call calculated \`(GHI-DHI)/cos(zenith)\` independently measured DNI.

Primary official sources:
- GeoSphere [dataset klima-v2-10min](https://data.hub.geosphere.at/en/dataset/klima-v2-10min), DOI [10.60669/8fya-7x87](https://doi.org/10.60669/8fya-7x87), CC BY 4.0, UTC.
- [GeoSphere API q21 official changelog](https://dataset.api.hub.geosphere.at/v1/docs/changelog.html).
- GeoSphere source original 20 station-year GeoJSON snapshots, preserved in successful workflow [#38134438339](https://github.com/dmitrievii/building-energy-tools/actions/runs/38134438339), artifact ID 11700138103.
- P6.3D original daily station QC solar archive from [#38128314291](https://github.com/dmitrievii/building-energy-tools/actions/runs/38128314291).
- P6.3E original NASA POWER source hourly GHI/DHI archive from [#38129047139](https://github.com/dmitrievii/building-energy-tools/actions/runs/38129047139).

## Three separate research quality claims

1. **Provider QC-confirmed:** full six-of-six original \`cglo\` (or \`chim\` if flags permit) with source-approved \`q21\`, source SHA and UTC labels. Independent historical measured GHI (not future validation).
2. **Unchecked, provisionally usable:** six-of-six observed non-null values and \`q21=0\` (or mixed original q0+approved), original byte source, absolute source timestamp, and physically reported screens. This is genuine observed source data with unknown formal QA, **not mathematically synthetic data**, and may be used for transparent exploratory numerical studies and sensitivity comparisons.
3. **Unavailable/invalid for the requested metric:** missing original numeric values, unknown q flags, incomplete six-of-six source hour or explicit physical anomaly requiring investigation. Do not impute or change.

Original observations are NOT altered, shifted, clipped, reassigned or filled. Physical plausibility is suggestive, **not independent sensor calibration**. No cherry-picking timestamp meaning to boost a correlation.

## Numerical validation design

Research module \`research/ige_cmip6/p6_3f_b_unchecked_diffuse_daily_closure.py\` requires *frozen input* directories containing first P6.3F original GeoSphere station data, frozen P6.3E NASA POWER and frozen P6.3D quality-approved daily station GHI data. All original ZIP source SHA and provided original CSV SHA are verified. Use only original station #30, because original station #16412 records and QC flags were identical aliases of #30 in 2005–2014.

### GHI and provisional DHI to NASA POWER

For each UTC hour, with two explicit timestamp hypotheses (ten-minute record start / record end), classify the GHI and \`chim\` component independently:
- \`QC_CONFIRMED\`
- \`COMPLETE_UNCHECKED_Q0\`
- \`COMPLETE_MIXED_Q0_QC\`
- \`PARTIAL_OR_MISSING\`
- \`UNRECOGNIZED_OR_REJECTED_FLAG\`

Require **6 distinct original ten-minute observations** in a complete hour. For provisional DHI use only complete hourly GHI+DHI with physically explicit screens. We do NOT require that GHI itself has an approved QC flag to consider DHI exploratory; GHI source tier stays visible for sensitivity, and calibration-independent uncertainty must not be understated.

Numerical physical review flags (kWh/m² per hour; thresholds intentionally diagnostic, non-normative):
- diffuse exceeds global by more than max(0.02, 5% × GHI);
- GHI or diffuse less than −0.005;
- deep-night \`cos(theta_z) < −0.05\` and either global or diffuse energy exceeds 0.020;
- NOAA approximate independent hour-midpoint solar geometry (no detailed horizon or angle averaging).

Compare NASA POWER original gridded GHI/DHI **at both preregistered locations**, report absolute bias NASA minus station, MAE, RMSE, Pearson, source coverage by year/season and original source tiers. These scores are **exploratory** for unchecked \`chim\`, even if correlations are high. Never describe POWER as another measured station.

### GeoSphere GHI original daily independent-integrity seam

Official QC-accepted \`cglo_j\` belongs to solar day labelled \`D\` that integrates from \`D-1 23:00 UTC\` to \`D 23:00 UTC\`. Reconstruct from **24 complete observed hourly ten-minute GHI sums** for each day. Report full-source coverage, QC-confirmed 24-h coverage, daily solar energy bias and MAE by each of the two time-label hypotheses.

This is a *different time-resolution source-internal consistency test*, not proof against a separate independently calibrated pyranometer. Lack of timestamp support evidence means neither hypothesis can be declared authoritative from higher correlation alone. The archive will preserve BOTH hypotheses.

## Outcome / next decisions

- If exploratory \`chim\` 2006–2009 passes physical checks and agrees sufficiently with gridded DHI, one may use it as a **provisional research benchmark**, explicitly QC-unverified. This reduces reliance on ARAD for method development, but a manuscript claiming **independently quality-assured DNI/DHI** would still need stronger ground evidence.
- If \`chim\` source physics are inconsistent, mark measurements as potential anomalies, investigate calibration/instrument history and repeat with/without screens.
- GHI has the larger 2007–2014 approved period; the DHI paired period is 2006–2009 only. Never extend uncovered data by interpolation.
- Full future EPW validation still needs direct/diffuse representation, original multivariable temporal/psychrometric consistency and building simulation impact.

**Original P1–P6.3E preservation remains unchanged.** \`production_epw_ready=false\`. \`main\` untouched.


## Preliminary independent recalculation from frozen original data (before full P6.3F-B CI)

A direct offline audit on the immutable original 20-GeoJSON research
artifact (workflow #38134438339), NASA POWER P6.3E full original hour
CSV and official QC-accepted GeoSphere daily GHI from P6.3D yields:

| Year | 6/6 present unverified chim + GHI hours | NASA POWER DHI correlation r | MAE (kWh/m²/hour) |
|---|---:|---:|---:|
| 2006 | 8,710 | 0.8824 | 0.02333 |
| 2007 | 8,643 | 0.8707 | 0.02273 |
| 2008 | 8,703 | 0.8727 | 0.02402 |
| 2009 | 6,183 | 0.8824 | 0.02802 |

This exploratory comparison uses unverified q0 rather than treating q0
as a failed instrument; excludes missing values and diffuse energy
above global by more than max(0.020 kWh/m²/hour, 5% of GHI). It did not
impute any source values. The full P6.3F-B code additionally applies
nighttime solar-position flags, temporal provenance, strict immutable
source checks and both time-label hypotheses; CI report is authoritative
for final publication figures. These r values are encouraging evidence
of a meaningful physical signal, **not proof of instrument calibration
or independently QC-approved DHI**.

### Unexpected discrepancy in OTHER (already QC-approved) source

The original QC-accepted 10-minute \`cglo\` hourly series was summed over
official solar day [D-1 23:00 UTC, D 23:00 UTC) and compared with
**official GeoSphere daily \`cglo_j\`** from P6.3D. The initial strict
daily 24-hour matched-source test detected average signed energy
differences \`10min − daily\` for q21-approved days:

| Year | Strict matched days (source start-label hypothesis) | Mean 10min minus daily, kWh/m²/day |
|---|---:|---:|
| 2007 | 355 | +0.0069 |
| 2008 | 360 | +0.0054 |
| 2009 | 364 | +0.0482 |
| 2010 | 363 | **+0.4617** |
| 2011 | 363 | **+0.2859** |
| 2012 | 365 | +0.0058 |
| 2013 | 362 | +0.0056 |
| 2014 | 365 | +0.0057 |

The 2010–2011 discrepancy is substantial (full calendar-year
source solar totals ~+14.8% and +8.0% respectively). The daily
quality-approved product and ten-minute quality-approved product
**both exist**, but their source versions, instrument histories or
aggregation/adjustment treatments might differ. This is **NOT**
proof which series is inaccurate. A systematic processing or sensor
change remains a hypothesis to investigate; do not silently normalize
2010–2011, call a QA flag "wrong", or select the source with a desired
future model correction. Explicit annual source-product discrepancy
screens are now part of P6.3F-B outputs.

**Scientific priority:** characterize the discrepancy and independent
direct/diffuse partition alongside usability of provider q0. Data may
be used with disclosed uncertainty; source QC and physical consistency
are complementary and not interchangeable.
