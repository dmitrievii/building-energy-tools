# IGE P7B.3B — Independent TAG-informed solar-variability benchmark

**2026-10-11 — Research only.** Origin: accepted P7B.3A commit `27365c2f949dbc5851f93d1f33289eb0e2811cc3`. Do not merge to `main`; do not replace final P7B.2 EPW.

## 1. Published methodological reference and boundaries

- Meteonorm 8.2, *Handbook Part II: Theory*, **§7.6.1.4, pp. 20–22**, equations 7.6.8–7.6.11: https://mn8.meteonorm.com/assets/downloads/mn82_theory.pdf
- Aguiar & Collares-Pereira (1992), *Solar Energy* **49**(3), 167–174, DOI 10.1016/0038-092X(92)90068-L.
- TAG uses a deterministic clear-sky-based mean daily GHI profile plus an hour-dependent AR(1) Gaussian perturbation. Its published parameters depend on the daily clearness index:
  - `phi(Kt)=0.148+2.356*Kt-5.195*Kt^2+3.758*Kt^3`
  - `sigma(Kt)=0.32*exp[-50*(Kt-0.4)^2]+0.002`
  - `innovation_sigma=sigma*sqrt(1-phi^2)`
  - handbook version-6 correction `y[h]=2*phi*y[h-1]+Gaussian(0,innovation_sigma)`.
- Note the handbook correction is not automatically a stationary AR(1) when `2*phi` approaches or exceeds one. We reset the residual at night. Do not present the resulting sequence as a calibrated stochastic process without independently testing autocorrelation.

**M1 is not Meteonorm 8.2 software, nor an exact replica.** The full ESRA/Solis atmospheric clear-sky profile is not available with this original-data pilot. To avoid inventing turbidity data we use the original P7B.2 hourly GHI divided by hourly extraterrestrial GHI as a surrogate mean transmittance; `Kt_day` uses original daily GHI divided by extraterrestrial daily irradiation. Physical cap is extraterrestrial solar GHI (rather than Meteonorm's approximately 110%-of-clear-sky cap), and a custom constrained monotone scaling conserves original corrected daily GHI to ~1e-9 kWh/m2/day. This is an explicitly labelled independent TAG-*informed* baseline, intended to test the value and limitations of the published autoregressive model, not reverse-engineer proprietary implementation. DO NOT claim Meteonorm performance from M1 outcomes.

## 2. Frozen independent sources, clocks and research design

- M0: P7B.2 final `p7b2_2013_synthetic_hourly_physics_and_sources.csv`, original SHA-256 `099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a`, 8,760 2013 hours.
- Ground: P6.3F actual GeoSphere open 10-minute `cglo` six-of-six quality-approved hourly aggregate, SHA-256 `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`. Only station **#30**, independently observed GHI; no repeated #16412, no NASA-as-ground, and no unapproved diffuse `chim`.
- Observed years **2012–2014**, previously examined in P7B.2 holdout: **not a virgin/unseen validation fold**. Two unresolved original timestamp hypotheses `record_start` and `record_end` remain fully separate. Fixed CET without DST, no paired-date synthetic-vs-observed skill claims. Observations have 26,292 approved hourly values for `record_start`, 26,289 for `record_end`.
- M0 and M1 share **identical 365 source-corrected daily GHI totals**. No station fitting or parameter tuning for M1. M1 ensemble of **20 predeclared seeds (0–19)**; deterministic hash of seed and model day for reproducibility.
- Main diagnostics: daylight month × clock-hour climatological MAE on 12×24 cells satisfying observed mean >=0.025 kWh/m2/hour; and p95 of absolute successive daylight-hour GHI changes in 4 seasons, with strict consecutive-hour checks (08:00–17:00 CET start hours). Report seed range, daily conservation and source hashes. These endpoints do NOT constitute complete model selection criteria.

## 3. Independent local original-archive numerical pilot

The following measurements derive from both original portable research freezes with a separate local implementation and precede original-data GitHub CI rerun. The Python implementation in this research branch is equivalent in published coefficients, M0 input, physical bounds, strict QC and 20-seed design; **quote CI-produced metrics as canonical after successful action**.

| Metric, source time `record_start` | Ground (GeoSphere) | M0 (P7B.2) | M1 TAG-informed mean of 20 seeds |
|---|---:|---:|---:|
| Daylight month-hour climatology MAE, kWh/m2/hour | reference | **0.032608** | **0.042432** |
| DJF p95 absolute adjacent daylight-hour GHI change | 0.1420 | 0.0982 | 0.2449 |
| MAM p95 absolute adjacent daylight-hour GHI change | 0.2859 | 0.1260 | 0.3941 |
| JJA p95 absolute adjacent daylight-hour GHI change | 0.3323 | 0.1190 | 0.4934 |
| SON p95 absolute adjacent daylight-hour GHI change | 0.1976 | 0.1214 | 0.2908 |

For `record_end` the corresponding daylight MAE changes 0.033774 (M0) to 0.039653 (M1 mean); JJA observed p95 is 0.3305, same synthetic values.

**Interpretation:** TAG-like stochasticity increases interhour variability as intended but **overshoots** the independent measured p95 on this configuration and worsens mean diurnal climatology. Therefore M1 is NOT automatically preferable to M0; this result does not indict full Meteonorm 8.2, whose actual clear-sky model and limiting procedure differ.

## 4. Next science / no data leakage

Do not optimize M1 noise, normalize to observed 2012–2014 p95, or claim this previously consulted fold is fresh holdout. Next prerequisite for M2 is an *a priori* cross-year and cross-station calibration/validation design, clear-sky physical reference (ESRA/Solis or independently documented alternative), a joint radiation temporal-dependence audit, and DHI/DNI limitations. Only after genuinely disjoint validation across years/sites and several GCM years can M2 compete with M0/M1. No new production EPW or future SSP from this P7B.3B benchmark.

## 5. GitHub source reproduction

Run `python -m unittest discover -s research/ige_cmip6 -p 'test_p7b3b_tag_benchmark.py' -v`; source-data workflow downloads original P6.3F #38134438339 and P7B.2 #38149471728 research artifacts (which expire). `python research/ige_cmip6/p7b3b_tag_benchmark.py --p7b2-hourly <CSV> --geosphere-hourly <CSV> --out <DIR> --seeds 20`. Output: original SHA record, M0/M1 QC-conditioned 20-seed statistics, seed-0 independently generated solar hourly series. Archive **derived** research products only, never publicly redistribute provider raw data or private portable ZIPs without source-specific rights review.
