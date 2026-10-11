# IGE Climate Analyzer — Paper Evidence Register and Figure/Table Backlog

**Draft target:** peer-reviewed building simulation / climate-engine paper. Journal/volume/format remain to be confirmed independently when manuscript preparation begins. This file describes experimentally supported evidence, not a claim of journal acceptance, method novelty or fully validated EPW engine.

## Earlier science and source evidence — P1–P5 added to the paper archive

The portable integrated science freeze now also contains the immutable pre-P6 research release **Independent Climate Engine v0.4.0**, 10 October 2026 (164 internally SHA-verified science files, recorded 152/152 tests passing). Primary original P1–P5 methodological evidence: benchmark studies of climate raster decoding and spatial/temporal interpolation; urban heat island and urban climate distributions; GeoSphere station/geographic/altitude/source-quality comparisons; CCKP/CMIP6 reference period and solar-source harmonization; eight GCM **monthly hybrid** GHI ensemble and source uncertainty. See `docs/IGE_CLIMATE_RESEARCH_P1_P5_BASELINE.md` and the original P5 `docs/INTEGRATED_SCIENTIFIC_REPORT_RU.md`, `docs/P5_CLOSEOUT_RU.md` inside the private original release.

For any future manuscript, distinguish **P5 monthly hybrid delta transfer** from **P6 model/source-side temporal and multivariate bias correction**, explicitly separate numerical tests, same-source closure checks, independent GeoSphere observations, external gridded NASA POWER, and still-unavailable ARAD precision hourly observations. The existing P6 evidence remains unchanged and P6 EPW validation remains open. The new integrated release is not publicly published or institutionally deposited.

## P6.3F — ground-hourly evidence currently blocked (2026-10-11)

