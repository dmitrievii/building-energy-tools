# IGE P9.1F — Physically Conditioned Terrain & Inversion Modelling: verified independent research results

**Проверено:** 17 октября 2026. **Вывод:** `P9_1F1_SOURCE_QC_AND_ALGORITHM_PASS_SCIENTIFIC_HYPOTHESIS_FAIL`; `P9_1F2_INDEPENDENT_OBSERVED_SPATIAL_PAIR_STRATIFICATION_PASS`; `P9_1F3_JULY_2019_SOURCE_QC_ROOT_CAUSE_VERIFIED`; `TRUE_LOCAL_INVERSION_NOT_ESTABLISHED`; `GLOBAL_SITE_SKILL_NOT_QUALIFIED`; `production_epw_ready=false`.

Никаких производственных правок Climate Analyzer / EPW Writer, никаких merge в main. Работа на отдельной ветке `research/ige-p9-1f-physically-conditioned-terrain-inversion-20261017`.

## 1. Основа и источники

Замороженный до доступа к контрольным температурам [P9.1F1 prereg](IGE_P9_1F1_TERRAIN_COLD_POOL_GUARD_2019_PREREG_RU.md): **9 исходных GeoSphere Austria станций** (Wien Hohe Warte 105; Linz Stadt 56; Salzburg Freisaal 145; Klagenfurt Flughafen 48; Bregenz 15; Eisenstadt Nordost 22; Innsbruck Universität 39; Patscherkofel 196; Galzig 14305); источник `klima-v2-1h` `tl` вместе с `tl_flag`, допустимые в P8/P9 `10,11,12,20,21,22`; периоды 10–16 января, июля и октября **2019 года** — исходно 27 вариантов station×season. Не менялись числа, станции, годы, исключения на основе итоговой MAE.

**Исходные физические данные:**
- Open-Meteo фиксированное `models=era5`, nearest 0.25° выбранная ячейка и исходные реальные 12 часовых переменных с `elevation=nan`; независимый black-box вариант с указанной официальной станционной высотой.
- Google ARCO ERA5 **регулярная орография 0,25° в точном центре возвращённой погодной ячейки**, поле геопотенциала `geopotential_at_surface` с высотой `z/9.80665`. Сохранён оригинальный набор/выборочный hash и проверка координат. Нельзя гарантировать, что внутренняя схема регуляризации высот Open-Meteo тождественна ARCO.
- Независимая SRTM v3 90 m от OpenTopoData, **17 точек на станцию: станция и 8 направлений × радиусы 5 и 12 км**. Исходные provider SHA, рельеф `p75(12km)−height(site)`, нет подмены DEM станционной официальной высотой и нет скрытой правки климатических данных. Оригинальные SRTM raster tile bytes/вертикальная система datum сами непосредственно не сверялись.
- Никакого применения 2019 станционной температуры в исходных признаках, выборе точек, временных интервалов или настройке коэффициентов.

Физические исследования поддерживают **существование** холодных пулов/температурной инверсии в альпийских долинах, но не являются калибровкой наших порогов: Rauchöcker et al. 2024 `https://doi.org/10.1002/qj.4644`, Rupp et al. 2020 `https://doi.org/10.1029/2020JD032686`. Риск по DEM+ERA5 — **косвенный индикатор вероятности**, не фактическое обнаружение локальной температурной инверсии.

## 2. Физические кандидаты, зафиксированные до проверки 2019 года

`L0_RAW` — исходный ERA5 T2m.
`P0_PROVIDER` — Open-Meteo provider elevation adjustment, black-box comparator.
`L1_REGULAR_LAPSE` — `ERA5_T − 0.0065 (z_station−z_ERA5_regular)`.
`L2_TERRAIN_NIGHT_GUARD` — L1, но **запрет положительной высотной коррекции** при одновременных source-only условиях: `z_station ≤ z_grid−150m`, `SRTM 12km p75 relief≥120m`, `month in Oct–Mar`, `GHI≤10 W/m²`, `wind10m<2.5m/s`, `cloud<60%`. Вместо L1 используется исходный ERA5 T.
`L3_TERRAIN_NIGHT_COLDPOOL` — в те же часы использовать `ERA5_T−1°C`. Дополнительный −1°C не калибровался на наблюдениях и является только фиксированным sensitivity baseline.

18/18 тестов фиксированного исходного source physics / no-target leakage PASS. Весь original weather retrieval code даёт source SHA, исходный UTC, station ID и качества и удаляет неподтверждённые случаи по исходным флагам.

## 3. P9.1F1 — фактические 2019 holdouts, отрицательный результат

