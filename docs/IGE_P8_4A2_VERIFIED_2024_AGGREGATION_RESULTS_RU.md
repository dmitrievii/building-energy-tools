# IGE P8.4A2 — verified original 10-minute→hourly wind closure results

**Checked:** 2026-10-17. **Scope:** source-local numerical aggregation audit, January 2024, three MeteoSwiss and two GeoSphere Austria station series. **Result:** `NUMERICAL_SOURCE_AGGREGATION_RECONSTRUCTION_PASS__ERA5_TEMPORAL_EQUIVALENCE_NOT_ESTABLISHED`.

## Reproducibility

- [GitHub Actions run #38981044619](https://github.com/dmitrievii/building-energy-tools/actions/runs/38981044619): **2/2 jobs SUCCESS**, **58/58 synthetic/regression tests PASS** (16 A2 + 24 A1 + 18 F3) on computation SHA `42fca61c35ced9452ce598f9ecb65bb87bd1ea04`.
- [Original-source aggregate artifact #12080698080](https://github.com/dmitrievii/building-energy-tools/actions/runs/38981044619/artifacts/12080698080), ZIP original SHA256 `3c7922d4ac754699f6c357aa674200cba8c5acdeb2f812273d2f32574c799dde`; aggregate JSON SHA256 `b1c6b08eeb9648c66d9b30bde3f73a9a24269c855b5edc360490547478253fe6`; ZIP CRC verified.
- **January 2024 10-minute 4464 records and full 743 completed six-sample UTC hour windows per site** (January 1 01:00 through January 31 23:00). 2024 January 00:00 on the first day excluded because prior six 10-min samples start in December. **3×743 Swiss + 2×743 Austrian = 3715 matching 1h station-pairs**. No original 10min/hour time series redistributed. Original source SHA256 recorded per site in artifact.
- The first CI attempt failed in one synthetic north-angle test because mathematically identical 360° versus 0° representation was not canonical. Fixed in code (`canonical_from_components`, independent unit-circle reliability), and green original-source run is **after** that fix. No source-data-dependent hyperparameter fitted.

## Source hourly wind-speed reconstruction

Each row: MAE between original published one-hour station wind-speed and either mean six original ten-minute scalar-speed magnitudes, or magnitude of averaged six ten-minute velocity vectors. Same **743 hours** for both estimates.

| Station | Provider / 1h speed semantics | Scalar 6×10 MAE (m/s) | Vector 6×10 MAE (m/s) | Preferred metric |
|---|---|---:|---:|---|
| BAS | MeteoSwiss original scalar mean `fkl010h0` | **0.024675** | 0.068465 | scalar |
| GRA | MeteoSwiss original scalar mean `fkl010h0` | **0.024630** | 0.106424 | scalar |
| MUB | MeteoSwiss original scalar mean `fkl010h0` | **0.024607** | 0.117625 | scalar |
| Graz Thalerhof `16400` | GeoSphere vectorial hourly mean `ff` | 0.166330 | **0.023651** | vector |
| Graz Universität `16412` | GeoSphere vectorial hourly mean `ff` | 0.112786 | **0.034528** | vector |

All five original sources yielded complete 743/743 matched hours for these comparisons. Swiss scalar bias respectively −0.00713, −0.00830, −0.00926 m/s; residual MAE ≈0.025 m/s is consistent with rounding and internal source-hour aggregation on the examined data (not proof of the full provider algorithm). Austrian vector bias −0.000092 and −0.013467 m/s respectively. Both Austrian 10-minute source series had 4464/4464 QC-approved wind points (Thalerhof `ff_flag=dd_flag=11` for 1327, `12` for 3137 samples; Graz Universität `12` for all 4464).

## Six-sample scalar minus vector difference

The **Jensen/triangle-inequality bound** `|mean(v_i)| <= mean(|v_i|)` passed on every 743-hour directional sample for every station. Resulting mean differences (m/s):

| Site | Mean scalar–vector difference | Maximum difference |
|---|---:|---:|
| BAS | 0.05443 | 1.05262 |
| GRA | 0.09414 | 1.22006 |
| MUB | 0.10561 | 0.68304 |
| Graz Thalerhof | 0.15875 | 1.84059 |
| Graz Universität | 0.12177 | 1.29850 |

Differences are not universally only a roundoff error; replacing a scalar-speed time series by vector magnitude can introduce meaningful systematic negative bias and change regime statistics.

**Measurement caveat:** original MeteoSwiss `fkl010z0` = scalar ten-minute mean; GeoSphere `ff` ten-minute wind is provider-defined and the full underlying sampling/instrument integration differs. Six 10-minute scalars and directions are only candidate vector reconstruction; their near-agreement with GeoSphere's 1h vector-derived metric is strong internal evidence, not independent instrument equivalence.

## Hourly direction reconstruction on strictly identical resolved hours

Meteorological **FROM** direction of weighted six-sample velocity-vector sum vs unit-circle azimuth (same source six samples); metrics are circular absolute error against published one-hour station azimuth, on hours where **both predictions** were defined. Thus angular MAE figures are paired fairly but conditional on the common subset.

| Station | Matched noncalm hours with BOTH defined | Speed-weighted/vector direction MAE | Unit direction MAE | Weighted azimuth coverage of reference noncalm |
|---|---:|---:|---:|---:|
| BAS | 702 | **0.985°** | 1.815° | 95.65% |
| GRA | 565 | **1.064°** | 1.993° | 86.52% |
| MUB | 491 | **1.337°** | 2.539° | 85.69% |
| Graz Thalerhof | 466 | **0.234°** | 2.796° | 93.20% |
| Graz Universität | 643 | **0.613°** | 2.372° | 95.83% |

The **weighted/vector candidate** is consistently closer to the hourly provider direction **on the common resolved hours**. However it has **lower directional coverage than the unit-circle candidate**: published direction can remain defined even when model vector speed falls below the predeclared 0.5 m/s acceptance threshold. Therefore unconditional superiority and provider algorithm identity are NOT established, and reporting only conditional MAE would be misleading. Change of the method's threshold requires new preregistration and independent-year evaluation, not post-hoc optimizing January 2024.

## Scientific conclusions / non-claims

**Affirmative source-local finding:** MeteoSwiss hourly speed corresponds numerically to the scalar mean of its six ten-minute speeds; GeoSphere hourly speed corresponds much more closely to vectorial aggregation. Their 1h speed fields are not directly interchangeable despite common units and hour labels.

**Remaining blockers:**
- ERA5 historical gateway 10 m speed/direction are instantaneous validity-time records, and **neither a 10-minute ERA5 wind archive nor an equivalent station-hour aggregation of ERA5 model states was evaluated**; exact time-mean/point-vs-grid physical comparability is NOT proved.
- 2024 January only: five regional station series, no full-year or multi-region variation. Station instrument mounting height, 10-min source-level gust or sensor averaging details and validated z0 remain unavailable.
- Reconstructed direction conditional accuracy and coverage do NOT uniquely identify the official provider aggregation operator.
- P8.4A2 is **source-internal hourly reconstruction research PASS**, **not overall P8.4A closure**, and not demonstrated wind forecast/EPW predictive skill.
- `P8.4B=false; P8.4C=false; P8.4D=false; production_epw_ready=false`, no `main` changes or merge.

## Recommendation for P8.4A3

Close the remaining source/time comparability gap by checking genuine ERA5 u10/v10 at **native valid times**, and independently verifying subhourly station averaging, direction threshold and vector/scalar semantics over extra months/years and stations. If ERA5 subhourly wind is unavailable or cannot be validated, explicitly classify it as instantaneous background and **do not** manufacture equivalence by shifting hour labels. Then proceed to full-census historical spatial donor selection P8.4B and future CMIP6 vector-wind generator P8.4C with separate acceptance gates.