Research protocol: `docs/IGE_P6_3F_ARAD_GROUND_ORIGINAL_VALIDATION_PROTOCOL.md`. Official GCOS source access is restricted, and original ARAD Graz 2012–2014 minute measurement files/metadata are **not acquired**. Successful source/QC-preflight CI [#38132968798](https://github.com/dmitrievii/building-energy-tools/actions/runs/38132968798) verified P6.3E source SHA, 26,304 UTC NASA POWER historical hours per location, and 20 automated tests, but yielded **no actual ARAD-vs-POWER observed scores**. `comparison_statistics=null` by design. **Do not show P6.3F as an observational results section until actual source-custodian-approved ARAD data exist.** German ARAD request drafted, not sent. Scientific manuscript may include the independent-ground-data gap as an explicit limitation, not substitute satellite products as independent station observations.

## P6.3F Open GeoSphere ten-minute radiation test — source in progress

The project's ARAD-restricted-source preflight remains a legitimate archival negative finding, but its **necessity** was superseded by a new GeoSphere 10-minute audit. The official open `klima-v2-10min` includes `cglo` and `chim` and distinct parameter quality flags. The new independent observational study is **only scientifically completed** if Graz 30/16412 2005–2014 source-specific flags, 10-minute data coverage, official timestamp semantics, and sensor diffuse-horizontal definition support accepted 6-of-6 hourly GHI/DHI. Until actual original API results are accepted, manuscript tables must show coverage/skill as PENDING, not impute ARAD or NASA proxy data. Measured direct-normal DNI is **not** supplied by `chim` and requires a different observational reference for fully independent beam irradiance validation. Earlier P6.3E claims remain source-internal only.

## P6.3F true open-data ground results — evidence updated 2026-10-11

**New independent historical GHI validation:** GeoSphere `klima-v2-10min cglo` yields 73,393 6/6 q21-approved hourly observations out of 87,648 in 2005–2014 (2007–2014: 69,913/70,128 = 99.69%). Original source-vs-NASA POWER Graz point hour-`record_start` hypothesis: Pearson r 0.9393704, MAE 0.0383689 kWh/m² per hour, RMSE 0.0810568, NASA−ground bias −0.0114482. Interval timestamp semantics are UNRESOLVED; the alternative end-label hypothesis and site/instrument representativeness must remain reported.

**Critical correction to paper tables:** `chim` has **zero approved per-original QC slots** across all ten years for Graz #30/#16412; its occasionally populated unchecked values are **not measured DHI ground reference for scientific validation**. No independent DHI/DNI ground performance statistic exists. The combined station #30 and child #16412 return identical observed radiation/QC series and represent only **one independent station**, not two replicated measurement sites. See `docs/IGE_P6_3F_GEOSPHERE_10MIN_OBSERVED_RESULTS_2005_2014.md`, successful source-run #38134438339 and archived originals. Future figures must not plot zero-source DHI performance or treat combined station IDs as independent sources. Prod EPW remains blocked.

## P6.3F-B — Distinguish source-QC uncertainty from measurement error and product inconsistency

Do not equate GeoSphere `chim_flag=0` with invalid radiometry. Original `chim` (Himmelsstrahlung) values exist from 2006–2009; use source-original complete six-of-six q0 observed hours for **provisional methodological benchmarking**, source physical checks and NASA POWER satellite/reanalysis DHI comparison, always labelling original provider-QC uncertainty. Initial independent frozen-source calculation gives DHI correlations of ~0.87–0.88 (2006, 2007, 2008, 2009 respectively). These indicate a potentially useful climatic signal, not certified sensor accuracy. Archive: `docs/IGE_P6_3F_B_UNCHECKED_SOLAR_RESEARCH_TIERS_AND_DAILY_CLOSURE.md` and frozen source provenance from P6.3F, D and E.

**New internal contradiction:** Official GeoSphere provider-quality-approved 10-min and daily GHI records at Graz differ materially in 2010–2011 (around +0.46 and +0.29 kWh/m² per QC-complete observed daily comparison). This demands instrument/source-version/date-aggregation investigation and explicit uncertainty reporting. Positive QC flags on each product are not proof of agreement, and q0 alone is not evidence of poor physical accuracy. Both record-start and record-end 10-minute mean timestamp hypotheses remain provisional. Figures for a future paper should explicitly compare approved-vs-unchecked cohorts, yearwise solar-day closure, and radiation-partition provisional results without treating q0 and provider-certified samples as one statistical class.

## Candidate main question

How can a reproducible source/QC and correction framework produce scientifically auditable local climate-change inputs for building simulation while identifying the limitations of single-variable solar bias adjustment and temporal/multivariate physical coherence?

## Preliminary paper narrative

1. **Motivation / research gap:** official observed climate, GCM-derived local projections and hourly building weather inputs are different statistical objects; solar flux source differences, QC interpretation and time integration semantics can dominate apparently small calibration errors.
2. **Source collection and provenance:** 8 NEX-GDDP-CMIP6 GCMs × five original 20-year windows (40 native-derived model products), GeoSphere station #30 daily and 1995–2014 hourly source/QC (175,320 UTC hours), NASA POWER gridded short/longwave; original NCSS subset provenance and SHA. The climate model is not Meteonorm and RCP cannot be silently recoded as SSP.
3. **Four solar approaches:** M0 original already-downscaled NASA, M1 ratio, M2 *monthly* QDM redistributed proportionally within each model month, M3 *daily* FAO-56 clear-sky index QDM. Calibration 1995–2004 and independent historical holdout 2005–2014; explicitly separate monthly accuracy, intra-month distribution, dependence, future signal and source physical envelope.
4. **Observed data science/QC:** GeoSphere \`rr=-1\` means dry, \`rr=0\` means <0.1 mm trace; GHI station daily time 23–23 UTC vs precipitation different window; hourly station GHI q21=0 unverified. Sensitivity of lagged correlations and four regional sites.
5. **Physical dependence and scenario signal:** Model-source temperature/GHI, precipitation/GHI, humidity/GHI, wind/GHI, longwave/GHI correlations per season, M0–M3. Report two M3 future delta-r discrepancies but do not call them future observation errors.
6. **Independent historical external source comparison:** NASA POWER hourly satellite/reanalysis GHI against accepted GeoSphere *daily* GHI at station and model cell, quantified correlation/MAE, no assertion that hourly satellite flux is validated against a measured hourly instrument.
7. **Source-internal hourly solar closure and limits:** GHI/DNI/DHI/TOA/clear-sky source consistency (2 sites × 2005–2014, 175,296 records), approximate independent solar geometry and night checks. Distinguish physical screening from independent radiometry.
8. **Future work before simulation-grade weather:** obtain original ARAD Graz 2012–2014 quality-flagged minute radiation and prove DNI/DHI hourly skill; multivariate hourly meteorology, direct/diffuse partition, sky longwave, psychrometric pressure and building-energy sensitivity.

## Evidence status per publication deliverable

| Paper exhibit | Source / dataset | Quantitative or factual statement | Readiness |
|---|---|---|---|
| Figure 1 — source and QA dataflow | P6.1–P6.3E protocols | 8 GCM × 5 windows + GeoSphere #30 + NASA POWER; source and QC branches distinguished | Can draft from source files |
| Table 1 — provider sources/license/time/units | P6.1 \`source_provenance.json\` × 40; P6.2B, P6.3C/D/E | GCM model/member/scenario, period, unit, QC, station vs grid and monthly/daily/hourly integrals | Data available, cmip6_license review still required |
| Figure 2 — historical heldout solar skill by M0–M3 | \`IGE_P6_2D_B_CLEARSKY_HOLDOUT_8GCM.zip\`, \`IGE_P6_2D_SOLAR_METHODS_HOLDOUT_1995_2014.zip\` | Per-model test metrics on *historical* 2005–2014 holdout | Candidate; extract explicit sample sizes/CI before manuscript |
| Figure 3 — future solar signal sensitivity | \`IGE_P6_2D_C_FUTURE_SENSITIVITY_RESULTS.zip\` | 8-GCM SSP245/585 × 2040–2059/2080–2099 change, method sensitivity | Candidate; no future observational verification |
| Figure 4 — multivariate structure from M0–M3 | P6.3A \`p6_3a_solar_joint_seasonal_correlations.csv\`; \`p6_3a_historical_to_future_dependence_signal_drift.csv\` | Pearson/Spearman dependence and two M3 case studies | Candidate; scientific REVIEW_REQUIRED |
| Figure 5 — independent historical observed joint climate | P6.3B original GeoSphere/NASA POWER and \`p6_3b_independent_station_and_gridded_reference_JJA.csv\`; P6.3C multi-station | Observed/reference summer T/GHI, RH/GHI, precipitation/GHI, proxy LW/GHI, bootstrap/lag limitations | Candidate; compare harmonized dates/windows, don't pair GCM years |
| Table 2 — precipitation code and QC scientific correction | P6.3C frozen original metadata and original station 3652-daily rows | \`rr=-1\`: 2,122 verified dry; \`rr=0\`: 163 trace; 399 light & 968 ≥1 mm | Ready as *descriptive* QC result |
| Figure 6 — original hourly solar QA boundary | P6.2B hourly original, P6.3C original hourly report | 87,648 original 2005–2014 GHI hours all q21=0 (unchecked); daily QC separately passed | Ready, explain QC code definition |
| Figure 7 — satellite hourly source → station daily agreement | P6.3D CSV and original hourly NASA POWER | Daily 2005–2014 Pearson 0.9366/0.9635, MAE 0.5881/0.4345 kWh/m²/d | Ready for gridded-versus-daily-reference descriptive comparison, not hourly truth |
| Figure 8 — GHI/DNI/DHI closure by hour/season | P6.3E 175,296 hourly source records | Daylight closure MAE 0.01754/0.01613 kWh/m²/h; 565/417 screen exceedances | Ready for diagnostic figure, threshold should be tested |
| Table 3 — independent measured hourly radiometry | Future P6.3F ARAD | Original quality-flagged GHI/DNI/DHI/LW 2012–2014, site/time/QC matching | **MISSING / DO NOT CLAIM VALIDATION** |
| Figure 9 — building performance consequence | Future case-study simulations/EPW | Solar gains, overheating risk, heating/cooling deltas under historically calibrated/future scenarios | **NOT COMPUTED** |

## Candidate contribution types — do not overclaim

- Auditable open-source architecture for climate source provenance and acceptance gates.
- Identification of non-trivial source/QC semantics and 23–23 UTC daily solar integration that commonly make simple weather comparisons biased.
- Numerical comparison of one-dimensional solar correction variants and implications for **multivariate dependence climate-change signal**.
- Detailed documentation of negative results / method hazards, e.g. verified daily vs unverified hourly GHI and 2 flagged future structural M3 cases.

A paper intended to demonstrate a *complete simulation-ready future weather engine* requires more evidence than currently exists. If publication is drafted now, frame as source-QC/method-validation/multivariate-dependence methodological research, not validated future hourly EPW generation.

## Required independent checks before article submission

- [ ] Confirm original model NetCDF \`cmip6_license\` by model and exact source product; decide redistribution rights.
- [ ] Review numerical reference comparisons in actual CSV (sample counts, uncertainty and temporal conventions), not assistant summaries.
- [ ] Check bootstrap setup, cross-model uncertainty, temporal autocorrelation and multiple testing across 3,200 screens; report false-positive context.
- [ ] Predefine effect-size thresholds before interpreting future scenario results; consider alternative solar-geometry formulations and observational constraints.
- [ ] Obtain and validate original ARAD radiometry rather than relying on network QC percentages in literature.
- [ ] Verify independence of calibration vs validation station products and underlying satellite/reanalysis model sources.
- [ ] Select an explicit scientific manuscript hypothesis, figures, section structure and reproducible figure generator.
- [ ] Decide which licensed data can be publicly deposited, and publish DOI/data availability statement.
- [ ] Add original model source CMIP6 and GeoSphere/NASA acknowledgments, licensing and separate Meteonorm proprietary-data statement.

## Source citations to retain

- NASA NEX-GDDP-CMIP6 v2 Tech Note (NASA NCCS) and underlying CMIP6 original model/license provenance: https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf
- GeoSphere Austria dataset API \`klima-v2-1d\` original metadata and data terms: https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d/metadata ; https://dataset.api.hub.geosphere.at/v1/docs/user-guide/license.html
- NASA POWER official API: https://power.larc.nasa.gov/docs/services/api/temporal/hourly/
- ARAD precision radiation source and station: https://climatephysics.uni-graz.at/en/meteorological-station/
- Original ARAD network scientific dataset reference: Olefs et al. (2016), Atmospheric Measurement Techniques, https://amt.copernicus.org/articles/9/1513/2016/

**Important:** These source links must be rechecked for a final paper bibliography, including permanent DOI and exact author/year; tool-source citations above do not constitute a complete journal-style reference list.
