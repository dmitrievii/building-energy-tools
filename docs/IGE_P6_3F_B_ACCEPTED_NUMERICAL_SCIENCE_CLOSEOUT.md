# IGE P6.3F-B — Accepted numerical source evidence and phase closeout

**Evidence date:** 2026-10-11. **Original source calculation:**
[GitHub Actions #38135836142](https://github.com/dmitrievii/building-energy-tools/actions/runs/38135836142),
scientific execution commit \`8d6a0b7d68f97d0a6200877ab75cfd0be4c70615\`,
conclusion \`success\`, original artifact ID \`11700429246\`,
\`ige-p6-3f-b-original-geosphere-unchecked-dhi-provisional-nasa-and-daily-closure\`.
The artifact contains the exact original-source annual physics-screen summaries
and hourly and daily pairwise tables, source provenance and report.

**Computational status:** \`RESEARCH_QC_TIER_SENSITIVITY_COMPLETED\`.
**Scientific status:** \`GHI_QC_CONFIRMED_DHI_PROVISIONAL_UNCHECKED_ONLY\`.
**Future EPW production ready:** \`false\`.
All six derived output CSV SHA-256 hashes match the frozen original
JSON \`p6_3f_b_unverified_solar_research_science_report.json\`.

## 1. The result: unchecked \`chim\` is worth analyzing

Provider \`q21=0\` explicitly means \`ungeprüfte Daten\` (unchecked);
this is not evidence that an original measurement is wrong.
Complete original ten-minute \`chim\` (Himmelsstrahlung) intervals exist
for 2006–2009 and can be analyzed as an **uncertainty-labelled
exploratory observation**, without recoding flags or inventing samples.

Original source GeoSphere Graz station #30, all 10 min:
- Provider QC-approved GHI 2005–2014, strict 6/6: **73,393 hours**
  under \`record_start\` and 73,392 under \`record_end\`.
- Original \`chim\` source with all 6/6 numerical values and original
  unchecked q21: **32,239 hours** under \`record_start\`, 32,238
  under \`record_end\`; **0 provider-QC-approved DHI hours**.
- No negative radiation, diffuse > global above screen, or unusual
  nighttime hourly flux crosses the explicitly declared provisional
  physical-review screen for this particular source.
- Both source time-window conventions are **HYPOTHESES**,
  not selected based on higher correlations.

| Source 10-min label hypothesis | Channel and independent comparator | Source-matched hours | Pearson r | MAE (kWh/m²/hour) | RMSE | POWER-minus-ground bias |
|---|---|---:|---:|---:|---:|---:|
| Record start | Official QC-approved observed GHI vs NASA POWER Graz grid | 73,393 | 0.9393704 | 0.0383689 | 0.0810568 | −0.0114482 |
| Record start | Original unchecked \`chim\` provisional diffuse vs NASA POWER DHI | 32,239 | **0.8713210** | **0.0242561** | **0.0494369** | **+0.0069970** |
| Record end | Official QC-approved observed GHI vs NASA POWER Graz grid | 73,392 | 0.9387326 | 0.0388674 | 0.0814183 | −0.0114493 |
| Record end | Original unchecked \`chim\` provisional diffuse vs NASA POWER DHI | 32,238 | 0.8712464 | 0.0242174 | 0.0494563 | +0.0069908 |

NASA POWER is an independent gridded satellite/reanalysis product,
NOT a second calibrated ground pyranometer. The above agreement
supports the **plausibility of using unchecked observations as
research evidence**, not validation of their absolute radiometric
accuracy or the exact \`chim\` instrument definition. Original q0
source cohort is not mixed into the \`QC_CONFIRMED\` cohort.

## 2. Critical different-source-resolution solar energy discrepancy

Solar-day \`D\` is the official GeoSphere reference
\`[D−1 23:00 UTC, D 23:00 UTC)\`. Original \`cglo\`
ten-minute GHI integrated from exactly **24 full QC-approved hours**
against original \`cglo_j\` accepted provider daily GHI:

| Year | Fully matched QC-approved days | Mean 10min minus daily (kWh/m²/day) | Same-day total energy ratio | Review |
|---|---:|---:|---:|---|
| 2006 | 144 | +0.014014 | 1.00514 | no |
| 2007 | 355 | +0.006915 | 1.00198 | no |
| 2008 | 360 | +0.005378 | 1.00159 | no |
| 2009 | 364 | +0.048188 | 1.01416 | no |
| 2010 | 363 | **+0.461663** | **1.14755** | **YES** |
| 2011 | 363 | **+0.285946** | **1.08168** | **YES** |
| 2012 | 365 | +0.005789 | 1.00165 | no |
| 2013 | 362 | +0.005587 | 1.00167 | no |
| 2014 | 365 | +0.005717 | 1.00176 | no |

Year 2005: zero strictly approved full 24-hour days; do not
present a QC-approved solar-day comparison for that year.

This is a comparison of **two original GeoSphere products** from
the SAME provider and overlapping station metadata: it is NOT
independent verification and does NOT establish which product is
miscalibrated. **Official QC approval is compatible with
source-processing differences, particularly 2010–2011.**
Potential causes include time-support semantics, sensor change,
historical correction policy and station product resolution; do not
claim any particular mechanism without instrument/provider evidence.
The 2010–2011 anomaly exists under BOTH studied timestamp hypotheses
and is not explained by an arbitrary ±10-minute solar-day shift.

## 3. Methodological decisions and limits

1. Retain \`q21=0\` original values as genuine observed source data
   for exploratory sensitivity and assessment; label them
   \`COMPLETE_UNCHECKED_Q0\` and document uncertainty.
2. Keep fully QC-approved \`cglo\` as **a separate source-quality tier**,
   not infallible. The official daily and ten-minute products may
   disagree despite valid flags.
3. Never force \`chim <= cglo\` by clipping, or replace questionable
   2010–2011 values to make daily totals agree.
4. No measured DNI is available in this open 10-minute
   \`cglo\`/\`chim\` pair. Any DNI algebraically derived using sun
   elevation is **model-derived**, not independent measured DNI.
5. Interpret Himmelsstrahlung as a provisional diffuse-horizontal
   candidate on magnitudes/physical behavior, pending primary
   original instrument technical documentation.
6. Do not combine combined #30 and child station #16412 as two
   observational replicas (identical saved sources).
7. Neither historical agreement nor good GitHub CI is physical
   validation of future hourly weather or future EPW.
8. The scientific follow-up for the **2010–2011 daily mismatch** is
   independent instrument/source lineage research and annual/monthly
   breakup, with no post-hoc data overwrite.

## Data custody

The accepted original P6.3F-B archive is a 30-day GitHub Actions
artifact, not durable preservation; download and add a SHA-verified
immutable original to an updated long-lived TU Graz research
freeze. The existing separately frozen P1–P6.3E archive must
remain unmodified. \`main\` was not changed.
