# IGE P8.4 — Wind Generation & Physical Closure: preregistered architecture and A1 source audit

**Frozen before running new original-source P8.4A CI (2026-10-16).** Branch `research/ige-p8-4-wind-closure-20261016`, base F3 report head `43522a08ee19ecacc8c0bbfe6f2f60a2cee0b21b`. **Research only.** No merge, EPW wind substitution, or Streamlit changes.

## Formal outputs and stage acceptance

A. **Wind Source Semantics & Quality Closure** — inspect original source-provided parameter metadata, timestamp conventions, aggregation kinds, quality flags, heights and coordinate semantics; independent field value checks. Distinguish documented facts from empirical clock hypotheses. A1 is a *limited original-source pilot*; full A requires observational aggregation closure (prefer verified 10-min samples reconstructed into 1h observations), hourly source interval proof, site-specific instrument exposure and QC resolution, direct ERA5 u/v or verified gateway transformations. Reject unsupported log-profile 10m correction.
B. **Historical Wind Spatial Reconstruction** — **full donor census**, qualified 90% data, P8.3D altitude ranking vs geographic-only and DEM candidates, time/site/region holdouts, stratification valley/slope/flat, exposure uncertainty; historical contemporaneous donor measurements only, not future weather. Independent 2025/other years; no four-donor restricted pool masquerading as full-census P8.3D.
C. **Future Wind Climate Synthesis** — ERA5 historical baseline, independently validated scenario-specific CMIP6 historical/future changes in `uas,vas` where accessible/qualified, or compatible vector alternatives; beware CMIP6 daily u/v vs hourly temporal resolution and point/grid scale. No invention of SSP wind direction from temperature or re-use of observed event clock. Use stochastic coherent blocks only after validated wind rose/speed persistence/weather-covariate closure. Unavailable CMIP6 vectors -> explicit not-supported, not forced scalar morphing.
D. **Integrated EPW Physical Closure** — check both wind fields of 35-column EPW at 8760/8784 hours, angular meteorological FROM convention, calm missing direction, plausible speeds, continuity, monthly/annual wind roses, calm, day/night, high quantiles, persistence, consistency with pressure/T/radiation. Preserve accepted P7B climate and P8.2 moisture; regression and negative controls. Promote only after B/C scientific gates.

**Global policy:** deploy neither F1 nor F2/3 monthly donor residual correction by default; raw ERA5 is current ERA5-only baseline, not an approved generator. 2022/2025 Swiss F3 showed 32/32 residual variants lose on aggregate. P8.3D full-pool donor altitude benefit cannot be inferred from 10-donor F3 ablations.

## P8.4A1 — document-backed source semantics (without assuming temporal equivalence)

Sources:
- Official MeteoSwiss SwissMetNet parameter metadata CSV `ogd-smn_meta_parameters.csv` (record SHA256). Hourly `fkl010h0` = **scalar wind speed average (m/s)**, `dkl010h0` = **wind direction hourly mean (degrees)**. Original `reference_timestamp` UTC parsed by existing source parser. Exact window boundaries **not certified by time-series parse alone**; must be separately proven from official reference semantics or independent 10-minute reconstruction.
- GeoSphere Austria `klima-v2-1h` /metadata: for `ff`, `dd` inspect actual per-parameter units, descriptions, timestamp semantics, flag definitions `ff_flag`/`dd_flag` and q21 code list. Individual QC status is available; reject unknown/unapproved flags, and document `0` unverified. Check station 30 against immutable ID metadata. Local DST never applied to UTC data.
- ECMWF ERA5 instantaneous analysis field validity times 00:00 etc for u10/v10. Open-Meteo historical archive `models=era5` `wind_speed_10m` / `wind_direction_10m`, 10m at **indicated hour, instantaneous representative**, derived/provider gateway rather than original gridded ERA5. Explicit `timezone=GMT` / `wind_speed_unit=ms`. Gateway may apply automatic elevation correction/cell-selection; **record returned grid-cell elevation/lat/lon and requested metadata**, and separately flag `downscaling_status=unverified`. Do not silently assume requested coordinate equals grid-cell coordinate or gateway output equals raw ECMWF u/v.
- All source records are samples of their own area/interval/measurement process. Matching same nominal hour is an **administrative alignment**, not proof of identical temporal mean or site representativeness.

Official references:
1. https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations
2. https://data.hub.geosphere.at/en/dataset/klima-v2-1h
3. https://confluence.ecmwf.int/pages/viewpage.action?pageId=111151514
4. https://open-meteo.com/en/docs/historical-weather-api

## P8.4A1 frozen actual-source screens

1. Fetch MeteoSwiss official parameters, station metadata and original January 2024 hourly **BAS/GRA/MUB**; verify schema, units, full timestamp coverage, no silent shifts; original 2024 source file hashes.
2. Fetch explicit ERA5 gateway hourly January 2024 for same 3 coordinates. Validate 744 unique contiguous GMT hourly timestamps, units m/s and °, report returned selected *grid* lat/lon and elevation. Compute predeclared observational timing diagnostics: ERA5 clock offsets `-1,0,+1` hour vs original station clock, on the **same interior 742 hours** for each site; scalar speed MAE/bias, angular MAE (valid noncalm direction) and vector-u/v RMS. **NO "optimal clock" selection**. Result remains observationally confounded due to ERA5 instantaneous vs station hourly mean, and can only indicate sensitivity.
3. Fetch original GeoSphere `klima-v2-1h` /metadata and Jan 2024 station #30 observed `ff,dd,ff_flag,dd_flag`. Record source metadata semantics and original QC code distributions; require >95% complete UTC hourly axis, >85% QC accepted speed, report joint QC and calm hours; check source's declared units in metadata. No source time-shift tuning. Preserve approved original Q21 set (10/11/12/20/21/22), unknown statuses **not silently assumed good**.
4. Publish aggregate metrics + SHA-256 only, no raw 1h observations, no fabricated heights, no copying original third-party gridded weather data. Strict schema contract tests with adversarial mock data.
5. Mark `source_semantics_validated_partial=true`; `identical_temporal_support_proven=false`, `a_physical_closure_complete=false`, `production_epw_ready=false`. External provider outages are operational failures, NOT negative scientific scores.

### Essential scientific caution

- The best of -1/0/+1 hours is not proof of whether the station stamp marks the interval beginning or end: synoptic autocorrelation and representativeness make that inference ambiguous. Preserve all hypotheses with unchanged accepted nominal alignment until independent documentation/testing.
- A station scalar hourly speed is not magnitude of hourly averaged velocity vector; likewise averaging wind directions requires circular/vector treatment, calm handling and original provider semantics. Verify source-specific algorithms if possible; do not infer exact 10-minute aggregation weights from CSV labels.
- Do not mix station observation height above ground (unknown) with official altitude above mean sea level (known). No guessed z0 or `wind profile correction`.
- These results are a **pilot in Swiss and Austrian domains**, not global physically closed climate generation.
