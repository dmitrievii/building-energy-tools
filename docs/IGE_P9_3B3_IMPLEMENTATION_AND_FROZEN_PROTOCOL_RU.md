# P9.3B3 — реализация pressure-conditioned T–q–RH closure

Дата: 20.10.2026. Исследовательская ветка `research/ige-p9-3b3-t-p-q-rh-closure-20261020` от `8dc2de733b82eaa2d8269161775450a01e3df236`. `main` и все существовавшие Python/отчёты остаются неизменными. Merge не выполняется.

## Реализованное поведение

- Исходный `tas` CanESM5/NEX, производный от Tmin/Tmax, проверяется как midrange. Временная средняя T — отдельный оператор, используемый только для подтверждённого `TIME_MEAN_TAS` либо явно построенного coherent test.
- Термодинамическое состояние T[K], абсолютное p[Pa], q[kg/kg]. RH/e/Td — производные. Murphy & Koop 2005, eq.7/10, с отдельными water/ice policies. Buck и константа `.62198` сохранены в явно обозначенном legacy comparison mode.
- Внешнее pressure reference неизменно и содержит source/frame/QC/неоценённую uncertainty. B4 остаётся неквалифицированной. Native high-frequency GCM pressure mode закрыт до появления аутентифицированного адаптера; невозможно выдать внешнее ERA5 давление за восстановленный CanESM5 `ps_day`.
- DWD: hourly `P0`, urban `P0_ST_10`, subdaily `PP_TER`. Морские `P`/`PP_ST_10` не подставляются вместо пропусков. Нативные QN и отсутствие QN сохраняются.
- Совместный solver изменяет T/q в пределах заранее выбранного температурного prior ±2 K, сохраняя source extrema, нужный температурный оператор и mean q/RH. p не является переменной оптимизации.
- Fixed-T/p feasibility: явный q/RH witness; глобальный KKT RH maximum; MILP secant lower bound для минимума RH. MILP timeout — UNRESOLVED. Для подвижной T используется консервативный monotone-box q-capacity certificate; если он не доказывает невозможность, локальный отказ не считается доказательством. Более сильный новый LP chord certificate пока не реализован, старый LP сохранён без изменений.
- Screening всех допустимых same-month/wet-dry donors, NLP не более чем для 8 source-ranked кандидатов. Полная невозможность не утверждается по восьми проверкам, если остальные не покрыты.
- Отдельная lexicographic **local** reconciliation: mean-q error, затем mean-RH error, затем shape. Modified targets журналируются; нет утверждения глобальной оптимальности или калиброванного correction budget. Производственный допуск false. Если secondary search находит точный исходный witness, он помечается как exact, без ложного source-modified.
- Независимый scalar validator повторно вычисляет психрометрию без импорта основного thermodynamic core. CLI запрещает перезапись существующего output directory.

## Обновлённые доказательства источников

После планирования удалось прочитать **точные NEX-GDDP v2.0 CanESM5 historical 2013 DAP DAS headers** `hurs/huss`. Они подтверждают `cell_methods=area: time: mean`; `hurs.comment` прямо указывает воду T>0 °C и лёд T<0 °C. Сохранены native attributes, tracking ID, SHA header и URL в `p9_3b3_source_semantics_evidence.json`.

Явных time bounds в этих headers нет. Заголовок `tas` в двух ограниченных попытках остался HTTP 500/503. Поэтому происхождение midrange tas опирается на NASA 2022 Table 1 и архивные 730 суток с зарегистрированным CSV SHA, а полная source-time semantics остаётся PARTIAL. Равенство полю с documented processing не доказывает истинную временную среднюю. Никакие старые значения или результаты не переписываются.

## Локальная проверка

Полный новый набор: 55 тестов — PASS. Включены source/operator contracts, нижняя область ice equation, joint feasibility, независимый validator, frozen scoring и одинаковая временная выборка bootstrap.

Проверены также 14 прежних P9.3A, 50 P9.2, 8 pressure-model tests и B2D source-field contracts — PASS. Новые feasible oracle tests включают 20 независимых constructed states, обязательную joint-temperature reconstruction, known-impossible conditions, vertex enumeration против MILP bounds, q/e inverse и published reference values. Отказ на обязательном feasible oracle — FAIL.

Синтетический development benchmark: 28 аналитических кривых, N=24/48/96; refinement gate пройден на этих кривых. Максимальное различие Tmin/Tmax между 24/96 узлами 0.01103 K; RH mean около 7.1e-15 п.п.; q mean около 1.6e-17 kg/kg. Все 84 заранее фиксированных pressure stress cases (−500/0/+500 Pa) дали exact defined-operator witnesses. Это **не наблюдаемая погода, не uncertainty interval и не доказательство для всех климатических рядов**.

## Регрессии и научная проверка

`p9_3b3_regression_audit.py` читает существующий registered P6 архив, проверяет SHA и прежние canonical ERA5 donor digests. Старые baseline выполняются как P9.2D 2013 и P9.3A 2014; ожидаемые числа с граничными сутками: 360/366 и 351/366. При изменении baseline запуск завершается ошибкой. Изменения выводятся в новые файлы.

