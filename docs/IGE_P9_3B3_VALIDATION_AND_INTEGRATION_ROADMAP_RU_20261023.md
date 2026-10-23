# IGE P9.3B3: план проверок и интеграции после Work/NV1

Дата: 23 октября 2026. Это исполнимый план; новые scientific calculations и изменения Python в рамках его подготовки не выполнялись. Основание — crosscheck `e667f9600aa8efea5d2dce494a8daf5d2a6e3cb9`; main, Work, NV1 и старые результаты сохраняются. Интеграция развивается в отдельных research-ветках; merge не входит в этот план.

**Ближайшая реализация — NV2: source-only admission по каждому уровню прибора и парное P1/P2 pressure reconstruction.** Следом — единый thermodynamic adapter, интегрированный research generator, регрессионный прогон и одна заранее зарегистрированная независимая проверка AT/DE/CH. Исследовательское программное соединение модулей начинается до квалификации; эксплуатационный допуск зависит от независимых результатов.

## 0. Текущая база и развилка реализаций

Проверено по актуальным GitHub refs при составлении плана:

- Work completion `aebdc005…`: 50/50 native source profiles, 285 tests в CI 39757573033; независимый raw-score replay подтвердил pressure metrics. Pressure MAE DE/CH соответствует development gate, AT в старом stencil blocked; это два раскрытых дня.
- NV1 release `a8f9c358…`, tested `bd6f200d…`: 6 source-only tests; в R≤50 km две Graz колонки проходят нижнюю границу barometer. Из них одна проходит нижнюю границу T/RH. Полных новых hourly T/q/p profiles ещё нет.
- Crosscheck `e667f960…`: старые четыре точки — bracketing stencil; оба новых donor восточнее Graz, target вне их convex hull. Полный горизонтальный gradient из двух значений не определяется.
- Параллельная ветка `research/ige-p9-3b3-joint-tpq-water-projection-20261022`, head `b943d5fb…`: собственная реализация fixed-T/p convex q projection и fail-closed diagnostics. По её отчёту: 11/14 дней 2012 закрывают заданное среднее q; 3/14 blocked; в 6 из 11 среднее hurs вне условных fixed-T/p bounds. Этот план не заменяет отдельный аудит её CI/артефактов и области сертификатов.

**C1/C2 в ветках обозначают разные задачи.** Work C2 может выдавать физически допустимые исследовательские candidates с журналом q/RH corrections и неустановленным acceptance budget. В параллельной ветке C2 — только отказ/диагностика без hourly output. Fixed-T/p q projection не эквивалентна совместному замыканию всех NASA diagnostics. Соединять ветки следует через явные версии математических контрактов, сохраняя обе старые реализации.

## 1. Контракты до объединения кода

Результат: единый versioned protocol, таблица соответствий существующих модулей и три интерфейса:

| Интерфейс | Обязательная информация |
|---|---|
| `DailyClimateConstraints` | original values/units, model/experiment/member/grid/calendar, source SHA; определение tas; time bounds/weights; RH phase; source versus derived diagnostics |
| `PressureTrajectory` | Pa, timestamps, target role/coordinates/height/datum/epoch, anchor, source mode/date, air-domain coverage, active columns/weights, uncertainty interpretation, provenance |
| `ThermodynamicDayResult` | T/p/q/e/RH/Td, requested и achieved diagnostics, state validation, correction ledger, certificates/assumptions, unresolved/source blockers, четыре раздельных статуса качества |

Новые адаптеры используют существующие `PressureReference`, generator `pressure_by_date` и независимый state validator, а не переписывают frozen code. Generation принимает model/reconstruction pressure; station observations остаются validation-only.

Перед общими численными сравнениями фиксируются ε=Rd/Rv, gas constants, saturation formula/version, phase convention, temperature units, averaging operators и tolerances. Например, Work и параллельный projection используют разные thermodynamic formulations; одинаковое имя q или C2 ещё не означает одинаковую задачу.

