# IGE P9.2D — Final Original-Source Annual EPW Integration and Conditional EnergyPlus Closure (RU)

**18 октября 2026 г.** Ветка `research/ige-p9-2d-integrated-epw-qualification-20261018`; код основан на замороженном P9.2C `393c39b8`. **Научный/программный аудит выполнен; оригинальный 8760-EPW не сгенерирован, поскольку 6/365 суток не прошли обязательное замыкание. Производственная квалификация остаётся BLOCKED.** `main` не изменён.

## 1. Исходные оригинальные данные, воспроизводимость и окончательная выборка

- [Оригинальный годовой расчёт GitHub Actions #39078876855](https://github.com/dmitrievii/building-energy-tools/actions/runs/39078876855): **3/3 jobs SUCCESS** как строгий аудит; **32/32 offline contracts PASS**: 7 EPW/calendar + 9 P9.2C humidity donor + 16 P9.2B energy/mass. [Исходный научный годовой artifact #12117503460](https://github.com/dmitrievii/building-energy-tools/actions/runs/39078876855/artifacts/12117503460); [архив статуса EnergyPlus #12118216843](https://github.com/dmitrievii/building-energy-tools/actions/runs/39078876855/artifacts/12118216843), explicitly `NOT_EXECUTED` для *реального* файла.
- Original NASA NEX-GDDP-CMIP6 v2 `CanESM5/r1i1p1f1/historical/1995–2014`, source-native noleap 365-day 2013, плюс исходный **2012-12-31** для годовой UTC→CET границы. Оригинальный `joint_daily_raw.csv` SHA256: `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef` — независимо перепроверено против существующего immutable P7C.3 реестра.
- Original ERA5 через Open-Meteo 2019+2020, `models=era5`, nearest grid, `elevation=nan`, timezone GMT. 2019: **365 суток / 8760 часов**, original response SHA `9c7a19d5ae018df41dc6045de4d5cc2e9e8ae37d63e361bad3e079e1d2c97576`; 2020: **366 суток / 8784 часа**, SHA `1b18154ca9f0a774a500a9a4e4dab7744cc1866f590fef36ec1e2db09ee6c4b9`; Open-Meteo returned nearest ERA5 grid (47.0N, 15.5E). Это **ERA5-derived**, не оригинальный ECMWF CDS GRIB.
- Source GCM grid (46.875N,15.375E) и donor nominal city coordinate (47.0707N,15.4395E) **не совпадают**. Из прошлого P9.2C известен негативный исход независимой 2025 станционной T/RH-валидации. Нет повторного настраивания seed или изучения другой страны — только Graz, один исторический год, фиксированная `seed=7313`.

## 2. Оригинальная годовая физика: 360/366 суток допустимы; шесть блокировок

При исходных 366 суточных UTC-входах, включая одну граничную дату из 2012 года:
- **360/366** получили допустимого ERA5 донора и все восемь исходных суточных ограничений: mean/min/max T, native `huss`, native precipitation, native GHI, native LW, native mean wind.
- **6/366** остались без физически допустимого оригинального суточного донора, все в целевом году **2013**; таким образом, для собственно годового 2013 набора **359/365 успешных, 6/365 заблокированных**.
- **267/360** одновременно воспроизвели native daily `hurs` и native `huss`, **58/360** native `hurs` выше математически достижимого максимума для выбранных hourly T/P, **35/360** находятся ниже найденного допустимого low-RH witness (статус остаётся недостаточно классифицированным; это *не* доказанная глобальная невозможность).
- По исходному коду соответствующие кандидаты отклонены именно `P92B_HUSS_EXCEEDS_SELECTED_DONOR_T_P_SATURATION_CAPACITY` (не по solar, wind или LW), полный отчёт сохраняет число отклонённых месячных суточных доноров.

| Заблокированная дата | Отклонённых original ERA5 wet/dry donor days | Физическая причина |
|---|---:|---|
| 2013-02-14 | 19 | Native `huss` выше `mean q_sat` при выбранном донорском T/P |
| 2013-02-21 | 19 | Аналогично |
| 2013-07-09 | 40 | Аналогично |
| 2013-11-19 | 26 | Аналогично |
| 2013-12-11 | 32 | Аналогично |
| 2013-12-15 | 32 | Аналогично |

**Fail-closed решение:** полноформатный NASA/ERA5 совместный 8760 EPW **не выпускается**, если исходные 365+boundary суточные состояния не полны. Не заполнять запрещённые шесть дней оригинальными 2013 ERA5, синтетическим солнечным климатом или случайными соседними режимами. Реальный годовой EnergyPlus на этом файле **не выполнен**, поскольку файла корректно нет. CI SUCCESS свидетельствует о соблюдении отказа, **не** о 8760 производственной готовности.

## 3. Отдельный original-source научный аудит `huss` × температуры × давление

[Original NASA native daily saturation source audit Actions #39079305200](https://github.com/dmitrievii/building-energy-tools/actions/runs/39079305200) — **2/2 jobs SUCCESS**, **5/5 дополнительных термодинамических тестов PASS**. [Source-derived pressure envelope artifact #12117978708](https://github.com/dmitrievii/building-energy-tools/actions/runs/39079305200/artifacts/12117978708), оригинальный исходный SHA подтверждён.

Использована модель: для **гипотетического постоянного давления P** в течение суток, при заданных нативных `Tmin ≤ T_h ≤ Tmax` и `mean(T_h)=tas`, при выпуклом `q_sat(T,P)` верхнюю границу среднесуточной допустимой специфической влажности задаёт хорда между `q_sat(Tmin,P)` и `q_sat(Tmax,P)` с весом `w=(tas-Tmin)/(Tmax-Tmin)`. Истинный почасовой профиль и источник давления могут накладывать более строгие ограничения; выпуклость проверена численно на исходных температурных интервалах. **В исходном девятипеременном NEX-GDDP файле нет собственного `ps`**, поэтому никакое рассмотренное P не объявляется измеренным или родным давлением GCM.

| Условное постоянное P | Число 2013 native days, где source `huss` выше даже верхней хорды (из 365) |
|---:|---:|
| 90 кПа | 0 |
| 92.5 кПа | 2 |
| 94 кПа | 5 |
| 95 кПа | 7 |
| 97 кПа | 9 |
| 100 кПа | **20** |
| 101.325 кПа | 23 |

Для шести исходно заблокированных суток рассчитаны **гипотетические максимальные P**, ниже которых upper-envelope-mass ещё мог бы быть физически достижим **для некоторого распределения T**, с теми же нативными Tmean/min/max. Это **не оптимальное/калиброванное давление для генератора**:

| Дата | Условный верхний P, кПа |
|---|---:|
| 2013-02-14 | 92.673 |
| 2013-02-21 | 94.642 |
| 2013-07-09 | 93.938 |
| 2013-11-19 | 90.083 |
| 2013-12-11 | 93.276 |
| 2013-12-15 | 90.953 |

Эти значения объясняют, почему перераспределение влажности по имеющимся донорским профилям не решает универсально проблему. **Они НЕ доказывают ошибку NASA/CanESM5**, потому что pressure, исходная частота временного усреднения `tas/huss/hurs` и источник hourly ERA5 local T/P различаются; не подменять исходное `ps` «подобранным» `P`.

## 4. Экспортёр EPW — инженерные контракты PASS, но НЕ на исходном полном годе

Новый `p9_2d_annual_cet_epw_export.py` проверяет исходные 12 метеорологических полей, 8 обязательных EPW-header строк, **365×24=8760** почасовых записей, **35 полей**, часы EPW 1–24 / minute 60, фиксированный `CET UTC+1` без DST. 1 января 2013 года 00–01 CET строго привязан к **2012-12-31 23:00 UTC**; последнее начало часа года — **2013-12-31 22:00 UTC**. Преобразование GHI W/m²→Wh/m² на часовом интервале и DHI/directH/DNI, psychrometric dewpoint, wind, precipitation depth-hours, total sky cover и longwave проверено численно.

Opaque sky cover (EPW N23), iluminance, visibility и иные неизвестные значения остаются missing sentinels. GCM не прогнозирует эти величины через исходный донор ERA5. Навязать ясную opaque sky вместо отсутствующей физики **запрещено**. Оpaque `99` и illuminance `999999` честно блокируют дневную освещённость/часть EPW-сценариев.

Реальная проверка EnergyPlus выполнена **исключительно на двух явно математически синтетических 8760-часовых EPW-контрольных файлах**, НЕ на исходном CanESM5 P9.2D. Оба фактически прочитаны EnergyPlus **26.2.0** с SHA-pinned original upstream binary и официальной 1-zone IdealLoads test моделью; оба 0 Severe, 0 Fatal, 2 Warnings; для каждого есть реальный 8760 Hourly SQL. В фикстурах искусственно добавлено +5°C ко всем температурам: служебная проверка знака чувствительности, а не климатическое сравнение. Аудит/численные итоги: [EnergyPlus synthetic-only artifact #12118541211](https://github.com/dmitrievii/building-energy-tools/actions/runs/39079305200/artifacts/12118541211), маркировка источника `SYNTHETIC_FORMAT_FIXTURE_*_NOT_CMIP6_NOT_ERA5` и в EPW заголовках, и в JSON.

| Synthetic EPW format-control | Real EnergyPlus total heating, kWh | Cooling, kWh | Severe/Fatal |
|---|---:|---:|---:|
| Synthetic baseline offset 0°C | 17,956.68 | 0.00 | 0 / 0 |
| Synthetic warmed offset +5°C | 11,201.53 | 1,699.39 | 0 / 0 |

Оба значения не относятся к реальному Graz или будущему климату. **Реальный P9.2D EnergyPlus на исходном годовом CanESM5/ERA5-климате по-прежнему NOT EXECUTED**, поскольку не создан годовой файл.

## 5. Явное решение по P8.5/P8.6 release gates

| Scientific gate | Outcome |
|---|---|
| Registered native NASA full 2013+boundary source and ERA5 2019/2020 provenance | PASS |
| P9.2C real annual original donor physical admissibility | **BLOCKED 6/366** |
| Genuine original 2013 8760×35 CET EPW generated and original-weather readback | **NOT GENERATED** |
| Original-source native `huss` and `hurs` simultaneously closed | **NOT QUALIFIED**, 267/360 |
| Format 8760 CET, 35 fields, 8 headers, time-zone crossing on purely synthetic test EPW | PASS |
| Official pinned EnergyPlus 26.2 actual simulation on only synthetic exporter fixtures | PASS for format smoke |
| Actual real EnergyPlus 26.2 full-original P9.2D year | **NOT EXECUTED** |
| Independently observed AT DE CH 2025 native measured precipitation/cloud/solar/LW QC skill | NOT QUALIFIED |
| Original P8.5 private licensed 28 P7C.5B byte reread and true 28 EnergyPlus source simulations | BLOCKED |
| Opaque sky, daylight illuminance, future wind direction and pressure qualified by native GCM | NOT AVAILABLE / NOT QUALIFIED |
| Scientifically qualified arbitrary point / global EPW generator | BLOCKED |

**Сформулированная граница P9.2D:** EPW calendar/format converter and synthetic EnergyPlus interoperability **research PASS**; original full annual multivariate weather generation **FAIL-CLOSED / NOT QUALIFIED**. Без исходного натурного `ps`, определения совместимости суточных `huss/hurs/tas` и физически обоснованной joint T-q реконструкции нельзя легитимно закрыть шесть суток. Инженерный выпуск **запрещён**. Не подбирать T/P/seed под известные шесть дней и не нарушать исходные суточные суммы.

Следующий исследовательский шаг — исходно согласованная **pressure-aware joint temperature–water-vapour formulation** с научно оправданными допусками в условиях неустранимо несовместимых GCM daily diagnostics, отдельный заранее зафиксированный независимый год, затем первичная натурная независимая radiation/cloud/rain validation AT/DE/CH и исходные P8.5/P8.6 P0. До научной статьи не расширять мировой coverage. **Не сливать в main. Все workflow — manual only после закрытия.**
