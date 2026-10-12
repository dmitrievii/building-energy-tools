# IGE P7C.5B — Solar–Illuminance Coherence and Private Full-EnergyPlus Qualification

**Research status, 2026-10-12:** local EPW photometric correction executed and source-verified for **28/28** GCM × SSP × period members. **No claim of 28-case EnergyPlus simulation success:** EnergyPlus 26.2.0 binary is not yet available in the private local execution environment. The previous GitHub P7C.5 benchmark independently established five synthetic-fixture EnergyPlus runs; those five are **not** the 28 proprietary-source cases.

## Provenance and data partitions

- P7C.4: 28 user-provided authentic-Graz-Meteonorm-derived research EPWs; original immutable archive and `manifest_sha256.json` validated independently; eight-GCM P7C.3 signals upstream, IPSL-CM6A-LR excluded from full EPW because `huss` is missing.
- Original reference: `Graz-hour_contemporary_seed1.epw`, Meteonorm 8.2.0.24079, 8760 hours, 35 EPW columns. Baseline SHA-256 printed in audit. **Not included in the public repository.**
- P7C.5B: only EPW columns **16–18 zero-based** (global horizontal illuminance, direct normal illuminance, diffuse horizontal illuminance) may change. EPW 19 (zenith luminance) remains missing `9999`; all other meteorological fields must be bytewise identical as parsed values.
- All 28 derived commercial-input EPWs are retained in the user-only research ZIP; only source code, methods, aggregate audit and public fixture tests go to GitHub.

## Method

For each hourly record, use the *source-referenced luminous efficacy* of the original Meteonorm hourly record: \(\eta_\mathrm{beam}=E_{\mathrm{dn,source}}/I_{\mathrm{dn,source}}\), \(\eta_\mathrm{diff}=E_{\mathrm{dif,source}}/I_{\mathrm{dif,source}}\), where source irradiance is sufficiently positive and luminous efficacy is finite and physically plausible (2–220 lux per W/m²). If it is undefined, use the **median efficacy for the same calendar month**, calculated only from valid source records. This is an explicit *empirical assumption*, not reconstructed direct observations. Irradiance energy remains unchanged.

Derive apparent projection \(c=(GHI-DHI)/DNI\) when \(DNI>0\); require \(c\in[0,1]\) up to integer round-off. Set future direct illuminance and diffuse illuminance by scaling the corresponding future irradiances by their luminous efficacies; set global horizontal illuminance to \(E_{\rm dif}+c E_{\rm dir}\), with integer-lux rounding. In source twilight with all irradiance channels zero (both baseline and future), preserve original near-horizon illuminances. Never create zenith luminance from thin air.

This is a **cross-field closure repair**, not a validation of absolute illuminance or Perez/CIE sky distribution. The model also inherits existing sky-cover, cloudiness, opaque sky and horizon/event sequencing limitations of P7C.4.

## Local results

- Original corrected source EPWs: **28 of 28**; **245,280 hourly records**.
- EPW hours with one or more modified illuminance variables: **127,305**.
- Maximum reconstructed instantaneous photometric closure error: **0.499985 lux**.
- Monthly fallback luminous-efficacy instances (beam/diffuse channels counted separately): **37,632** across 28 EPWs (**1,344 per file**).
- Source positive twilight illuminance records with unchanged zero irradiance: **2,044** aggregated (73 per file).
- Exact parsed-field comparison across all 245,280 records: only indices 16/17/18 changed. Changed counts: global 127,128; direct 122,072; diffuse 127,143.
- 14/14 local mathematical and source-boundary tests PASS. Deterministic byte-reproducibility verified on fixtures.
- Baseline zenith luminance missing for every hour; stays unchanged. No new independent daytime brightness evidence.

## EnergyPlus experiment design (not simulated until executable available privately)

- Official EnergyPlus **26.2.0 (4bd7a1f26f)**, release asset SHA-256 `b848da8236482a2171a67d7eab00c82162105b653ffab3ae3b6c2217c433a8a1`.
- Use pinned official v26.2.0 `testfiles/1ZoneUncontrolled.idf` with the P7C.5 already-validated modifications: simple one-zone 232.25m² enclosure, `IdealLoadsAirSystem`, 20 °C heating/26 °C cooling, no window, no daylight controls. This fixture validates climatic changes in heating/cooling demand, **not daylight-controlled electric lighting or glare**.
- Execute **29 weather files**: the authentic contemporary Graz EPW as reference plus all **28 corrected** EPWs. For each file: independent `energyplus -w ... -d ...` execution, check `eplusout.err`, fail on any Severe or Fatal, require `eplusout.sql`, extract 8760 hourly records for heating, cooling and zone mean temperature, sum joules to kWh. Report pressure, solar or psychrometric warnings rather than suppressing them.
- Only after executing all 29 locally and verifying scientific diagnostics can mark the actual-28 case as `ENERGYPLUS_BENCHMARK_PASS`. Until then the accurate flag is `energyplus_actual_simulation_executed=false`.
- Paired P7C.4 vs P7C.5B heating/cooling invariance would be a **useful additional check** for the no-window fixture; its results should be indistinguishable within solver numerical precision because the correction only changes EPW illuminance. This claim is a **hypothesis**, not yet measured.
- For **daylight/lighting** qualification additionally build a windowed `Daylighting:Controls` reference model, validate photopic efficacy against independent measurements or accepted luminance model, and propagate uncertainty. Do not pass production daylight qualification based on present cross-field repair alone.

## Explicit open blockers

1. EnergyPlus 26.2 real 29-weather-file benchmark on original Meteonorm-derived input **not yet executed** (binary unavailable in local container at time of writing). The GitHub public workflow contains only public synthetic fixture tests and may distribute public EnergyPlus runtime, **never the licensed EPWs**.
2. Original solar sky-luminance measurements and zenith-luminance data are unavailable, so absolute daylight predictions remain unqualified.
3. P7C.4 humidity optimizer had not demonstrated strict optimizer convergence; modifying illuminance does not resolve it.
4. Four IPSL-CM6A-LR future scenarios remain blocked by missing `huss`.
5. Meteorological and irradiation future-event chronology remains inherited from the contemporary source EPW.

**Conclusion:** P7C.5B solar–illuminance cross-field consistency passes local research QC. Full real-source EnergyPlus and production qualification **remain OPEN**.