В Work source evidence для зарегистрированного NEX archive tas отмечен как derived midrange, RH как WATER_ICE, а полная временная поддержка остаётся не подтверждённой bounds. В параллельной реализации используются hourly mean T и Buck-over-water. Это повод проверить определения конкретных файлов, а не автоматически принять любой из операторов. Дополнительное условие hourly mean T=(Tmin+Tmax)/2 нельзя выдавать за требование источника без основания. Фазы наблюдаемого RH и NASA diagnostic также могут требовать разных observation operators.

Приёмка: round-trip units/time/reference checks; отсутствие observed-pressure leakage; невозможность смешать несовместимые roles/epochs; cross-formulation comparisons с явными версиями. Неустановленная семантика сохраняет статус conditional/source-blocked, а не автоматически verified.

## 2. NV2 — давление и допуск native колонок

### NV2.1: геометрия до station scores

Зарегистрировать R≤50 km как source-only решение по NV1; политику фиксированных donors A/B, weights и обработки missing profiles. Для каждой страны и роли отдельно формировать:

\[
I_s(t)=\{j:d(\mathbf r_j,\mathbf r_s)\le R,
\ \Phi_{sj}\le\Phi_s\le\Phi_{top,j}(t),\quad
T_j,q_j,p_j\text{ complete and valid}\}.
\]

Для Graz: barometer 378.8 m, T/RH 368.7 m; поверхности 372.5593 и 339.8641 m. Первая проходит только barometer lower boundary; вторая — обе lower boundaries. Высоты — датированные instrument MSL references с прежней явно объявленной datum approximation. Nominal 2m buffer не заменяет uncertainty datum/height.

Старый окружающий stencil сохраняется как G0 regression. Подземное продолжение, выбор по pressure residual и молчаливая подмена другой станцией запрещены. Публикуется полный каталог проверенных candidates, а не только первые пять: coordinates, d, Φs, margins для всех roles, причины каждого отклонения.

### NV2.2: одинаковые опоры для сравнения P1/P2

Primary candidates: P1 isothermal, P1 fixed Γ=0.0065 K/m и P2 native layer integration **отдельно для каждого фиксированного допустимого donor**. В каждой паре одинаковы donor, anchor p/Φ, target, gas formulation и temporal operator. Blended P2 — отдельный sensitivity candidate с заранее заданными weights и common-air anchor. Точный список методов и всех country/day/method denominators фиксируется в protocol до scoring.

\[
T_v=T[1+(R_v/R_d-1)q],\qquad
\ln p_*(t)=\ln p_a(t)+\int_{\Phi_*}^{\Phi_a}
\frac{d\Phi}{R_dT_v(\Phi,t)}.
\]

При two-column transfer публикуется первый момент m1=Σwj(rj−r*). Он не равен нулю для найденных Graz donors; проверка геометрии не определяет весь 2D pressure gradient. Donor spread — sensitivity, не calibrated confidence interval. Pressure gradient следует сравнивать на одном физическом уровне, а не между surface pressures на разных высотах.

Пилот остаётся прежним: 2021-02-01 и 2021-08-01, AT/DE/CH, плюс CH boundary nodes. Эти данные раскрыты. Источник Φs/lnsp — та же native цепочка; T/q — согласованные hybrid levels. Предсказания и SHA записываются до доступа к station products. DWD absolute/reduced mapping определяется конкретным продуктом; urban truth — P0_ST_10.

Приёмка: 50/50 planned source hours либо explicit source failure; per-role air-domain checks; независимые hydrostatic/analytic oracles; полный census cells и paired-hours comparison. Для pressure development сохраняются MAE≤2 hPa и coverage≥90%; прохождение не означает независимой квалификации. Отсутствие преимущества P2 — допустимый научный исход; сложность не становится критерием выбора.

### NV2.3: ссылка на thermohygrometer

Reconstruct p/T/q на координатах и уровне T/RH отдельно от barometer validation. Для DE учесть 44.7 m и около 266 m разнесения, для CH — 1.65 m. p у thermohygrometer не объявлять напрямую измеренным barometer truth. Native state на 28.84 m над model terrain не становится 2m observation operator над реальным station ground.

Приёмка: явный surface-layer/vertical mapping или ограниченный conditional status; одинаковая временная поддержка state и наблюдений. RH_water convention и instrument epochs прослеживаемы. q, полученная из измеренных T/RH и восстановленного p, — derived diagnostic с propagated uncertainty, не независимое прямое измерение q.

