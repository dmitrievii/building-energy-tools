# IGE Climate Analyzer — Scientific Research Master Record

**Freeze date:** 2026-10-11 (Europe/Vienna)  
**Project:** independent, reproducible climate modelling and future weather-generation research for building performance  
**Repository:** [dmitrievii/building-energy-tools](https://github.com/dmitrievii/building-energy-tools)  
**Research lineage last validated:** \`3ef8140a15ee9b9bd3ff209f3f5892b4949025fb\` (P6.3E)  
**Freeze documentation branch:** \`research/ige-research-preservation-freeze-20261011\`  
**Production main at freeze:** \`2a82a77d0fe8cc87a2324b820d6c6843b6598548\` — untouched  
**SCIENCE STATUS: REVIEW_REQUIRED / NO FUTURE-HOURLY-EPW VALIDATION**

## 0. Authority and evidence hierarchy

Scientific facts here are extracted from the successful GitHub Actions reports and their original archived JSON/CSV artifacts, cross-checked with the local portable research freeze. Treat these as evidence, not conversation memory. Every numerical claim requires a source archive, archived path, specific scenario/period and source provenance; convenient summaries or outputs from an earlier chat are secondary. CI PASS means the code executed and declared assertions passed; it **does not** establish independent observational skill.

Canonical handoff: \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\`.  
Methods, metrics and paper candidate: \`docs/IGE_CLIMATE_PAPER_EVIDENCE_REGISTER.md\`.  
Decision log: \`docs/IGE_CLIMATE_RESEARCH_DECISION_LOG.md\`.  
Data custody: \`docs/IGE_CLIMATE_DATA_AND_REPRODUCIBILITY.md\`.

## 1. Research objective and scope

Investigate a reproducible pipeline for climate source ingestion, ground-observed comparison, multivariate consistency, local bias adjustment, climate-change signal preservation and possible later derivation of hourly building simulation weather inputs. This is **not** an integration of proprietary Meteonorm software; Meteonorm-generated EPWs are external user-controlled validation examples, not included in this public archive or freeze bundle.

Do not conflate CMIP6 **SSP** experiments with Meteonorm 8 **RCP** EPW scenarios. Neither future temperature nor future hourly radiation can be observationally validated.

Historical station reference: GeoSphere Austria, Graz Universität station **#30**; solar observation \`cglo_j\` source unit J/cm², \`kWh/m²/day = J/cm² ÷ 360\` when originally QC-approved. Different GeoSphere daily variables have different clock windows. GCM historical dates are *not* paired to observational dates as if they describe the same weather events.

Climate models (8): ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR, MPI-ESM1-2-HR, MRI-ESM2-0, NorESM2-MM.

Five source model windows (each ~20 years):
- \`historical-1995-2014\`
- \`ssp245-2040-2059\`
- \`ssp245-2080-2099\`
- \`ssp585-2040-2059\`
- \`ssp585-2080-2099\`

The models and years are explicitly encoded in **40 frozen P6.1 source-derived ZIP artifacts**. Most are supplied as native daily CSV plus source trace (original NASA NCSS NetCDF subset URLs and SHA), rather than as all upstream NetCDF byte streams.

## 2. Experiment stage chronology — verified accepted runs

| Stage | GitHub Actions successful run | Source code / protocol | Narrow claim supported |
|---|---|---|---|
| P6.1 daily/multivariate | [38066587048](https://github.com/dmitrievii/building-energy-tools/actions/runs/38066587048), [38067931031](https://github.com/dmitrievii/building-energy-tools/actions/runs/38067931031) | \`research/ige_cmip6/p6_daily_multivariable.py\`, \`p6_access_full_period.py\` | NASA original daily provenance and first ACCESS-CM2 multivariate source |
| P6.1 seven-GCM repair | [38077903914](https://github.com/dmitrievii/building-energy-tools/actions/runs/38077903914) | \`p6_seven_repair_stage.py\` | Historically failing source windows corrected and source availability checked |
| P6.2A eight GCM | [38081529709](https://github.com/dmitrievii/building-energy-tools/actions/runs/38081529709) | \`p6_2a_eight_model_ensemble.py\` | Eight-model 5-window climate comparison, station bridge |
| P6.2B station hourly | [38082122721](https://github.com/dmitrievii/building-energy-tools/actions/runs/38082122721) | \`p6_2b_hourly_observations.py\`, \`p6_2b_hourly_archive_audit.py\` | GeoSphere #30 1995–2014 original hourly source/QC: 175,320 UTC hours |
| P6.2B solar source | [38084157993](https://github.com/dmitrievii/building-energy-tools/actions/runs/38084157993) | \`p6_2b_solar_reference_audit.py\` | Independent daily solar source, temporal window and solar bias identified |
| P6.2B source forensics | [38085165876](https://github.com/dmitrievii/building-energy-tools/actions/runs/38085165876), [38086631124](https://github.com/dmitrievii/building-energy-tools/actions/runs/38086631124) | \`p6_2b_solar_bias_triangulation.py\`, \`p6_2b_gmfd_direct_source_forensics.py\` | Historical radiative source discrepancy and GMFD/NASA source lineage |
| P6.2D baseline correction | [38088092141](https://github.com/dmitrievii/building-energy-tools/actions/runs/38088092141) | \`p6_2d_solar_methods_benchmark.py\` | Historical calibration 1995–2004, independent holdout 2005–2014 |
| P6.2D-B daily clear-sky QDM | [38089064925](https://github.com/dmitrievii/building-energy-tools/actions/runs/38089064925) | \`p6_2d_b_daily_clearsky_benchmark.py\` | M3 daily clear-sky index and solar physical envelope |
| P6.2D-C future sensitivity | [38090002603](https://github.com/dmitrievii/building-energy-tools/actions/runs/38090002603) | \`p6_2d_c_sensitivity_future_signals.py\` | Four method/scenario original future signal sensitivity, NOT multivariate closure |
| P6.3A multivariate joint | [38123017733](https://github.com/dmitrievii/building-energy-tools/actions/runs/38123017733) | \`p6_3a_solar_joint_coherence.py\` | 40-source dependence structure, two M3 effect-size warnings, REVIEW_REQUIRED |
| P6.3B observed references | [38124674795](https://github.com/dmitrievii/building-energy-tools/actions/runs/38124674795) | \`p6_3b_independent_reference_sources.py\`, \`p6_3b_anomaly_attribution_and_observed_validation.py\` | Reproduced M3 anomalies; independent GeoSphere/PPOWER historical comparisons |
| P6.3C precipitation/UTC | [38126567048](https://github.com/dmitrievii/building-energy-tools/actions/runs/38126567048) | \`p6_3c_precip_semantics_daily_alignment.py\`, \`p6_3c_hourly_original_source_alignment.py\` | Official GeoSphere \`rr=-1\` dry, \`rr=0\` trace, UTC lag/donor QC |
| P6.3D independent hourly proxy | [38128314291](https://github.com/dmitrievii/building-energy-tools/actions/runs/38128314291) | \`p6_3d_hourly_satellite_reference_validation.py\` | NASA POWER hourly source vs QC-approved DAILY GeoSphere, gridded proxy only |
| P6.3E solar components | [38129047139](https://github.com/dmitrievii/building-energy-tools/actions/runs/38129047139) | \`p6_3e_hourly_solar_components_arad.py\` | 2 sites × 2005–2014 source-internal GHI/DNI/DHI/TOA checks, ARAD NOT ACQUIRED |

Intermediate failed workflows are part of the code/debug provenance, **not** scientific evidence.

## 3. Corrected solar methods

All share NASA NEX-GDDP-CMIP6 original data and accepted historical station solar calibration; label them precisely:

- **M0**: original NASA NEX-GDDP-CMIP6 \`rsds\`, itself already subject to NASA downscaling and original BCSD processing, **not uncorrected raw GCM radiation**.
- **M1**: historical monthly GHI mean-ratio calibration; source-day monthly proportional factor.
- **M2**: monthly multiplicative QDM and uniform scaling within each model-month to conserve monthly corrected energy. **Not a fully calibrated daily QDM**.
- **M3**: daily clear-sky-index QDM using FAO-56 \`Ra\`/\`Rso\`, provenance-specific elevation approximation and explicit physical cap \`min(Ra, 1.10 * Rso)\`. A research variant, not a claim of publication-standard exact method.

Training/calibration 1995–2004, historical evaluation 2005–2014; future SSP source windows above. M1/M2 monthly energy conservation is not equivalent to plausible intra-day coherence.

## 4. Main numerical results (from frozen original evidence)

### P6.3A and P6.3B: two physical-dependence concerns

Across 8 models × 5 windows × 4 methods × 5 seasons × 5 relationships, P6.3A identified **2** model/season/relationship correlation effect-size threshold crossings and status \`REVIEW_REQUIRED\`. P6.3B independently reproduced from original model sources:

| Case | Future SSP window, JJA | Change in correlation climate-change signal induced by M3 (Pearson) |
|---|---|---:|
| CanESM5 \`tas ↔ rsds\` | \`ssp585-2080-2099\` | +0.10090383691079702 |
| IPSL-CM6A-LR \`rlds ↔ rsds\` | \`ssp585-2080-2099\` | +0.13913161372266142 |

These are **screen distortions**, not a demonstrated failure of future climate against observations. The historical external comparisons do not verify the 2080–2099 future daily physical truth.

### P6.3C: official precipitation sentinel and clock semantics

Official \`klima-v2-1d\` metadata: \`rr=-1\` means **no precipitation**, i.e. clean 0 mm if QC-accepted; \`rr=0\` means **trace below 0.1 mm**, not a proven dry day. Source raw values and q21 remain preserved. Graz #30 in 2005–2014:
- 3,652 daily reference records;
- 2,122 days \`rr=-1\` (verified dry);
- 163 days \`rr=0\` (interval-censored trace);
- 399 light precipitation (0–1 mm) and 968 precipitation ≥1 mm.

GeoSphere \`cglo_j\` daily integrates **23:00 previous UTC to 23:00 labelled UTC**; daily \`rr\` integrates a different 06:01-to-next-day-06:00 UTC interval. A source label is NOT synonymous with synchronized measurement windows.

GeoSphere original 2005–2014 hourly \`cglo\`: **87,648 original hours, zero hours with accepted q21**; \`q21=0\` is **ungeprüfte Daten (unchecked)**. Close agreement with accepted daily GHI does not certify an hourly station truth.

### P6.3D: gridded hourly external proxy, daily comparison

NASA POWER hourly native UTC source from two locations compared with accepted GeoSphere **daily** solar for 2005–2014 (3,652 days/site), GeoSphere 23–23 UTC window.

| Metric | near Graz station | NASA model cell |
|---|---:|---:|
| daily Pearson \`r\` | 0.9365886441374048 | 0.9634951684310117 |
| MAE kWh/m²/day | 0.5880715017648959 | 0.434548460813034 |
| mean bias kWh/m²/day | -0.1738931678231654 | +0.05874568486029573 |
| complete-day coverage | 100% | 100% |

NASA POWER is not an independent instrument at Graz. Do not assign an hourly observation label to it. Good daily totals do not validate DNI/DHI decomposition.

### P6.3E: physical component/geometry screening

Two sites × 87,648 UTC source hours (2005–2014) = **175,296** complete hourly NASA POWER source records, source-internal \`GHI ≈ DHI + DNI cos(zenith)\` screening with independent approximate solar midpoint geometry:

| 2005–2014 annual diagnostic | near Graz | NASA cell |
|---|---:|---:|
| daylight hours | 41,712 | 41,640 |
| daylight closure MAE kWh/m²/hour | 0.017537910919077592 | 0.01612799184589507 |
| above provisional closure review screen | 565 (1.35%) | 417 (1.00%) |
| deep-night GHI > screening threshold | 0 | 0 |

Thresholds are **provisional screens**, not authoritative pass/fail scientific physical-closure tolerances; a GHI+DNI+DHI source-internal closure cannot establish independent observational correctness.

## 5. Publication stance and non-negotiable limitations

Publication-candidate evidence includes traceable source QC discoveries, source integration-period mismatch, solar correction benchmark, multivariate dependence distortion, multi-station comparison, and independent NASA POWER/GeoSphere comparison with explicit limits. See Paper Evidence Register.

**Unfinished scientific work:**
- independently measured ground hourly GHI/DNI/DHI/downwelling longwave; ARAD Graz since Sep 2011 identified, **original raw observations/QC/permission not yet acquired**;
- source-representative validation beyond Graz and satellite vs ground spatial mismatch;
- subdaily solar distribution, terrain horizon, cloud/aerosol, direct/diffuse and multispecies humidity/pressure consistency;
- source-specific per-GCM licensing and long-term immutable repository deposit;
- out-of-sample building energy simulation validation; no physical coupled future hourly weather synthesis passed.

Do not describe P6.3E as validated ground hourly radiation. Do not merge research code into production without independent scientific and engineering acceptance.

## 6. Portable evidence frozen locally, not published in the public repository

Portable file: \`IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip\`  
Size: **68,062,328 bytes**  
SHA-256: **\`2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7\`**

Verified after independent unzip:
- **81 nested original workflow ZIPs** (40 NASA GCM-window + 20 GeoSphere original hourly years + 21 research-stage evidence bundles);
- **467** internal evidence members with individual SHA-256;
- 40/40 GCM-window combinations and 20/20 years; annual original 175,320 hours expected;
- zero detected ZIP/CRC/SHA mismatches.

**Custody warning:** this archive currently exists as a ChatGPT downloadable research package, not as a permanent TU Graz or GitHub Release deposit. The exact institutional permanent location and record identifier are **PENDING USER DEPOSIT**. Do not claim the freeze is institutionally archived until an independently verified deposit location and checksum exist. Do not upload original data blindly to the public repository; NASA NEX-GDDP/CMIP6 per-model use rights require review.
