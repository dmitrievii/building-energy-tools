# IGE P9.2B — preregistered daily-constrained joint weather-generation pilot

**17 October 2026, prospective.** No historical 2022 P9.2A skill tuning, no new weather stations, no global extrapolation. Branch `research/ige-p9-2-joint-hourly-regimes-20261017`; `main` unchanged.

## P9.2B research question

Can the frozen original P9.2A *joint* ERA5 hourly meteorological regimes be conditionally morphed under **authentic single-GCM daily NEX-GDDP-CMIP6 constraints**, conserving prescribed daily temperature mean/min/max, precipitation depth, GHI energy, mean wind, q (huss), and LW while retaining original wet/cloud/solar crossfield pattern? This is algorithm feasibility and daily physical closure; it is NOT a measured weather prediction or production EPW.

One single regional site Graz AT (only Austria within allowed AT/DE/CH); **not** using Graz GCM grid as climate forecast for Oberstdorf/Davos. ERA5 donor: Graz (47.0707,15.4395) same fourteen 2019+2020 training source days per month used in P9.2A, 10–16 Jan & Jul. Target authentic CanESM5 r1i1p1f1 original original registered NASA P6 at grid (46.875,15.375) covering:
- `historical-1995-2014` genuine 2013-01-10..16 and 2013-07-10..16
- `ssp245-2040-2059` genuine 2050-01-10..16 and 2050-07-10..16

Source artifacts GitHub Actions run **38072042977**, exact `ige-p6-CanESM5-historical-1995-2014` & `ige-p6-CanESM5-ssp245-2040-2059`. Immutable registered daily `joint_daily_raw.csv` hashes from existing `p7c3_expected_daily_source_shas.json`: history `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`; SSP245 future `5cdc6bad425127a8d7a232a2cfd1c649306821f1e0ea8376b90839a8472d97b3`. Source provenance and QUALITY REPORT verified by `p7c3_ensemble.read_source` (not metadata invented for test). Exactly 28 original daily targets, no selection of favorable dates after scoring. Frozen RNG seed `7313`; fixed site/month/CESM year independent of any outcome.

**Physical algorithm frozen prior to source execution:**
- Meteorological donor selected among native P9.2A 24-hour weather vectors, same month, and strictly same **dry/wet** class as original GCM daily precipitation (no fake wet hours). Donor selection conditioned on target climatological source (T, wind, rain, GHI, RH, q), with fixed heuristic weights and previous-day seam; **not** optimized against target validation or historical weather observations.
- Temperature: constrained monotone profile matching GCM `tasmin_c,tasmax_c,tas_c` exactly within 1e-6 °C if mathematically feasible; no invented forecast observations.
- Precipitation: nonnegative, exactly GCM daily total; zero daily total → every hour dry. A wet GCM day requires genuinely wet donor day, not clear sky rain substitution. Preserve donor temporal wet-hour structure unless physically blocked.
- GHI: target original daily solar energy exactly, geometrically zero at night and capped by extraterrestrial horizontal potential, conserving physical sum. DHI/directH/DNI all coherent with solar altitude, capped radiation, donor diffuse signature where feasible. No fake observed DNI claim.
- Humidity: GCM native `huss` daily mean q is a hard water-mass target; adjust donor within physical hourly `q<=qsat(T,p)`, derive consistent RH/dewpoint and **report** source daily `hurs` mean mismatch rather than falsify both q and RH (joint constraints may be physically inconsistent). RH is soft only; if source huss missing (e.g. IPSL) block.
- Wind: match original GCM `sfcWind` mean, preserve weather-vector wind azimuth and relative hourly speed variation; bounded 0–90m/s else block.
- Downward longwave: `rlds_kwh_m2_day` hard conserved by bounded sky-emissivity proxy; **not** independent observed longwave or spectrally accurate clouds.
- Cloud: inherit original donor full cloud cover hour, no cloud variable in GCM native daily input, therefore cloud is **not** a native CMIP6 prediction. Change radiation but retain rain/cloud joint donor signature, flag mismatch risk.
- Daily target outside physically feasible source solar/temperature/vapor-pressure constraints: explicitly `BLOCKED`, no silent clipping that changes daily totals.
- One forward algorithm with no coefficient fitting, no ablation grid, no repeated seed selection.

**Criteria:** exact source provenance SHA, UTC calendars, daily T mean/min/max, precipitation mm, solar kWh/m², wind m/s, specific humidity kg/kg, downwelling LW kWh/m² within numerical tolerance; RH mismatch (pp), 24-hour wet spell transitions, solar cap, dewpoint and saturation, discontinuities, no leakage from CMIP6 source into donor ERA5. Report 28/28 successes and all **negative/blocked cells** transparently, plus comparison with original P7B solo-field daily/hourly conservations if source permits. All GCM output remains 28-day exploratory segment; no 8760 EPW, no future station skill claim.

**Research gates:** `P9_2B_algorithm_contract_pass` distinct from `P9_2B_authentic_CMIP6_conservation_pass`; both distinct from `P9_2B_multivariable_observation_skill_qualified=false`; `production_epw_ready=false`. One manual/one-shot CI experiment only. Full AT/DE/CH independent station validation later P9.2C; worldwide only publication stage; no merge without user approval.