## 3. Совместная T–p–q–RH модель

Первый интегрируемый режим — условный при независимо заданной PressureTrajectory. Оптимизировать p ради устранения несогласованности huss/hurs нельзя. Полностью coupled hydrostatic вариант потребует отдельного вертикального профиля и пересчёта transfer с изменёнными T/q при фиксированном внешнем anchor; pointwise vapor closure сама по себе этого не доказывает.

\[
e_h=\frac{p_hq_h}{\varepsilon+(1-\varepsilon)q_h},\qquad
RH_h=100\frac{e_h}{e_s(T_h;\mathrm{phase})},\qquad
0\le q_h\le q_{sat}(T_h,p_h;\mathrm{phase}).
\]

\[
\mathcal A_T[T]=D_T,\quad \mathcal A_q[q]=D_q,\quad
\mathcal A_{RH}[RH]=D_{RH};\qquad
\mathcal A_{RH}[RH]\ne100\frac{e(\mathcal A_q[q],\mathcal A_p[p])}
{e_s(\mathcal A_T[T])}\ \text{в общем случае}.
\]

Операторы относятся к конкретным source products, time intervals и phase definitions. Нельзя подставить средние вместо нелинейного почасового оператора. Сохранение заданного среднего specific humidity — усреднительное ограничение, не доказательство сохранения полной массы воды в атмосферной колонке.

Сравнить через общий validator три различающихся по смыслу варианта:

1. **Strict joint:** все подтверждённые source diagnostics жёсткие; допустимый witness, sound infeasibility certificate или UNRESOLVED.
2. **Fixed-T/p q projection:** жёсткое среднее q и hourly bounds; RH диагностическая. Уникальность convex q subproblem не означает уникальности общей реконструкции погоды.
3. **Reconciled C2:** заранее объявленные soft diagnostics, journal и обоснованные correction budgets. При отсутствии budgets — research-only candidate или diagnostic; production acceptance не выдаётся.

В C2 записываются original/achieved values, signed deltas/units, причина, неизменные hard constraints, pressure provenance и область certificate. Числа вроде q scale=1 g/kg или RH scale=5 pp из objective metric не являются автоматически допустимой ошибкой NEX. Nonconvergence и исчерпание search budget не являются физической невозможностью.

## 4. Регрессия и research-интеграция

Создать интеграционный runner/adapter в новой ветке; frozen implementations вызывать через версии контрактов. Не переносить одну ветку целиком поверх другой из-за совпадения названий C1/C2.

Проверки регрессии:

- Неизменный старый контур воспроизводит 727 exact +5 conditional infeasible records со своим boundary accounting. 2013/2014 остаются regression-only; параметры на них не подбираются.
- Для Davos 13.02.2021 сохранён certificate по одному frozen T-donor prior: дефицит mean T≈1.072738 K. q/RH corrections не лечат этот T-domain blocker; он не доказывает невозможность погоды Davos.
- Отдельно разобрать область фиксированных T/p сертификатов параллельной ветки: 2012 pilot и 15 известных 2014 blocks. При тех же предпосылках выводы сохраняются; при новых p/operators результаты могут измениться только с явной новой областью и журналом, без переписывания старых доказательств.
- Проверить warm/freezing/cold conditions, water/ice semantics, infeasible source means, calendars, day boundaries, missing hours и sensor roles. Свойства проверять независимыми residuals/bounds, а не только сравниванием двух функций одного solver.

Research pipeline:

`daily drivers → совместный weather regime/donor → site pressure adapter → thermodynamic closure → state/cross-variable validation → export + quality sidecar`.

Сохраняются общие regime/day identity и воспроизводимые seeds для T/q, wind, radiation, precipitation и clouds; независимое перемешивание переменных требует отдельного обоснования. После thermodynamic correction проверяются суточные sums/means, межсуточные скачки, night solar, GHI=DHI+DNI·cos(zenith), wet/dry duration, T–RH и cloud/rain/radiation relations.

