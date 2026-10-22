# P9.3B3: проверенный native CI, неполное покрытие и следующий допуск

Проверен [CI 39753778078](https://github.com/dmitrievii/building-energy-tools/actions/runs/39753778078), tested commit `cca2c8e3255ef34b2498ff5d2581b59e973e510b`. Оба jobs зелёные, но полный сравнительный пилот **не завершён**: из 50 source-hour profiles вычислены 39, одиннадцать летних часов заблокированы сетевым бюджетом. Согласованная native цепочка Φs/lnsp и датированные ссылки на приборы подтверждены. Устойчивого преимущества P2 над P1 в доступной выборке нет.

Старые результаты, protocol и научные формулы сохранены. Текущая ветка — `research/ige-p9-3b3-native-completion-audit-20261022`, основанная на tested commit. main не изменяется, merge не выполняется.

## Что действительно проверено

- Логи двух jobs, точный tested SHA и **277 успешных тестов**: 205 B3, 14 P9.3A, 50 P9.2, 8 B2. Контракт исходного абсолютного DWD pressure — PASS.
- SHA ZIP `8d6ecd929913e0a0601fd3112a0e1d1d738523d57ac2c604edcfb06e22c7ff10` совпадает с GitHub artifact digest. Проверены все семь JSON-файлов, protocol SHA и пять implementation SHA по **git blobs tested commit**. 58 прежних scientific hashes совпали и в tested commit, и в текущем checkout.
- SHA предсказаний одинаков в prediction seal, manifest и scores. Сначала записаны source-only predictions, затем открыты station products; это дополнительно проверено по runner и журналу CI.
- Все 24 country/day/method cells сохранены. Знаменатель — 144 уникальных station hours; совпавших часов **74**, а не 296 независимых наблюдений от четырёх методов. Coverage пересчитан из predictions и CH boundary nodes.
- Четыре original-GRIB→CO controls дают точное float32 равенство всех 410240 коэффициентов каждого поля. Это контроль двух часов, не удостоверение всех T/q GRIB messages.
- Исторические WMDR ссылки покрывают 2021: barometer MSL AT **378.8 m**, DE **82.5 m**, CH **1595.58 m**. T/RH — 368.7, 37.8 и 1593.93 m. AT combined 30 / individual 16412: pressure values, flags и времена совпали точно на обеих датах. DWD truth — **P0_ST_10**; 48 исходных QN имеют значение 3. MSL PP_ST_10 не используется.
- Независимый скалярный расчёт, без импорта production pressure helpers, проверил 696 layer equations и 16 P1/P2 результатов на выгруженных deep columns: максимальный residual **1.001·10⁻¹¹ m²/s²**, расхождение pressure **3.493·10⁻¹⁰ Pa**. Это проверка математической реализации на реальных source columns.

Machine-readable evidence: [p9_3b3_native_verified_CI_39753778078.json](../research/ige_cmip6/p9_3b3_native_verified_CI_39753778078.json). В нём сохранены все score cells, paired differences, sensor references, source controls, file/log hashes и ограничения аудита.

Raw station truth не входит в public artifact, поэтому ошибки по исходным наблюдениям локально заново не рассчитаны. Проверены source parsers, единицы, временная поддержка, coverage, gate logic, метрики по контрактным примерам и арифметика парных aggregate differences. Это не объявляется независимым повтором station truth. Воспроизводимый offline audit:

```bash
python research/ige_cmip6/audit_p9_3b3_native_CI_39753778078.py \
  --evidence-dir /path/to/evidence-39753778078 \
  --out /path/to/new-audit.json
```

Каталог evidence содержит проверенный `artifact.zip`, семь распакованных JSON в `artifact/`, `contracts.log` и `pilot.log` из двух указанных jobs. Output не перезаписывается. Старый GitHub artifact имеет ограниченный срок хранения; хеши и агрегированные результаты сохранены в repository audit.

## Фактическое сравнение P1/P2

MAE в hPa. Летние значения относятся **только к 13 часам**, не к полным суткам; летний gate INCONCLUSIVE_COVERAGE. Даты уже раскрыты: 2021-02-01 и 2021-08-01.

| Страна / день | Совпало / 24 | P1 изотерма | P1 Γ=0.0065 | P2 single | P2 до 4 колонок |
|---|---:|---:|---:|---:|---:|
| AT, февраль | 0 | — | — | — | — |
| AT, август | 0 | — | — | — | — |
| DE, февраль | 24 | 0.158924 | 0.159454 | 0.158928 | 0.214894 |
| DE, август | 13 | 0.338087 | 0.338710 | 0.338703 | 0.326028 |
| CH, февраль | 24 | 0.951103 | 0.768642 | 0.856827 | 0.856827 |
| CH, август | 13 | 0.209566 | 0.340878 | 0.370208 | 0.370208 |

DE single P2 практически совпадает с P1; multi-column зимой ухудшает MAE на 0.055965 hPa. CH fixed-lapse P1 зимой лучше P2 на 0.088184 hPa, летом на имеющихся часах изотерма также лучше P2. Эти числа нельзя использовать для подбора градиента, соседей, weights или выбора победителя на уже раскрытых данных.

В CH допустима единственная колонка примерно в **34.28 km** от датчика, поэтому single и multi совпадают. В AT все четыре native surfaces выше barometer: минимальная H≈395.128 m против 378.8 m. При наличии исходных профилей AT блокируется геометрией, а в одиннадцати оставшихся часах — ещё и source I/O. Это не отрицательная station MAE и не разрешение объявить ERA5 грунт воздухом.

На двух контрольных часах углубление 124→109 изменило single P2 не более чем на 1.90·10⁻¹² hPa; multi DE — на 0.000149 hPa. Это чувствительность к верхней опоре при данном построении, не оценка общей метеорологической неопределённости.

## Техническая причина неполноты и выполненные исправления

Фактически загружено **1,877,424,095 HTTP-body bytes**, 1425 requests; основной runner занял **153.65 s**, peak RSS **493696 KiB ≈482.1 MiB**. Общий job с setup занимает дольше.

Найдены две отдельные причины:

1. До получения Content-Length каждый из шести readers резервировал до 80 MB — ceiling любого object, хотя T/q chunks занимают около 1.57/1.19 MB. Конкурентные reservations вызывали ранние отказы при наличии фактического свободного бюджета. Теперь атомарно резервируется известная длина тела **после headers и до чтения body**. Для неизвестной длины сохранён консервативный предел. Request cap, byte cap, range checks и освобождение reservations при ошибках сохранены.
2. Полный расчёт требует 730 T и 730 q chunks: 50×14 + 2×(29−14). По фактическим сжатым размерам непрочитанных chunks полный объём оценивается в **2,193,978,356 bytes ≈2.0433 GiB**, больше старых 2 GiB. Это оценка, не измерение завершённого run.

Добавлен отдельный `p9_3b3_native_completion_protocol.json` с ресурсной поправкой **3 GiB**, ссылкой на старый protocol SHA и обоснованием по source I/O. Исходный `p9_3b3_native_protocol.json` сохранён побайтно. Guard требует равенства всех научных полей исходному protocol: cohort, уровни, высоты, gas, веса, методы, временные операторы и gates не меняются. Разрешены только новая phase, resource journal и byte budget.

Runner отдельно публикует `source_profile_hours_expected/complete/missing_or_failed` и `engineering_execution_status`. С флагом `--require-complete-sources` неполный primary source run возвращает ненулевой exit code **после сохранения evidence**. Geometric AT blocker и optional deep-diagnostic failure не подменяются ошибкой программы; их научные ограничения остаются явными. Source execution success также не означает прохождения accuracy gates.

Старый workflow переведён в manual-only. Новый `.github/workflows/ige-p9-3b3-native-completion.yml` запускает тот же пилот с completion protocol, сохраняет summary и artifact также при ошибке. Push ограничен новой research веткой и новым resource protocol; после проверки этого повтора следующий audit также должен перевести workflow в manual-only.

Добавлены восемь регрессионных тестов: все шесть реальных тел помещаются при несовместимых ceilings; запрет чтения сверх оставшегося бюджета; truncated-body accounting; неизменность science при resource amendment; разделение geometric/deep blockers и primary failures; observation-source failure; ненулевой CLI exit при неполном source run. Локально **285 PASS =213 B3 +14 P9.3A +50 P9.2 +8 B2**, canonical DWD contract PASS. Ожидаемые затраты повторного CI: около 2.2 GB body traffic, примерно 1661 requests, ориентировочно 3–10 min с setup; жёсткие пределы — 3 GiB, 2000 requests и 45 min для data job. Фактическая полнота и стоимость ещё требуют проверки нового CI.

## Следующий научный блок

Первый допуск — **закончить и проверить этот же пилот**: 50/50 primary source profiles, оба CH boundary nodes, все 24 score cells, DE/CH по 24 часа в обоих днях либо явно обоснованные missing observations. AT geometric blocker сохраняется. Проверить повторный SHA, reproducibility на пересекающихся часах и все отрицательные результаты; ещё не выбирать P1/P2 по двум дням.

Затем нужен отдельный protocol переноса в реальную атмосферу станции и к T/RH датчикам. У DE thermohygrometer на 37.8 m, barometer на 82.5 m и в другой горизонтальной точке: успешный pressure-only pilot у barometer ещё не даёт p для совместного T–p–q–RH. Lowest model layer также не является оператором 2m T/RH.

Кандидаты следующего geometry/surface-layer исследования необходимо заморозить до новых scores:

| Кандидат | Математическая основа | Что может дать | Ограничение |
|---|---|---|---|
| G0: нынешние четыре колонки | Только общий воздушный интервал | Контроль физической допустимости | AT остаётся blocked |
| G1: расширенный source-only stencil | Выбор воздушных колонок по расстоянию и геометрии с заранее заданной областью поиска; один ln p anchor | Может увеличить покрытие без underground extension | Горизонтальная репрезентативность и градиенты требуют отдельной неопределённости; наличие подходящей AT колонки пока не установлено |
| V1: явная новая valley column | Гидростатика от допустимого верхнего anchor с внешними T/q bounds | Условный интервал давления и журнал допущений | Это синтетическая колонка, не native ERA5 air; без независимой T/q информации точечное решение не идентифицировано |
| V2: источник с более мелкой орографией | Собственные согласованные Φs/lnsp и T/q, собственные высоты и временные операторы | Возможный альтернативный физический reference | Источник ещё нужно найти и проверить; сплайс с другой pressure/orography цепочкой не квалифицируется автоматически |

Для V1, если Φa>Φ* и положительная виртуальная температура ограничена Tmin≤Tv≤Tmax:

\[
\ln p_* = \ln p_a+\int_{\Phi_*}^{\Phi_a}\frac{d\Phi}{R_dT_v(\Phi)},\qquad
\ln p_a+\frac{\Phi_a-\Phi_*}{R_dT_{\max}}
\le\ln p_*\le
\ln p_a+\frac{\Phi_a-\Phi_*}{R_dT_{\min}}.
\]

Bounds следует брать из независимой информации о состоянии и её uncertainty, а не подбирать по ошибке Graz. При отсутствии таких данных сохраняется identified interval или blocker. Остатки p, неопределённость datum, высот, пространственного переноса и временных операторов публикуются раздельно. Для AT точный hourly observation interval пока не сертифицирован; CH trapezoid остаётся приближением среднего, а не точной quadrature.

После фиксации geometry/surface-layer и observation operators — новый закрытый AT/DE/CH holdout, с блоками по station/season/time и заранее заданными критериями coverage/MAE/uncertainty. Уже раскрытые 2021 и прежние 2013/2014 остаются development/regression; не становятся независимыми примерами после смены названия модели. Глобальные исследования отложены.

Только затем pressure reference возвращается в суточную NASA closure. Совместная постановка должна использовать собственные временные операторы, поскольку в общем случае

\[
\langle RH\rangle=100\left\langle\frac{e(q,p)}{e_s(T)}\right\rangle
\ne100\frac{e(\langle q\rangle,\langle p\rangle)}{e_s(\langle T\rangle)}.
\]

C2 projection и её журнал не заменяют независимую точность. Старый Davos T-donor certificate, допустимые q/RH correction budgets и NASA temporal constraints этим пилотом не закрыты.

## Разделение статусов

| Уровень | Статус после проверки CI |
|---|---|
| Корректность кода | 277 tested-commit tests PASS; найденная I/O incompleteness исправлена отдельно, 285 local tests PASS; повторный CI ещё требует аудита |
| Физическая допустимость | Условная гидростатика положительной газовой смеси в допущенных воздушных колонках; datum, saturation, condensate и surface layer не квалифицированы |
| Независимая точность | NOT QUALIFIED: два раскрытых дня, неполное лето, AT без предсказаний, преимущество P2 не установлено |
| Готовность к эксплуатации | FALSE; B4 NOT QUALIFIED; production EPW FALSE; native future CanESM5 ps не восстановлено |
