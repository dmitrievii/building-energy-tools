# IGE P8.3E1/F1 — original-source verification results (2026-10-15)

**Source-backed CI:** [#38652690936](https://github.com/dmitrievii/building-energy-tools/actions/runs/38652690936), code commit `d20cdbda2236ca727beb472d6bc886a8be68ac5e`. **3/3 jobs SUCCESS**: contracts, E1, F1. Original JSON artifacts `ige-p8-3E1-research-science-aggregates` and `ige-p8-3F1-research-science-aggregates`, IDs 11935736055 and 11935877992; numerical results below verified directly against downloaded originals. No production integration.

## E1 — station exposure metadata

| Station | Original `station_exposition_en` | Elevation (m asl) |
|---|---|---:|
| BAS | height (30-100 m above valley) | 316 |
| CHD | southern oriented slope | 1028 |
| GRA | height (30-100 m above valley) | 651 |
| MUB | plain | 480 |
| STG | north-western oriented slope | 776 |
| VIS | plain | 639 |
| PAY | height (30-100 m above valley) | 490 |
| SIO | plain | 482 |

All 8/8 descriptions are populated. **Not one** confirms site-specific sensor height over ground or roughness `z0`. The word `height` in BAS/GRA/PAY is **topographic height above valley**, NOT measurement mast height. Normalization authorization 0/8. E1 is a successful descriptive classification/census, not physical exposure or sensor-height qualification.

Source station metadata SHA-256 `b0025fb9909f28d536e90983337525697c27b75a607d1724f2d411ef3477ab59`.

## F1 — 2023 donor climatology evaluated on withheld BAS/GRA/MUB 2024

All 10 candidate donors successfully source-qualified for 2023. 3 targets × 8784 same nominal UTC hours each. Speed error on common-hour 2024 target observations:

| Target | ERA5 MAE | ERA5+residual MAE | Station IDW4 MAE | Residual minus ERA5 | Residual minus station IDW4 |
|---|---:|---:|---:|---:|---:|
| BAS | 0.77370 | 0.77036 | 0.90454 | -0.00334 | -0.13418 |
| GRA | 1.12387 | 1.10470 | 0.85056 | -0.01917 | +0.25414 |
| MUB | 0.80487 | 0.85313 | 0.67025 | +0.04826 | +0.18289 |

MAE units m/s. Values rounded to five decimals; the CI artifact retains full precision. Lower is better.

| Target | ERA5 directional fixed90 | ERA5+residual fixed90 | Station IDW4 fixed90 |
|---|---:|---:|---:|
| BAS | 53.040° | 53.034° | 71.754° |
| GRA | 48.194° | 47.241° | 41.84° |
| MUB | 69.29° | 68.17° | 67.55° |

The fixed90 measure assigns 90° for unresolved noncalm reference direction. Resolved-direction conditional MAE cannot alone support physical improvement: residual correction reduces resolved hours (BAS 8596 -> 8207; GRA 7917 -> 7292; MUB 6775 -> 6016). MAE improvements near 0.003 or 0.019 m/s cannot establish statistical superiority without uncertainty estimation.

Seasonal residual-versus-ERA5 MAE differences (m/s, negative is better):

| Target | DJF | MAM | JJA | SON |
|---|---:|---:|---:|---:|
| BAS | -0.0065 | +0.0011 | +0.0197 | -0.0280 |
| GRA | -0.0202 | -0.0403 | -0.0153 | -0.0007 |
| MUB | -0.0186 | +0.0915 | +0.1203 | -0.0014 |

This method **does not consistently beat uncorrected ERA5**, and generally does **not beat the contemporaneous station baseline**. At MUB it has a material deterioration in spring/summer. Frozen same-hour IDW4 baseline is not the exact P8.3D terrain method and relies on real same-year station observations, unlike ERA5 bias climatology.

## Independent deployment blocker

The unrelated Streamlit [Live Browser Audit #37953132708](https://github.com/dmitrievii/building-energy-tools/actions/runs/37953132708), rerun attempt #2, is again FAILURE. Expected runtime hash `f589c62e43b645b1fa903eaea854e78f8bb0715175872f5b1a4d90f8dd53b6c9`; observed `004e35c6b1087638dc0aed5f24240b449291f5f411ed5fe75533d77930c0115f`. Browser UI usable, catalog matches, but live runtime does not match GitHub checkout after propagation timeout. Re-running alone does not repair an unpropagated cloud deployment. Check actual deployed branch, file, and Streamlit Cloud rebuild/reboot; preserve strict runtime equality.

## Scientific gates and decision

- E1 metadata evidence PASS, **sensor-height & roughness qualification unresolved**.
- F1 2023->2024 original-source experiment PASS, **predictive improvement FAILED** as general model selection criterion.
- Do not promote residual hybrid to production or `main`.
- Next controlled model variants: leave-one-target-out geographically blind on more stations; monthly/seasonal bias shrinkage to ERA5 baseline; conditional residual weighting using physical exposure/terrain; exact-clock reconciliation for ERA5 instantaneous vs station hourly mean; bootstrap uncertainty of site/season deltas; compare contemporaneous P8.3D on common hours.
- Same 3 target sites and 2024 are not untouched globally; no virgin geographic holdout claim.
