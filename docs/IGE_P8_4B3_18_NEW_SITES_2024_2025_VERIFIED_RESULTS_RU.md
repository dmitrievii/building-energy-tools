# IGE P8.4B3 — VERIFIED 18 novel Swiss target stations, 2024/2025, original-source scientific closure

**Verified:** 17 October 2026. **Result:** `CI_PASS / SCIENTIFIC_BROAD_GENERALIZATION_FAIL_4_OF_4 / FROZEN_B2_SELECTOR_NOT_PRODUCTION_READY`.

## 1. Verified computation and integrity

- [GitHub Actions #39023515729](https://github.com/dmitrievii/building-energy-tools/actions/runs/39023515729) on code SHA `c73275842ea378027866f663dc5f880c1642f627` **2/2 jobs SUCCESS**: 14 P8.4B3 + 20 B2 + 17 B1 = **51/51 tests PASS**. Previous CI #39023481192 initially failed because its *synthetic unit-test fixture* supplied only two far-away donors despite preregistered pool >=10; fixture repaired, not the scientific algorithm or registered gates.
- [Scientific original-data artifact #12097702297](https://github.com/dmitrievii/building-energy-tools/actions/runs/39023515729/artifacts/12097702297), ZIP SHA256 `33e1f8fc85fbf0de9c2baa820fc58adfd1e7ee02dd4661b67ad50397da83e8c7`, contained JSON SHA256 `9a6886589b23ff84cbf1c70c67efc6469b25982b1fdbd2232ff310c23c785be0`; ZIP CRC PASS.
- Independent off-CI artifact audit checked **159/159** metadata IDs attempted, **158 original source CSV obtained**, source `MLJ` HTTP 403 logged, original source SHA256 in artifact, exactly 18 globally distinct previously untested target identities, exactly 72 unique `(site, year, scenario)` test records, all three selectors compared on identical true matched UTC hours for every station-year-scenario, sufficient >=80% annual coverage, exactly four donors per selector, **zero target/source leakage**, 25-km distance exclusion and *all four gate outputs recomputed from per-site metrics*, consistent to numeric tolerance.
- Same 18 new target IDs in both years, chosen deterministically by metadata+availability without examining held-out forecast errors. Sites by preregistered elevation bin:
  - Low <600 m: `MOA, GVE, SBO, CHU, FAH, SIO`.
  - Mid 600–1300 m: `PIO, HAI, ROB, FRE, PLF, LAG`.
  - High >=1300 m: `SIM, NAS, GSB, JUN, SBE, CIM`.
- Donor pool after **global exclusion** of 18 new targets plus six old B2 targets: **127** eligible 2024 donors, **126** in 2025. `qualified[year]` filters >=90% original hourly wind and >=75% original frozen 2023 donor-hour training coverage. Original measured instrument height and per-record source QC are still unverified.
- All 18 sites match the same UTC hours for three selectors and both scenarios: **157709/158112 site-hours 2024** and **157482/157680 site-hours 2025**, per scenario. Over two spatial scenarios there are **630382** aggregate method-matched site-hour evaluations, of which half are the same original site-hour reference under the other scenario (not independent observations).

## 2. All four registered scientific gate results

**Sign convention:** Δ = Joint Coherence − Altitude IDW4; negative ΔMAE is improvement; positive Δ angular fixed90 diagnostic means degradation. **Preregistered thresholds**: equal-site ΔMAE <=−0.020 m/s, >=6 of 18 site improvements of at least 0.020 m/s, >=12 nonworsening site speeds, no single speed loss >0.150 m/s, average direction coverage change >=−2pp, no single site direction coverage loss >10pp, average fixed90 diagnostic change <=0°. ALL must hold in every one of four year×scenario conditions.

| Original validation | Baseline altitude equal-site speed MAE m/s | Joint equal-site speed MAE m/s | ΔMAE m/s | Materially improved ≥0.02 m/s | Nonworsening speed sites | Δunion coverage pp | Δfixed90 diagnostic degrees | Acceptance |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2024 unbuffered | 1.476044 | 1.467661 | **−0.008383** | **1/18** | 15/18 | +0.2531 | −0.1827 | **FAIL** |
| 2025 unbuffered | 1.380516 | 1.370239 | **−0.010277** | **1/18** | 15/18 | +0.3202 | −0.2065 | **FAIL** |
| 2024 25km exclusion | 1.417559 | 1.400317 | **−0.017242** | **4/18** | 14/18 | +0.1571 | **+0.8945** | **FAIL** |
| 2025 25km exclusion | 1.317317 | 1.300008 | **−0.017309** | **5/18** | 15/18 | −0.1243 | **+0.9691** | **FAIL** |

Material gain and 6-site criterion fail **all four** validations; direction fixed90 diagnostic additionally fails **both 25km** validations. All other registered gates passed. This is an **honest research negative result with healthy code/CI**, not a runtime error.

## 3. Donor-selection effect is extremely sparse

- Unbuffered **only 5/18** sites had changed selected donor ID sets; **13/18 got identical donor sets and numerically unchanged forecast results** in both years. The five changed IDs were `MOA, SIO, PLF, GSB, CIM`.
- Under 25 km source exclusion, only **9/18** sites changed donor IDs, **9/18** unchanged.
- Large repeatable positive effect: high-altitude **CIM** speed MAE improved **−0.2674 m/s in 2024** (paired 7-day block 95% CI `[−0.3064,−0.2307]`) and **−0.2552 m/s in 2025** (`[−0.2846,−0.2223]`). This station improved equally in unbuffered and buffered scenario.
- Negative effects: low-altitude `MOA` speed worsened +0.0545 and +0.0351 m/s (unbuffered 2024/2025); `SIO` worsened +0.0623 and +0.0420 m/s (unbuffered), and **+0.0907/+0.0889 m/s** under 25km exclusion (paired 7-day 2024 CI `[+0.0624,+0.1255]`, 2025 `[+0.0606,+0.1216]`).
- Note that *all* this takes place on a population preselected for data availability and spatial dispersion. The previously observed B2 win `DIA` has not generalized to most other new stations.
- **Sensitivity only, not a change of acceptance set:** without `CIM`, mean ΔMAE on remaining 17 sites is **+0.006853 m/s (2024 unbuffered)** and **+0.004128 (2025 unbuffered)**, i.e. joint selector is worse than altitude on average in those subsets. In 25km scenarios the analogous leave-CIM-out mean gains shrink to −0.002526 and −0.003319 m/s. This demonstrates single-site concentration, not wide transferability.
- Equal-site mean 25km altitude baseline MAE happened to be lower than unbuffered altitude baseline on this selected sample. This is not proof that excluding neighboring donors is universally beneficial; it is consistent with heterogeneous local exposure and selection differences, and still lacks independent external-country anemometer metadata.

## 4. Directional robustness and elevation strata

Average directions are conditional on original MeteoSwiss hourly scalar-mean wind vs meteorological FROM direction, not independent forecasts. Fixed90 adds a *penalty to missing predictions*, not an actual observed angle.

| 2024 unbuffered elevation bin | Mean Joint − Altitude scalar MAE (m/s) | Changed selected donor ID sets |
|---|---:|---:|
| Low <600m | **+0.01946** (worse) | 2/6 |
| Mid 600–1300m | −0.00212 | 1/6 |
| High >=1300m | −0.04249 | 2/6 |

2025 analogous group effects: low **+0.01286**, mid −0.00136, high −0.04232 m/s. The apparent advantage is again driven primarily by high-altitude CIM.

- Under 25km exclusion, one alpine/high-altitude site `SBE` suffers union-direction **fixed90 diagnostic deterioration +14.06° (2024)** and **+11.18° (2025)**; nearby cases `LAG` likewise suffer +6.51° and +9.71°. Thus the new coherence term can make the *directional* criterion worse, despite mean direction coverage remaining relatively high.
- Crucially, missing-direction coverage alone is insufficient as a definition of direction quality. Monitor both common-hour strict directional MAE, source-direction uncertainty, local exposure and sector climatology.
- 2024–2025 observations at the **same sites are temporally replicated, not geographically independent replications**. Correlated source sensor characteristics and the unchanged B2 donor pool carry through across years. The two 25km scenarios likewise reuse original target readings.

## Decision

**P8.4B3 is closed as a verified, preregistered negative scientific result.** The 0.65/0.25/0.10 coherence-weighted four-donor Joint Selector is **NOT ACCEPTED as broadly generalizable historical Swiss wind reconstruction** on this 18-site elevation-stratified holdout; the P8.4B2 limited six-site research PASS remains descriptively true but is not promoted to a universal selector.

**Do not retune B2 weights to manufacture an in-sample win, do not merge to main and do not release to future EPW generation.** The currently most defensible baseline remains physically screened source eligibility and *altitude IDW4 as a comparative research benchmark*, with separate rigorous qualification of spatial bias, meteorological direction uncertainty, anemometer exposure, and independent external-country samples. Even altitude IDW4 did not uniformly improve P8.4B1 sites, so it is not a universal production method either.

Next research question: whether wind direction/topographic channeling needs a **regime-conditional physically interpretable predictor with independently measured site anemometer exposure**, instead of a static source-source directional coherence criterion. Freeze physical assumptions and use geographically distinct validation years/sites *before* any fitting. Future CMIP6 wind generator P8.4C and physical EPW P8.4D remain unapproved.

`main` unchanged, `production_epw_ready=false`.
