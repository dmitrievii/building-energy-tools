# P9.3B3: согласованные Φs/lnsp, история датчиков и сравнение P1/P2

Ветка `research/ige-p9-3b3-p2-source-lineage-20261022` основана на `bfd5ab3e748505d10b2068de3c5e09b707f76700`. Найдена и реализована одна native ERA5 цепочка без подмены высоты барометра землёй станции. Исторические ссылки на barometer/T/RH за 2021 прочитаны для AT/DE/CH. Парный pressure pilot подготовлен на двух уже раскрытых сутках. Полный локальный расчёт столкнулся с отказами сетевого контура 403; **локальной оценки точности по этим суткам нет**. Запускаемый CI должен вычислить её либо сохранить явные source blockers.

## Подтверждённые результаты и границы

| Свойство | Подтверждение |
|---|---|
| Предыдущий CI | Run [39739417052](https://github.com/dmitrievii/building-energy-tools/actions/runs/39739417052): 2/2 jobs SUCCESS, 251 tests; SHA ZIP совпал с GitHub digest; фактические implementation hashes и 49 protected hashes совпали с tested commit |
| Новые математические контракты | 26 новых tests; вместе с прежними P9.2/P9.3A/B2/B3 — 277 PASS локально; 58 прежних scientific hashes неизменны |
| Φs/lnsp | Четыре пары source variable/time проверены по оригинальным GRIB: все 410240 коэффициентов каждого поля совпали с CO после float32 cast; A/B из original GRIB, поверхности, T и q совпадают |
| Высоты приборов | Датированные WMDR deployment records покрывают обе даты 2021 для barometer/T/RH всех трёх стран. Геодезический переход к ERA5 datum этим не сертифицирован |
| Физическая допустимость | Условная гидростатика газовой смеси на native N320, только в воздухе; не проверка приземной турбулентности, конденсата или всей динамики атмосферы |
| Независимая точность | Не квалифицирована: зарегистрированы уже раскрытые даты, всего два дня. Локально нет полного набора предсказаний из-за 403; результаты CI ещё требуют проверки |
| Эксплуатация | Не готово; B4 NOT QUALIFIED, native future CanESM5 ps не восстановлено, production EPW false |

[Локальный machine-readable отчёт](../research/ige_cmip6/p9_3b3_native_local_results_20261022.json) содержит исходные URL/SHA, metadata histories, результаты тестов и явные пределы неполного локального расчёта.

Предыдущий audit сохранён отдельно в `p9_3b3_reference_verified_CI_39739417052.json`; прежние результаты не редактировались. Старый P1/P2 workflow переведён в manual-only. Новый workflow запускается отдельно, с ограниченной веткой и новым protocol.

## 1. Одна цепочка исходных данных

Авторский ARCO каталог различает преобразованные `ar/` и cloud-optimized `co/` копии исходных GRIB [S1]. Выбраны:

| Переменные | Источник | Представление |
|---|---|---|
| Φs и lnsp | `co/single-level-surface.zarr-v2` | Один Zarr store, T639 spherical harmonics, paramId 129/152, model-level surface fields |
| T | `co/model-level-wind.zarr-v2`, `t` | T639 harmonics, paramId 130, original 137 hybrid levels |
| q | `co/model-level-moisture.zarr-v2`, `q` | Native reduced Gaussian N320, paramId 133, те же hybrid A/B |
| Контроль Φs и ps | `co/single-level-reanalysis.zarr-v2`, `z/sp` | Второе кодированное представление на тех же N320 coordinates; диагностические остатки сохраняются |

Φs и lnsp извлекаются совместно из native spectral surface chain. lnsp не вычисляется из `ar/full_37` surface pressure. Регулярная сетка 0.25° не вставляется в колонку. T и поверхность синтезируются точно на native N320 points q; q при построении колонки не интерполируется на иную горизонтальную сетку.

Дополнительный контроль — первые GRIB2 messages оригинальных monthly files `202102_hres_zs.grb2`, `202102_hres_lnsp.grb2`, `202108_hres_zs.grb2`, `202108_hres_lnsp.grb2`. Каждый message имеет **822674 bytes**. Читаются HTTP ranges сначала 0…15, затем ровно длина первого message; ответ 200 вместо 206 блокируется до чтения всего месяца. Проверяются paramId, level, J/K/M, UTC date/time, analysis type, нулевой forecast step и A/B. Все четыре messages соответствуют заранее выбранным 2021-02-01 00:00 и 2021-08-01 00:00.

Для каждого из четырёх полей выполняется точное равенство:

\[
\operatorname{float32}(X^{original\ GRIB}_{nm})=X^{CO}_{nm}
\quad\text{для всех 410240 Re/Im чисел.}
\]

Это удостоверяет конкретные GRIB→CO copies в двух контрольных часах. Оно не выдаётся за проверку всех monthly messages, исходных T/q GRIB bytes или будущего CanESM5 давления. Проверенные максимальные float32 cast errors для Φs — около 7.63·10⁻⁶ m²/s², для lnsp — около 5.79·10⁻¹¹; это ошибки cast коэффициентов, не полная ошибка GRIB packing и не uncertainty реального давления.

На независимом N320 `z/sp` source comparison сохраняются небольшие cross-encoding остатки, перечисленные в local report. Они не обнуляются, не используются для сдвига Φs/lnsp и не становятся подбираемым accuracy gate. Полная оценка ошибок spectral/grid packing здесь не построена. Прежнее расхождение Φ137 до 28 m между двумя `ar/` цепочками остаётся в старом отчёте. Новая native цепочка использует другой spatial support; это не исправление старого ARCO поля по station error.

## 2. Спектральная математика и hydrostatic transfer

ECMWF хранит коэффициенты парами Re/Im, сначала все n=m…639 при m=0, затем при m=1 и т.д. Нормировка [S2]:

\[
\frac12\int_{-1}^1[\bar P_n^m(\mu)]^2d\mu=1,
\qquad \mu=\sin\varphi,
\]
\[
f(\varphi,\lambda)=\sum_n X_{n0}\bar P_n^0(\mu)
+2\sum_{m=1}^{639}\sum_{n=m}^{639}
\bar P_n^m(\mu)[\Re X_{nm}\cos(m\lambda)-\Im X_{nm}\sin(m\lambda)].
\]

Для SHTOOLS real 4π normalization/no-CS:

\[
C_{n0}=\Re X_{n0},\qquad
C_{nm}=\sqrt2\Re X_{nm},\quad
S_{nm}=-\sqrt2\Im X_{nm}\quad(m>0).
\]

Нормировка, порядок и знак проверяются аналитическим диполем, независимым complex-basis oracle SciPy, случайными гармониками до degree 12 и sparse degree 639. Они не выбираются по близости к станции. SHTOOLS Fourier/Legendre synthesis остаётся в одном потоке; независимые HTTPS chunks читаются шестью потоками с общими защищёнными byte reservations.

Далее используется ранее проверенное ядро:

\[
p_{k+1/2}=A_k+B_k e^{lnsp},\quad
T_v=T[1+(R_v/R_d-1)q],\quad
\Phi_{k-1/2}-\Phi_{k+1/2}=R_dT_{v,k}\ln\frac{p_{k+1/2}}{p_{k-1/2}}.
\]

Primary gas: прежние B3 `Rd=287.05`, `Rv=461.5`; опубликованное ECMWF приближение не смешивается с этим режимом. Давление внутри слоя интегрируется по half-levels с положительным T_v. Арифметическое full-level p и alpha-геопотенциал не объявляются точной point-pair.

Для станции заранее выбираются четыре **геометрически окружающие** native N320 points: две latitude rings и две стороны longitude на каждой ring. Это не два ближайших longitude с одной стороны. Затем допускаются только колонки, чей воздушный интервал содержит целевой геопотенциал. Через грунт и выше верхней границы профиля экстраполяции нет.

P2 multi-column использует фиксированные inverse-squared-distance weights по допустимым колонкам, смешивает T/q на общем воздушном интервале и интегрирует от одного upper ln p anchor. Физическая модель:

\[
T_*=\sum_jw_jT_j,\quad q_*=\sum_jw_jq_j,\quad
\ln p_a=\sum_jw_j\ln p_j(\Phi_a),\quad
\ln p_*(\Phi_*)=\ln p_a+\int_{\Phi_*}^{\Phi_a}\frac{d\Phi}{R_dT_*(1+cq_*)}.
\]

Количество соседей или веса не меняются по station residual. Если ни одна native колонка не покрывает barometer height, станция остаётся SOURCE_BLOCKED. В частности, доступная source geometry для Graz показывает, что устранение ошибки высоты само по себе не создаёт недостающую valley atmosphere. Отдельный valley/surface-layer adapter в этот блок не добавлен.

## 3. Исторические высоты AT/DE/CH

OSCAR WMDR XML прочитан непосредственно с официального WMO API [S3]. Выбираются deployment periods, покрывающие обе даты 2021; temperature 5 cm исключается при выборе 2m T. Повтор одного deployment в разных network affiliations не считается независимым прибором.

| Страна / WIGOS | Barometer MSL, m | T/RH instrument MSL, m | Историческая запись |
|---|---:|---:|---|
| AT, `0-20000-0-11290` | **378.8** | **368.7 /368.7** | Pressure deployment с 2002 до 2026-06-30; T/RH с 2002 до 2023-06-28 |
| DE, `0-276-6-399` | **82.5** | **37.8 /37.8** | Barometer deployment с 2016-07-27; T/RH с 2015-07-01 |
| CH, `0-20000-0-06784` | **1595.58** | **1593.93 /1593.93** | Датированные instrument references с 2006-12-13 |

Для AT native GeoSphere metadata показывает `COMBINED id=30` и `INDIVIDUAL id=16412, group_id=30`, единственный individual member этой группы, покрывающий 2021. Новый Heinrichstraße member 16414 начинается в 2022; новый WMO `0-40-0-11291` начинается в 2023 и для 2021 запрещён. Данные combined/individual p, native flags и timestamps дополнительно сравниваются после seal; несовпадение блокирует AT scores, не инициирует выбор более удобного ряда. Если nested geolocation period отсутствует, явно фиксируется наследование периода датированного deployment; оно не подменяется датой текущего snapshot.

Для DE используется **городской** WIGOS `0-276-6-399`, совпадающий с DWD urban station 00399 и эпохой с 2015. Старый `0-20000-0-10389`, закрытый до 2021, не подставляется по одному имени. Barometer coordinates отличаются от T/RH coordinates, поэтому для давления выбирается собственная горизонтальная точка. Высота 35.8 m — station ground metadata, она не заменяет 82.5 m barometer reference. Масштаб 46.7 m высотного различия при 1000 hPa/280 K — около 5.7 hPa; это оценка чувствительности, не доказанная декомпозиция старой ошибки B4.

Для CH нынешнее CSV значение 1596 m подтверждено более точным датированным instrument altitude 1595.58 m. T/RH имеют собственные координаты. **В geospatial instrument altitude AGL уже учтена**: к 1593.93 m или 37.8 m нельзя снова прибавлять 2 m. Отдельное AGL поле сохраняется для reference/selection, а не складывается повторно с absolute altitude.

WMO observed-variable 12249 означает RH with respect to water; этот код установлен для исторических RH deployments всех трёх стран. Это новый источник определения, не ретроспективное переписывание прежних отчётов. Полная pressure enhancement/measurement uncertainty модель этим кодом не устанавливается.

Подтверждены **датированные MSL ссылки в metadata**. Преобразование национального height datum в ERA5 geopotential datum отдельно не сертифицировано. Для этого пилота объявлена постоянная-g0 аппроксимация `Φ*=g0·height_MSL`; этот статус сохраняется в результатах. Она не даёт production qualification.

## 4. Замороженный сравнительный пилот

Даты: 1 февраля и 1 августа 2021, по 24 target hours каждой страны. Это уже раскрытые development dates, не новый независимый holdout. 144 expected station hours, **24 country/day/method score cells**. Алгоритм детерминированный; повторения с seed не выдаются за новые независимые измерения.

Основной native профиль: уровни 124…137, четырнадцать нижних слоёв. Предварительные 130…137 достигали у единственной нижней CH колонки только H≈1414.68 m при barometer 1595.58 m. Глубина изменена по source-only геометрии до получения любого matched station error; причина сохранена в protocol design-amendment journal. Дополнительная глубина 109…137 проверяется только в двух зарегистрированных control hours; изменение верхнего anchor публикуется как sensitivity без выбора по station errors. Отказ дополнительного deep source не стирает уже вычисленное primary prediction.

Предварительно объявлены четыре метода:

1. P1 isothermal, ближайшая допустимая native колонка и её surface anchor.
2. P1 fixed Γ=0.0065 K/m, тот же single-column anchor и target-layer T/q proxy.
3. P2 single column, та же ближайшая допустимая колонка, с её настоящими слоями T/q.
4. P2 up to four columns, общий воздушный интервал и один weighted ln p anchor.

P1 сравнивается с P2 при одинаковых исходных опорах. Недопустимая подземная колонка не создаётся для заполнения AT. Давления всех методов записываются и SHA-sealed **до** доступа к station observation products. Сначала обязательно проходят raw-GRIB lineage controls; при их блокировке observation scoring не открывается. Если исторические sensor references страны не установлены, её observation source также не открывается, а score cells остаются в знаменателе.

Наблюдения pressure-only: AT `p` и исходные good flags, DE исходное **P0_ST_10**, CH `prestah0`. DE PP_ST_10 — MSL pressure — исключено из station truth. Геометрические ссылки barometer/thermo отдельно сохраняются; полная provider pressure processing/uncertainty модель не объявляется независимо квалифицированной.

Временные операторы фиксированы заранее:

- AT: provider 1h с прежним node proxy; точный интервал этого ряда остаётся несертифицированным.
- DE: исходный HH:00 instantaneous pressure; native QN сохраняется, пустой QN не объявляется final QC.
- CH: preceding-hour mean/end stamp с заранее объявленным trapezoid proxy `(p[h−1]+p[h])/2`. Дополнительно вычисляются 23:00 31 января и 31 июля: всего 50 source-hour profiles для 48 validation hours. Missing boundary node не заполняется.

Публикуются MAE, bias, RMSE, max absolute error, coverage и парные изменения на **одинаковых** часах. Gate прежний: MAE≤2 hPa при coverage≥90%; PASS_THIS_REVEALED_CELL не означает независимую квалификацию. Если хотя бы одному методу не хватает данных, это отражается в coverage и общей парной выборке. Raw station values не выгружаются в public artifact.

## 5. Исполнение, затраты и следующий допуск

Новые модули `p9_3b3_native_sources/heights/columns/validation/run.py` и три test modules отделены от прежнего P1/P2/C2. `p9_3b3_native_protocol.json` фиксирует 58 scientific hashes, даты, candidate set, geometry, time operators и ресурсы.

```bash
python -m pip install numpy==2.3.5 scipy==1.17.0 numcodecs==0.16.3 pyshtools==4.13.1 eccodes==2.50.0 eccodeslib==2.50.0.33
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s research/ige_cmip6 -p 'test_p9_3b3_*.py' -q
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -u research/ige_cmip6/p9_3b3_native_run.py --stations --private-cache inputs/private-native-cache --out outputs/native-pressure-new-run
```

`--cache-only` выполняет аудит уже полученных bytes без HTTP. Выходной каталог не перезаписывается; private cache нельзя размещать внутри public output.

Ограничения полного pilot: **2 GiB нового сетевого трафика**, 2000 requests, 80 MB/object и 80 MB/decompressed chunk, socket timeout 20 s. Шесть параллельных читателей делят один счётчик и резервируют bytes до загрузки; сумма download+reservations ограничена тем же бюджетом. HTTP range responses проверяются до тела. После ошибки резерв освобождается; cached objects также ограничены размером до чтения.

Один native T chunk — 1,640,960 bytes, q — 2,168,320 bytes после распаковки. Для 50 source hours ×14 уровней T/q суммарно распаковывается около 2.667 GB; два deep controls добавляют около 0.114 GB T/q, поверхности — около 0.164 GB. Это суммы последовательно обработанных chunks, не требуемый resident RAM. Сжатый сетевой объём измеряется отдельно. Для CI установлен wall timeout 45 min; фактическая стоимость ещё должна быть проверена по завершённому run, не экстраполирована из неполного локального расчёта.

Локально до отказов сети получены все четыре original-GRIB controls и все sensor histories, часть profiles. Остальные запросы вернули `Tunnel connection failed: 403 Forbidden`. Полный accuracy pilot поэтому передан в новый GitHub Actions workflow; локальные нулевые coverage cells не выдаются за отрицательную/положительную точность модели. Cache-only verification воспроизводит уже полученные source evidence и контракты, сохраняя missing-source blockers.

После CI необходимо проверить artifact digest, tested-commit hashes, все 24 score cells, coverage/парные часы и отрицательные результаты. Только затем фиксируется verified audit и workflow переводится в manual-only. Для AT при отсутствии воздушной native колонки следующий отдельный математический блок — valley/surface-layer adapter с заранее объявленными допущениями. Старый Davos T-donor certificate, NASA temporal bounds, C2 correction budgets и полноценная совместная T–p–q–RH квалификация этим pressure pilot не закрываются. main не изменяется; merge не выполняется.

## Первичные источники

- [S1: ARCO catalogue и native CO lineage](https://github.com/google-research/arco-era5); конфигурации [surface geopotential](https://github.com/google-research/arco-era5/blob/main/raw/monthly/era5_ml_zs.cfg), [lnsp](https://github.com/google-research/arco-era5/blob/main/raw/monthly/era5_ml_lnsp.cfg).
- [S2: ECMWF spherical harmonic ordering and normalization](https://confluence.ecmwf.int/spaces/UDOC/pages/188034345/How+to+access+the+data+values+of+a+spherical+harmonic+field+in+GRIB+-+ecCodes+GRIB+FAQ); [SHTOOLS MakeGridPoint](https://shtools.github.io/SHTOOLS/pymakegridpoint.html).
- S3: WMDR XML — [Graz 11290](https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-11290), [Berlin city climate 399](https://oscar.wmo.int/surface/rest/api/wmd/download/0-276-6-399), [Davos 06784](https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-06784); [WMO observed-variable table](https://github.com/wmo-im/wmds/blob/master/tables_en/1-01-01.csv).
- [GeoSphere historical hourly native metadata](https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata); DWD/MeteoSwiss original source URLs и SHA — в machine-readable results и frozen protocol.
