# IGE P7C.4 — Seven complete GCM hourly EPW members and explicit IPSL block (2026-10-12)

## Scope / source integrity

- Research branch on previous **P7C.3** source-registered pilot; not merged into `main`.
- 8 GCM × (SSP245, SSP585) × (2040–2059, 2080–2099) = **32 GCM climate states**.
- 40 independently validated native original P6 daily ZIPs (8 models × historical+4 future), 20 source-years each, explicit Gregorian and noleap handling, native ensemble member `r1i1p1f1`.
- SHA-256 of all 40 daily CSVs was checked against the P7C.3 registered immutable provenance. Each of the 384 monthly climate-change signals was independently recomputed from the 40 source archives and compared with the public P7C.3 monthly signal CSV.
- Original **Graz-hour_contemporary_seed1.epw** was SHA-pinned (`dad69174304c3a13cc095841c4cb9636bf99cc3f33a81502c553af862cd06677`), Meteonorm 8.2; 8,760 hourly rows and no missing wind directions. This is a **generated contemporary typical weather EPW**, not observed meteorological year 2005.
- 7 models × 4 windows = **28 complete exploratory EPWs**; IPSL-CM6A-LR × 4 windows **BLOCKED** because native daily `huss` was absent in historical and future archives. No seven-model humidity surrogate, unchanged-humidity fallback, or imputed data were used.

## Physical closure and numerical verification

- 28 fully serialized EPWs: **245,280 hourly rows × 35 fields**. 336/336 monthly mean specific-humidity balances reproduce monthly GCM humidity ratio (maximum absolute serialized residual **9.872e-14 kg/kg**).
- Original 8,760 hourly wind directions per EPW retained; original rain occurrence and original timestamps retained. RH between 1 and 100%, dewpoint ≤ drybulb; untouched 26 of 35 EPW fields identical to original.
- GHI solar: daily input EPW radiation × monthly native GCM `rsds` ratio, then cap-bounded projection to the original day's solar geometry. Daily maximum absolute solar-energy residual **3.778e-11 kWh/m²**; hourly GHI=DNI·cosθ + DHI verified after EPW serialization (empirical Erbs decomposition, not independent direct/diffuse measurement).
- P7C.1B → P7C.1C reference-aware RH optimizer removed **132 → 0** artificially introduced jumps >20 percentage points per hour (not claiming all such jumps are physically impossible). Pre-existing source RH transitions intentionally preserved.
- 4/4 final CanESM5 EPW records agree with earlier P7C.1C canonical accepted outputs, **every one of 8,760×35 field values** unchanged. Only EPW header research metadata differs.
- **Limitation:** all 28 optimization runs reached the 600-iteration limit, none met strict `converged_by_delta`. Feasibility, descent, and mass closure are proven by the computed guards, but global optimum is **not** proven. More theoretical convergence work remains.

## Seven-model *complete-EPW* spread, relative to the same Meteonorm contemporary baseline

| Future window | Seven-model median ΔT °C | Model min–max ΔT °C | Seven-model median GHI kWh/m² |
|---|---:|---:|---:|
| ssp245-2040-2059 | +1.64 | +1.07 to +2.68 | 1291.6 |
| ssp245-2080-2099 | +2.20 | +1.66 to +3.55 | 1288.9 |
| ssp585-2040-2059 | +1.94 | +1.44 to +3.20 | 1278.6 |
| ssp585-2080-2099 | +4.61 | +3.37 to +6.93 | 1291.6 |

**Do not confuse these statistics with eight-model P7C.3 climate-signal medians.** The complete-hourly subset is seven GCMs because IPSL has no `huss`. These are samples of model structures, not probabilistic confidence intervals.

## Unresolved physical/scientific qualifications

1. The source EPW is *Meteonorm generated*, the future members are climate-morphed Meteonorm event sequences, **not independent future 20-year weather realizations**. Extreme-event persistence/frequency may not reproduce the 20-year native GCM changes, despite daily-temperature quantile conditioning.
2. Native P6 `hurs>100` in a small number of EC-Earth3 and MPI source days is source-flagged, never silently used to impute missing IPSL `huss`.
3. Future wind direction, precipitation occurrence, sky cover, ground temperature, visibility and precipitable-water fields are not independently predicted. Monthly morphing adjusts wind speed and rain amount but inherits source event ordering.
4. DNI/DHI are calculated using empirical Erbs split. Conservative TOA-bounded closure is a numerical guard, not an empirical validation of DHI or DNI.
5. Source original and derived EPWs are **not published to GitHub**. GitHub CI will use public P6 archives and public P7B.4 synthetic fixture for test contracts, never claim it processed the authentic proprietary Meteonorm input. Authenticated 28-EPW validation here was local and separately source-hash audited.
6. No EnergyPlus building simulation or independent weather-observation validation. **production_epw_ready=false**; do not merge into public Climate Analyzer UI without explicit product and scientific release gates.

## Outputs

- `epw/`: 28 full 8,760×35 research-only EPW files for the original authenticated Graz Meteonorm source, **one GCM per file**.
- `audit/`: 28 scenario metrics, 336 monthly q closures, 4 blocked IPSL entries, 4 windows seven-model spread and full source SHA audit.
- `source/`: reconstruction Python module + 15 public synthetic unit tests, GitHub workflow, P7C.3 original-source SHA registry reference, and scientific report.
- `figures/`: seven-model full-EPW temperature signal plot.
- `manifest_sha256.json`: checksum for every included file.

**Stage disposition: `RESEARCH_HOURLY_CLOSURE_PASS`, production EPW still blocked.**