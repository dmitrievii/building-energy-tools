# IGE P9.1H1 — First genuine 2018 near-surface tower observation probe (Hyytiälä), preliminary scientific source readback

**Research date: 2026-10-17.** Branch `research/ige-p9-1h-near-surface-inversion-20261017`. **Not a qualified model result. Source QC currently OPEN. Main unchanged.**

## Evidence and original source

Real Hyytiälä SMEAR II tower temperatures from University of Helsinki SmartSMEAR API, verified live:
- Original provider variable lookup: `HYY_META.T42` = 4.2 m Pt100 shielded, `HYY_META.T672` = 67.2 m Pt100 shielded, both °C, HYY_META, provider metadata valid for 2018; public rights metadata.
- Genuine API OpenAPI version `1.1.1`, SHA256 `b66e35b80f0e77d453d900122ef445fb8b3ba0e493e1f19ba8ffd753a8fd3ece`. Request parameters `tablevariable,from,to` and provider output fields `aggregation,aggregationInterval,columns,data,endTime,recordCount,startTime`. `aggregation=NONE`, interval null.
- **Time semantics** source `samptime` is Hyytiälä local *standard* UTC+02:00 year-round, not Europe/Helsinki DST. Source API provides interval start. UTC conversion done explicitly. Every source minute at both heights paired by identical UTC time, no spatial or temporal interpolation. Reanalysis/model values were not accessed.
- Source original bytes read but NOT uploaded; provider response SHA256 pinned below. Aggregate original-source QA artifacts from [GitHub Actions run #39061254895](https://github.com/dmitrievii/building-energy-tools/actions/runs/39061254895), source artifact ID 12111526997. Real-source script: `research/ige_cmip6/p9_1h1_original_2018_SMARTSMEAR_profile_exploratory.py`.
- Provider online QA/coverage tier **not qualified**, no accompanying per-reading documented good flag. Sentinel/missing/nonphysical values dropped; absence of a missing flag does **not** prove full quality check. Independent 2021 data remain unread.

## Registered 2018 development windows: real source-only descriptive observations

Both 2018-01-10..16 and 2018-07-10..16 inclusive are *local standard* date selection from API (2018 only). Paired 4.2 m and 67.2 m, so `Δz=63.0m`. `ΔT=T_67.2-T_4.2`; preliminary inversion `ΔT>0.10K`. Mean hourly ΔT computed from >=45 synchronous measured 1-min pairs, no filling. These are **candidate observed structure**, not qualified cross-regional or temperature-prediction accuracy.

| Source diagnostic | 2018 January | 2018 July |
|---|---:|---:|
| Provider native row support per height | 10,080 | 10,080 |
| Unusable T42 original values | 0 | 28 |
| Unusable T672 original values | 0 | 26 |
| Synchronised valid minute pairs | 10,080 | 10,052 |
| Hours with >=45 real synchronous minute pairs | 168 | 168 |
| Mean hourly ΔT K (upper minus lower) | -0.692011 | +0.875046 |
| Minimum hourly ΔT K | -1.122833 | -1.879333 |
| Maximum hourly ΔT K | +1.025000 | +6.363833 |
| Hours with ΔT>0.10 K | 5/168 | 77/168 |
| Fraction of hours with ΔT>0.10 K | 2.976% | 45.833% |
| Hours with ΔT<−0.10 K | 161/168 | 90/168 |
| Near-neutral (neither extreme) | 2/168 | 1/168 |

Source ZIP/API response SHA256 identifiers:
- Jan T42: `16baa2f1e6f034dad438d5a2dc855f492164eab42b8f50d1364585f054efe2e0`
- Jan T672: `12f0edc6cbeb1f77d3fb8745e5d3835536b681c3d0b980f7ca27bde8f867dc89`
- Jul T42: `78befac7624ffdf4161bfdee46a969e6725e5d09933f796101c46c9c05ff6e2c`
- Jul T672: `3e8b2b139484cea098eab65b56273a99e93441bcd44186a9c6986e714aa13290`

Interpretation **limited**: 63m difference spans below- and above-canopy air in a boreal forest. Summer frequent positive vertical ΔT may include nighttime stratification/forest canopy energy exchange; actual radiation, snow, topographic valley exposure and instrument QA are not yet linked. Winter rare positive vertical ΔT over these seven days should **not** be generalized to all of Finland or used to claim poor or strong inversion detection by ERA5; ERA5 was not scored. Do not confuse positive `dθ/dz` with directly observed positive `dT/dz`. No temperature-model MAE, cross-region validation, or future EPW qualification is supported.

## Original scientific gates — intentionally unchanged

| Scientific gate | Status |
|---|---|
| P9.1H preregistration, source registry, date freeze | PASS |
| Original HYY metadata and public API schema verified | PASS |
| Original independent HYY 2018 paired physical sensor-response readback and minute alignment | **PASS as exploratory observation source read**, not full QC |
| Native per-reading provider QC documentation and qualification | **OPEN / NOT QUALIFIED** |
| Other independently authenticated geographical sources (KNMI Cabauw, ARM USA) | **NOT YET READ** |
| H2 physical inversion predictors radiative/snow/topography source validation | **NOT STARTED** |
| H3 physically conditioned ERA5 2m temperature model | **NOT STARTED** |
| H4 independent new site and unobserved new year holdout | **NOT STARTED** |
| Arbitrary-site / production EPW integration | **NOT READY** |

## Next experiment

**H1B multi-region real source qualification**: obtain actual raw and manual-QC KNMI Cabauw tower 2/10/20/40/80/140/200m on both 2018 and 2021 registered windows via documented API key or other authoritative KNMI-hosted source; audit 2018 first and keep 2021 holdout blind. In parallel probe DOE ARM SGP 25m/60m actual source and QA, or an equivalent independent open multiheight site. Resolve native SMEAR quality option/metadata and sensor-calibration provenance before labeling any 2018 profile fully qualified. Until >=2 distinct regions and native QC are admitted, H1 source gate stays OPEN. Do not silently replace blocked source/date windows or retrofit to Austria/Germany 2019 P9.1G skill samples.

**2021 untouched. No `main` merge.**
