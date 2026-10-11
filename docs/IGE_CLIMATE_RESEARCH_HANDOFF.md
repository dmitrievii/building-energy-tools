# IGE CLIMATE RESEARCH — CANONICAL HANDOFF FOR A NEW CHAT

**Project:** climate modelling / research phases P6.1–P6.3E, Graz  
**Status at 2026-10-11 freeze:** Research code up to P6.3E computationally tested; ground hourly solar independently unvalidated.  
**Repo:** \`dmitrievii/building-energy-tools\`. **NO automatic merge into \`main\`.**

## Minimum source-of-truth reading order

1. This file: \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\`.
2. Full verified research lineage: \`docs/IGE_CLIMATE_RESEARCH_MASTER_RECORD.md\`.
3. Methods and publication readiness: \`docs/IGE_CLIMATE_PAPER_EVIDENCE_REGISTER.md\`.
4. Decision chronology: \`docs/IGE_CLIMATE_RESEARCH_DECISION_LOG.md\`.
5. Artifact SHA, source licenses and recovery: \`docs/IGE_CLIMATE_DATA_AND_REPRODUCIBILITY.md\`.
6. Original phase protocols: \`docs/IGE_P6_*.md\`, especially P6.2D / P6.3A–E; source code \`research/ige_cmip6/p6_*.py\`.
7. Original JSON, CSV, model-window source-provenance and SHA inside the portable 81-archive research freeze.

## Code checkpoint

- Last complete scientific execution commit: \`3ef8140a15ee9b9bd3ff209f3f5892b4949025fb\`
- Last successful workflow: [#38129047139](https://github.com/dmitrievii/building-energy-tools/actions/runs/38129047139) — P6.3E, pass.
- Current research documentation branch: \`research/ige-research-preservation-freeze-20261011\` (forked from the successful P6.3E commit).
- \`main\` at freeze: \`2a82a77d0fe8cc87a2324b820d6c6843b6598548\`. **Untouched**.
- The documentation freeze branch may include additional docs and verification script commits beyond the P6.3E execution commit. Check HEAD and CI before deriving future research branch.
- When restarting from a new chat, first fetch these exact files and inspect the actual current GitHub branch/CI rather than presuming remembered results.

## Portable evidence freeze (NOT a persistent institutional deposit)

\`IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip\`  
68,062,328 bytes; SHA256 \`2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7\`.

Contains 40/40 eight-GCM × five-period NASA source-derived ZIPs, 20 original hourly GeoSphere #30 ZIPs (1995–2014), 21 phase result ZIPs, MANIFEST.json/CSV, 467 individual original member hashes and a self-contained verifier. Local verification after unzip PASS. **Ask the user for institutional archive location/URI only if needed and not already present; do not assume it was deposited.** GitHub Actions stored copies expire after 30 days.

## Scientific state

- Training original solar: 1995–2004; holdout 2005–2014.
- NASA NEX 8 GCM × 5 windows (historical 1995–2014 plus SSP245/585 × 2040–2059/2080–2099).
- M0 = NEX original already bias-corrected; M1 monthly ratio; M2 monthly QDM (not daily calibrated); M3 FAO-56 daily clear-sky QDM.
- P6.3A/B: 2 M3 future-multivariate-dependence screen anomalies, scientific REVIEW_REQUIRED, do **not** claim future validation.
- P6.3C: official precipitation \`rr=-1\` dry and \`rr=0\` trace below 0.1 mm; GeoSphere 23–23 UTC solar period vs 06:01–next-day 06:00 precipitation; all 87,648 Graz historical hourly GHI samples q21 unverified.
- P6.3D: NASA POWER gridded, NOT verified ground hourly. Historical daily-aggregate vs accepted GeoSphere \`r≈0.9366\` (Graz), \`r≈0.9635\` (model cell); DO NOT transfer validation to individual hours.
- P6.3E: 2×87,648 original hourly GHI/DNI/DHI/TOA, provisional source-internal solar closure, 565/417 daylight screen exceedances, 0 deep-night source GHI flagged. ARAD Graz precision ground GHI/DNI/DHI/LW candidate identified since Sep 2011; original measured records not obtained.
- \`production_epw_ready=false\`. No measured future projections, no proven hourly physical weather generation or building-energy validation yet.

## Next research phase after freeze

**P6.3F: ARAD Graz original ground radiation acquisition and independent comparison.**
1. Identify ARAD official custodian/access method, available 2012–2014 raw one-minute data, original UTC convention, flags, calibration documents, use/licensing.
2. Obtain explicit access without fabricating data; published QC percentages are NOT the downloaded series.
3. If data can be obtained, align site/date/horizon, aggregate to hourly, hold out validation years, compare NASA POWER measured GHI/DNI/DHI/LW independently.
4. Investigate P6.3E 565/417 closure outliers and uncertainty; do not classify all as numerical defects.
5. Only then plan physical hourly future EPW synthesis and independent building simulation validation.

**Requested GitHub working rhythm:** For a long GitHub Actions CI (typically 5–7 minutes), start it, report workflow/run/commit, **stop polling**. User will say \`проверь\` when complete. Never merge to main without explicit approval.

## Restart prompt (copy verbatim)

> Продолжай научный проект IGE Climate Analyzer из GitHub \`dmitrievii/building-energy-tools\`. Прочитай \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\`, \`docs/IGE_CLIMATE_RESEARCH_MASTER_RECORD.md\`, \`docs/IGE_CLIMATE_RESEARCH_DECISION_LOG.md\`, \`docs/IGE_CLIMATE_PAPER_EVIDENCE_REGISTER.md\` и \`docs/IGE_CLIMATE_DATA_AND_REPRODUCIBILITY.md\` из ветки \`research/ige-research-preservation-freeze-20261011\`. Проверь current GitHub HEAD, не изменяй main. Источники и результаты P6.1–P6.3E зафиксированы в evidence freeze; научный статус REVIEW_REQUIRED, почасовая радиация не валидирована наземными данными. Следующий этап P6.3F ARAD Graz. CI запускай и прекращай polling до моего запроса. При необходимости попроси сам ZIP evidence freeze и сверь SHA.
