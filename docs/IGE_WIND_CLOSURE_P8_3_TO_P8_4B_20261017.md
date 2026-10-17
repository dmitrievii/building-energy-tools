# IGE — WIND CLOSURE: P8.3/P8.4A/P8.4B (research stage closed, 2026-10-17)

**Scope of closure:** historical wind data semantics and experimental spatial donor selection, NOT production historical weather and NOT future-wind generation. Freeze all donor experiments. No main merge. Parent verified evidence: `8d8821605107a4aebd960cdb9ae9159cfec28d73`.

## 1. Evidence and decisions

| Workstream | Verified evidence | Decision |
|---|---|---|
| P8.3A/B/C | Original SwissMetNet scalar `fkl010h0` / FROM angle `dkl010h0`, calm-direction and missingness, independent sample years, speed IDW, vector- and unit-circle direction metrics. | Source/vector scientific contracts PASS; no universal interpolation quality claim |
| P8.3D | 2024 physical altitude and terrain donor ranking, six sites; originally geographically restricted 92-station candidate pool; observed altitude-dependent average speed improvement. | Altitude candidate remains **research comparator only** |
| P8.3F2/F3 | Independent original-source ERA5/physical/exposure corrections, 2022 and 2025; 32 correction combinations did **not** consistently outperform raw ERA5 (previous baseline MAE ~1.1064 / 1.0917 m/s). | **Reject all unverified “universal” ERA5 wind corrections** |
| P8.4A1/A2 | Original provider source provenance, hourly vs 10-minute aggregation (5 Swiss/Austrian sites; Jan 2024); MeteoSwiss hourly scalar 6×10min reconstruction MAE ~0.025m/s; GeoSphere hourly vector-reconstruction MAE ~0.024–0.035m/s. | **Source-internal aggregation PASS**; ERA5 instantaneous validity time NOT equivalent to station-hour mean |
| P8.4A3 | Independent 0.25° Google ARCO ERA5 `u10/v10` vs Open-Meteo ERA5 nearest no-downscaling, 3 sites × 4 Jan 2024 UTC samples, matched cells: speed MAE 0.014–0.026m/s, direction 0.59–1.06°. | **Source provenance limited PASS**; no native T639 grid or full-year temporal equivalence claimed |
| P8.4B | Full original MeteoSwiss station-catalog census 159 attempted (158 retrievable, MLJ HTTP 403), 144 exclusive donors in 2022/2025. Altitude IDW4 improved six-site mean speed by ~19.7–19.8%, but only 3/6 sites improved; AIG deteriorated, ZER direction coverage notably deteriorated. | **Do not promote altitude ranking to universal production algorithm** |
| P8.4B2 | Frozen source-only 2023 direction coherence (.65 geometry/.25 direction/.10 availability), six new targets 2024/2025, correctly preregistered rerun 73/73 tests; 6/6 registered acceptance gates each year. Only DIA selected materially different donor set. | **Local/conditional research PASS only**; original off-protocol (.45/.45/.10) run explicitly invalid for confirmation |
| P8.4B3 | 18 new source-eligible geographically spread Swiss targets stratified by altitude, independent 2024/2025, 25km donor buffer. 51/51 tests PASS. **All four** scientific generalization acceptance cases **FAIL**: unbuffered joint minus altitude mean MAE only −0.0084/−0.0103m/s (1/18 sites materially improved), buffered −0.0172/−0.0173m/s (4/18,5/18), buffered direction fixed90 penalty worsened. Most benefit concentrated CIM. | **Joint Coherence IDW4 REJECTED for general-purpose spatial interpolation** |

Authoritative reports in this branch:
- `docs/IGE_P8_4A2_VERIFIED_2024_AGGREGATION_RESULTS_RU.md`
- `docs/IGE_P8_4A3_ERA5_NATIVE_VERIFIED_RESULTS_RU.md`
- `docs/IGE_P8_4B_FULL_CENSUS_2022_2025_VERIFIED_RESULTS_RU.md`
- `docs/IGE_P8_4B2_PREREGISTERED_2024_2025_VERIFIED_RESULTS_RU.md`
- `docs/IGE_P8_4B2_PREREGISTRATION_AUDIT_AND_REPAIR_RU.md`
- `docs/IGE_P8_4B3_18_NEW_SITES_2024_2025_VERIFIED_RESULTS_RU.md`

