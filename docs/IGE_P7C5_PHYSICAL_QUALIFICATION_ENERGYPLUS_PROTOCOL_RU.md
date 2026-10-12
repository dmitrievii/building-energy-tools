# IGE P7C.5 — Independent EPW Physical Qualification & EnergyPlus Benchmark

Date: 2026-10-12. **Research-only; production EPW status BLOCKED.**

## 1. Scope and exact evidence levels

The independent physical audit was performed locally against the original user-supplied Meteonorm 8.2 `Graz-hour_contemporary_seed1.epw` (SHA-256 `dad69174304c3a13cc095841c4cb9636bf99cc3f33a81502c553af862cd06677`) and the 28 immutable P7C.4 future EPWs archived in `IGE_P7C4_SEVEN_GCM_28_HOURLY_EPW_ENSEMBLE_RESEARCH_2026-10-12.zip`. No P7C.4 hourly records were edited to make this audit pass. Physical audit is **not** the same as running EnergyPlus.

EnergyPlus was **not installed in the local container** and direct downloading of executable binaries was unavailable. A true EnergyPlus 26.2.0 CI job is provided independently. It downloads a SHA-pinned official Linux release (`b848da8236482a2171a67d7eab00c82162105b653ffab3ae3b6c2217c433a8a1`), uses the upstream EnergyPlus 26.2 `1ZoneUncontrolled.idf` adapted to a conditioned single-zone research model, and must actually execute 5 annual weather-driven simulations to pass. **Public CI uses P7B.4 synthetic baseline and the 4 earlier P7C.1 CanESM5 synthetic-derived EPWs, NOT the 28 proprietary-input Meteonorm members**. This distinction is machine-audited. Results require completed CI, not just a launched workflow.

## 2. Local independent physical findings, 28 EPWs × 8760 hours

- All 28: 8 EPW header rows, 8760 hourly records, 35 fields, time alignment intact.
- No negative DNI, GHI or DHI; no negative precipitation or wind speed; no missing wind directions.
- No dewpoint above drybulb, RH outside [0,100] or >2 percentage point RH-vapor-pressure disagreement (Buck approximation).
- **14,536 hours with exactly 100% RH across 28 EPWs**, compared to 229 in the original 8760-hour Meteonorm reference. This concentration requires its own condensational/microphysics sensitivity study; humidity monthly conservation alone is not statistical validation.
- **103,283 changed GHI hours with original unchanged nonmissing global horizontal illuminance**.
- **91,715 changed DNI hours with unchanged direct normal illuminance**.
- **104,305 changed DHI hours with unchanged diffuse horizontal illuminance**.
- All 28 inherited their ground temperature header and cloud/event chronology unchanged. Visibility is missing (EPW sentinel) across all 245,280 output hours; the existing baseline has the same limitation. The source header's data-source token was replaced with `IGE_P7C1_RESEARCH_ONLY` even in P7C.4 results; this is a provenance metadata error, not proof the source was P7C.1. These are not grounds to describe the entire weather vector as a future measurement.

**Disposition**: the 28 EPWs pass the currently implemented *basic physical-domain* gates, but fail the **full cross-variable/lighting consistency** qualification. They may be used only for controlled research sensitivity with explicit weather model assumptions. `production_epw_ready=false`.

## 3. EnergyPlus reference benchmark specification

- Engine: DOE EnergyPlus 26.2.0, release `v26.2.0`, pinned official Ubuntu 24.04 x86_64 binary and SHA-256.
- Building: original EnergyPlus `testfiles/1ZoneUncontrolled.idf` version 26.2 (a sealed, 232.25 m², no-window one-zone test building) with weather-file annual RunPeriod, ideal sensible/latent loads using `ZoneHVAC:IdealLoadsAirSystem`, thermostat 20 °C heating / 26 °C cooling, and a declared simple infiltration component. Building orientation and geometry unchanged from official fixture; this is NOT the Vienna Twin Towers or an office building.
- Simulator outputs: SQL-recorded hourly ideal-load heating and cooling energies plus mean zone air temperature. Reject any fatal/severe `eplusout.err`, missing SQL, empty annual output, or negative energy. Compare absolute kWh and changes relative to baseline, **not** energy consumption by an actual mechanical system.
- Public GHA inputs: synthetic 2013 P7B.4 baseline plus 4 P7C.1 CanESM5 hourly morphs; no licensed Meteonorm data is exposed.
- Grounded validation is pending until actual EnergyPlus GitHub Actions execution succeeds. To run the full 28-user-EPW benchmark, the runner must have user-controlled private access to the source bundle and a trusted locally executed EnergyPlus binary. There is no claim that CI executed the 28 Meteonorm-derived EPWs.

## 4. Corrections

P7C.4 `verify_hourly()` previously set `authentic_source_graz_epw_reused=true` even when called from the public synthetic fixture. P7C.5 adjusts the flag to default `false` and explicitly sets `true` only inside the authenticated Meteonorm generation path. Also future-generated P7C.4 header LOCATION provider tags are labeled `IGE_P7C4_RESEARCH_ONLY` rather than `IGE_P7C1_RESEARCH_ONLY`. This correction changes provenance metadata on future regenerations; archived P7C.4 hourly files and checksums remain unchanged.

## 5. Remaining qualification items

1. Physical correction or explicit disabling of inherited illuminance fields for daylighting simulation; never silently invent them.
2. Ground-temperature treatment, long-wave cloud relationship, sky condition/coherence, precipitation/wind-rose changes, and water-vapor temporal statistics.
3. Independent measured climate and radiation benchmarks, multiyear and inter-model distribution-level checks.
4. Formal optimizer convergence or a verified bounded optimality tolerance, plus humidity temporal QC beyond a single 20 pp/hour threshold.
5. True annual EnergyPlus end-to-end simulations on the 28 authentic member files, run in a private licensed context and compared to Meteonorm projections with careful RCP/SSP distinction.
6. IPSL-CM6A-LR `huss` unavailable for four windows: no full EPWs until sourced or independent scientifically justified alternative validated.

Neither EnergyPlus acceptance nor passing EPW structural checks alone establishes physical fidelity of future weather or production readiness.