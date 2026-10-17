# P8.4B2 — audit of preregistration breach and frozen-method repair (17 Oct 2026)

## Original execution — technically GREEN but NOT valid preregistered science

- Workflow: [#39020743237](https://github.com/dmitrievii/building-energy-tools/actions/runs/39020743237), commit `ac9dd3cd9b4b8543673fc23cf18cf91643563498`; all 73 tests passed and original source acquired.
- Artifact: [#12097010139](https://github.com/dmitrievii/building-energy-tools/actions/runs/39020743237/artifacts/12097010139). Original 159 catalog stations attempted, qualified donor pools: 2024 145, 2025 144, `MLJ` HTTP 403. On six target sites, 2024 and 2025 original source datasets.
- **A SCIENTIFIC PREREGISTRATION MISMATCH WAS DETECTED BEFORE SCIENTIFIC ACCEPTANCE:** [frozen protocol](IGE_P8_4B2_JOINT_WIND_PREREGISTERED_PROTOCOL_RU.md) explicitly prescribed `geometry=0.65`, `donor pairwise direction disagreement=0.25`, `missing fraction=0.10`. Executed code erroneously used `0.45, 0.45, 0.10`. The original `test_frozen_objective_coefficients_sum_to_one` only checked that their sum was one, not that they matched preregistration.
- **Therefore the original #39020743237 CANNOT be called an independent confirmatory test of the frozen P8.4B2 model.** Metrics from the original wrong-weight run are a *post-discovery off-protocol sensitivity*, NOT the final B2 scientific conclusion:
  - 2024 joint-minus-altitude equal-site hourly speed MAE −0.0421463 m/s; direction coverage +0.12963 percentage points; fixed90 direction diagnostic −0.12697°. Main site CRM worsened speed by +0.286549 m/s; failed frozen no-individual-deterioration >0.15 m/s gate.
  - 2025 joint-minus-altitude speed MAE −0.0326206 m/s; direction coverage +0.12228 pp; fixed90 −0.00579°; CRM speed worsened by +0.286903 m/s; identical gate failure.
  - The off-protocol solution therefore ALSO failed the registered multiobjective acceptance criteria, but the true registered candidate **has not been evaluated by this workflow**.

## Exact frozen-weights repair without retuning

- Scientific code repaired on commit `28bd2d6d7914bb9d2d4a69d154f99825148db64e`: restore original fixed weights `(0.65, 0.25, 0.10)` from the **pre-existing** registered protocol. Do not modify source station identities, years, ten-donor pool, physical ranking parameters, threshold values, training (2023) or evaluation years (2024/2025).
- Test repaired on `312f6e47a2012b8f154bdcf1cbbd6099cd14b5d8` to assert **exact matching** `(.65, .25, .10)`, not merely sum of weights.
- Latest [CI run #39021862209](https://github.com/dmitrievii/building-energy-tools/actions/runs/39021862209), computation and tests from `312f6e47`: contract stage green at audit time; original source holdout running. Its science results have NOT been examined yet and must not be invented.
- Correction is *restoration of an already-frozen protocol*, NOT post-hoc tuning. Nevertheless both the off-protocol numerical run and awareness of its site-specific outcomes are recorded transparently for scientific reproducibility.

## How to interpret next results

1. Confirm both CI jobs PASS and that original-source artifact genuinely contains all 159 attempted source station IDs and original source hashes; check failures and qualification.
2. Calculate six-site and each-site speed MAE, 3-way strict direction error, union coverage, fixed90 missing diagnostic separately for **2024 and 2025** on identical hours and registered thresholds.
3. Evaluate *all six* registered multiobjective gates. `CI_SUCCESS` never implies `scientific_joint_selector_accepted`.
4. Preserve negative results and isolated failure sites; do not tune coefficients or relax >0.15 m/s site loss or >10pp site direction coverage loss after seeing current results.
5. Even a research PASS is still not physically qualified future weather/EPW wind. Train uses contemporaneous original donors in 2023; evaluation uses same-time original donors in 2024/2025; 10m ERA5 instantaneous vs original hourly scalar values remain distinct physical quantities.
6. `main` unchanged, no merge, `production_epw_ready=false`.

The original metadata source and complete off-protocol artifact remain available for sensitivity reanalysis. Original source observations and gridded raws are not redistributed.
