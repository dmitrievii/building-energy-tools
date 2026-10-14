# IGE P8.3D — 2024 independent wind donor physical suitability: scientific results

**Check date:** 2026-10-14. **Status:** `CI_PASS / ALTITUDE_SELECTION_RESEARCH_SUPPORTED / TERRAIN_INCREMENT_NOT_DEMONSTRATED / PRODUCTION_NOT_APPROVED`.

## Verified execution and input control

- Original [GitHub Actions #38639636205](https://github.com/dmitrievii/building-energy-tools/actions/runs/38639636205) `success`, original head `6bfe2fe4741d110d4f0b990c0318d01349b5064b`. **2/2 jobs succeeded**, physics/QC contracts **52/52 pass** (20 P8.3D + 16 P8.3A + 16 P8.3B).
- Evidence artifact `11930026508`, ZIP SHA-256 `eec00d4017e7d4bce40e09810632562c77ecd368608ca5818fed6c7647b879e1`, 6 files, ZIP CRC test PASS.
- 2024 leap year, six predeclared wind-target stations BAS, CHD, GRA, MUB, STG, VIS. 6×8784 = **52,704** possible site-hours; **52,585** matched scored hours, VIS with 8,665 due to 119 missing/unusable reference hours, five other sites with 8,784 each. **47,228** reference noncalm scored hours.
- Original station metadata `159` sites; `92` nearby or existing-pool candidate files requested, of which **86** qualified under numerical yearly wind-coverage checks. This is NOT exhaustive QC of all 159. Per-hour source QC classification `source_qc_individual_verified=false`.
- Donor selection uses target geographical location, station heights, derived DEM features and donor availability, **never target wind observations**. Actual 2024 contemporaneous donor observations feed a retrospective spatial hindcast, **not a 2024 future-weather generator or a simulated SSP climate**.
- Methods:
  - `distance_idw4`: nearest four complete-enough wind donors by true horizontal distance.
  - `altitude_idw4`: nearest four under `sqrt(d_km² + (0.04 Δz_m)²)`.
  - `terrain_idw4`: same plus DEM TPI/ruggedness quadratic penalties (0.03 and 0.02 km/m).
- **All coefficients frozen before 2024 results**. They are engineering heuristics, not mechanistic atmospheric models. **Final solver unchanged:** physical-distance 1/d² hourly weights, P8.3A scalar speed/vector direction and P8.3B unit-circle direction.

## Hour-matched pooled scores — six targets, 2024

| Metric | Pure distance | Height-aware | Height + DEM |
|---|---:|---:|---:|
| Hourly matched evaluations | 52,585 | 52,585 | 52,585 |
| Scalar wind speed MAE (m/s) | 1.5197 | **1.0428** | **1.0428** |
| Scalar speed mean bias (m/s) | +0.7650 | **+0.1752** | **+0.1752** |
| Speed MAE relative change | reference | **−31.4%** | **−31.4%** |
| Vector direction emitted-only circular MAE (°) | 57.39 | **52.03** | **52.03** |
| Vector direction availability, % of ref noncalm | **90.81%** | 86.88% | 86.88% |
| Vector direction fixed-denominator 90° missing penalty (°) | 60.38 | **57.02** | **57.02** |
| Unit-circle direction emitted-only MAE (°) | 55.75 | **55.17** | **55.17** |
| Unit-circle direction coverage | 95.38% | **97.41%** | **97.41%** |
| Unit-circle fixed-denominator 90° missing penalty (°) | 57.33 | **56.08** | **56.08** |

Note that vector-direction emitted-only MAE uses different resolved-hour subsets (coverage changes), so it is not a same-hour paired quality improvement claim. The 90° missing-penalty is a **diagnostic utility**, not an observed angle error; on the common target-noncalm denominator it decreases.

## Speed error and heterogeneous performance per site

| Site | Distance MAE m/s | Height-aware MAE m/s | Difference | Distance vector direction 90°-penalty | Height-aware vector direction 90°-penalty |
|---|---:|---:|---:|---:|---:|
| BAS | 0.720 | 0.729 | +1.3% worse | 46.32° | 46.51° worse |
| CHD | 2.711 | **1.154** | −57.4% | 85.01° | **76.52°** |
| GRA | 0.751 | 0.751 | 0% | 39.55° | 39.55° |
| MUB | 1.728 | **0.860** | −50.3% | 68.52° | **58.80°** |
| STG | 1.103 | **0.734** | −33.4% | 48.54° | **40.20°** |
| VIS | 2.113 | **2.043** | −3.3% | **77.81°** | 82.63° worse |

Important site diagnostics:
- **CHD:** pure-nearest donors CDM/MLS/DIA/MAS, with severe elevation mismatch including DIA at 2,964m; height-aware CDM/MAS/ORO/BOL removes high mountain MLS/DIA from the four.
- **MUB:** distance BER/CRM/CHM/CHA, containing 1,136m and 1,594m donors; height-aware BER/CRM/NEU/GRE replaces those with low-altitude stations.
- **STG:** distance BIZ/ARH/OBR/SAE including SAE at 2,501m; height-aware BIZ/ARH/OBR/GUT avoids that mountain donor.
- **VIS:** speed modestly better but emitted vector error grows 75.40°→81.02° and 90°-penalty rises 77.81°→82.63°; speed bias becomes more negative (-0.800→-1.086m/s).
- **BAS:** small deteriorations. So do not describe altitude model as improving **every** site/metric.

## DEM increment assessment

DEM TPI and ruggedness were actually calculated and included in `ranking_score`, with original station heights preserved separately from sampled DEM center. However all six **sets** of four height+DEM donors are exactly the same as the four height-only donors (some ordering differs in VIS and GRA). With original physical-distance IDW weighting and same observations, predicted speed/direction and metrics are **identical**.

**Therefore no independent experimental value of DEM features was established in P8.3D.** They must NOT be described as improving forecasts. This does not imply they are intrinsically useless: finer terrain exposure, valley-axis sheltering, anemometer placement and upwind roughness are not represented by TPI/std elevation alone.

## Scientific decision

1. **P8.3D computation PASS.** The **height-aware selection** is a substantial and physically plausible research improvement for scalar wind speed (−31.4% MAE), without tuning the solver, but there are exceptions at BAS and VIS and many remaining site-dependent errors. Record as **candidate research selector**, not universal or production-accepted model.
2. **Reject claims of extra terrain gain** for this test: `terrain_idw4` selected identical donor sets.
3. Preserve all original P8.2F moisture, P8.3A/B/C wind, and `main` unchanged. Do not replace wind directions in a 35-field production EPW.
4. Next scientific question: independent data on measurement height, actual anemometer exposure/roughness, orographic wind corridor and station class, and **predeclared fresh year/site validation** of a fixed height-aware selector, with wind speed and direction separately scored. Never retrofit original 2024 scores into selector coefficients.
5. Source original records are not distributed, DEM tiles are not public in repo; only derived metrics, feature summaries and provenance/SHA are exported.

**Scientific status:** `RESEARCH_METHOD_CANDIDATE / WIND_PHYSICAL_SELECTION_REVIEW_REQUIRED / PRODUCTION_EPW_READY_FALSE`.
