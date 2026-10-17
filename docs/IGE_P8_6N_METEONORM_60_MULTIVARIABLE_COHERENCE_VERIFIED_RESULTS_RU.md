# IGE P8.6N — Independent 60-EPW Coupled Weather Coherence: Verified Original Source Results

**2026-10-17 · status**: `METEONORM_SOURCE_EPWS_INTERNAL_CONDITIONAL_COHERENCE_PASS` / `ANOMALY_EXPOSURE_QC_WARNINGS` / `INDEPENDENT_IGE_COMPARATIVE_ACCURACY_NOT_EVALUATED` / `IGE_PRIVATE_P7C5B_28_EPWS_NOT_AVAILABLE` / `PRODUCTION_EPW_READY=false`.

## 1. Evidence and scope

Independent computation on user-provided `epw_new(2).zip`, original Meteonorm 8.2.0.24079 EPW (archive SHA256 `03e82c369ada2e6c20389ae01df06e498ee8edf66d3872b85eaee92a201edc57`): **60 files, 5 sites × 4 climate scenarios × 3 seeds, 525600 time-stamped hourly weather records**. User-owned hourly licensed data and 60 EPW file contents **NOT** committed to GitHub. The corresponding code, 8 PASS aggregate scientific regression tests, full Russian research report, 60/45/720-member coupled-statistic tables, charts and 14 daily aggregate anomaly cases are in local user download package `IGE_P8_6N_meteonorm_60_coupled_weather_validation.zip` (ZIP SHA256 `d8980a70f2eb87abde4abf88ac6b6ff7cba53405780feadb20c8b8518742ff7f`). No GitHub CI run on private EPWs is claimed.

**Statistical question:** when the EPW precipitation depth field N33(index 33) is positive, is the physical co-occurrence of cloudy sky, moisture, low shortwave insolation, high diffuse fraction and atmospheric longwave plausible? Use conditional same-local-calendar-month × same-hour comparisons *within each EPW* (same-month day comparisons separately). Do not compare raw nighttime GHI to daylight sunshine. Normalized solar clearness `Kt = GHI /(1361Wm-2 × Earth–Sun eccentricity × max(cosZ_noaa,0))` only when `cosZ>0.15` under EPW local standard time. Meteorological weather associations can have exceptions; this is NOT causal attribution or independent station observational validation.

**Critical precipitation metadata caveat:** the accumulation period field N34(index 34) is **99 (missing) for ALL 525600 hours**. The user EPW contains a precipitation depth value per hour-record but does **not** identify an independently verified period of accumulation (mm/h). Conditional wet `N33>0` is supported, but sums of N33 across a day (e.g. ">=1mm/day") are **conditionally interpreted**, not attested station rain observations. EnergyPlus EPW Data Dictionary defines N33/N34 accordingly: https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html . Meteonorm documentation: https://docs.meteonorm.com/overview/parameters .

## 2. Statistically conditioned common-hour numerical findings

**44986/525600** EPW precipitation-positive hour records. Mean across all **60 distinct EPW**:

| Associated quantity | EPW N33>0 | EPW N33=0 |
|---|---:|---:|
| Total sky cover (tenths) | **9.65** | 4.33 |
| Noncalm cloud >=8 tenths / sky cover probability (%) | **95.7** | 31.8 |
| Near-surface relative humidity (%) | **85.7** | 73.2 |
| Approx water-vapor specific humidity (g/kg) | **9.44** | 6.95 |
| Dew-point depression T−Td (°C) | **2.52** | 5.30 |
| Daytime astronomical clearness Kt | **0.249** | 0.555 |
| Diffuse shortwave ratio DHI/GHI (daytime) | **0.939** | 0.482 |
| Sky effective emissivity `LW/(sigma T_K^4)` | **0.897** | 0.818 |

**More credible than unconditional averages:** *rain-minus-dry within identical same-month and same-clock-hour source bins*, weighted by rain observations per bin then equally by EPW:
RH **+13.1887 percentage points**, cloud cover **+5.3536 tenths**, specific humidity **+1.8450 g/kg**, clearness Kt **−0.31194**, diffuse fraction DHI/GHI **+0.4640**, effective sky emissivity **+0.07459**, dewpoint depression **−2.987°C**. **All 60/60** original files have RH-rain positive, cloud-rain positive and Kt-rain negative associations.

Conditional independent daytime correlations **within each file**:
- Total cloud vs Kt: Pearson range **−0.854..−0.793**, mean **−0.829**, sign 60/60.
- Total cloud vs daytime diffuse fraction: **+0.927..+0.958**, mean **+0.945**, sign 60/60.
- Total cloud vs effective IR emissivity: **+0.516..+0.689**, mean **+0.588**, sign 60/60.

Rain source site×scenario×seed **date sequences are not independent of one another**, and correlation may be partly **built into Meteonorm's algorithm**. This is **self-consistency, not independent truth of clouds/precipitation physics**.

## 3. Day and station-level conditional contrasts

**5387** file-days with daily SUM of recorded N33 >=1mm, **14579** strictly dry days (other 1934 days with positive but <1mm summed N33). Day classifications are **conditionally based on missing N34 accumulation interval**. Within same calendar month, average rainy minus dry day: RH **+9.53pp**, cloud cover **+5.30 tenths**, solar Kt **−0.297**, specific humidity **+1.509g/kg**, GHI **−2.405kWh/m²**.