Первый end-to-end набор: один зарегистрированный historical annual case и один future scenario/year, пока research. Проверять calendar/timezone conversion в стандартное время EPW, полный ожидаемый ряд, units, отсутствие незаявленных fills, actual EPW readback и EnergyPlus smoke test. Успешный EnergyPlus run подтверждает использование файла программой, а не его климатическую точность.

Если source constraints остались несовместимы, runner завершает воспроизводимый diagnostic census и не выдаёт неполный/подменённый ряд за полную source-preserving погоду. Полнота исполнения программы и полнота научно допустимого weather year — разные статусы.

## 5. Одна заранее зарегистрированная независимая AT/DE/CH проверка

До открытия truth: inventory уже просмотренных site/variable/time blocks, выбор cohort по source availability/metadata, primary method, baseline, uncertainty treatment, sample size, thresholds и code/protocol SHA. Две недели 2012 из параллельного pilot также уже раскрыты. Нельзя объявлять новым holdout 2013/2014, эти 2021 дни или иной ранее просмотренный блок после смены имени метода.

Практический ограниченный pressure/subdaily pilot: **3 станции ×2 сезона ×14 последовательных суток =84 site-days /2016 target hours**, даты/станции выбираются после exposure inventory. Если используются только нынешние станции и новые даты, это temporal validation; перенос на новые места требует действительно удержанной станции. Scope остаётся AT/DE/CH, global study — к публикации.

Разделить задачи оценки:

| Задача | Корректная проверка |
|---|---|
| Pressure transfer из синхронной ERA5 | Абсолютное station pressure на тех же часах, правильные instrument references/QC; MAE/bias/RMSE/coverage |
| Subdaily disaggregation при заданных daily constraints | Hourly shape, joint distributions и persistence на held-out днях; использование observed daily aggregates явно обозначается как conditional reconstruction |
| GCM-driven исторический/будущий климат | Сезонные/годовые distributions, quantiles, diurnal cycles, spell durations, cross-variable statistics, building-relevant outputs; календарный hourly MAE к реальной погоде не является правильной основной метрикой несинхронизированного GCM |

Последняя задача использует отдельно заранее заданный более длинный observational interval и climatological uncertainty; двух недель для климатической квалификации недостаточно. Длительность и критерии репрезентативности фиксируются в том же протоколе после metadata/exposure inventory, до открытия truth. При недостаточной информации статус остаётся limited/inconclusive; выборку не расширяют до удобного результата. Эта задача не требует native 137-level ERA5 retrieval на каждый час многолетнего ряда. Будущую погоду нельзя валидировать по отсутствующим будущим наблюдениям: проверяются hindcast behaviour, scenario/source fidelity и физическая допустимость.

Основные прежние development thresholds: pressure MAE≤2 hPa, source coverage≥90%; зарегистрированные noninferiority margins T=0.1 K, RH=0.5 pp, derived q=0.05 g/kg — исходные кандидаты для протокола, обоснование проверяется по задаче и measurement uncertainty **до truth**. Paired uncertainty assessment учитывает day/block/site dependence; множество seeds не создаёт независимые дни. Если interval слишком широк, вывод остаётся inconclusive.

Primary candidate выбирается на development и замораживается до holdout. Выбор другого победителя по раскрытому holdout не превращает его результат в независимую квалификацию. Неудача сохраняется; критерии не ослабляются после ошибок. Повторная независимая выборка нужна только для новой версии после содержательных изменений, а не для поиска удачного запуска.

## 6. Отдельный обязательный контракт будущего давления

Native ERA5 reference решает historical/source-transfer задачу. В зарегистрированном NEX наборе нет согласованного fine-grid ps; original GCM daily/subdaily pressure пока не квалифицирован. Успешный NV2 автоматически не восстанавливает future CanESM5 ps.

Два явно различных режима PressureDriver:

- **Verified native model driver:** исходный ps, если восстановлен и подтверждены model/member/experiment/calendar/time/orography mapping; перенос к site валидируется отдельно.
- **Declared reconstructed driver:** regime/reanalysis-based pressure со своей scenario treatment, provenance и sensitivity; research qualification отдельно от fidelity оригинальному GCM ps. Donor pressure не переименовывается в future target-day native pressure.

