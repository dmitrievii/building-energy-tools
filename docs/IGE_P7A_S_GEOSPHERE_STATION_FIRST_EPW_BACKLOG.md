# P7A-S — Station-first historical EPW from GeoSphere 10-minute observations (backlog, not P7B prerequisite)

**Status:** planned, not yet implemented or validated. **Date:** 2026-10-11.

## Motivation and corrective interpretation of P7A

The first P7A 2013 reference EPW used NASA POWER gridded **GHI/DNI/DHI** as a single native source because GeoSphere hourly original solar had q21=0 and no measured station DNI/DHI, and we needed a structural/units test. This is a legitimate original-source synthetic/mixed reference benchmark, but **not the preferred choice for station-first historical GHI**. We subsequently verified original GeoSphere \`klima-v2-10min\` station 30 \`cglo\` has **52,520 quality-approved ten-minute samples in 2013 and 8,750 complete six-of-six station GHI hours** (record-start convention being provisional), source audit [#38134438339](https://github.com/dmitrievii/building-energy-tools/actions/runs/38134438339). Therefore the production-oriented station reference should prioritize these genuine on-site solar measurements.

### Required independent research deliverable

Create **second, distinct** Graz 2013 source-first historical EPW without overwriting immutable P7A:
- original station \`tl,rf,p,ff\` from \`klima-v2-1h\`, observed GHI from ten-minute \`cglo\` six-of-six source hours with original quality flags and fixed CET UTC+1 calendar;
- prove original GeoSphere ten-minute \`Mittelwert\` hour-window timestamp semantics before selecting start/end support; preserve both hypotheses in diagnostics until documentary validation;
- model DHI/DNI where no original independent sensors were available in 2013, with source-independent energy closure \`GHI = DHI+DNI cos(zenith)\` and transparent partition method, no unannounced direct merging of NASA-only DNI/DHI and station-measured GHI;
- for 10 missing or incomplete observed-GHI hours (2013 source start-hypothesis), use explicitly flagged alternative NASA POWER GHI or documented physically-based infilling; retain an hourly provenance and input-imputation-mask file, and assess impact on simulation outputs;
- approximate/replace wind direction from an authenticated original ground source if available; otherwise keep NASA source and label it as gridded ancillary data;
- ensure correct EPW source conversions, missing value sentinels and actual EnergyPlus import, not merely 35-field syntax;
- compare 2013 station-first EPW with historical P7A NASA solar source and independent same-provider 23–23 daily \`cglo_j\` as a **source-internal**, not independently calibrated, check;
- keep 2010–2011 ten-minute vs daily provider discrepancies as an earlier research warning; they do not directly disqualify measured GHI in 2013 and must not be silently "fixed".

A separate observational source-run should output percent truly station-observed by variable, per-hour QC, source and physics flags, daily GHI closure and benchmark-derived uncertainty before final acceptance.

**Distinct from P7B**: P7B generates novel hourly weather from original **daily CMIP6** and must not leak **calendar-paired actual observed 2013** weather into CanESM5 synthetic days; only unpaired month/season distributions may be used for P7B historical skill comparisons. P7C would generate future SSP weather using the calibrated and validated P7B method. All remain research-only and \`main\` is untouched.
