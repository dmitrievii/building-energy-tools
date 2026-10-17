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

## 4a. P9.1D2 — географически независимые шесть новых станций (2022, 2016 часов)

Заранее зарегистрированы новые для P9.1D станции **St. Anton am Arlberg, Galzig, Galtür, Ischgl-Idalpe, Obergurgl и Pitztaler Gletscher**. Эти станции известны по прежним исследованиям вертикальной стратификации P8.1D, но не использованы при выборе физической коррекции или исходной экспериментальной таблицы D1. В двух периодах 2022 г. **все 12/12 сочетаний прошли источник QC**, **2016** реальных парных часов, данные целевой станции никогда не участвуют в предсказании.

| Station / season | L0 raw | P0 provider | L1 −6.5K/km | L2 bounded ±3C | L3 winter valley guard |
|---|---:|---:|---:|---:|---:|
| St. Anton January | 2.610 | **1.770** | 2.649 | 1.896 | 2.205 |
| Galzig January | **4.823** | 6.159 | 4.998 | 4.998 | 4.998 |
| Galtür January | **1.974** | 2.573 | 2.011 | 2.011 | 2.026 |
| Idalpe January | **3.909** | 5.069 | 5.030 | 5.030 | 5.030 |
| Obergurgl January | 4.589 | **3.561** | 4.650 | 4.650 | 4.650 |
| Pitztaler Gletscher January | **4.571** | 7.317 | 5.937 | 5.937 | 5.937 |
| St. Anton July | 3.370 | 1.501 | 1.328 | **1.069** | **1.069** |
| Galzig July | 3.192 | **2.216** | 2.890 | 2.890 | 2.890 |
| Galtür July | 2.699 | **0.819** | 1.633 | 1.633 | 1.633 |
| Idalpe July | 2.132 | 1.848 | **1.832** | **1.832** | **1.832** |
| Obergurgl July | **0.961** | 1.157 | 0.973 | 0.973 | 0.973 |
| Pitztaler Gletscher July | 4.814 | **2.155** | 2.702 | 2.702 | 2.702 |
| **Equal site-season macro MAE** | **3.304** | **3.012** | **3.053** | **2.968** | **2.995** |

**Научный отрицательный результат:** небольшой выигрыш L2 над P0 **0.044°C** в независимом наборе НЕ устанавливает статистического превосходства (всего шесть новых станций, две недели и сильная почасовая автокорреляция). Зимние горные станции Galzig и Pitztal резко ухудшаются от автоматической высотной коррекции; выбор температуры исключительно по разнице отметок не воспроизводит местные инверсии и высотно-экспозиционные условия. Физически мотивированный L3 guard не дал убедительной пользы. Данные всех изначально запланированных станций, включая отрицательные, сохранены без исключений.

**Подтверждённый CI:** [GitHub Actions #39046989759](https://github.com/dmitrievii/building-energy-tools/actions/runs/39046989759), **2/2 jobs SUCCESS, 19/19 tests PASS**, оригинальные источники и два независимых набора наблюдений. Научные агрегаты:
- [Original native N320 geopotential and independent SRTM DEM #12106007084](https://github.com/dmitrievii/building-energy-tools/actions/runs/39046989759/artifacts/12106007084);
- [P9.1D1 original 3-station 2022 fixed-method temperature holdout #12106277100](https://github.com/dmitrievii/building-energy-tools/actions/runs/39046989759/artifacts/12106277100);
- [P9.1D2 six new Alpine stations 2022 #12106680088](https://github.com/dmitrievii/building-energy-tools/actions/runs/39046989759/artifacts/12106680088).

### Combined descriptive estimate (not a model-selection gate)

Across all **9 distinct stations × 2 seasons = 18 site-season pairs**, the macro-MAE of the raw ERA5 source is approximately **3.54°C**, provider altitude **2.77°C**, fixed 6.5K/km **2.83°C**, bounded fixed lapse **2.95°C**, and winter guard **3.00°C**. The original 3-site and subsequent 6-new-site cohorts are deliberately tracked separately: selecting the best of these five methods after seeing 2022 is forbidden. The mixed cohort is limited to **Austria**, does not qualify global spatial generalization.

---

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