Этот workstream можно вести параллельно NV2. Если native source недоступен, историческая research-интеграция продолжается, а future output остаётся явно условным. Изменение p для получения удобного q/RH solution запрещено. Stress ±500 Pa не является calibrated confidence interval.

## 7. Эксплуатационная интеграция и конечный результат

Код генератора получает единый API и сохраняет четыре независимых поля: `code_status`, `physical_status/scope`, `independent_accuracy_status`, `operational_status`. Один зелёный CI не меняет все четыре. B4 остаётся NOT QUALIFIED; его старые отрицательные результаты сохраняются.

API сначала включается как research adapter в отдельной ветке. После соответствующих gates — доступные по квалифицированному domain сценарии для Climate Analyzer. Исторические реальные станции, синтетический historical климат и conditional future climate имеют различимое происхождение. Полный EPW выдаётся только при соблюдении его declared scientific mode; blocked states возвращаются как diagnostics.

Engineering checks: cold/cached replay, schema/version migration, bounded memory/network/time, interrupt/restart, no-overwrite outputs, сохранение inputs/provenance, отсутствие молчаливой подмены источника. Для полного годового интеграционного solver сначала измеряются p50/p95 на коротком наборе и расход на год; пределы фиксируются до длинного CI.

**Завершённый результат этой последовательности:** воспроизводимый integrated research engine, который на допустимых входах строит согласованные hourly states/EPW, а на несовместимых возвращает объяснимый отказ или явно маркированный correction candidate; независимая точность и future fidelity заявляются только в проверенном объёме. Глобальная универсальность и production design readiness не приписываются ограниченной AT/DE/CH проверке.

## Бюджет и порядок запуска

| Шаг | Объём и ожидаемые ресурсы |
|---|---|
| Контракты / локальные mathematical tests | Без новых station scores; короткие source-independent tests |
| NV2 development | Прежние 50 source hours, около 2.2 GB body traffic /1661 requests как измеренная база; 3 GiB cap; несколько минут CI плюс setup. Новые точки используют те же глобальные chunks, но фактические CPU/bytes проверяются заново |
| Joint/C2 integration | Короткий synthetic + registered regression pilot; annual cost оценивается по измеренным p50/p95, без обещания фиксированного runtime заранее |
| Independent 84 site-days native-pressure pilot | При общих двух календарных окнах для трёх станций: 28 уникальных UTC days +2 boundary nodes =674 source hours; грубая оценка около 30 GB суммарно, ≈14 shards по2 days под прежним per-job budget. Три страны делят глобальные source chunks; network cost не умножается ещё на3. Для разных окон бюджет пересчитывается по объединению уникальных часов |
| Annual/climate validation | Повторно использовать compact pressure/column caches и existing daily/hourly drivers; не запускать всю native global-column загрузку на год или на каждый seed |

Контрольная последовательность: contracts → NV2 admission/reconstruction → co-located thermo/closure → integrated research + regressions → замороженная independent validation → ограниченный эксплуатационный допуск. Future PressureDriver — параллельная зависимость будущего режима. Следующий конкретный CI — **только NV2 development**, а не вся матрица сразу.

## Прочитанная основа

- [Work/NV1 independent crosscheck](IGE_P9_3B3_WORK_NV1_INDEPENDENT_CROSSCHECK_RU_20261022.md), включая links на исходные CI и machine-readable audits.
- `p9_3b3_generator.py`, `p9_3b3_pressure_reference.py`, `p9_3b3_source_semantics.py`, `p9_3b3_source_semantics_evidence.json`, frozen protocol, C2 runner и verified CI39672278715.
- Параллельные [fixed-T/p projection report](https://github.com/dmitrievii/building-energy-tools/blob/b943d5fb34f45cc87807cbae34127e597410103d/docs/IGE_P9_3B3_JOINT_T_P_Q_RH_FIXED_SOURCE_CONVEX_PROJECTION_FINAL_RU.md), source code и `p9_3b3_original_CanESM5_2012_2014_physical_source_final_summary.json`. Отчётные результаты этой ветки требуют cross-contract audit перед импортом в интеграционную версию.
