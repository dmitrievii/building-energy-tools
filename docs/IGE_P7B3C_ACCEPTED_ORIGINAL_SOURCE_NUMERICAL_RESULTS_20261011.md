# IGE P7B.3C — Accepted original-source numerical experiment: conditional cloud analogue M2

**11 October 2026.** Original GitHub Actions [#38162488876](https://github.com/dmitrievii/building-energy-tools/actions/runs/38162488876) **SUCCESS**, source commit `7371894586b0f779aa825c6b188a4d87bef05ff9`. Independent source SHA checks, 38/38 relevant unit/regression tests, original 10-minute GeoSphere QA, 8-seed coefficient selection and 20-seed final comparison passed.

Original derived-only GitHub output artifact: `ige-p7b3c-observed-conditional-cloud-m2-solar-research`, artifact **11710587690**, ZIP SHA256 `bada5c24d377743ad34ae524d3f5a33e58e86ce54c56508e5c3fba15aa9f3c6e`, expires 10 November 2026.

**Original sources (immutable, never commit original provider data to public GitHub):**
- Original GeoSphere 10-minute observed hourly QC `p6_3f_geosphere_10min_hourly_pairwise.csv`: SHA256 `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`.
- Original source P7B.2 `p7b2_2013_synthetic_hourly_physics_and_sources.csv`: SHA256 `099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a`.

## Model and statistical provenance

M0 is unchanged P7B.2 synthetic 2013 CanESM5 GHI. M2 is an independently implemented **seasonal and clearness-index-conditioned measured-day cloud-analogue model**, NOT the Meteonorm 8.2 internal code or its exact stochastic method. Haurwitz geometric clear-sky reference (`1098 cos(z) exp(-0.059/cos(z))` W/m²) and 15 nearest observed same-season analogue days supply 24-hour cloud shapes. Alpha mixes cloud-analogue and M0 profiles; bounded projection preserves **each corrected source GHI daily sum** and 0≤GHI≤TOA. NOAA approximate geometric sunrise geometry; provisional low-sun cap `min(TOA,max(1.25 Haurwitz,0.65 TOA))` mitigates Haurwitz horizon shape but remains a review item.

**Train:** 2007–2008 actual original-approved hourly GHI; 715 (record_start) / 713 (record_end) complete-source-day analogues. **Select alpha:** 2009 only; eight deterministic seeds, same coefficient across two unresolved clock interpretations. Predefined alpha set [0,0.25,0.5,0.75,1.0] and score `0.35*(daytime monthly-hour MAE/M0 MAE)+0.65*(mean seasonal absolute relative p95 error)`. Selected **alpha=0.75**. **Evaluate:** 2012–2014, 20 deterministic seeds of 2013 independent GCM-generated weather. The evaluated 2012–2014 observational period is **previously consulted in P7B.2 / P7B.3A / P7B.3B** and **NOT a virgin holdout**. The model did not train its patterns or select alpha from those dates. No model date vs observation event-date matching and no 2010–2011 use.

## GitHub-original numerical metrics

| Metric | GeoSphere (record_start) | M0 P7B.2 | M2 20-seed mean |
|---|---:|---:|---:|
| Summer JJA p95 abs hourly ΔGHI, kWh/m² per hour | 0.3323333 | 0.1189794 | **0.3031349** |
| Daylight month-hour climatological MAE, kWh/m² per hour | reference | **0.0326082** | 0.0350876 |
| Four-season mean absolute relative error in p95 abs ΔGHI | reference | 0.4739904 | **0.0915067** |

For original `record_end` interpretation: GeoSphere JJA p95 0.3305000; M2 0.3016848; M0 and M2 daytime MAE 0.0337744 and 0.0338338; season-mean relative p95 errors 0.4687314 (M0) and 0.0943754 (M2). Strict observational sample counts in 2012–2014 are 26,292/26,289 hours for start/end clock interpretations.

**Numerical physical closure:** maximum source-day solar energy residual on seed zero `1.77636e-15` and `2.66454e-15` kWh/m² (start/end), respectively. This is not proof of independent observational skill.

**Research conclusion:** M2 markedly reduces conditional variability error but makes the monthly-hour mean profile slightly worse for record_start (+7.6% MAE). M0 and M2 do NOT dominate each other across all criteria. Compared with the prior M1 TAG-informed pilot's JJA p95 0.4934, M2 is nearer observed variability, but these approaches use different baseline assumptions. Future-model generalization and joint solar/DNI/DHI physics remain unproven.

## Publication and engineering blockers

**SCIENCE REVIEW_REQUIRED; `epw_production_ready=false`.** Only one synthetic CanESM5 model-year, one ground station and a previously consulted evaluation interval. No truly new site, no independent observed DHI/DNI, no radiometric-instrument cloud duration validation, no interannual or 8-GCM ensemble, no probabilistic interval calibration, no final hourly EPW, no solar–temperature–humidity joint closure or building energy response.

Further research must evaluate site/year holdout, alternative clear-sky reference and near-horizon cap sensitivity, real measured diurnal/cloud persistence, and DHI/DNI partition against trustworthy sources. Maintain the accepted original P7B.2 EPW untouched and `main` untouched. See `docs/IGE_P7B3C_CONDITIONAL_CLOUD_ANALOGUE_PROTOCOL.md`.
