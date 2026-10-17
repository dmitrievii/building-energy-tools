# IGE P9.2B — Original NASA CanESM5 × ERA5 Joint Hourly Weather Regime Generator: Verified Pilot

**Scientific audit, 17 October 2026.** Research stage P9.2B completed at original-source algorithm-feasibility level; **not yet fully physically qualified for arbitrary CMIP6 daily inputs**. [GitHub Actions #39070382922](https://github.com/dmitrievii/building-energy-tools/actions/runs/39070382922) **SUCCESS** (code passed and negative source cells explicitly reported). Independent offline contract Actions [#39070199721](https://github.com/dmitrievii/building-energy-tools/actions/runs/39070199721) **SUCCESS**, 16 P9.2B + 13 P9.2A = 29/29 tests. Original genuine source/provenance results [artifact #12114544242](https://github.com/dmitrievii/building-energy-tools/actions/runs/39070382922/artifacts/12114544242).

## Sources, exact cohort, limitations

**Independent original *daily climate* constraints:** NASA NEX-GDDP-CMIP6 v2, CanESM5 r1i1p1f1, quality PASS, source original SHA from `p7c3_expected_daily_source_shas.json`; original P6 archives acquired without re-downloading NASA weather datasets, from GitHub Actions source archives #38072042977. The historical original daily `joint_daily_raw.csv` SHA256 is `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`; the SSP245 future 2040–2059 20-year source SHA256 is `5cdc6bad425127a8d7a232a2cfd1c649306821f1e0ea8376b90839a8472d97b3`. All source provenance/quality read back and validated by the existing P7C.3 source parser.

**Hour-shape source:** ERA5-derived through Open-Meteo P9.1A, Graz WGS84 (47.0707 N 15.4395 E) original 2019 and 2020 hours (not measured independent stations); original NASA GCM grid (46.875 N 15.375 E) is not exactly the ERA5 donor location. Same fixed seven consecutive January and July days (10–16) in each training year. Scenario targets 2013 historical and 2050 SSP245, 7 days each per season: **28 original native daily constraints**, no alternate site/year or target-day replacement, one seed 7313. 2022 P9.2A experimental skill results are not training data.

## Physical algorithm actually implemented

- Same-calendar-month donor day, **source genuine wet/dry regime** gated by native GCM daily precipitation: no fictitious rainy hour if no wet donor.
- Monotonic donor-hour temperature transform conserving native daily mean, min and max.
- Original wet-hour locations retained and positive intensity scaled to conserve daily precipitation exactly; zero daily precipitation remains dry.
- GHI distributed with solar altitude (night zero), hourly extraterrestrial horizontal cap; DNI/DHI recomputed with `GHI = DHI + direct_horizontal` and `DNI ≤ 1400 W/m²`.
- Donor dewpoint/pressure derived specific humidity varied with capacity constraint `q≤q_sat(T,p)`, conserving native GCM daily mean `huss` **exactly** where feasible. RH and dewpoint rederived physically. **Mean source `hurs` is soft**, explicitly reported as a residual; jointly exact `huss`, `hurs`, `T` with no supersaturation may be mathematically impossible.
- Original hourly wind-direction and cloud sequence retained as ERA5 donor proxies, scaled wind speed mean conserved; downwelling sky LW daily native `rlds` conserved via explicitly modeled, bounded hourly emissivity proxy, not original native hourly observation.
- Importantly **native GCM daily data do not include measured future hourly cloud cover**, and ERA5 donor clouds are analogues; generated 2050 hourly weather is a single research realization **not an individual-day future forecast**.

## Exact genuine original CMIP6 results

Source original file SHA verified; every conservation success has hard residuals for native `tas_c,tasmin_c,tasmax_c,pr,rsds,rlds,sfcWind,huss` below 1e−6 in source units (in logs essentially floating-point arithmetic precision).

| Original GCM scenario | Month | Registered native daily targets | Conserved | Blocked | Mean absolute mismatch daily mean RH (pp) | Maximum RH mismatch (pp) |
|---|---|---:|---:|---:|---:|---:|
| 2013 historical | January | 7 | 7 | 0 | 3.385 | 6.924 |
| 2013 historical | July | 7 | 6 | 1 | 4.812 | 7.527 |
| 2050 SSP2-4.5 | January | 7 | 7 | 0 | 3.604 | 10.712 |
| 2050 SSP2-4.5 | July | 7 | 7 | 0 | 1.903 | 3.603 |
| **Total** | | **28** | **27** | **1** | **3.375** (mean across 27 conserved days) | **10.712** |

### Rejected original day: no post hoc rescue

**2013-07-10 (historical)** rejected with original `InfeasibleDailyClimate: P92B_DAILY_TOTAL_EXCEEDS_PHYSICAL_HOURLY_CAPACITY`. Exactly one genuine native daily input was **not** forced through by relaxing saturation, solar or daily conservation limits. The existing generic capacity message does **not** distinguish solar energy capacity from water-vapor saturation without a more specific diagnostic: report only the verified generic source incompatibility.

Original source quantities on this registered day, read from the ZIP (SHA verified): `tas_c=22.216821°C`, `tasmin_c=18.388361°C`, `tasmax_c=26.045313°C`, `hurs=93.665344%`, `huss=0.0177468285 kg/kg`, precipitation `12.510715 mm/day`, solar `6.17273584 kWh/m²/day`, longwave `9.26369312 kWh/m²/day`, wind `1.09903467 m/s`. This humidity is high for the prescribed daily temperature and likely warrants a separate specific thermo-capacity diagnostic. **Do not assert which of the two constraints tripped until instrumented.** Source data remain unchanged.

The source `huss` vs `hurs` issue is substantive: 2050 January source-constrained pilot reached **10.712 pp** absolute daily mean RH difference on one accepted day. It is incorrect to claim both fields exact. No 2022 parameter calibration or multiple seed search performed.

## Qualified scope and next decision

| Scientific criterion | Outcome |
|---|---|
| Registered native original NASA daily climate source, hash, QA | **PASS** |
| Reproducible source-to-hourly, 24h original donor joint vectors | **PASS (pilot)** |
| Hard conserved eight original daily quantities | **27/28 pass, 1 source-physical blocker** |
| Native mean `hurs` and `huss` simultaneously physically closed | **NOT QUALIFIED (soft RH residual)** |
| Native cloud/rain/GHI/longwave event temporal climatology relative to independent stations | **NOT TESTED** |
| 8760-hour EPW, geographic generality, production usability | **BLOCKED** |

**Decision:** P9.2B original-source pilot completed with 27/28 valid physically constrained generated days, one honest reject, and an explicitly nonzero native relative-humidity compatibility mismatch. This shows **feasibility but not scientific closure of a future EPW generator**. Do not automatically weaken physical limits or select new seed to hide rejected source day. Retain entire implementation in research branch; `joint_weather_generator_qualified=false`, `production_epw_ready=false`; no main merge.

**Next limited scientific task:** before P9.2C real-station independent crossfield validation, clarify precise infeasibility (source `q` vs `q_sat`, or solar), define science-grounded q/hurs source consistency handling, and preserve risk annotations for CMIP6 radiation and other variables. Do not expand beyond AT/DE/CH or start world validation; publication-stage worldwide validation remains deferred.