**27 исходных станция×сезон было зарегистрировано; всего 18 соответствуют заранее объявленному QC.** 9 зимних + 9 осенних рядов (в каждом 168 оригинальных станционных QC-часов), **3024 оригинальных парных часа**. 9 июльских рядов остались BLOCKED; причина независимо исследована P9.1F3, **они не включены в оценку MAE**.

| Frozen candidate | Equal site×season macro-MAE 2019 | Winter-only macro MAE | Number of site×seasons better than L1 |
|---|---:|---:|---:|
| L0 raw ERA5 | **2.2689°C** | 2.1834°C | 5/18 |
| P0 Open-Meteo provider altitude | **1.6250°C** | 1.2882°C | 10/18 |
| L1 regular ARCO z lapse | **1.6256°C** | **1.2849°C** | — |
| L2 physically screened cold-pool guard | **1.7387°C** | 1.3423°C | **3/18** |
| L3 guard with extra −1°C | **1.8168°C** | 1.3756°C | **1/18** |

*Scientific negative:* fixed source wind+cloud+irradiance+DEM valley screen **worsens average** relative to source-height lapse and provider correction. L2 increases macro-MAE vs L1 by **+0.1131°C**; L3 by **+0.1912°C**. No universal release. A conditional rule may help particular valleys, but no valid generalized test of improved error.

**Guarded events:** 282 original QC hours across 8 station-season cases. Source-regime-only, not measured inversion. Error weighted strictly by **number of original guarded QC observations**, NOT by site-season macro:

| Method | MAE on 282 frozen guard-selected hours |
|---|---:|
| Raw ERA5 | 2.9851°C |
| Open-Meteo adjusted | 1.7730°C |
| L1 regular lapse | **1.7719°C** |
| L2 suppress height | 2.9851°C |
| L3 extra −1°C | 3.8220°C |

This is decisive **misclassification of when to remove a useful correction**; occasional valley success is outweighed by false risk alerts.

**Selected negative/positive winter cases (overall 168h MAE):**
- **Klagenfurt Flughafen** Jan: raw **1.417**, provider 2.746, L1 2.722, L2 **2.444**, L3 2.494°C; 37 guarded hours, guarded L1 2.718 vs raw 1.457°C. Rule identifies *some harmful height-correction hours*, but also leaves 131 unguarded hours, so still much worse overall than raw.
- **Innsbruck Universität** Jan: raw 5.465, provider 1.615, L1 **1.596**, L2 2.075, L3 2.164°C; 15 guarded hours. At those hours raw MAE 6.087 vs useful L1 correction 0.728°C. The same risk triggers in a totally opposite error regime.
- **Bregenz** autumn: raw 2.084, L1 **1.644**, L2 2.095, L3 2.499°C; 70 guarded hours.
- **Salzburg** autumn: L1 1.424, L2 1.397 (small improvement); L3 1.628°C.

A finite source diagnostic model with 0/1 labels and no measured inversion cannot infer actual cold-air pooling from the available predictors. A physically richer vertical stability and local exposure model is required. **Do not retune these guard thresholds on 2019 to make the completed negative experiment appear positive.**

## 4. P9.1F2 — независимая пространственная наблюдательная стратификация (НЕ co-located)

Отдельно зафиксированы **четыре долина–верхняя станция пары GeoSphere**: St. Anton→Galzig (119→14305), Galtür→Idalpe (28→17005), Obergurgl→Pitztaler Gletscher (66→184), Innsbruck→Patscherkofel (39→196). 2019 winter/July/autumn, оригинальные `tl` + `tl_flag`, 7 source-contract tests PASS, 8/12 пар-сезонных оригинальных групп QC-qualified, **1339 совместных парных часовых слотов**, июль не проходит QC по той же причине.

**Доля ночных совместных QC часов с измеренным `T_upper > T_lower`:**

| Spatial station pair | Jan 2019 | Oct 2019 |
|---|---:|---:|
| St Anton → Galzig | 14.29% | **69.64%** |
| Galtür → Idalpe | 16.07% | **67.86%** |
| Obergurgl → Pitztal | 5.36% | 12.50% |
| Innsbruck → Patscherkofel | 0.00% | 17.86% |

Это реальные **пространственные** события «верхняя площадка теплее нижней», совместимые с холодным пулом/орографической неоднородностью. **НЕЛЬЗЯ выдавать их за коллокированную вертикальную инверсию температуры над одной точкой**: станции разделены горизонтально и отличаются микросредой. Отдельный показатель «теплее, чем ожидалось при −6.5K/km» также не равен фактической инверсии.

