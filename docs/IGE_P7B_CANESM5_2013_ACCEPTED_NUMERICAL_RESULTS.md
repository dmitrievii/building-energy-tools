# IGE P7B — Verified CanESM5 2013 Daily-to-Hourly Science Pilot

**Accepted source run:** GitHub Actions [#38144426555](https://github.com/dmitrievii/building-energy-tools/actions/runs/38144426555), **SUCCESS**, execution commit \`f763a84a90c2a2d3d0ec53e5d97e23d333b35553\`. Original Actions artifact ID \`11703589310\`, name \`ige-p7b-canesm5-original-daily-to-synthetic-hourly-graz-2013\`. An original standalone ZIP was independently downloaded, its CRC checked and all **four** original derived-file SHA-256 hashes matched the embedded \`p7b_science_audit.json\`.

## Accepted computational milestone

Original source: immutable CanESM5 NASA NEX-GDDP-CMIP6 (NASA BCSD, historical 1995–2014, source grid [46.875, 15.375], 2013 non-leap subset), 365 daily input rows. This is a **historical GCM weather realization, not the actually observed Graz 2013 weather**. Input original source \`joint_daily_raw.csv\` SHA-256 \`77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef\`.

First genuinely synthetically generated weather file:
\`Graz_2013_CanESM5_P7B_SYNTHETIC_DAILY_TO_HOURLY_RESEARCH.epw\` — **8,760 hours, 35 EPW data columns, eight EPW headers**, local standard CET fixed UTC+01:00 (no DST), 1,893,657 bytes, SHA-256 \`eb3d2813ce1ef9a3e240a5e0760a55cf3c96098c643771560e76a05a503cf857\`.

Original-sourced native daily conservation closure, 365/365 days, maximum absolute residual **5.329070518200751×10⁻¹⁵** for the eight explicitly constrained daily source variables: tas mean, tas min, tas max, hurs mean, wind speed mean, precipitation total, GHI total and downwelling longwave radiation total. Note this **does not include native huss (specific humidity)**. Solar Erbs-derived split internal closure flagged zero hourly calculation-review cases: this proves neither measured DNI/DHI nor independent solar accuracy.

The first CI attempt [#38143898411](https://github.com/dmitrievii/building-energy-tools/actions/runs/38143898411) FAILED at a *test error-message mismatch*. A separate source-file examination revealed a scientifically relevant input nuance: original CanESM5 mean daily T differs from exactly (Tmin+Tmax)/2 by up to ~0.00001526 K due to independently rounded source variables. The corrected synthesis applies a tiny nonextreme-hour adjustment, keeping the 03:00 minimum and 15:00 maximum unchanged while preserving native temperature mean. Two subsequent original-source CI runs passed, including final accepted [#38144426555](https://github.com/dmitrievii/building-energy-tools/actions/runs/38144426555). Do not claim the initial failed run passed or that source hourly realism was established by the software test.

## Scientific limitations visible in the actual results

**Water-vapor closure remains unresolved:** P7B currently conserves mean original hurs by holding RH constant across each source day and derives dewpoint from hourly T/RH at a standard-atmosphere height-pressure proxy, but original native huss cannot simultaneously match. The largest absolute hourly-derived daily-mean q minus native \`huss\` difference is **0.0035708528554075254 kg/kg** (3.57 g/kg); 82/365 model days exceed 0.001 kg/kg (1 g/kg). This is a substantial research issue and a first-priority P7B.1 psychrometric correction target. The generated EPW is not physically valid against all original daily moisture constraints.

**Historical solar distributions differ strongly:** P7B derived model-year annual GHI is **1,635.483 kWh/m²**, while source-assembled P7A actual-calendar-year 2013 NASA POWER hourly original reference gives **1,155.021 kWh/m²**, a ratio **1.416**. The model year and observed year are independent weather realizations; a single-calendar-year difference is **not** by itself a defensible model bias or proven radiometer error. A seasonally stratified multi-year comparison is needed before deciding how to apply P6 solar adjustment methods M0–M3. Nonetheless, this magnitude is a critical problem for using this exploratory EPW directly for building energy forecasts.

**Temperature and wind:** monthly mean P7B minus P7A temperature differences range **−2.35°C to +4.07°C** (unpaired model-year-versus-observed-year distribution), wind-speed monthly means differ by **+0.19 to +2.10 m/s**. Neither is a day-by-day model error statistic. Intraday temperature uses uncalibrated cosine and the wind has seeded exploratory autocorrelation; no measured wind direction is available (EPW missing marker 999). Pressure is standard-atmosphere proxy (not native surface pressure), rain timing is seeded and daily depth preserving, and sky diffuse/DNI are estimated by Erbs rather than observed.

## Frozen derived output SHA and reproducibility

- \`p7b_hourly_synthetic_weather.csv\` SHA \`e021f8ae458e5e0f3119ddb7df04a420bd081e2bca84869d56e0cae4269d67dc\`
- \`p7b_daily_native_conservation.csv\` SHA \`80d816ea3fb3b0181e8cf23a330222f89a3986029f7732fdd8d56f5ab61d521d\`
- \`p7b_monthly_unpaired_reference_comparison.csv\` SHA \`9ec2ddfa29f83ba4c44a7e23a535bb19ac1132705ecf16660f78ce9739752707\`
- EPW SHA as above. Original source artifact [#11703589310](https://github.com/dmitrievii/building-energy-tools/actions/runs/38144426555/artifacts/11703589310) is short-lived (30-day retention); download into institution-approved persistent research custody and keep raw source/commit and per-file SHA separately.

**Accepted technical status:** \`DAILY_CONSERVATION_AND_8760_EPW_FORMAT_PASS\`.  
**Scientific status:** \`SYNTHETIC_HOURLY_DAILY_CONSERVATION_ONLY_NOT_OBSERVED_CLIMATE\`.  
**Production readiness:** \`epw_production_ready=false\`.

## P7B.1 follow-up, rather than scaling this exact algorithm prematurely

1. Close joint daily \`hurs\`–\`huss\`–T–p water-vapor physics, with a documented source hierarchy where mathematically incompatible daily constraints are not silently "reconciled."
2. Validate diurnal T dynamics, rain spell/occurrence, wind autocorrelation and solar hourly partition against original independent multi-year observations; use **unpaired annual/monthly/seasonal climatological distributions**, not arbitrary same-date comparisons.
3. Revisit solar bias: prior P6 M0–M3 solar correction must be tested on model windows without double applying corrections to the already BCSD-adjusted NASA NEX raw \`rsds\`.
4. Use a scientifically documented wind-direction and pressure source/reconstruction strategy, perform EnergyPlus simulation smoke run and quantify heating/cooling sensitivity before publishing this as a practical EPW.
5. Preserve P7A reference and P7A-S proposed GeoSphere measured GHI EPW separately. Avoid any change to production \`main\` without user instruction.
