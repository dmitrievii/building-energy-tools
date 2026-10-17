# IGE P8.4D — VERIFIED integrated EPW wind field qualification + native EnergyPlus (2026-10-17)

**Verified stage status:** `P8.4D_WIND_ONLY_EPW_STRUCTURAL_RESEARCH_PASS / 3_OF_32_DIRECTION_EXPOSURE_BLOCKED / REAL_ENERGYPLUS_INFILTRATION_PASS / REAL_ENERGYPLUS_WIND_AND_STACK_OPENING_PASS / LICENSED_28_EPW_REQUALIFICATION_NOT_RUN / PRODUCTION_EPW_READY_FALSE`.

## 1. What was actually executed

- Latest [GitHub Actions #39030016808](https://github.com/dmitrievii/building-energy-tools/actions/runs/39030016808), computation commit `c6c42648d7001aca9d1258fa59dd2c4a0ee42236`. **3/3 jobs SUCCESS**; **57/57** physics/regression contracts PASS: 18 integrated EPW + 7 native opening + 23 P8.4C + 9 P7C.5 tests. The first CI #39029686962 failed on a test wrongly comparing literal `999` and `999.000`, numerically identical EPW missing-direction codes; fixture assertion corrected, scientific algorithm unchanged. Prior successful #39029724063 qualified structure+infiltration alone; latest run adds and confirms native wind+stack opening.
- Public P7B.5 original scientific wind analogue [run #38174920762](https://github.com/dmitrievii/building-energy-tools/actions/runs/38174920762): `Graz_CanESM5_2013_IGE_P7B5_WIND_ANALOGUE_RESEARCH_ONLY.epw`, immutable source SHA256 **`9d8af9d4e42e3cd875dcaaee06a6474f9c865537cfd0ad7d381e164e4a858a08`**; original P7B.5 scientific audit SHA256 `b1cb5e3a5a047749f2244835917f9ff39051d56ec4e8910c531fe0c90548c72b`. The EPW has **research synthetic P7B.4 radiation/thermodynamics**, and QC-supported **analogue** hourly directions from GeoSphere training (not contemporaneous with synthetic EPW temperatures/speeds); **NOT a site-measured weather year or licensed original Meteonorm weather**.
- Full original-public-EPW structural and wind-morph numerical [artifact #12100440403](https://github.com/dmitrievii/building-energy-tools/actions/runs/39030016808/artifacts/12100440403): ZIP SHA256 `02ebedfbeccc9df5503fea3886e00d63a9f17abb4009ee7cd32f52545cb6688f`; derived aggregate JSON SHA256 `a62d6b69d19b1ac94183567d87414cbea7c535dac96954775cf22747bca75d8f`; CRC PASS. No source/derived hourly EPW archived.
- Actual native EnergyPlus v26.2.0 release, verified GitHub official SHA256 `b848da8236482a2171a67d7eab00c82162105b653ffab3ae3b6c2217c433a8a1`, official upstream one-zone IDF with ideal loads. **Nine genuinely executed annual simulations**, checked `eplusout.err` and nonempty SQLite hourly flow and HVAC output values; [artifact #12099863009](https://github.com/dmitrievii/building-energy-tools/actions/runs/39030016808/artifacts/12099863009), ZIP SHA256 `a82c39fca24d79129429f9c3fc70a3f21e4a18a26f805f2ac9ed09e23298cec5`; original EnergyPlus infiltration JSON SHA256 `df79c0d59a70dec7d8c4f4c704d196df7487170c7517abc09ac7c5c92bceefef`; opening JSON SHA256 `c7c50d4f79b312df72930f3a97a15d46cbe5e54b3716e1f4770f5208a5b9c58f`. Artifact ZIP CRC PASS. Each simulation showed **0 severe, 0 fatal, 2 warnings**: official 1Zone design-day pressure 81198 Pa differs >10% from current local standard ~97005 Pa. Warnings are in the **upstream official fixture/design-day**, not evidence of verified design-day physics at Graz.

## 2. Actual EPW physical wind fields: 32/32 wind-only transformations

- Every source and derived research record: **8 header rows, 8760 strict non-DST noleap-hour timestamps, 35 EPW columns**; source wind 0–360° FROM or 999 missing, finite speeds. **34 of 35 fields numerically/string-identical to source** during pure speed morph, including direction and all thermodynamic/solar/rain fields.
- GCM factors: original preregistered P7C.3 **384 (8 GCM×4 SSP/windows×12 months)** daily scalar `sfcWind` change factors. **384/384** original EPW-month mean speed balances close, maximum absolute ratio residual **0.000110882 m/s** (3-digit m/s speed serialization).
- Base research EPW: mean speed **2.413062 m/s**, 95th speed percentile 4.4823m/s, calm (<0.5m/s) **0.02283%**. All 32 wind-only morphed research scenarios: annual mean speed **2.19368–2.56819 m/s**, calm fraction **0.01142–0.11416%**, conditional 16-sector wind-rose total-variation change between 0 and **0.000528** in this source. These are **changes relative to a synthetic research EPW**, not future climatological predictions.
- **Critical source-calm activation guard found 3/32 physical wind-exposure blockers**, each exactly **one** hourly case where historical speed <0.5m/s, morphed speed >=0.5m/s but the inherited original calm-hour azimuth is **not physically qualified** despite being numeric. No non-calm `999` missing angular sentinel in this source. Affected GCM states:
  1. `ACCESS-CM2 / ssp585-2080-2099` — 1 promoted unqualified calm direction;
  2. `MPI-ESM1-2-HR / ssp245-2040-2059` — 1;
  3. `MPI-ESM1-2-HR / ssp585-2080-2099` — 1.
- These three remain **EPW structural PASS, physical local-wind suitability BLOCKED**. The other 29 pass *this specific inherited-direction/calm consistency gate*, but **none** gains proof of future atmospheric direction/exposure/pressure. Model speed changes preserve actual source angle numbers and within-month order by construction; real future wind rose and synoptic timing are NOT forecast. GCM `sfcWind` is scalar, no projected `uas/vas` here.
- **IPSL-CM6A-LR wind-only factors are included**, but four full future P7C.4 EPWs remain blocked because native historical/future `huss` was unavailable. No 32 member FULL EPWs were constructed/qualified in P8.4D.

## 3. ACTUAL EnergyPlus: wind-dependent infiltration, identical weather except wind speed

Wind-responsive research formula per EnergyPlus `ZoneInfiltration:DesignFlowRate`:
`I_design=0.080m³/s, A=0.10, B=0, C=0.20 s/m, D=0`. Reference model deliberately fixed `A=1,B=C=D=0`. These coefficients are **not calibrated** n50/window leaks. Other 34 EPW fields and all construction/HVAC parameters remain identical within the wind-scale comparisons.

| Research run | Weather wind scaling | Actual annual mean standard-density infiltration (m³/s) | EnergyPlus heating (kWh) | Cooling (kWh) |
|---|---:|---:|---:|---:|
| Wind-responsive | 0.5× | **0.0183554** | 10,966.59 | 881.69 |
| Wind-responsive | 1.0× | **0.0285702** | 12,080.53 | 682.17 |
| Wind-responsive | 1.5× | **0.0387851** | 13,248.21 | 537.81 |
| Fixed-airflow control | 0.5× | **0.0814052** | 16,749.17 | 759.21 |
| Fixed-airflow control | 1.5× | **0.0814052** | 16,993.34 | 497.89 |

**Pass:** EnergyPlus directly reports monotonic wind-responsive infiltration flow and constant wind-independent control flow. **Important interpretation:** heating/cooling still change in fixed-airflow control because wind can change **external convection** even when infiltration is held constant. Thus do not attribute all heating/cooling energy changes to infiltration, do not claim component-level causal isolation beyond direct measured airflow.

## 4. ACTUAL EnergyPlus: independently executed wind+stack opening area

A **new supplementary exploratory verification**, added **after initial infiltration output was inspected but before any actual opening outcomes were accessed**, uses official `ZoneVentilation:WindandStackOpenArea`, not a substitute infiltration model. Opening `0.25m²`, outward azimuth `180°`, opening effectiveness `AutoCalculate` (responds to meteorological wind angle), height difference `0.5m`, discharge coefficient `AutoCalculate`. Control thresholds: indoor 21–40°C, outdoor 10–28°C, `T_inside-T_outside>=0.5K`, max wind speed 15m/s. No occupant-controlled opening schedules, no AirflowNetwork, no façade CFD. All thermodynamic/radiometric source records unchanged between tests.

| Research WindAndStack actual EnergyPlus run | Average ventilation (m³/s) | Peak ventilation (m³/s) | Heating (kWh) | Cooling (kWh) |
|---|---:|---:|---:|---:|
| wind 0.5×, azimuth original | 0.008731 | 0.152331 | 16,774.51 | 638.12 |
| wind 1.0×, azimuth original | 0.008757 | 0.218071 | 16,871.17 | 513.29 |
| wind 1.5×, azimuth original | 0.008324 | 0.285675 | 17,011.25 | 416.77 |
| wind 1.0×, azimuth rotated +90° | **0.009913** | **0.245660** | 16,870.16 | 505.77 |

**Pass:** both speed and azimuth changes have a **measured, nonzero influence** on actual native hourly EnergyPlus ventilation outputs; EPlus converged with 0 severe/fatal. The *annual mean* need **not** increase monotonically with speed, because indoor temperatures and the opening eligibility schedule respond dynamically to changed weather. Peak ventilation increases with wind multiplier. Directional +90° test shows orientation sensitivity but is a deliberately artificial wind-sector perturbation, not validation of future rotation of the prevailing wind.

**This is not proof of pressure-driven whole-building airflow.** There is no actual façade permeability/pressure coefficient array, no AirflowNetwork/CFD, no window-control behavioral calibration, and input azimuth originates from P7B.5 research analogues. Treat annual energy differences as illustrative only; do not transfer to any real building without exposure, envelope and use calibration.

## 5. Research versus production decisions and handoff

- **Scientific research integration**: P8.4D has demonstrated structural EPW wind transformation, numerical monthly source parity, protective direction/calm guard, and both actual EnergyPlus wind-responsive infiltration **and** orientation-aware natural opening simulation in public CI. **Research Integration PASS**.
- **Physical direction exposure**: the 3/32 blocked states must remain flagged; even the other 29 cannot be marketed as predicted future rose. This research's public P7B.5 EPW is explicitly **not** a measured full site weather year.
- **Full authentic licensed user EPWs**: P8.4D was **NOT rerun on the 28 preexisting licensed Meteonorm-based P7C.4 EPWs** or the original licensed baseline; those bytes were not available to public CI. Previous P7C.5 local independent 28 EPW physical audit is still historical evidence, NOT the same as this P8.4D source.
- **Operational climate engine**: need qualified wind source for requested arbitrary coordinates and to bind a user-authorized 8760h EPW into production paths, define domain-applicability flags for infiltration/natural-ventilation sensitivity, complete 28 authentic EPW readback/wind audit or a securely reproducible equivalent, and explicitly preserve source-level missing angular uncertainty.
- `research_complete=true`, `historical_station_to_any_point_wind_validated=false`, `future_direction_change_predicted=false`, `licensed_28_epw_current_ci_verified=false`, **`production_epw_ready=false`**. No merges to `main`.

Further development of wind direction should be a **separate advanced physical model**, not retuning failed generic P8.4B donor coefficients. Only after production-quality source/provenance and physical P8.4D requirements are satisfied should wind module be integrated into official Climate Analyzer.