## 5. P9.1F3 — подтверждённая причина отсутствия июля 2019

Форензический эксперимент на **девяти прежних станциях** запросил исходные наблюдения за 2018-07, 2019-06, 2019-07, 2019-08 и 2020-07, по 168 часов. Не менялся набор пригодных исходных QC-флагов, исходные значения температур не загружены в публичный артефакт.

| Source period | Source `tl` finite hours across 9 stations | Original QC accepted |
|---|---:|---:|
| July 2018 | 1512 | **1512** |
| June 2019 | 1512 | **1512** |
| **July 2019** | **1489** | **0** |
| August 2019 | 1502 | **1502** |
| July 2020 | 1512 | **1512** |

**Root cause**: original July 2019 `tl_flag=0` at registered stations, unlike other periods' `tl_flag=10`. Official GeoSphere Austria quality code list explicitly states `0 = ungeprüfte Daten` (unverified), `10 = automatisch geprüft` (automatically checked), `11/12,20/21/22` further validated states. Documented in https://dataset.api.hub.geosphere.at/v1/docs/changelog.html and dataset https://data.hub.geosphere.at/en/dataset/klima-v2-1h . Therefore **values exist but cannot enter the STRICT ORIGINAL QC-QUALIFIED validation**; this is an original-data quality limitation, not missing meteorology and not solver physics failure. No approval to relax `0` to qualified.

6/6 P9.1F3 contracts PASS. Summer 2018/2020 availability could be used for a **separate, explicitly labelled exploratory** summer-baseline validation without rewriting original 2019 preregistration.

## 6. Decision & next research objective

**Close P9.1F1/F2/F3 as finished, scientifically valid experiments with a negative physical model outcome and a fully diagnosed original-source QC limitation.** Do not promote L2/L3 to runtime EPW generation or silently override source flags. The original provider adjusted or physically fixed regular-grid height temperature is currently a more defensible default **baseline research estimator**, but not a proven universal site model, especially when raw can outperform it in winter Klagenfurt.

**Next P9.1G should target actual atmospheric profile/stability rather than station residual fitting**: native ERA5 multi-level pressure/model-level temperature, surface/850hPa potential temperature stability with below-ground level safeguards; snow cover/soil cooling, longwave sky loss, advection/valley openness, DEM/valley sky view, altitude-aware source exposure; **original collocated sounding or temperature profiler observations at independent sites** if possible, new geography outside Austria with separate calibration and holdout years. Compare against L0 raw, P0 Open-Meteo and L1 regular-lapse without inventing better parameters after inspecting 2019.

No global climate engine site-accuracy release yet. P9.2 joint future hourly multi-variable synthesis remains a separate milestone. `global_spatial_skill_qualified=false`, `production_epw_ready=false`.

## Final independent QA — source/claim separation

[GitHub Actions #39055183522](https://github.com/dmitrievii/building-energy-tools/actions/runs/39055183522): **SUCCESS**, original downloaded P9.1F1/F2/F3 scientific result artifacts were independently rescored without re-fetching or re-fitting source observations; **31/31 frozen unit contracts PASS** across F1 (18), F2 (7), F3 (6). Verified each 2019 original case's macro MAE, 282-hour conditional subset-weighted error, actual 2019 summer missing QC, 1339 observed original station-pair slots and **July 2019 flag0 not peer-reviewed/quality checked**. Reproduced negative verdict `L2_macro > L1_macro`. Raw station hourly temperatures and ERA5 original global grids not republished.

## Provenance GitHub Actions / artifacts

- **P9.1F1 original 2019 source and fixed guard:** [run #39054277766](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054277766) — **2/2 jobs SUCCESS, 18/18 unit contracts PASS**; [original 2019 9-site independent DEM/ERA5/GeoSphere aggregations #12108951334](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054277766/artifacts/12108951334).
- **P9.1F2 original observed paired station gradients:** [run #39054622938](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054622938) — **SUCCESS, 7/7 unit contracts PASS**; [observed 2019 paired QC evidence #12108912676](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054622938/artifacts/12108912676).
- **P9.1F3 original summer 2019 QC gap:** [run #39054915474](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054915474) — **SUCCESS, 6/6 unit contracts PASS**; [source histogram and SHAs #12109276242](https://github.com/dmitrievii/building-energy-tools/actions/runs/39054915474/artifacts/12109276242).

All source studies live only on P9.1F branch, source SHA captured, raw original station time series and global ERA5 grids **not** uploaded to GitHub. Results use original source observations downloaded by GitHub Actions; no production readiness claimed.
