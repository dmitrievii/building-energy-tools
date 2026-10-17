# IGE P8.5 — FINAL INDEPENDENT EPW GENERATOR AUDIT (17 October 2026)

**Authoritative audited state:** `RESEARCH_EVIDENCE_AUDIT_PASS / OPERATIONAL_RELEASE_BLOCKED / PRODUCTION_EPW_READY_FALSE`.

This stage is an honest independent audit of **the whole registered P7–P8 EPW research chain**, not an attempt to manufacture a green production label. It checks **immutable published model and member SHA relationships** and independently rereads **six actual public research EPWs**. The **28 licensed Meteonorm-derived P7C.4/P7C.5B hourly EPWs were not available in public CI**. Therefore all 28-file original byte and licensed EnergyPlus certifications must remain UNVERIFIED; earlier per-file P7C5 research reports are historical evidence only.

## 1. Reproducibility and completed CI

- Predeclared fixed protocol: `docs/IGE_P8_5_FINAL_EPW_GENERATOR_AUDIT_PREREG_RU.md`.
- Final verified run: [GitHub Actions #39033019408](https://github.com/dmitrievii/building-energy-tools/actions/runs/39033019408), source SHA **`8c8330b0e198597808b451b2152c39e06b420a73`**, **2/2 jobs SUCCESS**, **65/65 tests PASS** (18 newly authored P8.5 + 15 P7C.4 + 14 P7C.5B + 18 P8.4D). Prior first CI #39032721461 detected a previously hidden **RH saturation metric definition difference**; fixed by explicitly preserving both definitions and thresholds without changing original files. Later CI #39032976097 failed on a synthetic test fixture lacking a newly required field; it was corrected without changing any physical criterion or source result.
- Immutable original aggregate scientific artifact: [#12101630112](https://github.com/dmitrievii/building-energy-tools/actions/runs/39033019408/artifacts/12101630112), ZIP **SHA256 `158874b7c768991cd974b7b377059db3bf34c5942608792082c6ef0fcc6aa3c6`**, JSON **SHA256 `265d4a735f2ca0aa7978e625cc7e2d3a35fcb1241951650057e8787c7e6ecbdb`**, CRC PASS.
- Public code performs true member/source bijection verification, not row-count-only: P7C4 28 immutable SHA values, P7C5 original physical 28 member SHA, P7C5B 28 inputs (exact matching P7C4 SHA) and distinct repaired output SHA; 4 blocked IPSL identities must match original registered GCM+window set. Tests mutate/damage original manifests and require FAIL-CLOSED. No proprietary hourly EPWs are downloaded/uploaded.

## 2. Eight scientific domains and evidence

| Gate | Scientific outcome | Operational decision |
|---|---|---|
| GCM source lineage | **PASS:** 8 models × 4 SSP/windows × 12 months = 384 unique monthly signals. The 40 original daily GCM source ZIPs were independently audited in prior P7C4; not re-fetched in P8.5. | Previous source provenance PASS, current byte-level 40-archive audit not repeated |
| Climate scenario coverage | **28/32 full P7C4 research EPWs**, all 28 unique source hashes and bijective identities; 4 IPSL-CM6A-LR scenarios explicitly BLOCKED by unavailable historical/future `huss`. | Missing 4/32 means no complete registered eight-model full-EPW portfolio |
| Temporal/EPW structure | Six ORIGINAL archived public EPWs each 8 headers + 8760 time-contiguous standard-time rows ×35 columns PASS. P7C5 previously found all 28 licensed files structurally valid. | **Six public real byte reads PASS**; **28 private byte reads NOT REPEATED** |
| Dry-bulb, humidity and monthly moisture | Historical P7C4 all 28 serialized monthly q balances, max published 9.872e-14 kg/kg; source-aware optimizer decreased its objective and no new >20 pp/hour RH jumps. | **28/28 humidity optimizers exhausted 600 iterations without strict convergence.** Distribution, saturation persistence and condensation risk not independently qualified |
| Solar irradiance | Published full 28 original EPWs pass daily GHI balance and hourly GHI/DNI/DHI projection/Erbs decomposition, max published daily balance 3.778e-11 kWh/m². | Broadband source projection algebra PASS; empirical beam/diffuse partition and seasonal direct/diffuse distribution not independently validated |
| Radiation–illuminance | Earlier P7C5 detected changed irradiance but stale illuminance in **103283 GHI**, **91715 DNI**, **104305 DHI** hours across 28 member EPWs. P7C5B created 28 SHA-linked revised files with max photometric closure residual **0.499985 lux**. | **Photometric *algebra* repaired, independent daylight measurements absent**; P7C5B output is a separate file version, not an in-place mutation of P7C4 |
| Wind | P8.3–P8.4D source/aggregation/donor-negative-generalization and scalar future morph documented; P8.4D 32 wind-only morphs and 9 true native EnergyPlus wind/infiltration/opening cases passed research contracts. | Direction is **inherited, not projected**. P8.4D public analogue study flagged **3/32** calm-to-wind exposure blockers. Not valid future local pressure/wind rose |
| Simulation and product | P7C5/P8.4D public research EPWs were genuinely simulated by pinned official EnergyPlus. EPW code and source provenance are available, but final 28 corrected licensed Meteonorm-derived EPWs are not in public CI. | **No full 28 licensed EnergyPlus comparison / no arbitrary-coordinate generator operational qualification / no main deployment** |

## 3. Newly reconciled saturated-RH metric definitions

- P7C4 member-hour `np.isclose(RH,100,atol=1e-5)` returned **14520** across 28 files (NumPy uses nonzero default `rtol=1e-5`).
- P7C5 `RH>=99.995%` returned **14536**, i.e. **16 more**. The different implicit thresholds are why these previous numbers should not be asserted identical. Neither archive was changed or “corrected” using the other figure.
- Historic original 8760h licensed Meteonorm baseline had **229** strict near-saturation hours in P7C5 report. This increase warrants seasonal distribution/QC/psychrometric phase check (real saturation is possible; percentage alone is not proof of an error). Distinguish ordinary condensation physics, dewpoint/RH numerical consistency, and extremal wetness clustering.
- **Required release action**: unify the *reporting* definition explicitly (`abs(RH−100)<...` or `RH>=99.995`) and rerun 28 original bytes under one immutable definition. Do not alter humidity values merely to match summary counts.

## 4. Actual six public research EPW bytes: wind field deficiency in early fixtures

The complete 2013 original **P7B.4** and four original **P7C.1** generated public EPWs plus the original wind-analogue-corrected **P7B.5** were restored from their own earlier immutable GitHub Actions artifacts, SHA-checked, parsed and structurally validated. They are **synthetic/analogue research fixtures**, not authentic 28 Meteonorm future weather files.

| Archived public source | Complete noncalm FROM direction? | Missing-direction noncalm hours |
|---|---|---:|
| P7B.4 original integrated EPW | **NO** | 8758 |
| P7C.1 CanESM5 SSP245, 2040–2059 | **NO** | 8755 |
| P7C.1 CanESM5 SSP245, 2080–2099 | **NO** | 8755 |
| P7C.1 CanESM5 SSP585, 2040–2059 | **NO** | 8755 |
| P7C.1 CanESM5 SSP585, 2080–2099 | **NO** | 8753 |
| P7B.5 research wind analogue EPW | **YES (analogue)** | 0 |

**Total 43776 source-fixture site-hours without noncalm direction among five early EPWs.** P7B.5 fills the direction via an original-QC-based *analogue* donor model, not date-matched observations with its synthetic 2013 baseline. A completed 8760×35 file can be **structurally valid while physically unqualified for wind-exposure use**. Do not misattribute this deficit to 28 original Meteonorm-based P7C4 EPWs: the separate earlier P7C5 original-byte audit found **zero missing directions** in those files.

## 5. Strict operational-release blocker matrix

Machine-enforced audit release gates: three **PASS** (384 signal identities, 28+4 SHA manifest bijection, 6 public EPW time/width readbacks), **11 not passed** including completeness, optimizer, independent humidity/sun/cloud/wind, full 28-private-EnergyPlus, missing public-fixture directions and arbitrary location validation. The exact list is in the JSON artifact, not a probability score. The audit CI legitimately says SUCCESS because it correctly DETECTED blockers. It does **not** say IGE is ready to deploy.

**P0 — essential before claiming full production EPW**
1. Re-open original user-authorized Meteonorm baseline and **all 28 latest P7C5B corrected hourly files** in a private licensed environment. Check baseline SHA, source lineage, all field sentinels and immutable member SHA, physical consistency and 8760 valid timestamps; do not publish their raw hourly records.
2. Run a native EnergyPlus benchmark across the real 28 latest EPW files, comparing baseline and scenario results with independent source projections where available. Keep separate from existing nine public research wind tests.
3. Resolve the **humidity temporal optimizer's 28/28 nonconvergence** with independently tested stopping/feasibility diagnostics and season/regime checks; do not assume a low monthly q residual proves realistic RH.
4. Declare the 4 IPSL no-`huss` scenarios ineligible for full climate EPW until independently sourced data or scientifically valid method exists; **no automatic fallback**.

**P1 — scientifically material applicability limits**
5. Independently validate P7C5B luminous efficacies, DNI/DHI, zenith/sky luminance, inherited cloud cover/longwave and ground temperature; explicitly prohibit unrestricted daylight-performance claims meanwhile.
6. Establish validated source-selection/mapping quality for arbitrary geographic coordinates and historical climate (P8.1/P8.2/P8.3 study results are research diagnostics, not final generator operation). Evaluate independent station geography/year with provenance and quantified uncertainty.
7. Define explicit modes and risk labels: `historic_station_reconstruction`, `future_monthly_morphing`, `wind_exposure_sensitive`, `daylighting_sensitive`; segregate references and never claim future azimuth, new synoptic events or independently modeled precipitation event occurrence.

**P2 — deployment and documentation**
8. Add output manifest per EPW containing original-hourly provider, SHA/license, grid/elevation, fixed local standard-time zone, model/member/scenario/20-year window, all 12 monthly ratios, field-wise morph rules, missingness, error budgets, GCM baseline vs station measurement support, and explicit validation flags.
9. Provide reproducible production runner/CLI, checksums, regression gates and climate uncertainty reports; connect Climate Analyzer only AFTER P0/P1 acceptance.

## 6. Scientific closure and decision

**`P8.5_RESEARCH_TECHNICAL_AUDIT=PASS`**: published research input/outputs are traceable and mathematically self-consistent within declared algorithms, six genuinely archived EPW files can be parsed and checked, and the system correctly fail-closes when confronted with scientific missing evidence.

**`P8.5_OPERATIONAL_EPWS_READY=BLOCKED`**: the program has not been qualified to provide accurate full physical weather vectors at arbitrary geographic locations or independently verified future wind, humidity, solar luminance and native simulation on 28 original user-restricted EPW files. This does not nullify the considerable completed research; it states precisely what it establishes.

**Next recommended project stage:** **P8.6 — Original Licensed 28-EPW Private Final Readback & Cross-Variable Qualification**, followed by P9 production architecture/application integration. Avoid reopening rejected donor-weight optimisation. No `main` merge.
