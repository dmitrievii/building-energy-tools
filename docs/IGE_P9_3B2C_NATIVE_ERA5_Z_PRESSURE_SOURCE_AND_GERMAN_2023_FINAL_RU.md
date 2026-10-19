# IGE P9.3B2C — Original ERA5 Surface Geopotential & Pressure Reference Closure

**19 October 2026.** Research branch `research/ige-p9-3b2c-native-era5-geopotential-20261019` based on P9.3B2 `9e17d612`. Region AT/DE/CH only; not a world validation, no main merge. Pre-registered fresh Germany DWD station/year before original new German P observations or ARCO geopotential readings: `docs/IGE_P9_3B2C_GEOPOTENTIAL_PRESSURE_PREREG_20261019_RU.md`, initial prereg commit `6712543e`.

**SCIENTIFIC STATUS: ERA5 REGULAR 0.25° GRID GEOPOTENTIAL PRESSURE SURFACE RECOVERED; OPEN-METEO GRID ELEVATION SEMANTICS PHYSICALLY VERIFIED AT FOUR GRID CELLS; SURFACE PRESSURE CROSS-SOURCE COMPARISON 6/6 SOURCES READ; NEW INDEPENDENT GERMAN STATION P PRESSURE OBSERVATIONS 0/336, BLOCKED; FULL THREE-COUNTRY PRESSURE QUALITY NOT QUALIFIED; PRODUCTION EPW FALSE.**

## 1. Original ERA5 geopotential field and provenance

