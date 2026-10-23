# P9.3B3-NV2: реализация и границы проверки

23 октября 2026. Предварительная регистрация: commit `cdc25a87ae237ccdfc584e694c06358e1a40efe4`, protocol `p9_3b3_nv2_protocol.json`. Его canonical SHA256 `4e00ddbb585ceeb1f93feaa7d033081b1c2ff22427a2e82cc98302f77df9b004`; SHA256 bytes `3c2101732cc310c07ce5c79f2805fe3b0cc1561e2c4da0319e4cc858e65ce363`. Ветка `research/ige-p9-3b3-nv2-terrain-pressure-20261023` основана на утверждённом roadmap. Новые scores не использовались для выбора donor, радиуса, формул или gate.

## Что реализовано

| Новый модуль | Поведение |
|---|---|
| `p9_3b3_nv2_geometry.py` | Полный каталог в объединении R≤50 km вокруг pressure, temperature, RH_water; два контроля поверхности; фиксированные donor slots; distances, margins, причины отказа, 2 m sensitivity, first moment и convex-hull support |
| `p9_3b3_nv2_columns.py` | Адаптер frozen native reader; допуск по каждому прибору и часу; три метода на одной native surface anchor; строгий двухколоночный blend; отдельный старый G0 |
| `p9_3b3_nv2_validation.py` | Все 26 NV2 score cells и все 54 попарных сравнения, включая пустые; пересчёт MAE/RMSE на пересечении часов; одинаковая truth для NV2/G0; проверка hashes до и после observation I/O |
| `p9_3b3_nv2_run.py` | WMDR-only refresh исторических датчиков; 50 source hours; source-only geometry до T/q; экспорт всех primary profiles; seal шести source products; scores после seal; manifest ресурсов/статусов; отказ от перезаписи output |

Исторические provider identities сохранены отдельно в `p9_3b3_nv2_dated_sensor_references.json`, с привязкой к проверенному артефакту Work. Это позволяет не загружать содержащий наблюдения DWD ZIP для чтения географии до prediction seal. Перед опытом WMDR читается заново: геометрия и эпохи должны совпасть с frozen references, новый XML hash сохраняется. Pressure products скачиваются только после seal.

Старые реализации не редактировались. Новый protocol проверяет SHA256 **80** прежних scientific Python/protocol/result files; отдельный guard не позволяет незаметно изменить дизайн NV2. Новые T/q/pressure profiles и scores сохраняются новым запуском в новом output directory. Наблюдения не являются аргументами source predictor. Старые 2013/2014 результаты не пересчитываются с целью подбора параметров.

## Проверено локально

**323 теста PASS**: 251 B3 tests (включая 32 новых NV2 и 6 NV1), 14 P9.3A, 50 P9.2, 8 B2. Canonical DWD script: `P93B2D_ORIGINAL_PRESSURE_FIELD_SEMANTICS_CONTRACTS_PASS`. Все 80 SHA совпали. Workflow YAML прочитан и проверен; секреты и observation cache в artifacts не включаются.

Математические checks включают независимую аналитическую isothermal формулу, численную quadrature для P1 lapse, независимое произведение layer pressure ratios для 12 stratified profiles и аналитический common-top blend. Полный 50-hour runner выполнен на synthetic source profiles с реальным NV2/G0 predictor и подставной validation truth; проверены strict JSON, seals, role-specific refusal и оба score census. Failure checks включают Graz D1 ниже T/RH, отсутствие D2 без перенормировки blend, несовпадающее время/gas, верхнюю границу, CH boundary, разные paired-hour supports, изменение sealed geometry/profiles/predictions до I/O и изменение после I/O.

Пустой source-only cache проверен через реальный CLI без сети: сохраняются все 50 заблокированных prediction hours, 26 NV2 и 24 G0 cells, manifest с нулём обработанных source hours; процесс возвращает ненулевой статус. Это корректное выполнение scientific refusal, а не успешное восстановление данных. Успешный технический статус отдельно не требует физического допуска каждого target: геометрические отказы остаются в denominators и журнале.

Локальное подтверждение тестов: `research/ige_cmip6/p9_3b3_nv2_local_contract_results_20261023.json`. Оно содержит hashes тестируемого Python, версии зависимостей, counts и durations; не содержит новых pressure scores. Полный расчёт 50 T/q profiles локально не выполнялся: для этого предназначен новый CI job.