## 2. What is, and is not, closed

**CLOSED**: current P8.3/P8.4A/B scientific *hypotheses* and their bounded research outcomes, original source documentation, scalar-vs-vector semantics, donor selection benchmarks, negative generalization results, source auditing. No further grid searches, changing donor weight parameters, or retuning on already exposed sites should be run as "validation."

**NOT CLOSED**: observational wind for an arbitrary uninstrumented point, quality of independent historical wind synthesis, faithful temporal aggregation of subhour ERA5 wind vs hourly station reference, true wind-exposure/anemometer-height/roughness corrections and physically justified mountain-flow channeling, local diurnal/sector regime predictions.

**NOT A COMPLETE FUTURE WIND MODEL**: `p7c1_epw_morphing.py` already sets `row[21]=base_speed*GCM_monthly_sfcWind_ratio`, preserves `row[20]` (baseline direction); `p7c4_hourly_ensemble.py` validates the unchanged direction and 28 member-hourly EPWs for seven qualified GCMs. This is **climatological change-factor baseline**: it preserves historical direction/time ordering, DOES NOT predict changes in future direction, calm probabilities, local pressure, wind gusts, turbulence, or specific future weather sequences. `sfcWind` is a daily scalar wind speed magnitude and cannot be used to reconstruct future vector direction or daily future wind rose.

## 3. First-version wind policy for IGE

1. Treat historical EPW with properly verified original provenance as the **wind pattern reference**. Preserve every original historical direction and hourly order (including unresolved/missing flags); do not silently fill missing directions or fabricate a prevailing direction. Source temporal-support differences must be annotated, not force-matched by shifting ±1 hour to improve MAE.
2. For research future EPW, apply only **registered monthly scalar GCM ratio** to nonnegative source speeds with no weather-event pairing; propagate provenance and explicit flag `wind_direction_inherited_historical=true`. `EPW_WIND_DIRECTION_IS_FUTURE_PROJECTION=false`.
3. QA MUST fail for nonfinite/negative speed, invalid direction, missing non-calm direction and mismatch between GCM source-month factor and morphed baseline target month mean (unless serialization tolerance clearly documented). Explicitly track changed calm-hour incidence due to speed scaling and report it; do not claim preserved calm frequency merely because direction is unchanged.
4. Treat original user Meteonorm/EPW files as restricted user-owned licensed data; never commit or redistribute proprietary hourly series. Public original source GCM signals and research-only aggregates are fine. Reuse the authentic P7C.4 source provenance.
5. Distinguish **EPW structural/data-science readiness** from **physical wind-exposure validity** for pressure-driven infiltration, cross-ventilation, natural ventilation and CFD. These applications are HIGH wind sensitivity and require local wind-rose uncertainty and site exposure. Do not silently classify the morphed wind as suitable.

## 4. Decision and next gate

**Wind Closure = completed research *decision log*, not readiness declaration.** This document freezes donor research and hands off to:

- **P8.4C — Future Wind Baseline:** audit original eight-GCM × four-SSP/window × twelve-month `sfcWind` ratios, source authenticity/assumptions and all 8760 hour scalar/missing/direction/persistence/calm/moment/season checks. Verify any physical limitations on future wind direction and cross-variable dependence.
- **P8.4D — Wind-integrated EPW qualification:** full EPW serialization/provider licence, 365day/8760h physical and temporal QC, compare thermal and pressure-driven energy/ventilation sensitivity, flag domain applicability and quantified uncertainties. P7C.5 prior physical audit does not by itself establish wind exposure correctness.

**`production_epw_ready=false`**, `future_local_wind_generalization_proven=false`, no code merge to main.
