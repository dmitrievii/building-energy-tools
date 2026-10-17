# IGE P8.6 — Private 28 EPW Original-Byte and Cross-Variable Final Qualification

**Frozen protocol, 2026-10-17.** Scientific predecessor: P8.5 `a947eb6fa4c3ebe139f987e094e75cb24acc58bd`. **No change of GCM signals, previous 28 original files, algorithms or production branch**. Do not assert completed original-source qualification without real bytes.

## Acquisition audit (executed before code development)

- The original restricted `Graz-hour_contemporary_seed1.epw`, 28 full P7C.4 hourly EPWs, and 28 latest P7C.5B photometrically corrected EPWs **are absent from mounted files, conversation/Library file search and public GitHub CI**. They are user-controlled Meteonorm-origin licensed artifacts; never download/republish or substitute publicly generated P7B5 or P7C1 fixtures to fabricate P8.6 completion.
- Available evidence: 28 P7C.4 original SHA hashes in `results/p7c4_28_hourly_model_summary.csv`, 28 P7C.5B input/output SHA in `results/p7c5b_photometric_28_summary.csv`, baseline SHA `dad69174304c3a13cc095841c4cb9636bf99cc3a81502c553af862cd06677`, all previous scientific reports.
- Audit is executed on actual private files **only when all required byte inputs are available**. Public CI only runs unit/contract regressions and one actual publicly archived P7B.5 research EPW as expressly labeled *smoke test*, not a validation of 28 authentic Meteonorm files.

## Immutable input/source gates (FAIL CLOSED)

1. Exact original licensed baseline SHA and EPW 8 header/8760×35 structure.
2. Exactly 28 unique original P7C.4 EPWs, required filenames and their individual exact SHA values. Exactly 28 unique P7C.5B outputs, each exact expected SHA and linked by its `source_p7c4_sha256` to the correct GCM/SSP/time period; no missing/extra mix-ups.
3. P7C.4→P7C.5B: identical hourly timestamps and **all EPW fields other than 16,17,18**, including entire original meteorology, direction, precipitation, solar radiation, sky longwave, and cloud-cover values. Preserve original 8 headers.
4. Respect typical-year EPW **calendar month/day/hour-ending 1..24/60 no DST**; original EPW `Year` values may vary by component year in a TMY/typical-year file, so require canonical month/day/hour and consistency with baseline, not a fictitious year=2013 assertion.
5. No rewriting original 28 files; run once and archive **only aggregate metrics, input SHA provenance and explicit scientific pass/block flags**.

## Independent physical cross-variable diagnostics (each member + baseline)

- **Psychrometrics**: drybulb, dewpoint, RH, pressure and Buck saturation vapor pressure, derived humidity ratio, vapor-pressure deficit; no valid dewpoint>T by >0.15°C, RH outside [0,100], dry/wet reporting sentinel pollution, or RH-dewpoint discrepancy >2 percentage points on quality-eligible hours. Report monthly q, annual/monthly RH, dewpoint depression, and continuous episodes `RH>=99.995%` with counts, lengths and seasonal breakdown. Calculate P7C.4 legacy `np.isclose(RH,100,atol=1e-5,rtol=1e-5)` metric independently — do not obscure 14520 vs 14536 differences. No claim that global monthly q mass balance validates humidity temporal distribution.
- **Solar**: GHI/DNI/DHI finite/≥0; `DHI<=GHI+rounding`, `(GHI−DHI)/DNI` in physical cosine bounds daylight; measured/EPW solar local-time geometry mismatch diagnostic by independent astronomical approximation. Report solar annual/day/month, diffuse fraction, high DNI tail, zero-at-night and cross-model radiation limits. Compute extraterrestrial TOA/sun height separately rather than treating the Erbs closure alone as independent measurement. Different EPW horizontal/normal channels must retain exact source units.
- **Illuminance**: match irradiance/photometric recomposition `lux_GHI≈lux_DHI+lux_DNI·(GHI−DHI)/DNI`, with ≤2 lux daylight closure (registered numerical tolerance; no independent efficacy validation). Check original P7C.4 vs P7C.5B field-only repair and missing zenith luminance sentinel; flag fallback/efficacy calibration uncertainty. No production daylight claims.
- **Longwave/clouds and coupling**: evaluate EPW downwelling horizontal IR `W/m²`, sky-effective emissivity `L/(sigma*T_K⁴)`, implied sky temperature, cloud-cover (total/opaque 0–10 tenths or explicit 99 missing), correlations of IR vs T/RH/clouds and solar vs clouds. Do not treat correlation as a physical law or hard-fail for realistic inversion. Report inherited cloud-hour fraction under future solar morph, altitude and reference longwave uncertainty, and missing visibility/sky luminance explicitly.
- **Precipitation / wind**: compare EPW inherited precipitation occurrence and wind direction against exact baseline on same hours; velocities must be finite nonnegative; noncalm directional 999 missing or calm → new noncalm directions are physical suitability blockers even if a numeric direction was inherited. Check monthly wind-speed ratio against original frozen P7C3 384 signals, but do not call source azimuth a future projection. Count calm changes and 16-sector rose changes.
- **Cross-variable weather time coherence**: 1h/3h/6h difference and run-length diagnostics, conditional RH saturation during high temperature, hot&humid joint exposure, near-zero calm wind, precipitation with clear-sky and thermal/moisture state, P7C4 altered irradiance while cover unchanged, inherited longwave/ground-temperature metadata, anomalous artificial step changes at month boundaries. Thresholds are diagnostics unless physically inviolable; never adjust an input EPW to pass.
- **P7C.4 optimizer**: strict convergence was previously false 28/28 (600 accepted iterations); demand convergence proof or independent bounded optimality + humidity empirical validity, not just q monthly balance. This remains separate release BLOCKER independent of EPW algebra success.
- **Native EnergyPlus**: reuse existing `p7c5b_private_energyplus_benchmark.py` (29 annual actual runs: baseline+28, official EnergyPlus v26.2 pinned) only in licensed local environment, with strict weather/IDF checks and aggregate SQL outputs. Not an independent meteorological accuracy certificate.

## Predeclared release gates

PASS *private file-integrity* iff **all 57 authentic sources** (baseline+28 P7C4+28 P7C5B) match registered SHA/format/member mapping/allowed columns, all critical weather fields finite/physically valid with correct missing sentinels, and six-hourly temporal sequence unchanged. Fail closed if even one is missing/modified. Report actual source-byte availability and every failed file.

PASS *numerical cross-field research* iff every member has no critical psychrometric, radiation-negative, impossible solar cosine, invalid EPW date, unresolved noncalm direction, or illuminance algebra conflict >2 lx; retain warnings for probable but not logically impossible correlations/sky values. A single blocked result must not be called PASS.

PASS *physical/operational climate* requires independent climate validation, photometric/radiometric validation, 28+1 real EnergyPlus, temporal humidity solution and no unqualified future wind-direction/geography claims — **cannot be asserted by private EPW readability alone**. IPSL four missing `huss` states remain separately BLOCKED, not silently replaced.

No raw proprietary EPWs in GitHub Actions artifacts, no public upload, no merge to main. Keep `production_epw_ready=false` pending explicit acceptance.