На реальных источниках отдельно выполнен source-only census до T/q и pressure observations, затем точный cache-only replay его JSON. WMDR semantic identity подтверждена для всех трёх стран. В объединении приборных R≤50 km найдено **AT 8, DE 7, CH 9** точек; выгружены все, включая отказы. Fixed donors: AT D1 index 74588, D2 73689; DE D1 57155; CH D1 73673. Graz split admission подтвердился. У DE D1 surface H=37.2940581 m находится всего на **0.5059419 m ниже T/RH** 37.8 m: nominal lower-bound проходит, 2 m sensitivity не проходит. Это существенное ограничение datum/surface-layer интерпретации, без изменения выбранного donor. У CH D1 поверхность 1206.8191589 m; hourly top ещё проверяется полным CI. Результат: `p9_3b3_nv2_local_source_geometry_20261023.json`; этот небольшой опыт не является новым тестом pressure accuracy или полной original-GRIB lineage проверкой.

## Запуск и чтение результата

```bash
python -u research/ige_cmip6/p9_3b3_nv2_run.py --stations \
  --protocol research/ige_cmip6/p9_3b3_nv2_protocol.json \
  --private-cache inputs/private-NV2-source-cache-DO-NOT-UPLOAD \
  --out outputs/NV2-revealed-research-pressure-pilot
```

Output должен отсутствовать; `--cache-only` запрещает сетевой fallback. Режим без `--stations` также обрабатывает все 50 source hours, сохраняя source-only предсказания и пропуская pressure observations. Если технические prerequisites не выполнены, результаты отказов сохраняются до exit 1.

Новый workflow `ige-p9-3b3-nv2-terrain-pressure.yml` содержит два job: сначала все mathematical/source contracts, затем source/profile/sealed-score pilot. Scoped push действует только на новую NV2 branch и protocol/workflow paths; обычный push Python не запускает незарегистрированный эксперимент. Предусмотрен `workflow_dispatch`. Лимиты пилота: 45 min CI, 3 GiB body downloads, 2000 requests. Прежний полный Work потребовал около 2.2 GB, 1661 requests; новая геометрия не добавляет глобальные T/q chunks, но увеличивает число point syntheses. Фактические новые затраты берутся из manifest.

При аудите CI последовательно проверить:

1. Tested commit/protocol/code SHA; tests; 80 protected hashes; original GRIB z/lnsp float32 identity; датчики 3/3.
2. Полный source-only radius catalogue, фиксированные D1/D2, 50/50 primary hours и explicit blockers. Не путать завершённые профили с допуском всех приборов.
3. По экспортированным profiles независимо воспроизвести hydrostatic layer residuals, target pressures и одинаковые anchors P1/P2. Отдельно проверить deep sensitivity и G0, сохраняя прежние результаты.
4. Все 26 NV2 и 24 G0 score cells; boundary nodes/paired hours; правильный DWD P0_ST_10; hashes и raw observation replay. Не выбирать победителя по разным часам.
5. Сравнить D1/D2 и blend как горизонтальную sensitivity. First moment и donor spread не превращать в calibrated uncertainty. Отсутствие выигрыша P2 принять как допустимый исход.
6. Раздельно вынести code/conditional physics/independent accuracy/operational readiness. Затем переходить к versioned thermodynamic adapter по roadmap; не объединять разный смысл C1/C2 в старых ветках.

## Научные ограничения

Это revealed двухдневный AT/DE/CH development experiment. Ни MAE≤2 hPa, ни CI success не являются независимой квалификацией. Полный 2D gradient из двух Graz columns не определяется. Pressure/T/q на уровне thermohygrometer — native layer state при объявленной MSL→Φ approximation; отдельный station 2m observation operator не реализован. RH saturation и condensate loading не проверяются hydrostatic kernel. T/RH у барометра и thermohygrometer не отождествляются.

B4 остаётся NOT QUALIFIED. Native future CanESM5 ps не восстановлено. Production EPW, API/Climate Analyzer operational release и глобальная проверка не квалифицированы. `main`, Work, NV1 и прежние closure results не изменяются; merge не выполняется. Следующий независимый cohort выбирается только после exposure inventory и preregistration, отдельно от этого CI.