ECMWF source parameter `z` / 129 in **m² s⁻²** at surface, geopotential height `H=geopotential/9.80665` metres. The original-modeled surface is the necessary **source-pressure vertical reference**, NOT an SRTM90 sample from the 0.25° grid center. Original ERA5 source port used was Google ARCO-ERA5 `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`, **ERA5-derived 0.25° regular-grid replica, not original ECMWF CDS GRIB byte-identical or the native spectral Gaussian grid**. Dataset contains *both* pressure-level `geopotential` (NOT used) and correct single surface `geopotential_at_surface` (used). Verified original variable units, no `level` dimension, required exact nearest grid center and same geopotential for Jan and Jul 2023 timestamps. Source [source-only CI #39276980299](https://github.com/dmitrievii/building-energy-tools/actions/runs/39276980299) completed SUCCESS; [original geopotential artifact #12196679700](https://github.com/dmitrievii/building-energy-tools/actions/runs/39276980299/artifacts/12196679700).

| ERA5 site / grid | Original ARCO geopotential z, m²/s² | Original-model surface H=z/g0, m | Prior Open-Meteo elevation returned, m |
|---|---:|---:|---:|
| Graz (47.0, 15.5) | 4581.2109375 | **467.153507** | 467 |
| Davos (46.75, 9.75) | 19606.4296875 | **1999.299423** | 1999 |
| Oberstdorf (47.5, 10.25) | 11590.525390625 | **1181.904666** | 1182 |
| Potsdam (52.5, 13.0) | 377.955078125 | **38.540692** | 39 |

All four differences from original Open-Meteo response elevation are **at most 0.46 m**, consistent with provider integer-metre rounding; prior SRTM90 original geographical DEM at the centers AT=332 m, CH=1995 m, DE Oberstdorf=862 m mismatches true model-grid pressure surface. This independently settles which SOURCE elevation Open-Meteo reports, but the Zarr is ERA5 regular-grid derived, so native spectral surface orography and field-processing details remain separate provenance claims.

## 2. Original surface pressure reference cross-product equivalence (not station accuracy)

A separately registered post-source comparison uses original source `surface_pressure` from ARCO, **Pa**, same 0.25° points and exact UTC `2023-01-10T00:00`, `2023-07-10T00:00`, versus unmodified Open-Meteo explicit `models=era5/elevation=nan/nearest/GMT` provider `surface_pressure` converted hPa to Pa. Exactly 3 grids ×2 times = **6 comparable pairs**, source SHA and selected original coords verified:
- Graz January OM minus ARCO **−0.381719 hPa**, July **−0.296875 hPa**.
- Davos January **+1.061953 hPa**, July **−0.110313 hPa**.
- Potsdam January **−0.092422 hPa**, July **−0.021953 hPa**.
- **Mean absolute cross-source difference 0.327539 hPa**, maximum **1.061953 hPa**. These are small but **not zero** and constitute a six-hour source equivalence probe only, **not statistical cross-year guarantee or exact native-GRIB concordance**. Source [Actions #39277745912](https://github.com/dmitrievii/building-energy-tools/actions/runs/39277745912) SUCCESS; [original source pressure-equivalence artifact #12197544208](https://github.com/dmitrievii/building-energy-tools/actions/runs/39277745912/artifacts/12197544208).

## 3. Observed pressure: independent and retrospective results must not be conflated

New preregistered German independent test: DWD CDC Potsdam **03987**, original official station metadata latitude 52.3812, longitude 13.0622, station altitude **81 m**. Source original station metadata SHA `6c12581ac1d60e0d8ef3794967c90dea788a43877bab600ea8e0594e05a76970`. Frozen **10–16 January 2023** and **10–16 July 2023**, 168 hours each. Original DWD historical archive `stundenwerte_P0_03987_19750701_20251231_hist.zip` `P` must be genuine absolute station pressure; original `P0` is reduced to sea level and cannot substitute it.

Original field-P source audit **confirmed original 168 records per week with QN_8=3, but P and P0 each empty/sentinel in ALL 336 hours**. Consequently final-QC10 source hours=0 and automatic-QC3 source hours=0. **0 new German measurement pairs were scored.** It is prohibited to search replacement station/year based on this observed result and call it the same independent holdout. Full original test [Actions #39276980182](https://github.com/dmitrievii/building-energy-tools/actions/runs/39276980182) SUCCESS as fail-closed original source/physics audit; [original pressure/negative DWD artifact #12198346007](https://github.com/dmitrievii/building-energy-tools/actions/runs/39276980182/artifacts/12198346007). Same source missingness independently verified in [Actions #39277745912](https://github.com/dmitrievii/building-energy-tools/actions/runs/39277745912).

Retrospective **already-seen** P9.3B2 2024 GeoSphere Graz and SwissMetNet Davos original pressure, recomputed with exact original ARCO pressure-reference height. These are not a fresh holdout and no fit was performed:
| Original already-seen 2024 station | B3 OM returned-height sensitivity, MAE hPa | B4 ARCO original geopotential H, MAE hPa |
|---|---:|---:|
| Graz January | 0.435623 | **0.421982** |
| Graz July | **0.835916** | 0.849644 |
| Davos January | 4.125869 | **4.102958** |
| Davos July | **2.944598** | 2.972764 |

These near-identical B3/B4 scores are a numerical consequence of ARCO z/g ≈ Open-Meteo elevation and are NOT evidence of additional external generalization. Historical pressure model skill remains as described by P9.3B2; neither source p nor geopotential alone establishes native CanESM5 pressure, which P9.3B1 did not recover at daily/hourly frequency.

## 4. Closure gates and next non-tuning requirement

| Required test | Scientific status |
|---|---|
| Distinguish original surface `z` from pressure-level geopotential | **PASS** |
| Recover original ARCO 0.25° ERA5-derived surface `z/g0`, verify grid / variable units / time consistency | **PASS**, four cells |
| Independently verify Open-Meteo elevation against original ERA5 pressure-surface geopotential | **PASS on four matched cells, ≤0.46 m rounding** |
| Independently compare Open-Meteo `surface_pressure` to same-grid/UTC ARCO `surface_pressure` | **PASS finite six-source test**, MAE 0.328 hPa, nonzero |
| Original CDS ERA5 native spectral grid original GRIB byte-equivalent and source processing independently reproduced | **NOT VERIFIED** (ARCO is a regular-grid remap) |
| Fresh new DWD German station `P` measured pressure benchmark, 2023 | **BLOCKED: 0/336 source values, P and P0 both empty** |
| Independent 2024 AT/CH new unseen cohort | **NO**, those records already seen in P9.3B2 |
| Broad AT/DE/CH station-pressure generalization | **NOT QUALIFIED** |
| Native daily CanESM5 pressure + future GCM cross-variable T/q/RH consistency | **NOT AVAILABLE / NOT QUALIFIED** |
| Real 8760 generated EPW / production pressure future model | **BLOCKED** |

**Scientific closure:** B2C original ERA5 0.25° pressure *reference-height source* and bounded same-grid pressure equivalence are resolved. Full independent **Germany pressure-skill validation remains source-blocked** and cannot be declared completed. Do NOT plug B4/ERA5 z+P into future CanESM5 as if this recreated original daily GCM `ps`. Next, conduct station-pressure **availability/provenance census only** on explicitly defined German source sites before freezing a *new* independent station+year, then test true `P` without QFF/QNH substitution. Separately establish ERA5 original GRIB/model orography lineage if native-Copernicus equality is needed. Only thereafter attempt P9.3B3 physically consistent `T–p–q–RH`, separately from EPW release.

**Main remains untouched. All P9.3B2C one-shot workflows disabled for automatic push and left manual only.**