Same-hour/month conditional delta by site, 12 EPWs per geographic point:

| Site | ΔRH pp | Δcloud tenths | ΔKt | Δspecific humidity g/kg |
|---|---:|---:|---:|---:|
| Graz | +14.93 | +5.05 | −0.307 | +2.23 |
| Innsbruck | +13.10 | +5.79 | −0.288 | +1.86 |
| Sonnblick | +7.25 | +4.99 | −0.351 | +1.13 |
| Tripoli Greece | +17.52 | +6.34 | −0.320 | +2.24 |
| Wien Hohe Warte | +13.14 | +4.60 | −0.295 | +1.77 |

All four future/contemporary classes independently preserve the expected signs. Pair rain-hour counts over 15 EPWs in each class: contemporary 10695, RCP4.5 2050 10926, RCP8.5 2050 11325, RCP8.5 2100 12040. Mean rain-hour sky cover **9.78, 9.64, 9.66, 9.52/10**, RH **85.72%, 85.76%, 85.62%, 85.74%**, respectively. Comparing annual precipitation risk quantitatively remains limited by N34 missing and stochastic seed change.

## 4. Separate red-flag forensic evaluation

**Source sky-cover encoding:** across all 525600 hours, only 0,1,3,4,5,6,8,9,10 were observed; 2 and 7 absent. Meteonorm native **oktas** converted to EPW **tenths** is consistent with this exact quantization (Meteonorm docs). Do not count it as corruption; count it as limited spatial cloud fraction resolution.

- **0/44986** positive-precipitation records have sky cover <=2/10: minimum source wet-hour sky cover is 5/10. 37598/44986 wet records show sky cover **10/10** (83.6%). This exceptionally tight dependency may reflect a conditional rule in Meteonorm's stochastic disaggregation, NOT independent proof of accuracy.
- **1501/44986** wet records have RH below 60% (3.34%); **87/44986** have RH below 40%.
- With source N33 >=1mm in a record: **29/12087 (0.24%)** have RH below 50%, 124/12087 below 60%. With N33 >=5mm: **0/1322** have RH below 50% (three RH below 60%).
- **14/5387** conditional wet days have mean daily cloud <4/10 and RH <60%; **2** wet days are nighttime-only rain. Other identified sunny-daily summer days are usually short cloudy episodes. **Tripoli RCP8.5** has rarer physically suspicious combinations: one 2050 summer day with recorded 11.4mm summed N33, daily RH ~49%, cloud 2.54/10; its **five N33-positive records were fully overcast 10/10**, with mean near-surface RH **49%**, minimum **32%**. This is **a scientific REVIEW case**, not proof of impossible surface weather.
- **0** hours N33-positive at T<0°C; EPW reports *liquid* precipitation and does not certify snow water-equivalent, so don't infer absence of solid precipitation in alpine climates.
- **0** wet-hour coincidences of sky<=2/10 plus RH<60%; **0** source wet-hour coincidences of daytime Kt>0.7 and sky<=2/10.
- Composite from **7087** rain onsets preceded by >=6 dry hours (time labels not independent observed storm fronts): total cloud cover increased from **6.97/10 six hours before** to **9.40/10 at onset**, RH 77.43%→80.64%, sky ε 0.855→0.879. Model may have imposed this by a conditional event algorithm.

**No scientific claim that rainfall is physically impossible at low local RH or transient cloud/sun; precipitation can be aloft, convective, localized, or temporally averaged and N34 missing creates timing uncertainty.** Treat these as localized forensic inspection candidates and require true observations for calibration.

## 5. What this establishes about IGE

- Meteonorm RCP/CMIP5 outputs **regenerate cloud/rain occurrence across scenarios/seeds** while maintaining conditional statistical associations. This is a genuine implemented capability independent of accuracy proof.
- IGE P7C4/P8.4D *morphs existing baseline weather* with altered T, humidity, shortwave GHI and sky LW while **mostly inheriting precipitation occurrence and cloud cover**. This mathematically CAN introduce rain/humidity and cloud/solar mismatches even with excellent monthly marginal closure; **NO direct IGE error demonstrated** because original 28 licensed P7C5B hourly EPWs are unavailable here.
- Required production IGE EPW quality gate: use the same conditional per-site/per-model protocol (wet-vs-dry same-month/hour RH/q/KT/cloud/IR/solar partition; rain-day vs dry-day same-month; storm-onset composites; low RH heavy precip exceptions; sky cover octas→tenths and N34 metadata). Never hardcode Meteonorm conditional distributions as universal truth, never treat RCP4.5 vs SSP245 or RCP8.5 vs SSP585 as identical stochastic series.
- Retain the P8.3–P8.4B Wind Closure. Next scientific development should target a *joint stochastic weather-regime generator with physically guided precipitation/cloud/solar/humidity coupling and independent station heldout evaluation*, **after** existing P8.6 private 28-member source access/validation.

**No user-licensed hourly EPW uploaded to GitHub; no `main` merge; production EPW remains BLOCKED.**
