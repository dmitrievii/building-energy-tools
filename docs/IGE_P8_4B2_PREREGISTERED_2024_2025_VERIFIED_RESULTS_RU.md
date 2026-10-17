# IGE P8.4B2 — VERIFIED registered joint wind results, 2024/2025 (17 October 2026)

**Decision:** `CI_PASS / REGISTERED_SIX_GATES_PASS_BOTH_YEARS / SELECTOR_ACCEPTED_FOR_THIS_RESEARCH_PROTOCOL / SPATIAL_GENERALIZATION_NOT_DEMONSTRATED / FUTURE_WIND_PRODUCTION_REJECTED`.

## Reproducibility / preregistration integrity

- Scientific protocol frozen **before** target evaluation: [IGE_P8_4B2_JOINT_WIND_PREREGISTERED_PROTOCOL_RU.md](IGE_P8_4B2_JOINT_WIND_PREREGISTERED_PROTOCOL_RU.md), geometry = **0.65**, source directional disagreement = **0.25**, source-availability penalty = **0.10**.
- **Verified corrected, protocol-compliant numerical run**: [GitHub Actions #39021862209](https://github.com/dmitrievii/building-energy-tools/actions/runs/39021862209), source code commit `312f6e47a2012b8f154bdcf1cbbd6099cd14b5d8`. **Both CI jobs PASS; all 73 tests PASS** (20 B2 + 17 B1 + 20 P8.3D + 16 P8.3A), including exact coefficient assertion.
- Raw-source aggregate artifact [#12097232058](https://github.com/dmitrievii/building-energy-tools/actions/runs/39021862209/artifacts/12097232058), ZIP SHA256 `43c6a3266158909b84d6bfd102ca7861c16998be98dcde4a262a76ce3b8884f4`, JSON SHA256 `fd88347a137cdfc59523076274b2a572b7c102ad7b6eca443895be5896dd8f3f`, ZIP CRC PASSED. Original provider source SHA-256 and stations' donor IDs in JSON, no source hourly series uploaded.
- [Audit of original off-protocol run](IGE_P8_4B2_PREREGISTRATION_AUDIT_AND_REPAIR_RU.md). Historical #39020743237 used **wrong** (.45,.45,.10) weights, is **not confirmatory** even though it was CI green. The present result does **not** erase this exposed deviation. Restoration of prior frozen coefficients is not tuning.

## Original full catalog and actual matched hours

- All 159 SwissMetNet catalog station IDs **attempted**; one denied provider source `MLJ` (HTTP 403) but preserved as a transparent failure; training 2023 and observation-year qualification, qualified excluding targets: **145 eligible donors 2024** and **144 in 2025**.
- **Six distinct target sites** `DIA, CDM, GRE, BIZ, SAE, CRM`, globally excluded from ALL source donors. Same six targets in both years; donor coherence estimated exclusively from fixed 2023 source-hour samples (6-hour cadence). Historical contemporaneous donor observations used for predictions in 2024 and 2025 — never independent climate event generation.
- All three selectors compared on identical site/year original UTC hours. **2024**: 52,395/52,704 possible site-hours (including leap-year Feb 29); **2025**: 52,260/52,560.
- The donor sets chosen by the joint selector were **identical across the two evaluation years** for each target. Scientific temporal replication exists but is strongly correlated geographically. No original hourly per-record QC certification.

## Six-site equally weighted scores

| Score (on each site's strictly same source-eligible hours) | 2024 distance-only | 2024 altitude | 2024 preregistered joint | 2025 distance-only | 2025 altitude | 2025 preregistered joint |
|---|---:|---:|---:|---:|---:|---:|
| Scalar hourly speed MAE m/s | 2.35355 | 1.60294 | **1.55674** | 2.13223 | 1.44410 | **1.39563** |
| Union azimuth coverage % of actual noncalm reference hours | 97.0617 | 98.5153 | **98.4941** | 96.6164 | 98.0929 | **98.0698** |
| Union fixed90 missing-penalty diagnostic ° | 61.6326 | 43.7781 | **43.4229** | 61.8779 | 44.3232 | **43.8166** |
| Emitted-only union direction circular MAE ° (conditional) | 60.974 | 43.058 | **42.687** | 61.101 | 43.383 | **42.855** |

**Registered joint − altitude differences:** 2024 speed **−0.0462073 m/s** (~2.88% lower), 2025 **−0.0484691 m/s** (~3.36% lower). Direction coverage changes **−0.0212 and −0.0231 percentage points** (tiny deterioration, not improvement); fixed90 missing-penalty diagnostic improves **−0.3551° and −0.5066°**, respectively. These scores are derived from six-site equal weighting, not necessarily regional climatological weighting.

## Why the headline mean improvement does NOT show broad spatial generalization

The preregistered joint selector changed the original altitude ranking donor ID **set on only one out of six sites**: `DIA`, both years. Site `DIA` switched from altitude set `ATT, MLS, GSB, EVO` to coherence-selected `ATT, GOR, GSB, MLS`. The other five stations chose the **identical donor sets** under both methods. Any differences in donor ordering have no effect because interpolation uses real distances.

| Site | 2024 altitude MAE | 2024 joint MAE | 2025 altitude MAE | 2025 joint MAE | Changed donor membership? |
|---|---:|---:|---:|---:|---|
| DIA | 3.18710 | **2.90985** | 2.92105 | **2.63023** | **Yes** |
| CDM | 0.89316 | 0.89316 | 0.81461 | 0.81461 | No |
| GRE | 0.76349 | 0.76349 | 0.82305 | 0.82305 | No |
| BIZ | 0.65361 | 0.65361 | 0.58530 | 0.58530 | No |
| SAE | 3.39613 | 3.39613 | 2.85486 | 2.85486 | No |
| CRM | 0.72419 | 0.72419 | 0.66574 | 0.66574 | No |

The *entire* six-site improvement in speed comes from DIA, by **−0.277244 m/s in 2024** and **−0.290815 m/s in 2025**, dividing each by six. DIA 7-calendar-day, 400-sample paired bootstrap intervals: **2024 [−0.32961, −0.21121] m/s**; **2025 [−0.34729, −0.21548] m/s**. The other five sites have numerical noise-level deltas 0; no source-independent verification of this selector on new geographic domains. DPI and ZER from P8.4B1 are **not** new B2 target validations.

**Directional robustness is still modest:** pooled emitted-only direction error of ~43° is high for site-specific wind directions, even if direction coverage is high. Fixed90 is a **diagnostic** that assigns missing results 90°, not a measured angle in those hours. A low deterioration of coverage is explicitly allowed (<2 pp average); it must not be reported as improvement.

## Explicit frozen acceptance gates, independently for both years

| Registered gate | 2024 | 2025 |
|---|---|---|
| Joint equal-site speed MAE no worse than altitude | **PASS** | **PASS** |
| Equal-site union direction coverage >= altitude −2 pp | **PASS** | **PASS** |
| Equal-site fixed90 diagnostic nonworsening | **PASS** | **PASS** |
| No target union direction coverage loss >10 pp | **PASS** (max 0.1272 pp) | **PASS** (max 0.1386 pp) |
| No target speed MAE loss >0.15 m/s | **PASS** (max 0.0000) | **PASS** (max 0.0000) |
| >=4/6 sites speed MAE nonworsening | **PASS** (6/6 incl. ties) | **PASS** (6/6 incl. ties) |

Important distinction: six of six *nonworsening* sites includes **five sites with unchanged selection/prediction**, not six demonstrated improvements. Do not claim superiority at majority of sites.

## Final decision and next evidence

1. This precise pre-registered **B2 research candidate is ACCEPTED under the frozen gates** for the Swiss retrospective sample in 2024/2025. The previous off-protocol negative-run cannot overturn or masquerade as this result.
2. **External/general deployment NOT APPROVED:** benefit is concentrated at DIA; 2024/2025 share identical donor sets and six locations; no tested additional geography, independent station anemometer height/roughness, original individual-hour QC or true future wind synthesis.
3. Next essential scientific gate: pre-register geographically disjoint source-blocked sites / years, keep frozen objective and all thresholds, quantify true prediction-hour direction uncertainty, and test whether benefits repeat **beyond DIA**. Distinguish southern alpine/high-altitude/lowland stratification and cross-site wind roses/persistence. Do not retune .65/.25/.10 after seeing B2.
4. `P8.4C future CMIP6 SSP vector wind=false`, `P8.4D integrated full 8760 EPW wind validation=false`, `production_epw_ready=false`. Only `research/ige-p8-4b2-joint-wind-20261017` changed; no merge.
