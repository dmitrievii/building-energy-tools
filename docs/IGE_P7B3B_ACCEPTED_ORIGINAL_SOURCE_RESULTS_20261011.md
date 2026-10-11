# IGE P7B.3B — Accepted original-source M0/M1 TAG-informed pilot results

**Research date:** 2026-10-11. **Scientific status:** exploratory method benchmark; NOT a validated production hourly weather generator. **No merge into main.**

## Original evidence and immutable source

- Successful original-source GitHub Actions: [#38160211865](https://github.com/dmitrievii/building-energy-tools/actions/runs/38160211865), **SUCCESS**.
- Accepted source workflow commit: `02aa7268f0043d373c1b94216693f29ac6c75eeb`. P7B.3B started from accepted P7B.3A `27365c2f949dbc5851f93d1f33289eb0e2811cc3`.
- Source scripts: `research/ige_cmip6/p7b3b_tag_benchmark.py`, tests: `test_p7b3b_tag_benchmark.py`; earlier P7B.3A independent observation/QC source contracts also executed. **22/22 tests PASS**, full 20-seed original-source run and audit PASS.
- Original ground observation hourly CSV SHA-256 `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`.
- Original P7B.2 model hourly CSV SHA-256 `099c5b29f5c2ecdc9a72d274db5eb2a8bb870c7e3b54cfb5588c1567c6b2036a`.
- Original source output artifact `ige-p7b3b-m0-m1-tag-inspired-source-benchmark`, artifact ID **11710515185**, ZIP SHA-256 `1e66de89f888af2a1b0383701532926681fee83803785c3d1f58eb4cb3679cac`. Data retained by GitHub Actions only until **2026-11-10**; preserve a user-controlled local freeze. Artifact contains only source-hashed derived score CSV, seed-0 solar values and independent scientific audit JSON; no original licensed provider data.

## Original-GitHub-computed scores

All irradiance in kWh/m² per hour; p95 over absolute changes between *consecutive* daylight hours. Observations are genuine approved GeoSphere Graz #30 six-of-six 10-minute hourly aggregates, not a second station #16412 or external NASA gridded proxy. Synthetic CanESM5 2013 is not actual observed 2013 weather. Both original timestamp hypotheses retained.

| `record_start` | GeoSphere observed | M0 P7B.2 | M1 20-seed mean |
|---|---:|---:|---:|
| Daylight month-hour climatology MAE | reference | 0.032608195 | 0.042432178 |
| DJF p95 | 0.142016667 | 0.098165126 | 0.244923737 |
| MAM p95 | 0.285933333 | 0.125989147 | 0.394110455 |
| JJA p95 | 0.332333333 | 0.118979369 | 0.493426302 |
| SON p95 | 0.197633333 | 0.121382332 | 0.290810483 |

For `record_end` month-hour climatology MAE: M0 **0.033774443**, M1 mean **0.039653319**; JJA observed p95 **0.330500**. QC original ground hours: `record_start` **26,292**, `record_end` **26,289**. Only **one model-synthetic year** (2013) versus three years of observed distributions.

Original computed maximum corrected daily GHI energy conservation residual across 20 independent TAG-informed samples: **2.6645352591003757e-15 kWh/m² per day**. All candidate hours nonnegative, capped at source extraterrestrial horizontal energy. These are consistency checks, **not scientific validations of hourly realism**.

## Critical methodological interpretation

The first-order AR(1) coefficient and Gaussian innovation parameter are derived independently from Meteonorm 8.2 *Handbook Part II: Theory*, §7.6.1.4, Eq 7.6.10–11. `M1` intentionally *departs* from Meteonorm software by using original P7B.2 hourly GHI/TOA as its clear-sky-profile surrogate, TOA rather than physically modelled ESRA/Solis clear-sky caps, and an independent deterministic bounded daily-energy projection rather than the documented Meteonorm regeneration loop.

**Claim supported:** for this *specific independently implemented TAG-informed M1* under the fixed CanESM5/Graz 2013 source and two GeoSphere time interpretations, stochasticity increases short-term fluctuations but overshoots the observed extreme interhour variability and worsens the mean diurnal profile compared to M0. **Claim NOT supported:** Meteonorm 8 itself is worse than IGE, because actual Meteonorm outputs were not evaluated and the reference algorithm was not reproduced completely.

The 2012–2014 observations were previously consulted in P7B.2, so cannot be called a completely new holdout. The methodology is documented in `docs/IGE_P7B3B_TAG_METHOD_BENCHMARK.md`. Neither M0 nor M1 should be used for full-science-validated future EPW. **Next stage P7B.3C/M2:** separate calibration and disjoint evaluation years/sites, authentic independently documented clear-sky model, physically constrained stochastic dynamics, cloud persistence/autocorrelation calibration and multiseed/multimodel uncertainty, without fitting to already-consulted 2012–2014 results.

**Final P7B.2 EPW remains unchanged;** `epw_production_ready=false`.
