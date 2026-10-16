# IGE P8.4A2 — pre-registered 10-minute → hourly wind temporal-aggregation reconstruction

**Protocol frozen 2026-10-17 BEFORE new 2024 10-minute validation results.** Research child branch from P8.4A1 verified head `17be849ac4bb857f71f3e0a116d664d8c5b06abf`. Do not alter production EPW, Climate Analyzer, or `main`.

## Problem

MeteoSwiss `fkl010h0` is **scalar** hourly wind speed; GeoSphere `klima-v2-1h/ff` is **vectorial** hourly wind speed. ERA5 hourly u/v are **instantaneous validity-time** model fields, rather than source-equivalent historical 1h means. Previous nominal-hour ERA5 MAE is not a direct validation of the measurement aggregation operator.

**Official source 10-minute parameters:**
- MeteoSwiss `fkl010z0` (scalar ten-minute mean m/s) and `dkl010z0` (ten-minute mean wind FROM degrees); published hourly `fkl010h0` scalar m/s and `dkl010h0` hourly direction.
- Additional checks possible on `fve010z0` (vector speed 10-minute) or `fu3010z0` (km/h) only if their metadata unit/meaning is separately proven; **not used as substitutes** for `fkl010z0`.
- Official post-2018 Swiss `h` reference 16:00 = six `t` UTC end stamps 15:10, 15:20, ..., 16:00; **NO clock shifting/fitting**.
- GeoSphere `klima-v2-10min` parameters `ff`, `dd`, plus their `_flag` codes with source QC; hourly `klima-v2-1h` `ff`, `dd`. Need verify exact 10-min variable definitions and metadata and that hourly `ff` is vectorial; do not pretend all 10-min magnitudes are scalar observations.
- ERA5 `10u,10v` raw product components have validity times, and Open-Meteo `models=era5` derived wind speed/direction might differ from original raw ECMWF grid due gateway interpolation/elevation handling.

## Frozen pilot sources / sample

MeteoSwiss **BAS, GRA, MUB**, original `2024-01` (post-2018), original MeteoSwiss `t_historical_2020-2029.csv` and `h_historical_2020-2029.csv`. Parse only UTC reference stamps; allow complete six 10min windows without additional fills. Test **2024-01-01 01:00 through 2024-01-31 23:00** (743 available hours) to avoid needing 2023-12-31 10-min data. Require at least 85% complete six-sample speed hours at each station, otherwise fail closed.

GeoSphere **16400 Graz Thalerhof** and **16412 Graz Universität**; same `2024-01` UTC, original `klima-v2-10min` and `klima-v2-1h`, original q21 QC flags; independently check availability. Same six ten-minute 10:..:00 end-stamp hypothesis as diagnostic **NOT an asserted official GeoSphere hourly aggregation rule**. Do not qualify a site without >=85% independently provider-approved six-sample and hourly joint QC, and consistent units and verified metadata. Missing field or unavailable provider must be reported with provenance and blocked, no silent substitution.

## Candidate aggregation operators frozen before evaluation

Let speeds `v_i` be original six 10-min mean **scalar** Swiss speeds and meteorological FROM azimuth `θ_i` for noncalm records. Define:
- `speed_scalar = mean(v_i)` [m/s], compare to hourly Swiss scalar `fkl010h0`.
- `mean_u = mean(-v_i sin θ_i)`, `mean_v = mean(-v_i cos θ_i)`; `speed_vector = hypot(mean_u,mean_v)` (never substitute for scalar); physical bound `speed_vector <= speed_scalar` (on valid direction hours).
- Candidate hourly direction `dir_speed_weighted = meteorological_from(mean_u,mean_v)`; `dir_unit_circular` = angle of average unit vectors independent of speed. Exclude calm (`v<0.5 m/s`) from azimuth candidates rather than invent north; unresolved vector/circular result stays undefined. For fair angular MAE, score candidates on identical original reference noncalm hours on which **both** predictions are resolved. Separately report coverage and failure counts.
- 10-min samples with missing wind direction can still contribute to **scalar mean speed** (if original source speed valid); directional aggregation rejects unresolved noncalm samples. No imputation, zero is not a direction for calm.
- Compare hourly observed speed with both scalar and vector candidates on same complete directional six-sample windows, and separately report scalar across all six-speed windows. Quantify aggregation/Jensen gap `speed_scalar-speed_vector` by site, wind-speed strata, and mean, plus MAE/bias/RMSE for hourly speed.
- GeoSphere hourly `ff` vectorial: compare against speed-weighted vector resultant and scalar mean, without assuming the original 10-minute `ff` uses identical microscopic averaging. Report **candidate reconstruction**, not official equivalence unless shown quantitatively with source metadata.
- Predeclared threshold for *exploratory* numerical close matching: Swiss scalar MAE <=0.15 m/s and >=85% coverage, recognising 0.1-unit source rounding; no guarantee of success. For angular reconstruction use MAE and coverage, **no post-hoc threshold adoption**.

## Source integrity, limitations and decision gates

1. Strict duplicate and missing timestamp checks, expected physical 10-min cadence, UTC, units, direction FROM, wind vector conventions, station IDs, min complete windows, no reference leakage. Original-source SHA256; publish **only derived aggregates**, never original hourly/10-min observations or arrays.
2. Verify source raw CSV parameter metadata units from `ogd-smn_meta_parameters.csv`; where provider's field definition missing/ambiguous, mark source unsupported. No wind-height log corrections without original instrument height and z0.
3. The original Swiss 1h source is **not the sole statistical truth** for generalized aggregation method: comparing back to 1h from same 10min records tests internal consistency, not prediction skill. A numerical match cannot prove the official aggregation algorithm or representativeness vs ERA5.
4. Even perfect six→one internal station closure **does not supply subhourly ERA5 data**. Do not select -1/0/+1 shift via MAE; maintain `era5_vs_hourly_mean_same_temporal_support=false`.
5. GeoSphere metadata may not provide full parameter aggregation details; if not, report `geosphere_exact_aggregation_rule_unverified`. A2 partial does not approve A whole.
6. `P8.4A2_PASS` applies to functioning verified pilot computation. `physical_equivalence_complete` remains false until GeoSphere, station/source QC and era5 temporal-support conditions are independently demonstrated. `production_epw_ready=false` and absolutely no merge.

Sources: https://opendatadocs.meteoswiss.ch/general/download ; https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations ; https://data.hub.geosphere.at/en/dataset/klima-v2-10min ; https://confluence.ecmwf.int/pages/viewpage.action?pageId=111151514 .
