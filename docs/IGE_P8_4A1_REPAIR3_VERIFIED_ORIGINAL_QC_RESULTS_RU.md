# IGE P8.4A1 — source-backed QC repair3 and clock diagnostics, verified 16 October 2026

**Status:** `A1_SOURCE_PILOT_SUCCESS / TWO_GRAZ_WIND_SERIES_2024_QC_QUALIFIED / TEMPORAL_SUPPORT_PHYSICAL_CLOSURE_PENDING / PRODUCTION_REJECTED`.

- Independent [GitHub Actions #38916421953](https://github.com/dmitrievii/building-energy-tools/actions/runs/38916421953) on code head `c0647b3e9fe811018d8c908abc7241155e0ff2a4`: both jobs **SUCCESS**.
- Original artifact [#12053030387](https://github.com/dmitrievii/building-energy-tools/actions/runs/38916421953/artifacts/12053030387), SHA256 ZIP `143f271b8fc7eff5e4026bf3212f061aacbcaff840b9af1357379b54ed175372`, JSON `c143247db22b6867a934b9a309ba2dd9acc4875ff4260f95990522160f8ad457`; ZIP CRC PASS, original provider SHA256 included.
- Four original GeoSphere 2024 January sources were requested from the official 1h API with `ff,ff_flag,dd,dd_flag` and all 744 GMT hours. The **same** 85% joint-QC threshold, using original provider q21 flags 10/11/12/20/21/22, applied to each independently (not selected by model error).

## GeoSphere Graz 2024 January: actual physical values vs QC flags

| Station ID | Original source identity | Valid physical speed rows | Valid physical direction rows | Joint source QC accepted | Source speed/direction flags | Gate |
|---|---|---:|---:|---:|---|---|
| 30 | Graz Universität/Heinrichstraße (composite) | 0/744 | 0/744 | **0/744** | `null` all 744 | FAIL |
| 16414 | Graz Universität/Heinrichstraße (individual series) | 0/744 | 0/744 | **0/744** | `null` all 744 | FAIL |
| 16400 | Graz Thalerhof Flughafen | 744/744 | 744/744 | **744/744** | `10` all 744 | **PASS** |
| 16412 | Graz Universität | 744/744 | 744/744 | **744/744** | `10` all 744 | **PASS** |

The earlier failure was correctly raised because site 30 had no physical wind data or original approved QC in that month; merely receiving a complete timestamp axis had obscured this **site/parameter-period coverage issue**. This is **not** a common API failure or a relaxed original QC rule. Sites 16400 and 16412 are independently accepted for a 2024 January 1h wind-QC audit. Original site 30 remains unqualified.

GeoSphere original provider parameter definitions: `ff` = *Windgeschwindigkeit, vektorieller Stundenmittelwert*, m/s, and `dd` = *Windrichtung [360°], vektorieller Stunden-Mittelwert*. Therefore it is wrong to equate `ff` with Swiss `fkl010h0` scalar hourly mean speed or to treat either without verifying station exposure/height. The GeoSphere reference-time field support and exact 10-min aggregation operator remain to be independently established.

## Three-site Swiss versus ERA5 gateway: same 742 speed hours across -1/0/+1

| Site | ERA5 -1h speed MAE m/s | same-hour MAE | +1h MAE | strict three-way shared noncalm direction hours |
|---|---:|---:|---:|---:|
| BAS | **0.854919** | 0.880620 | 0.905984 | 734 |
| GRA | **1.749757** | 1.760445 | 1.778396 | 618 |
| MUB | **0.962507** | 0.977089 | 1.004151 | 542 |

The source checker was repaired after the first audit to use **exactly the same original timestamps and identical noncalm eligibility across all three shift hypotheses**; previously GRA and MUB directional denominators changed with shift. It still does not automatically choose a clock offset, and speed MAE reduction for -1h cannot establish temporal causality.

Official MeteoSwiss post-2018 source stamps (hourly reference 16:00 UTC means six 10-min end stamps 15:10..16:00 UTC) establish the **station** hour mean window. ERA5 10m wind (Open-Meteo explicitly `models=era5`) describes instantaneous model valid time, not the same temporal mean. No adjustment for representativeness, exact measurement mast height, source gateway orographic post-processing, or local 10-min gust distribution is authorized.

## Release gates

- Research source QC census: **PASS**, 2 of 4 specific Graz station series meet 85% full joint original wind quality in January 2024.
- Research three-shift paired clock sensitivity: **PASS**, 742 hours speed, strict paired direction denominators.
- Defensible equality of source temporal support across models: **NOT ESTABLISHED**.
- Verified wind instrument height / z0 / local exposure class: **NOT ESTABLISHED**.
- P8.4A full physical closure: **NOT COMPLETE**. A2 should reconstruct interval-equivalent model wind from subhourly input or document time-average limitations explicitly; expand source QC to additional regions/months/year and confirm GeoSphere station metadata.
- P8.4B historical full-census spatial wind: **NOT EXECUTED**.
- P8.4C future CMIP6 vector wind: **NOT EXECUTED**.
- P8.4D integrated 35-column EPW: **NOT EXECUTED**.
- `production_epw_ready=false`, main unchanged, no merge.
