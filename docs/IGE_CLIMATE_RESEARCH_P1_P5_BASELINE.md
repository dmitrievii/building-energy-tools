# IGE Climate Analyzer — Pre-P6 Scientific Baseline P1–P5 (Independent Climate Engine v0.4.0)

**Source-release date:** 2026-10-10. **Integrated archive date:** 2026-10-11.  
**Scientific status:** P5 formally CLOSED for its documented research scope; **not approved** for production or physically coherent future hourly EPW.  
**Authority:** Original immutable release \`IGE_Independent_Climate_Engine_v0.4.0_P5_CLOSED_2026-10-10.zip\`, not a reconstructed conversational summary.

## Why P1–P5 must be kept alongside P6

P6.1–P6.3E investigates independent source integrity, bias adjustment of solar radiation, cross-variable coherence and original-hourly solar physics. That later research is **not the original development history**. P1–P5 established the earlier independent, mostly monthly climate engine and contains original benchmarks, climate maps, local stations, baseline adjustments and ensemble implementation. Both lineages are required to evaluate the scientific evolution of the Climate Analyzer and to support a paper about the whole research program.

**Do not conflate P1–P5 with WEB-0.x application development, with the experimental Meteonorm 8 proprietary software, or with the later P6 research.**

## Verified phase inventory from the actual P5 original release

| Stage | Evidence and methodological scope | Main evidence files inside the original release |
|---|---|---|
| P1 — historical future-climate map/raster benchmark | Independent decoding and spatial/temporal validation of existing IPCC/RCP monthly references against benchmark locations; Vienna, Graz and Tripoli examples; benchmarking the behavior of Meteonorm-like references **without reproducing/providing proprietary code or datasets** | \`benchmark_only/p1_meteonorm8_raster_reference.py\`, \`research_evidence/P1_GRAZ_RU.md\`, \`P1_TRIPOLI_RU.md\`, \`P1_VIENNA_SEED2_AND_INTERPOLATION_RU.md\`, P1 scorecards and figures |
| P2 — urban climate/UHI | Urban climate distributions and selected heat-island effects; urban/monthly research contracts, Vienna urban EPW illustrative comparisons | \`benchmark_only/p2_urban_audit.py\`, \`p2_urban_reference.py\`, \`climate_engine/urban.py\`, \`research_evidence/P2_URBAN_RU.md\`, P2 CSV/figures |
| P3 — observed-station/spatial bridge | GeoSphere station observations, local interpolation, altitude/period bridging, solar station comparison; distinguishes station accuracy from neighboring gridded products | \`benchmark_only/p3_published_interpolation_reference.py\`, \`climate_engine/stations.py\`, \`spatial.py\`, \`period_bridge.py\`, \`research_evidence/P3_OBSERVED_TEMPERATURE_RU.md\`, \`P3_STATION_SOLAR_RU.md\`, station QC source and scorecards |
| P4 — independent modern scenarios/source bridge | CMIP6/SSP integration, historical reference period harmonization, NASA NEX-GDDP-CMIP6 solar research, CCKP temperature and precipitation delta indicators, source provenance | \`climate_engine/cckp.py\`, \`cmip6.py\`, \`solar_bridge.py\`, \`docs/P4_REAL_CMIP6_SOLAR_RESULTS_RU.md\`, \`docs/CMIP6_SSP_INTEGRATION_RU.md\`, source provenance |
| P5 — eight-GCM monthly solar ensemble closeout | 8 models, historical 1995–2014, SSP245/585 windows 2040–2059 and 2080–2099; original source-derived radiation provenance, period-bridged observed Graz GHI, monthly solar ratios and ensemble p10/p50/p90 **as descriptive model spread**, not predictive confidence; P5 closeout validation | \`climate_engine/solar_ensemble.py\`, \`docs/P5_MULTIMODEL_CMIP6_SOLAR_RU.md\`, \`docs/P5_CLOSEOUT_RU.md\`, \`results/multimodel_solar/\`, \`research_sources/nasa_gddp_ensemble/\`, \`results/all_tests_v040.log\` |

**Authoritative P5 release properties:**
- Original ZIP has **166 entries**, including \`MANIFEST.json\` and \`build_manifest.py\`; **164 original science files** are enumerated with individual sizes and SHA-256.
- Integrity: all 164 recorded P5 file SHA-256 values have been independently rechecked against the original ZIP.
- P5 original release reports **152/152 tests PASS**. This is a recorded historical result, **not** a claim that all P5 code was rerun in the present preservation operation.
- Eight GCMs are ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR, MPI-ESM1-2-HR, MRI-ESM2-0, NorESM2-MM.
- The P5 archived research reports **800 model/year NASA spatial subsets, 9,600 year-month records**, plus model-source hashes. Original upstream annual NetCDF files themselves were not redistributed.
- Graz original GeoSphere observed solar normal is 1991–2020, with model-specific 1995–2014 reference bridging. Unlike P6 daily solar correction, P5 uses a **monthly multiplicative delta-change** on station observed GHI.
- NASA NEX \`rsds\` is a source that already underwent its own downscaling/bias correction; it is not raw uncorrected GCM output.
- P5 temperature/precipitation monthly indicators and P5 solar ensemble are **hybrid, not one coherent multi-variable member**.
- Proprietary Meteonorm original binary data and the user’s Meteonorm scenario EPWs are **excluded**.
- P5 research closure explicitly denied production readiness.

## Reproducibility without replacing original results

### P5 source ZIP — immutable primary evidence

\`IGE_Independent_Climate_Engine_v0.4.0_P5_CLOSED_2026-10-10.zip\`  
Size: \`3,126,846\` bytes  
SHA-256: \`6e3dfefe03461feebeef36dd93ce4109861ad862c5e1c8ec312e10e541c57431\`.

The P5 release ships \`requirements.txt\` and executable Python code:
\`\`\`sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m tools.run_solar_ensemble
python tools/plot_solar_ensemble.py
\`\`\`
Recorded (not freshly rerun): \`152/152\` PASS. Compare new results against original \`results/\`, do not overwrite baseline.

### P6 source ZIP — separate immutable research evidence

\`IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip\`  
Size: \`68,062,328\` bytes  
SHA-256: \`2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7\`.

P6 contains 81 ZIPs (40 model windows, 20 original GeoSphere annual hourly archives, 21 research result archives) plus its original verifier and manifest. P6 scientific status remains **REVIEW_REQUIRED**, and \`production_epw_ready=false\`.

### Integrated preservation wrapper (NEW)

\`IGE_CLIMATE_RESEARCH_P1_TO_P6_3E_INTEGRATED_FREEZE_2026-10-11.zip\`  
Size: \`71,193,259\` bytes  
SHA-256: \`4b5d7dfc4b1805f0a3742e4f6e72ae9474718deb0683b321305f405939d46721\`.

This is a **nested ZIP preservation wrapper**, not a recomputed scientific release: it retains exact original bytes of both archives, a new outer \`MANIFEST.json\`, README and \`verify_integrated_freeze.py\`. The integrated verification checked both original whole-ZIP SHA256 hashes, internal ZIP CRC and 164 P5 original science hashes. The independent P6 scientific archive’s previous 81-source validation remains available unchanged.

## Scientific and legal caution

The repository is PUBLIC; do **not** commit the integrated original-data ZIP or release third-party model data publicly without a dataset-specific license/IP review. The local portable archive is **not** an institutional data deposit: original frozen ZIP and resulting wrapper must be copied to university-approved long-lived storage, and a stable URI plus depositor/access policy and restore test must be recorded separately.

## Paper claims and implications

P1–P5 documents the initial scientific methodology and infrastructure; P6 documents subsequent daily/source-physical investigations. A paper spanning both should report P5 monthly delta-change outcomes distinctly from P6 M1/M2/M3 comparison, avoid conflating RCP with SSP, never describe the selected eight-model quantiles as rigorous predictive uncertainty, and state when validation is numerical/source-internal rather than independently observed.
