# IGE CLIMATE RESEARCH — CANONICAL HANDOFF FOR A NEW CHAT

**Project:** independent climate engine **P1–P5** plus downstream CMIP6 scientific research **P6.1–P6.3E**, Graz  
**Status at 2026-10-11 freeze:** Research code up to P6.3E computationally tested; ground hourly solar independently unvalidated.  
**Repo:** \`dmitrievii/building-energy-tools\`. **NO automatic merge into \`main\`.**

## NEW ACTIVE PHASE P7A — first historical full-hour research EPW (2026-10-11)

**Active branch:** `research/ige-p7a-historical-hourly-epw-reference-20261011`. **Read:** `docs/IGE_P7_HOURLY_SYNTHESIS_EPW_EXECUTION_PROTOCOL.md`, `research/ige_cmip6/p7a_historical_epw_reference.py` and regression/CI `ige-p7a-graz-2013-epw-reference.yml`. User explicitly refocused after P6.3F source-methodology research on end-to-end future climate EPW generation; **the immediate deliverable P7A is a 2013 original-source historical EPW reference** with 8760 hours and exact field/time/unit/provenance verification. Do NOT call P7A `hourly synthesis from daily CMIP6` or `future SSP EPW`; those are **P7B** and **P7C**, respectively.

Historical 2013 benchmark: fixed **CET UTC+1 no DST** for EPW, local first hour equals 2012-12-31 23:00 UTC. GeoSphere Graz station30 original 2012/13 QC `tl/rf/p/ff`, NASA POWER original gridded ancillary meteorology for variables not measured, and P6.3E original NASA POWER 2005–14 GHI/DNI/DHI. Source lineage per hour and original hashes; no fabricated sky cover/illuminance/snow. The reference still requires an actual EnergyPlus model-run proof before being treated as runnable, plus independent hourly synthesis and future-scenario validation later. Never merge to `main` until explicitly requested. P6.3F-B immutable science archives and source uncertainties unchanged.

## Accepted P6.3F-B closeout and immutable addendum — 2026-10-11

**Original scientific run:** [#38135836142](https://github.com/dmitrievii/building-energy-tools/actions/runs/38135836142) SUCCESS; source commit `8d6a0b7d68f97d0a6200877ab75cfd0be4c70615`, original artifact `11700429246`. **Canonical numerical closeout:** `docs/IGE_P6_3F_B_ACCEPTED_NUMERICAL_SCIENCE_CLOSEOUT.md`. Complete source + original results are preserved in portable addendum **`IGE_RESEARCH_P6_3F_GROUND_QC_SOURCE_ADDENDUM_2026-10-11.zip`**, 17,827,987 bytes, SHA256 `78873fb088880688a434bb3caeaa1e14e062028ba455f64859ef31ac0adabb0b`. It contains unchanged original P6.3F and P6.3F-B workflow ZIPs (2 files / 33 verified original artifact members), MANIFEST.json and executable standalone SHA verifier. Both nested original ZIP SHA and member SHA checked after extraction PASS. **NOT** a permanent institutional deposit; keep alongside untouched integrated P1–P6.3E freeze (original integrated SHA `4b5d7dfc4b1805f0a3742e4f6e72ae9474718deb0683b321305f405939d46721`).

**Scientific result:** genuine original ten-minute `chim` q21=0 (not checked, NOT declared false) can support provisional DHI research in **32,239 complete original 6/6 hours** in 2006–2009, correlation NASA POWER r=0.871321, MAE=0.0242561 kWh/m²/hour (record-start hypothesis). GHI 73,393 quality-approved hours. Original source 10min GHI and QC-approved official daily GHI disagree notably during 2010 and 2011 (+0.461663 and +0.285946 kWh/m²/day on fully matched q21-approved days); **which source is incorrect is unknown**. Solar-day [previous 23 UTC, label day 23 UTC) and both 10-min averaging support hypotheses preserved. DHI data in 2010–2014 absent (not merely q0), and original directly measured DNI unavailable. No future EPW validation. Need further investigation of 2010/11 source processing/calibration provenance; cannot force data closure.

## ACTIVE P6.3F-B: Q21=0 is unchecked, NOT proved wrong (2026-10-11)

**Active branch:** `research/ige-p6-3f-b-provisional-dhi-daily-closure-20261011`; parent is successful P6.3F original source branch `research/ige-p6-3f-geosphere-open-10min-qc-2005-2014-20261011`. **Read** `docs/IGE_P6_3F_B_UNCHECKED_SOLAR_RESEARCH_TIERS_AND_DAILY_CLOSURE.md`, `research/ige_cmip6/p6_3f_b_unchecked_diffuse_daily_closure.py` and its test/workflow.

**SCIENTIFIC REVISION:** Official GeoSphere `q21=0 = ungeprüfte Daten` means original observation NOT quality-checked; it does **not** mean measurement physically false. Archive original `chim` (sky diffuse candidate) has numerical source data in 2006–2009: 52,439 / 51,995 / 52,267 / 37,139 original ten-minute values respectively, always q0, and zero source numeric values in 2005 and 2010–2014. Use complete q0 hourly values **provisionally** in exploratory comparison with original NASA POWER DHI, keeping independent qc flags/tiers/physical screens and not describing them as provider-QC-approved. Preliminary original pairs r~0.87–0.88 each year 2006–09; full source-audited CI is the final numerical authority.

**NEW INVESTIGATION:** official quality-approved daily GeoSphere `cglo_j` vs QC-approved 10min `cglo` have substantial original source disagreement in **2010 and 2011**, approx +0.462 and +0.286 kWh/m² per day (strict complete-source matched days). This means approved QC does not prove agreement across provider aggregations. Do not declare either source erroneous or adjust its values to force closure. P6.3F-B analyzes 23–23 UTC solar daily closure by year and both ten-minute timestamp hypotheses and records warnings; this is same-provider source consistency, not independent sensor skill. Exact cause unknown; instrument history and daily processing require investigation.

The existing integrated frozen P1–P6.3E source baseline is unchanged. Full future EPW `production_epw_ready=false`. ARAD email remains UNSENT; data not required merely to explore q0. `main` untouched; start CI and do not poll until the user requests a check.

## Integrated scientific custody added 2026-10-11 (P1–P5 + P6)

**PRIMARY INTEGRATED PORTABLE FILE:** `IGE_CLIMATE_RESEARCH_P1_TO_P6_3E_INTEGRATED_FREEZE_2026-10-11.zip`, **71,193,259 bytes**, SHA-256 `4b5d7dfc4b1805f0a3742e4f6e72ae9474718deb0683b321305f405939d46721`. This contains both ORIGINAL UNMODIFIED releases (P1–P5 Independent Climate Engine v0.4.0 and the previously accepted P6.1–P6.3E archive) and a standalone verifier. It is NOT hosted persistently in public GitHub and must be deposited to approved permanent storage.

**READ FIRST FOR P1–P5:** `docs/IGE_CLIMATE_RESEARCH_P1_P5_BASELINE.md`. P1–P5 release ORIGINAL immutable SHA-256 `6e3dfefe03461feebeef36dd93ce4109861ad862c5e1c8ec312e10e541c57431`; original 166 entries, 164 source-science entries independently SHA-verified. **P5 historical 152/152 PASS** was reported by the frozen v0.4.0 release; not rerun in this freeze. **P1–P5 is NOT the application WEB-0.x roadmap and NOT the P6 methods.** Preserve original standalone P6 SHA `2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7` unchanged.

## P6.3F LIVE GROUND GHI RESULTS — evidence retrieved 2026-10-11

**Successful accepted original-source workflow:** [#38134438339](https://github.com/dmitrievii/building-energy-tools/actions/runs/38134438339), commit `911c781d2b6ba410b175c176c57bee4663c67785`, artifact ID `11700138103`, archived name `ige-p6-3f-open-geosphere-10min-graz-ghi-diffuse-qc-2005-2014` (original 20 year ZIP source members/metadata + QC CSV, NASA hourly metrics). **Read primary science report:** `docs/IGE_P6_3F_GEOSPHERE_10MIN_OBSERVED_RESULTS_2005_2014.md`. All years requested 2005–2014 were downloaded without source errors. GeoSphere station **#30 COMBINED is parent of #16412 INDIVIDUAL**; all original GHI, chim and per-parameter QC observations agree exactly by date 2005–2014 (one source observational series, not two independent validation stations).

Original `cglo` 10-minute QC q21 accepted: **73,393** 6/6 fully approved 1-hour GHI observations (2005–2014: 83.736% of 87,648 hours); **69,913 / 70,128** approved hours during 2007–2014, 99.69%. 2005 zero QC-approved GHI, 2006 partially checked. Provisional `record_start` interpretation versus NASA POWER Graz point: **MAE 0.0383689 kWh/m²/hour, Pearson r 0.9393704, bias POWER minus ground −0.0114482**; `record_end` remains alternative **unresolved**. Original `chim` (Himmelsstrahlung) has **ZERO QC-approved ten-minute records across all 2005–2014**; **NO independent measured DHI skill can be reported**, despite some non-null unchecked source values. DNI is not directly observed in this open set. NO EPW production release.

A science correction to the P6.3F code/tests explicitly detects the station #30/#16412 alias and changes scientific status from mistakenly suggesting source DHI approval to **GHI_ONLY_DHI_UNVERIFIED**. Preserve original archived run evidence and cross-validate any rerun reports; do not rewrite historical source artifacts. ARAD remains optional for GHI but a potential actual ground DNI/DHI source if publication requires them; email not sent.

## P6.3F OPEN 10-minute GEOSPHERE PIVOT — active 2026-10-11

**Current active scientific branch:** `research/ige-p6-3f-geosphere-open-10min-qc-2005-2014-20261011` forked from the P6.3F ARAD-readiness branch. Open `klima-v2-10min` GeoSphere `cglo` (global GHI) and `chim` (Himmelsstrahlung, provisional diffuse sky radiation) with individual original `_flag` quality indicators may establish independent observed 10-minute/aggregated hourly GHI and DHI without a restricted ARAD request. The ARAD German email is **NOT SENT**; ARAD is fallback for genuine DNI, precision sensor comparisons or gaps only.

**Read** `docs/IGE_P6_3F_GEOSPHERE_OPEN_10MIN_GHI_DIFFUSE_VALIDATION.md` and `research/ige_cmip6/p6_3f_geosphere_open_10min_solar_qc.py`. The new separate CI workflow `ige-p6-3f-geosphere-open-10min-solar.yml` audits Graz IDs 30/16412, each 2005–2014 calendar year, original metadata and q21 flags, and pre-registered 10-min record-start/end hypotheses. **No claims** about station-specific QC availability, observed DHI fidelity or relative error may be made until successful original live data retrieval and interpretation of the saved report. Do not inherit GeoSphere hourly `cglo q21=0` failures to 10-minute observations automatically. Preserve original SNAPSHOT SHA and 6/6 minute complete-hour gate.

The previously green [ARAD readiness #38132968798](https://github.com/dmitrievii/building-energy-tools/actions/runs/38132968798) remains evidence of strict scientific custody but **not** ground skill. Historic completed integrated P1–P6.3E freeze unchanged; `main` untouched. Open ten-minute source, not a Meteonorm integration or direct EPW production. `production_epw_ready=false`.

## New active research workstream: P6.3F original ARAD restricted ground reference

The immutable integrated P1–P6.3E research freeze remains the **canonical completed historical baseline**. The new active development branch is `research/ige-p6-3f-arad-ground-validation-gate-20261011` (forked from verified freeze `f284de774f305f2953510b6bf9bb5119c8675451`). Do NOT reclassify P6.3F as independent observational validation until ORIGINAL ARAD Graz 2012–2014 minute readings and custodian metadata/rights are actually received and checked.

P6.3F source discovery confirmed **ARAD data are restricted** (GCOS Austria 2025). Official national contacts: `klima@geosphere.at`, `marc.olefs@geosphere.at`, `florian.geyer@geosphere.at`; University of Graz local station `messung.physik@uni-graz.at`. A ready-to-send **unsent** German request is documented in `docs/IGE_P6_3F_ARAD_GRAZ_DATA_ACCESS_REQUEST_DE.md`.

Read `docs/IGE_P6_3F_ARAD_GROUND_ORIGINAL_VALIDATION_PROTOCOL.md` and `research/ige_cmip6/p6_3f_arad_ground_qc_validation.py`. Public GitHub Action validates frozen P6.3E NASA original 2012–2014 source and deliberately reports `BLOCKED_ARAD_SOURCE_ACCESS_NOT_YET_ACQUIRED`, with null independent skill metrics; it cannot acquire restricted data. Full validation needs explicit original ARAD source bytes with source SHA, custodial authority, BSRN-style original minute QC, UTC conventions and research license. Do NOT upload private originals to public CI or silently replace them by NASA POWER or CAMS satellite/reanalysis grids. `production_epw_ready=false` throughout.

## Minimum source-of-truth reading order

1. This file: \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\`.
2. Full verified research lineage: \`docs/IGE_CLIMATE_RESEARCH_MASTER_RECORD.md\`.
3. Methods and publication readiness: \`docs/IGE_CLIMATE_PAPER_EVIDENCE_REGISTER.md\`.
4. Decision chronology: \`docs/IGE_CLIMATE_RESEARCH_DECISION_LOG.md\`.
5. Artifact SHA, source licenses and recovery: \`docs/IGE_CLIMATE_DATA_AND_REPRODUCIBILITY.md\`.
6. Original phase protocols: \`docs/IGE_P6_*.md\`, especially P6.2D / P6.3A–E; source code \`research/ige_cmip6/p6_*.py\`.
7. Original P1–P5 v0.4.0 immutable release and original P6 JSON/CSV, model-window provenance and SHA in the integrated P1–P6.3E ZIP (two untouched nested source releases).

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

## Active P6.3F preflight — original ground archive request outstanding

**The P6.3F software/QC preparation has PASSED GitHub Actions [#38132968798](https://github.com/dmitrievii/building-energy-tools/actions/runs/38132968798)**; source computation originally validated at `14fad0f088c86ea29086c8d0fc2d8bf37a2c7bd3`. This is a source-access gate **only**, not completed independent ground validation. NASA POWER reference checks 26,304 original 2012–14 UTC hours at each of 2 points (52,608 in total). ARAD real original observation records: **0 acquired**. The output explicitly has `comparison_statistics=null`, `scientific_status=BLOCKED_ARAD_SOURCE_ACCESS_NOT_YET_ACQUIRED` and `production_epw_ready=false`. Research module and custodian request are in this active branch. See `docs/IGE_P6_3F_ARAD_GROUND_ORIGINAL_VALIDATION_PROTOCOL.md` and `docs/IGE_P6_3F_ARAD_GRAZ_DATA_ACCESS_REQUEST_DE.md` (**draft, NOT SENT**).

**Next required action: custodian-authorized original ARAD Graz 2012–2014 one-minute GHI/DNI/DHI/DLW acquisition and independent comparison.**
1. Identify ARAD official custodian/access method, available 2012–2014 raw one-minute data, original UTC convention, flags, calibration documents, use/licensing.
2. Obtain explicit access without fabricating data; published QC percentages are NOT the downloaded series.
3. If data can be obtained, align site/date/horizon, aggregate to hourly, hold out validation years, compare NASA POWER measured GHI/DNI/DHI/LW independently.
4. Investigate P6.3E 565/417 closure outliers and uncertainty; do not classify all as numerical defects.
5. Only then plan physical hourly future EPW synthesis and independent building simulation validation.

**Requested GitHub working rhythm:** For a long GitHub Actions CI (typically 5–7 minutes), start it, report workflow/run/commit, **stop polling**. User will say \`проверь\` when complete. Never merge to main without explicit approval.

## Restart prompt (copy verbatim)

> Продолжай научный проект IGE Climate Analyzer из GitHub \`dmitrievii/building-energy-tools\`. Прочитай \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\`, \`docs/IGE_CLIMATE_RESEARCH_MASTER_RECORD.md\`, \`docs/IGE_CLIMATE_RESEARCH_DECISION_LOG.md\`, \`docs/IGE_CLIMATE_PAPER_EVIDENCE_REGISTER.md\` и \`docs/IGE_CLIMATE_DATA_AND_REPRODUCIBILITY.md\` из ветки \`research/ige-research-preservation-freeze-20261011\`. Проверь current GitHub HEAD, не изменяй main. Источники и результаты P6.1–P6.3E зафиксированы в evidence freeze; научный статус REVIEW_REQUIRED, почасовая радиация не валидирована наземными данными. P6.3F подготовлен: CI #38132968798 PASS, но оригинальный ARAD архив закрыт и ещё не получен; подготовь и отправь запрос ответственным GeoSphere, затем ожидай официальные данные для независимой оценки. CI запускай и прекращай polling до моего запроса. При необходимости попроси сам ZIP evidence freeze и сверь SHA.