Аblations зарегистрированы до нового scoring: L1 affine/Buck capacity-only; L2A joint/Buck; L2B joint/Murphy–Koop; L3 joint/source water–ice. Так joint optimization, saturation formulation и reference phase различаются явно. L1 считает **только q-capacity**, не выдаётся за exact q/RH reconstruction. Reconciliation — отдельный результат. Годы 2013/2014 остаются уже раскрытыми регрессиями; коэффициенты по ним не выбираются.

`p9_3b3_frozen_protocol.json` фиксирует один station cohort: AT Graz30, DE Urban00399, CH DAV; 01–14.02.2021 и 01–14.08.2021, 2016 ожидаемых site-hours до QC. Donors 2019/2020, основной seed 7313, sensitivity seeds 7314–7317. Учитывается прежнее изучение иных 2021 окон/переменных; не утверждается, что весь год или эти станции никогда не скачивались.

Сначала source-only preflight (schema, SHA, coverage, QC), затем генерация без station values, SHA-seal predictions и только затем scorer. Недоступный source остаётся blocked, без подстановки другой станции/года/морского давления. Отдельно coherent ERA5 daily reconstruction и station comparison. Daily control получает те же diagnostics; full-hourly ERA5 — более богатый reference. Истинные события CanESM5 не сопоставляются с реальными днями как weather forecast.

Swiss hour-end observations сравниваются с заранее заданной trapezoid approximation предыдущего часа; это приближение, не выбранный лучший lag. AT interval semantics остаются явно неполностью квалифицированными. В производных station e/q используется объявленная water reference, а отсутствие единой provider-phase/QC certification ограничивает научное утверждение. Все 480 ожидаемых method/seed/site-season-variable ячеек остаются в scorer, даже если источники недоступны. Bootstrap использует одинаковые часы обеих моделей, затем агрегирует по дням.

## Известные ограничения реализации

1. 24 representative-node solver; refinement benchmark относится только к зарегистрированным аналитическим кривым. Универсальная subhourly qualification реальной погоды не выполнена.
2. Reconciliation — локальный кандидат, без certified global lexicographic optimum. Source-error covariance не выдумывается.
3. Предыдущие Tmin/Tmax indices и shape bounds — declared donor prior. Пропущенное решение вне этого prior не доказывает физическую невозможность атмосферы.
4. Новые термодинамические states ещё не заменяют все поля существующего joint weather generator. Radiation/cloud/rain/LW после новой T/RH не переквалифицированы; EPW не выпускается.
5. Для неизменённого limited P9.2B/C pilot добавлен replay исходных 28 суток 2013/2050 из двух registered архивов. Проверяются прежние B=27/28, C=28/28 и C joint q/RH=17/28. Без аргумента future archive этот отдельный replay явно NOT RUN; CI передаёт оба архива.
6. Независимый scorer преднамеренно не повышает общий status выше `INCONCLUSIVE_SOURCE_SUPPORT_AND_LIMITED_COHORT`: pressure generalization, равный native QC и provider phase/support всех трёх стран не установлены. Численные результаты и non-inferiority diagnostics всё равно сохраняются.

## Запуски

```bash
python -m unittest discover -s research/ige_cmip6 -p 'test_p9_3b3_*.py' -v
python research/ige_cmip6/p9_3b3_development_benchmark.py --out <new-file.json>
python research/ige_cmip6/p9_3b3_run.py --mode strict --manifest <input.json> --out <new-dir>
python research/ige_cmip6/p9_3b3_run.py --mode reconcile-research --manifest <input.json> --out <different-new-dir>
python research/ige_cmip6/p9_3b3_regression_audit.py --original-canesm5-registered-zip <registered.zip> --out <new-dir>
python research/ige_cmip6/p9_3b3_at_de_ch_validation.py --cache <private-cache> --out <new-public-aggregate-dir>
```

Зависимости: Python 3.12, NumPy 2.3.5, SciPy 1.17.0. GPU не нужен.

Исследовательский CI имеет один initial push trigger только для регистрации этого нового протокола в этой новой ветке и `workflow_dispatch`. Обычные code pushes не запускают научный scoring заново. Это технический bootstrap первого запуска; после получения результатов workflow следует оставить manual-only. Длительные запуски не опрашиваются в цикле: сообщаются branch/commit/run, далее результат проверяется по сообщению пользователя.

## Раздельные статусы

| Утверждение | При первой реализации |
|---|---|
| Корректность кода | Локальные тесты пройдены; CI ожидается |
| Физическая допустимость | Подтверждена на synthetic oracles, для каждого реального результата проверяется отдельно |
| Exact NASA source closure | Требует результатов annual census и учитывает PARTIAL time semantics |
| Независимая точность | Новый station run ещё не завершён |
| Давление B4 / universal site pressure | NOT QUALIFIED, отрицательный B2D сохранён |
| Реальный native future daily ps | NOT RECOVERED |
| Эксплуатационная готовность / production EPW | false |

Первичные references: [NASA 2022](https://doi.org/10.1038/s41597-022-01393-4), [NEX v2 Tech Note](https://www.nccs.nasa.gov/wp-content/uploads/2025/06/NEX-GDDP-CMIP6-v2-Tech_Note.pdf), [Murphy & Koop 2005](https://doi.org/10.1256/qj.04.94), [DWD hourly pressure v24.03](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/DESCRIPTION_obsgermany_climate_hourly_pressure_en.pdf). B2D scientific erratum имеет приоритет над старой текстовой семантикой `P/P0`.
