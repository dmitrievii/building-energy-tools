# IGE P8.2E — Post-hoc hourly absolute humidity audit (2026-10-14)

## Статус

GitHub Actions https://github.com/dmitrievii/building-energy-tools/actions/runs/38594053461 — **SUCCESS**, 4/4 jobs, 7/7 contract tests. Frozen P8.2D/E donor-only predictor not modified. Years 2018, 2019, 2020; stations ABO, BER, PAY; native hours 26 280 + 26 280 + 26 352 = **78 912** target-isolated paired hours. Concurrent observations of independent donor sites required, so this is **spatial hindcast**, not future weather prediction.

## Физика и происхождение опорных данных

Absolute vapour density \(\rho_v=216.7e/(T+273.15)\) [g/m³], e [hPa], T [°C]. Reconstructed e/T vs MeteoSwiss published hourly e/T, with no use of target inputs in reconstructed series. The reference g/m³ is derived from observed hourly e/T; it is **not** independently measured by an absolute-humidity sensor. Atmospheric pressure P is absent from this density equation. Additional moist-air specific humidity: \(q=1000(0.621945e/(P-0.378055e))\) [g/kg].

## Результаты полного многодонорного варианта

| Год | Проверочных часов | MAE rho_v, g/m³ | RMSE, g/m³ | Bias, g/m³ | Mean observed, g/m³ | MAE/Mean |
|---|---:|---:|---:|---:|---:|---:|
| 2018 | 26280 | 0.5061 | 0.7142 | -0.1150 | 7.3518 | 6.88% |
| 2019 | 26280 | 0.4951 | 0.7211 | -0.0820 | 7.0275 | 7.05% |
| 2020 | 26352 | 0.5063 | 0.7134 | -0.0991 | 7.1203 | 7.11% |
| **All** | **78912** | **0.5025** | — | **-0.0987** | **7.1665** | **7.01%** |

All-row MAE and bias weighted by eligible hours. Bias of mean absolute humidity is approximately -1.38% relative to mean observed.

### Diagnostic oracle substitution (NON-DEPLOYABLE)

| Input to rho_v diagnostic | MAE g/m³, 2018–2020 |
|---|---:|
| Predicted e and predicted T | 0.50253 |
| Predicted e with actual target T | 0.50080 |
| Actual target e with predicted T | 0.02811 |

The oracle substitutions use target observations **only for attribution**, not for predictor fitting, calibration, production, or generation. MAE attribution is not additive; these are counterfactual diagnostic comparisons.

### Station MAE g/m³

| Station | 2018 | 2019 | 2020 |
|---|---:|---:|---:|
| ABO | 0.5879 | 0.5705 | 0.6142 |
| BER | 0.3553 | 0.3530 | 0.3314 |
| PAY | 0.5752 | 0.5619 | 0.5733 |

Station bias g/m³:

| Station | 2018 | 2019 | 2020 |
|---|---:|---:|---:|
| ABO | -0.3459 | -0.1789 | -0.3103 |
| BER | -0.1310 | -0.1206 | -0.1287 |
| PAY | +0.1318 | +0.0536 | +0.1417 |

### Subset of measured RH >= 90% (diagnostic cohort)

Across 20 956 observed high-RH target hours: MAE rho_v **0.3701 g/m³**, bias **-0.1709 g/m³**. The observed-HR conditioning is used only to select scoring hours. This does not in itself establish whether the missing wet-hour threshold events are caused by a temperature error or e-distribution error; RH=100 e/e_sat(T) is more temperature-sensitive than rho_v.

## Conclusion

The full multi-donor P8.2D/E predicts absolute vapour density with roughly **7% hourly MAE relative to the mean reference**, and a smaller systematic mean underestimation of **~1.4%** across the three tested Swiss stations and years. This supports **retaining the current physical e/T reconstruction model** rather than immediately adding a complex learned saturation model.

However, the persistent underdetection of RH>=90% still exists; absolute humidity error alone cannot establish its cause. Next lowest-complexity test: RH oracle decomposition from modelled/observed e and T, using **new diagnostic output only**, and inspect thresholds near 90% and site-specific bias before making any correction. Avoid training or retuning on the already-used 2018–2020 evaluation years. Another possible targeted check is a pre-registered stratified audit of nighttime/saturated conditions in a new year/site holdout.

## Research provenance

Source model: unchanged IGE P8.2D/E frozen annual prediction. Calibration GeoSphere Austria 1991–2010 only, donor MeteoSwiss observation years 2018–2020. Target data excluded from inputs and seen only in scoring. Raw MeteoSwiss series are not published. GitHub Actions artifact SHA-256:

- 2018 `b66b48a33fd02956b6d322104cc4d74cf85699f52f5268efd81f1c327fc778be`
- 2019 `401f14ae62da32030ce48eaea8e1861d50b33d451c2f2a12e6bf71acf809dcb5`
- 2020 `f434f4c96716193475b01cf8b703c7f1fefbde6d5609c596cf6ca97ceff243e5`

Each ZIP integrity CRC was checked and SHA-256 matched GitHub Actions artifact metadata. This is a post-hoc data audit, not an independently held-out prospective climate generator test. `main` unchanged.