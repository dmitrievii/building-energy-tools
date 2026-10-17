# IGE P9.1D — Native ERA5 Orography, Independent DEM & Physically Conditioned Site Adaptation

**Scientific results 2026-10-17.** Source provenance and original 2022 heldout station calculations have passed a green real-source GitHub Actions CI; **no site/continental or production climate qualification is implied**.

## 1. Источники реально проверены, не заменены суррогатами

- **ERA5 native N320 geopotential:** read actual **542,080-value** reduced Gaussian original ERA5 surface parameter 129 `z` in Google Research ARCO cloud-optimized Zarr `gs://gcp-public-data-arco-era5/co/single-level-reanalysis.zarr-v2`. Converted geopotential m²/s² to geopotential height `z / g0` with `g0=9.80665 m/s²`. Selected original 2022 timestamps; the first dataset time entry was **entirely 542080/542080 missing**, and must never be used as a zero grid. Two fixed 2022 samples verified physical static elevation. ARCO is a converted archive, **NOT independently re-hashed ECMWF original CDS GRIB**.
- **Independent DEM:** real SRTM Version 3 90-m elevations from OpenTopoData `srtm90m`, with original provider response SHA, WGS84 coordinates and bilinear extraction verified; independent of ERA5 native z and GeoSphere site metadata. **Original SRTM DEM raster tile SHA and vertical datum harmonization were not verified**, so site ±10–30 m differences are not authoritative geodetic accuracy estimates.
- **GeoSphere Austria station metadata:** original official station altitudes, station coords and QC observed drybulb, genuine model-to-observation temperature MAE; no target hourly temperature included in any predictor or source-field selection.
- **Weather:** fixed Open-Meteo `models=era5,elevation=nan,cell_selection=nearest,timezone=GMT`, plus the provider's separately requested site-height corrected values. **ERA5 native Gaussian N320 nearest-grid height is NOT the exact Open-Meteo nearest regular 0.25° cell height**; native z-based lapse corrections in this stage are labelled *nonproduction physical proxies*.

## 2. Реальные высоты трёх станций

| Наблюдательная станция | Официальная высота | Независимая SRTM | Ближайшая ERA5 native N320 z/g0 | Отдалённость N320 |
|---|---:|---:|---:|---:|
| Graz Universität/Heinrichstraße | **366 m** | **373 m** | **395.16 m** | 11.54 km |
| Innsbruck Universität | **578 m** | **578 m** | **1392.36 m** | 17.37 km |
| Patscherkofel | **2251 m** | **2237 m** | **1987.73 m** | 18.39 km |

Существенное расхождение Инсбрука `Δz=−814.4 m` объясняет правдоподобность высотной поправки, но причинность **не доказана** без независимого картирования высоты _соответствующей 0.25° ячейки_. Не трактовать ближайший N320 как прямую замену регулярной 0.25° поверхности.

## 3. P9.1D1 — независимая 2022 температура, 1008 часов

Два зарегистрированных недельных периода `2022-01-10..16` и `2022-07-10..16`, GeoSphere `tl/tl_flag`, **1008/1008** исходных QC-принятых пар. Пять заранее зафиксированных методов, включая P0 black-box поставщика:

| Станция, период | L0 raw ERA5 | P0 provider height | L1 lapse 6.5 K/km | L2 bounded ±3°C | L3 winter calm/clear valley guard |
|---|---:|---:|---:|---:|---:|
| Graz январь | 1.321 | 1.330 | 1.297 | 1.297 | 1.297 |
| Innsbruck январь | 6.040 | 2.374 | **2.329** | 3.226 | 3.860 |
| Patscherkofel январь | **4.693** | 6.465 | 5.247 | 5.247 | 5.247 |
| Graz июль | 1.107 | **0.886** | 1.016 | 1.016 | 1.016 |
| Innsbruck июль | 7.059 | **1.020** | 1.847 | 4.059 | 4.059 |
| Patscherkofel июль | 3.913 | **1.637** | 2.572 | 2.572 | 2.572 |
| **Macro MAE °C** | **4.022** | **2.285** | **2.385** | **2.903** | **3.008** |

**Scientific result**: no fixed physics proposal uniformly improves model-to-station error. Provider height correction has the best six-cell average, yet strongly worsens one mountain winter; model L1 also fails at Patscherkofel in winter. The simple winter-night wind/cloud inversion guard made Innsbruck January worse (3.860 vs 3.226°C for L2). Therefore **do not promote a single lapse rate or this simplistic guard into universal production**. Preserve it as a falsifiable negative result.

## 4. Spatially withheld P9.1D2 and generalization

The new-site registered protocol is in `IGE_P9_1D2_NEW_ALPINE_STATIONS_2022_PRE_REGISTERED_RU.md`. Target stations 119,14305,28,17005,66,184 are drawn from prior published P8.1D paired-station inventory but not from P9.1D1 ERA5 source score. Frozen candidate parameters unchanged. Results appear in separate CI artifact; no retrospective tuning allowed. This is **geographic holdout among Alpine sites only**, not global independent coverage.

## 5. Required remaining qualifications

**Scientific method assessment PASS** only if exact original provider station QC observations, native z, SRTM DEM and weather source are independently available; the **negative** method ranking is still a valid experimental result. A green CI is **not** proof all climate physics is qualified.

Unresolved:
1. Verify **original 0.25° regular ERA5 geopotential orography** at precisely Open-Meteo selected cell and compare to native N320 source; map latitude/longitude convention, regridding and height conversion. This is mandatory before releasing physics-conditioned correction computed from `Δz`.
2. Independently retrieve Copernicus GLO-90 DSM original COG tile(s) and cross-check SRTM/site altitude, local slope and valley/crest classes, vertical datum; don't overinterpret DEM vs station 5–20m difference.
3. Build truly physical **inversion/valley-exposure regime model** from independent predictor sources and calibration data **disjoint from test station+year**, with explicit no-degradation floor for mountain winter.
4. Independent geographic station holdouts in climates beyond Austria, including arid, monsoon, coast and high-latitude sites; 2022 weeks are not a complete year. Quantify multi-year, monthly and extreme metrics.
5. Source full 12-variable bias/skill validation, not only temperature. Cloud/precipitation and wind direction require their own independent provider-QC matchup.
6. Only after those, integrate global historical site-corrected hourly EPW and future P9.2 joint weather generator.

**Decision:** P9.1D native orography/DEM source discovery and 2022 experimental ablation can be accepted as **research evidence**; the universal site-spatial adaptation model is **not qualified**. `production_epw_ready=false`. No main merge.
