# IGE P9.3B2 — Terrain-Aware Pressure Baseline & Independent Station Validation: финальный физический аудит

**19 октября 2026.** Ветка `research/ige-p9-3b2-terrain-aware-pressure-stations-20261019`. Один заранее зафиксированный региональный эксперимент, **только AT/DE/CH**, станции Graz Universität/Heinrichstraße GeoSphere 30, Oberstdorf DWD 03730, Davos SwissMetNet DAV; **2024-01-10…16** и **2024-07-10…16** UTC, по 168 ч. [Проспективный протокол до чтения измерений](IGE_P9_3B2_TERRAIN_PRESSURE_STATION_2024_PREREG_RU.md), commit `e9ff95ec`. Главная цель — квалифицировать давление, не устранять известные годы P9.3A и не создавать EPW.

## 1. Абсолютное давление, оригинальные данные и источник рельефа

Оригинальные поля подтверждены до расчёта 2024:
- GeoSphere Austria, `klima-v2-1h` station **30**: **`p`**, `p_flag`; **`pred` — давление приведённое, не используется**. Исходная высота станции **366 м**, метаданные SHA256 `8eb42e3b9a4e3546d9fb04b5211be0ef7f8acb79dfc4f2a27017663673bf47f2`; 168 часов с исходным `p_flag=10` в январе и июле. Station-level original pressures SHA январь `d9d250d3ca0ae121e30c54e78c3880d88c2c58056b415e9f05df45ecd6523e94`, июль `4302538fada81b51c69b21b46380afb60965e135eded9fd3b08ade7eca368da3`.
- DWD CDC original hourly pressure historical station **03730 Oberstdorf**, исходная высота **806 м**; `P` — абсолютное давление станции, `P0` — приведённое к морю. Исходный архив `stundenwerte_P0_03730_19490101_20251231_hist.zip`, SHA256 `64d7a7ec11c3b74df754eac82b2284b4e7ddcae268acf38e20299de000fe5dff`. **SOURCE BLOCKED**: обе фиксированные недели имеют по 168 строк `QN_8=3` (автоматический QC), но **`P` и `P0` пусты в каждой строке**. Это подтверждено независимым просмотром ZIP, а не оценкой после фильтрации. Никакой морской `P0` в расчёт станционного давления не вводился. [Аудит исходного архива #39233374422](https://github.com/dmitrievii/building-energy-tools/actions/runs/39233374422), original source artifact #12177448751.
- MeteoSwiss original SwissMetNet **DAV**: **`prestah0`** — оригинальное часовое барометрическое давление (QFE), `pp0qffh0/pp0qnhh0` — приведённые к морю и не используются. Исходная высота станции **1594 м**, оригинальные метаданные SHA `b0025fb9909f28d536e90983337525697c27b75a607d1724f2d411ef3477ab59`; original 2020–2029 OGD pressure asset SHA256 `f2956f9dd418b04056eae334b061ce50fc567bfd4f630085384662e540f30e44`. Обе недели по 168 валидных опубликованных часов, но **нет сопоставимого с GeoSphere `p_flag=10` посэмплового QC**. Часовая метка OGD обозначает **конец** измерительного интервала; дополнительная заранее объявленная −1h sensitivity сохраняется отдельно, нельзя выбирать лучший лаг по результату.
- Оригинальные hourly `surface_pressure`, `temperature_2m`, `dew_point_2m` из **Open-Meteo derived ERA5** `models=era5,elevation=nan,cell_selection=nearest,timezone=GMT`, без провайдерского рельефного постпроцессинга; это **не оригинальные ECMWF CDS ERA5 GRIB**. Исходные 12 полей и канонические SHA каждого site-season зарегистрированы в оригинальном CI artifact #12177942533.
- Внешний OpenTopoData **SRTM90m** DEM для центров возвращённых ERA5 сеток, источник original response SHA256 `814dbcdafa7f9f9ea4f62a6219406e7fd821bb7f6a001bb174da5085bf20f1ad`; неизвестно, соответствует ли DEM локальная высота **модельной эффективной орографии ERA5**. Три высоты SRTM90: AT grid `(47.0N,15.5E)` **332 м**, DE `(47.5N,10.25E)` **862 м**, CH `(46.75N,9.75E)` **1995 м**. Open-Meteo в оригинальном grid-response возвращает соответственно **467, 1182, 1999 м**, но это **не исходный независимо верифицированный grid-cell geopotential ERA5**. Следовательно, автоматическая высотная поправка с SRTM90 по центру ячейки **не** равна гарантированной коррекции от исходной модельной поверхности.

## 2. Физическая постановка и заранее определённые модели

Исходное ERA5 давление на сетке `p_g` сравнивается с **измеренным абсолютным** давлением станции `p_s` (все показатели гПа). Варианты **не калибруются** по наблюдениям 2024:
- `B0`: исходное `p_g` без поправки.
- `B1`: изотермическое гидростатическое соотношение с влажной виртуальной T и `Δz=z_station−z_SRTM90_grid`: `p_s=p_g exp(−g Δz/(Rd Tv))`, `g=9.80665`, `Rd=287.05`, `Tv=(T_g+273.15)(1+0.61q_g)`.
- `B2`: до наблюдений зафиксирована чувствительность с `Γ=0.0065 K/m`: `p_s=p_g(1−ΓΔz/Tv)^(g/(RdΓ))`; тот же SRTM90 DEM и неизменные метеорологические поля.
- `B3`: **отдельная метаданная чувствительность, добавленная после чтения схемы провайдера, но ДО обращения к оригинальным измерениям 2024**: то же B1, но `Δz=z_station−z_OpenMeteo_response_elevation`. Источник такого `z_g` **не подтверждён как нативная ERA5 орография**; это не основание выбирать B3 как победителя по уже увиденным ошибкам 2024.

Восемь из восьми физических контрактов `test_p9_3b2_hypsometric_pressure_model.py` PASS: нулевая разница высот, знак поправки, влияние `q` на Tv, согласие методов при малых `Δz`, вертикальный предел, физически допустимое давление. [GitHub Actions #39232269153](https://github.com/dmitrievii/building-energy-tools/actions/runs/39232269153).

## 3. Genuine 2024 observations: strict identical-hour MAE (гПа)

[Оригинальный исходный CI **#39232747620**](https://github.com/dmitrievii/building-energy-tools/actions/runs/39232747620) **SUCCESS** (это запуск научного эксперимента, не научный статус всего генератора). [Original measured scores/SHAs artifact **#12177942533**](https://github.com/dmitrievii/building-energy-tools/actions/runs/39232747620/artifacts/12177942533). Идентичные исходные QC-часовые пары внутри каждого site-season:

| Original station | Period | N original p | B0 ERA5 | B1 SRTM90 isothermal | B2 SRTM90 lapse | B3 provider-height sensitivity |
|---|---|---:|---:|---:|---:|---:|
| Graz GeoSphere | Jan 2024 | 168 | 12.650 | 16.750 | 16.752 | **0.436** |
| Graz GeoSphere | Jul 2024 | 168 | 10.336 | 14.054 | 14.056 | **0.836** |
| Davos MeteoSwiss | Jan 2024 | 168 | 46.643 | 4.466 | 4.646 | 4.126 |
| Davos MeteoSwiss | Jul 2024 | 168 | 36.652 | 2.583 | **2.422** | 2.945 |
| Oberstdorf DWD | Jan 2024 | **0** | — | — | — | — |
| Oberstdorf DWD | Jul 2024 | **0** | — | — | — | — |

N original station-pressure records on identical source clock support = **672 / preregistered 1008**; 4/6 cells independently evaluable, German station original QFE source missing. Four-case *unweighted* macro MAE: B0 **26.571 hPa**, B1 **9.463 hPa**, B2 **9.469 hPa**, B3 **2.086 hPa**. Such mixed-station averages **are not climatological region-wide accuracy**: the large altitude contrast Davos dominates B0. B1 is better than B0 in **2/4** cells and worse in **2/4** (both Graz); B3 improves B0 in 4/4 but height-source semantics and limited observational cohort prohibit a general-production decision.

Bias note: Graz B0 January −12.650 hPa versus B3 −0.366; July B0 −10.336 versus B3 +0.794. Davos B0 January −46.643 versus B1 −4.332; July B0 −36.652 versus B1 +2.540. Means in these short periods are mostly systematic pressure offsets. Swiss OGD non-uniform per-sample QC and hour-end support produce additional uncertainty. The Swiss nominal and fixed shifted-hour sensitivity metrics are both preserved in the original artifact, no post hoc selected lag.

**Definitive altitude-source lesson:** At Graz, SRTM90 grid-center height 332 m vs original provider response 467 m, station 366 m, causing wrong B1 correction sign relative to provider effective height. At Oberstdorf, grid-center SRTM90 862 m vs provider 1182 m, station 806 m, an even larger contrast with *no available original station p* to judge the correction. At Davos SRTM90 1995 m ≈ provider 1999 m, station 1594 m, so both height corrections improve B0. The **right reference elevation must be the actual ERA5 model's pressure surface orography**, not a geographic DEM sample at the nominal cell center.

## 4. Scientific closure and release gates

| Qualification gate | Status |
|---|---|
| Station absolute/QFE identity and official source coordinates/height verified | PASS for 3 country metadata sources |
| Original station pressure QC available for all 3 countries in fixed 2024 holdout | **NOT PASSED: DE 0/336, both P and P0 empty** |
| Registered 2024 original pressure independent measured hours | **672 scored** |
| Isothermal/lapse hydrostatic correction and domain unit tests | PASS 8/8 |
| External DEM SRTM90 native grid-center source and SHA | PASS as **DEM geometric proxy only** |
| Verified true model ERA5 geopotential / model pressure effective surface height | **NOT VERIFIED** |
| B1 terrain-correction independent pressure improvement in all available sites | **FAIL (2 wins, 2 losses)** |
| B3 provider-elevation source-defined sensitivity original observed MAE improvement | **4/4 wins**, but retrospective one-year source skill does not certify source altitude or future generalization |
| Independent German station-level pressure measurement scored | BLOCKED |
| Native coarse CanESM5 `ps` original high-frequency pressure recovered (P9.3B1) | NOT RECOVERED |
| Coupled `T−p−q−RH` physically qualified for native original annual CanESM5 | NOT QUALIFIED |
| Full original EPW / real GCM EnergyPlus engineering release | BLOCKED |

**P9.3B2 research implementation and frozen independent source-observations DONE, but full three-country pressure qualification FAIL-CLOSED.** No pressure bias fitting against original 2024 observations and no substitution of sea-level P0. Do not feed B3 directly into P9.3A as native CanESM5 pressure: this is still a 2024 historical ERA5-derived source, whereas NEX bias-adjusted GCM daily `tas/huss/hurs` and future source `ps` remain inconsistent. Do not modify main.

**Next scientific task:** obtain authenticated *native ERA5 geopotential / model orography* (e.g. CDS `geopotential z` divided by `g` at ERA5 pressure-grid resolution and same source processing), rigorously compare with original Open-Meteo response altitude and DEM; register a new untouched pressure holdout with at least one German station actually measuring true absolute pressure `P` before reading outcome data; validate fixed pressure transforms with source original hourly T/p/RH across all AT/DE/CH. After scientifically qualifying historical pressure, proceed to P9.3B3 joint-source thermodynamic reconciliation, but not directly to full EPW. World station sweep only later for article.

**No main merge.** After final audit, workflows manual-only.
