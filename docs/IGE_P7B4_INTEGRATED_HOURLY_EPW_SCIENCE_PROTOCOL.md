# IGE P7B.4 — Integrated Hourly Weather Generation and EPW Validation

**2026-10-11. Research pilot only. NOT a production validated EPW.** Independent branch from accepted P7B.3F commit `19d638287d6a6d365f49fdd15ee5598cb7576a21`. `main` untouched.

## Scope / honest validation label

This first P7B.4 integration implements the **historical CanESM5 2013, Graz grid, fixed CET no-DST, 365-day / 8760-hour research file**. It does NOT implement future SSP calendars, missing wind-direction generation, independent sensor-grade DNI/DHI, true EnergyPlus execution or cross-GCM complete 40-window hourly EPWs. A 1R1C ideal load proxy is calculated for relative sensitivity **only**, not a building-simulation validation.

Crucial invariant: preserve the approved **P7B.2 hourly T, RH, dewpoint, pressure proxy, wind-speed, wind-direction-missing sentinel, precipitation, downward longwave and every non-solar EPW field unchanged**. Only columns 13 GHI, 14 DNI, 15 DHI (0-index EPW, Wh/m² accumulated over preceding hour) are replaced with new P7B.3F-capped observed-analogue cloud generator M2, source solar corrected daily totals unchanged. Header comments/version are updated with unambiguous research warnings.

The original P7B.2 data **already applied an additional GeoSphere climatology correction to NASA BCSD daily GHI using 2005–2009**. Preserved daily energy is *that corrected value*, not the original uncalibrated GCM daily rsds. Source event dates are model-weather realizations, not observations of actual 2013 weather. All station observations used for 2007–2008 M2 analogue training are independently original QC-approved, no year 2013 target hours leak into pattern fitting. Frozen alpha=0.75 selected on 2009 and unchanged. P7B.3C–F results remain explicitly research status.

## Source signatures and physical process

Original source SHA-256, enforced fail-closed:

- P7B.2 hourly CSV (8,760 rows): `099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a`.
- P7B.2 corrected daily source/constraint tradeoffs: `5835eff14472367f5eb30bfab9e69a50c358d965e856e757a1377c2224bd3021`.
- P7B.2 accepted original EPW: `ab7c06dcb28c969c7de7886a1afe0afb7917cc78815bb847d0fff1d846e7bd45`.
- GeoSphere P6.3F original 10-minute, strict approved six-of-six hourly GHI: `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`.

1. Parse original P7B.2 hourly, daily CSV and EPW, pin every source SHA and **every fixed-CET 1-hour timestamp**. Validate EPW's 8 headers, 8,760 rows × 35 columns, 1–24 end-of-hour labels, no invented leap day. P7B.2 retains earlier physical RH constraints and tradeoffs. No claim that source 365-day calendar can be generically remapped to 366 days or a different GCM's native time axis.
2. Apply P7B.3F's minimum fractional relaxation of registered previous cap `min(TOA,max(1.25*Haurwitz,0.65*TOA))` toward TOA, only if necessary to preserve the **P7B.2 corrected daily GHI**. In initial 2013 pilot, no relaxation is necessary on any of 365 days. A hypothetical TOA-exceeding day is a hard failure, never silently clipped.
3. Generate 20 reproducible M2 stochastic hourly GHI trajectories (seeds 0–19) with fixed Graz 2007–2008 analogue library, one original model-corrected daily energy per date, exact daily monotone bounded energy projection. Split GHI into DHI/DNI using bounded Erbs diffuse-fraction correlation and hour-integrated solar cosine; check `GHI=DHI+DNI*coszen` to numerical accuracy and physical nonnegativity. This closure is **algebraic only**. No independent measured radiation component is used.
4. Produce *one* structural EPW for seed 0; output statistics and source/solar closure for all 20 seeds; preserve every non-solar EPW field byte-for-byte as parsed CSV tokens, including original missing wind direction code `999`. Do not fill wind direction with a synthetic constant.
5. Compare M2 solar to original P7B.2 on *the same* fixed T/RH/precipitation/wind sequences. Present inter-variable GHI–T/RH/wind correlations as **descriptive**, not sensor-validated. Simulate only a documented **explicit 1R1C 100 m² ideal-load proxy**, UA=0.16 kW/K, C=28 kWh/K, internal 0.25 kW, 10 m² south window g=0.5, 20°C heating and 26°C cooling setpoints. Window gains from approximate geometric south-facing beam and isotropic diffuse/ground-reflected; this proxy is not EnergyPlus, 5R1C ISO 13790, or a calibrated test building.
6. Independent EPW read-back and scientific audit. `production_ready=false` regardless of structural pass; reject publication as finished weather until actual EnergyPlus/OpenStudio parsing/zone operation (if available), wind direction science, humidity and precipitation hourly dependence, independent DNI/DHI and wider climate/site evidence.

## Original-source local preflight (CI to reproduce)

CanESM5 2013, all 365 corrected daily source energies fit the unchanged M2 cap; 8,760 EPW hours written. Baseline original P7B.2 1R1C proxy: 8,321.85 kWh heating, 564.35 kWh cooling. New M2, **8 preliminary seeds**: heating mean 8,136.71 kWh (−2.22%), cooling mean 554.76 kWh (−1.70%). Values are NOT actual building demands, can change with aperture, envelope, shading, stochastic seed, beam/diffuse algorithm, and climate setting. Canonical results come from 20-seed original-source GitHub Actions once completed.

## Pending science gates

- Real EnergyPlus/Building Simulation execution with a documented model and measured/approved reference.
- International observed GHI hourly climate transfer beyond Austrian stations; no tropical/desert sensor-grade test yet.
- Wind direction source and multivariate dependence, precipitation occurrence and cross-variable cloud sequences, humid heat extrema and psychrometric holdout.
- Direct and diffuse solar **sensor measurements**, not just GHI identity closure.
- Multi-year eight-GCM and SSP EPW calendar mapping, including noleap/proleptic Gregorian 29 Feb policy and leap-year handling.

**EPW label:** `STRUCTURAL_RESEARCH_FORMAT_PASSED__SCIENTIFIC_NOT_VALIDATED`.