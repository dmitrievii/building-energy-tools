# IGE P8.3F2 — verified original-source 2025 benchmark and scientific decision

**Checked:** 2026-10-15. **Research-only; not production qualified.**

- **GitHub Actions:** [#38702325666](https://github.com/dmitrievii/building-energy-tools/actions/runs/38702325666), **SUCCESS**, commit `b69be7c9cbaa6299929b4ab43ef7aad5efdef404`.
- **CI:** both jobs SUCCESS; **67/67 scientific/contract tests PASS** (15 F2 + 13 E1/F1 + 20 D + 19 E–H).
- **Original aggregate artifact:** `ige-p8-3f2-2025-original-science-aggregates`, artifact ID `11956817547` (22,275 bytes compressed). ZIP CRC PASS; ZIP SHA-256 `2dde5dd64e70fb7aecb69bd1f22565b03405f5d84c12637b9865b55ad18c7243`. Uncompressed JSON SHA-256 `23238fe91525c4d35a003c498acfba3be20dfcd2a725f73e502402b4dd018917`.
- **Reference years:** 2023 training, 2025 evaluation. **2025 is not a globally unused IGE year**, and the Swiss sites were examined in prior research. Independent here means no 2025 reference target wind entered the F2 predictor or fitted correction.
- **Paired original hours:** BAS, CHD, GRA, MUB, STG 8,760 each; VIS 8,756; total **52,556**. All six variants scored on exactly the same per-site timestamps. Four missing/unusable VIS hours are not silently filled.

## Main result: equal-station and hour-weighted MAE (m/s)

| Method | Macro MAE | Micro MAE | Macro relative to uncorrected ERA5 |
|---|---:|---:|---:|
| ERA5 uncorrected | 1.085396 | 1.085298 | reference |
| F1 monthly residuals | 1.096795 | 1.096716 | +1.050% (worse) |
| F2 altitude-conditioned, shrunk | **1.078352** | **1.078262** | **−0.649%** |
| F2 altitude+exposure, shrunk | 1.079868 | 1.079778 | −0.509% |
| F1 station distance IDW4 (contemporaneous donors) | **1.005089** | **1.005018** | −7.40% |
| Frozen P8.3D altitude IDW4 (contemporaneous donors) | 1.030861 | 1.030780 | −5.02% |

The station IDW methods have an **information-set advantage**: their predictions use measured 2025 same-hour donor wind. They are retrospective reconstruction comparators, **not alternative 2025 future wind generators**. Differences to ERA5 must not be marketed as same-input forecasting skill.

## Speed MAE by site (m/s)

| Site | ERA5 | F1 residual | F2 altitude | F2 exposure | Station IDW4 | Frozen P8.3D altitude |
|---|---:|---:|---:|---:|---:|---:|
| BAS | 0.7623 | 0.7678 | 0.7552 | 0.7530 | 0.9859 | 0.7570 |
| CHD | **0.7953** | 1.0980 | 0.8802 | 0.8957 | 0.8372 | 1.0573 |
| GRA | 1.0653 | 1.0536 | 1.0506 | 1.0518 | 0.7500 | **0.7194** |
| MUB | **0.7479** | 0.7954 | 0.7589 | 0.7556 | 0.6852 | 0.8866 |
| STG | 0.7681 | 0.7274 | 0.7593 | 0.7595 | 0.8398 | **0.6660** |
| VIS | 2.3735 | 2.1386 | 2.2660 | 2.2635 | **1.9324** | 2.0988 |

F2 altitude wins over raw ERA5 on **4/6** targets (BAS, GRA, STG, VIS) and worsens CHD and MUB. The exposure variant also wins 4/6; its pooled MAE is slightly worse than F2 altitude alone.

### 95% seven-day block-bootstrap intervals for (F2 altitude MAE − ERA5 MAE)

| Site | Delta (m/s) | 95% CI (m/s) | Decision on this site/year |
|---|---:|---|---|
| BAS | −0.0071 | [−0.016, +0.004] | uncertain |
| CHD | +0.0849 | [+0.064, +0.102] | reproducible degradation |
| GRA | −0.0147 | [−0.025, −0.005] | reproducible improvement |
| MUB | +0.0110 | [+0.003, +0.019] | reproducible degradation |
| STG | −0.0088 | [−0.015, −0.004] | reproducible improvement |
| VIS | −0.1075 | [−0.135, −0.086] | reproducible improvement |

Site/year confidence bounds condition on the original observed trajectory and 7-day serial blocks; they are not multi-site or multi-climate generalization bounds. No pooled block-bootstrap CI has been established, so the small macro win (−0.0070 m/s) **must not be called statistically robust globally**.

## Critical method-attribution finding: donor sets do not change

**F2 altitude donor identities are exactly the same sets as F1 distance donors for all six sites** (VIS order only differs). F2's additional altitude-informed *ranking* therefore contributed **no new donor membership** in this restricted 10-donor candidate pool. The F1→F2 performance change comes from **one or more of**:
- explicit altitude attenuation in the residual weights `exp(-abs(delta elevation)/500)`,
- coefficient shrinkage `0.5`,
- taper of residual correction `min(1, vERA5/2)`.

The present experiment has **no ablation isolating these factors**. It is scientifically incorrect to attribute any of the benefit specifically to orographic correction or physical terrain representation.

The text-based exposure multiplier adds no mean gain: F2 exposure macro 1.079868 vs F2 altitude 1.078352. At CHD it worsens the already unfavorable result (F2-alt 0.8802 → exposure 0.8957).

## Direction: separate from speed

`direction_fixed90_deg` assigns unresolved noncalm target hours a fixed 90° penalty. Values (°):

| Site | ERA5 | F2 altitude | F2 exposure | Frozen P8.3D |
|---|---:|---:|---:|---:|
| BAS | 55.07 | 54.81 | 54.73 | **48.68** |
| CHD | 106.40 | 106.98 | 107.44 | **76.54** |
| GRA | 47.20 | 46.55 | 46.52 | **39.16** |
| MUB | 68.53 | 67.49 | 67.38 | **61.01** |
| STG | 43.80 | 45.06 | 45.07 | **41.77** |
| VIS | 63.97 | 64.04 | 63.67 | 91.34 |

Directional skill is not uniformly improved by F2; unresolved direction coverage also differs. Fixed90 is a predeclared *diagnostic penalty score*, not measured MAE on missing-direction hours. It may exceed 90° because resolved angular errors can exceed 90°.

## Seasonal failure signatures

- **CHD:** F2 altitude worsens ERA5 for DJF (+0.139 m/s), MAM (+0.097), JJA (+0.016), SON (+0.089). A persistent overcorrection; annual speed bias increases from +0.1623 to +0.3994 m/s.
- **MUB:** deterioration especially MAM (+0.028) and JJA (+0.040 m/s).
- **VIS:** benefit concentrated MAM (−0.173), JJA (−0.184), smaller in winter and autumn; raw ERA5 remains strongly negatively biased (−2.165 m/s, F2 altitude −1.968 m/s). This site disproportionately influences magnitude of pooled gains.
- **GRA:** original ERA5 speed underbias −0.498 m/s is partially reduced to −0.405 m/s by F2 altitude.

## Scientific decision

1. **P8.3F2 computational and reproducibility gates PASS**: authentic complete-year ERA5 gateway + MeteoSwiss data, six station holdout, full paired score, no source leakage, aggregate artifacts.
2. **Reject unconditional F2 deployment/production acceptance.** The 0.65% macro gain vs ERA5 is small and has systematic, bootstrap-resolved site-level failures at CHD and MUB.
3. **Reject attribution to altitude donor choice** without ablation: all F1 and F2-altitude sets are the same.
4. **Reject extra textual exposure correction** as proven improvement. P8.3F2 exposure is marginally worse pooled and notably worse at CHD.
5. **P8.3F3 next:** frozen 2025-independent factor ablation (distance vs altitude weights; no/partial shrinkage; taper; exposure), broader station candidate sets, evaluation in new year and different sites, direction-coverage-controlled score, ERA5 time integration alignment and calibrated physical exposure when original mast height and roughness become available.
6. All research-only. **`production_epw_ready=false`; no merge to `main`, no Streamlit deployment changes**.
