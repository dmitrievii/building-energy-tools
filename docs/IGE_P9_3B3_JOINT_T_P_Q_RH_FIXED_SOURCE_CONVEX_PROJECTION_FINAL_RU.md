# IGE P9.3B3 — Joint Pressure–Temperature–Water Vapour Reconstruction: Verified Scientific Implementation (RU)

**22 октября 2026 года.** Исследовательская ветка `research/ige-p9-3b3-joint-tpq-water-projection-20261022`, ответвлена от последней проверенной P9.3B2D `2be099e5`. Статус: **C1 физическая почасовая проекция при фиксированных внешних T и P реализована и математически проверена; C2 журнал невозможности сохранения исходной huss реализован; исходный 2012 год 11/14 C1, 3/14 C2; регрессия известных отказов 2014 года 15/15 корректно blocked. Инженерный EPW/будущий GCM ps НЕ квалифицирован.**

## 1. Источники и строгие научные ограничения

Оригинальный `NASA NEX-GDDP-CMIP6 v2 CanESM5 historical r1i1p1f1` имеет суточные `tas,tasmin,tasmax,huss,hurs`, но **не содержит** согласованного на той же мелкой сетке `ps`. Эту переменную запрещено объявлять восстановленной из `huss` и `hurs`. Источник оригинальных климатических суток: зарегистрированный пакет 1995–2014 `joint_daily_raw.csv` SHA256 `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`.

Почасовые давления `p_h` — ИСКЛЮЧИТЕЛЬНО **внешняя фиксированная траектория** из оригинальных Open-Meteo/ERA5-derived hourly donors, 2019 и 2020, ранее подтверждённые канонические SHA:
- 2019: `ac9749eb1cee4d2246b60871f1a139d8920451e30b8ed54ea134431fa0de4c29`
- 2020: `275804a076a81c3c8ae9a572e0359ca524ef9c90627ccca2c6862805093b019c`

Из P9.3B2C: эталонная геопотенциальная высота ERA5 на регулярной сетке 0,25° согласована с возвращаемой высотой Open-Meteo, но source pressure itself не строго идентично ARCO (~0,33 гПа MAE по шести часам). Из P9.3B2D: независимый измерительный тест Berlin-Tempelhof 2021, `QN_8=3`, B4 MAE 6,17/5,61 гПа, а ретроспективный Potsdam 2023, `QN_8=3`, B4 10,29/9,78 гПа против B0 5,13/4,87 гПа: **универсальный перенос станционного давления не квалифицирован**. В настоящем этапе давление и температура НЕ оптимизируются по исходным huss/hurs.

## 2. Математика C1 — единственная выпуклая физическая проекция

Для каждого из 24 часов заданы неизменные `T_h` (сохранены исходные суточные mean/min/max NASA, форма исходного ERA5 донора) и `p_h` (исходный внешний ERA5 pressure). Частичная давление водяного пара `e_h = p_h q_h/(epsilon + (1-epsilon)q_h)`, `epsilon=0.62198`; `e_sat(T)` по существующей P9.2B формуле Buck-над-водой, `q_sat=e_sat epsilon / (p_h-(1-epsilon)e_sat)`. Физические ограничения почасово `q_lo,h <= q_h <= (1-2e-9) q_sat(T_h,p_h)` и суточный баланс `sum q_h = 24 huss_native`.

Решение единственной строго выпуклой квадратичной задачи при условии непустого допустимого множества:
```
min_q  1/2 Σ_h (q_h − q_original_ERA5,h)²
s.t.   Σ_h q_h = 24 huss_NASA
       q_lo,h ≤ q_h ≤ q_sat(T_h, p_h)*(1−2×10⁻⁹)
```
По KKT `q_h = clamp(q0_h+λ,q_lo,h,q_hi,h)`; один скаляр `λ` ищется монотонной бисекцией 160 итераций (без случайных сидов и SciPy). Исходные q0 вычислены из исходной температуры точки росы и исходного давления донора. Численный контроль: `abs(mean(q)−huss_native) ≤ 1e−10 kg/kg`; `0≤RH≤100%`, `Td≤T`, давление и T не изменены. Низкий численный предел q связан с `e_sat(−90 °C)` для стабильной инверсии точки росы; он явно учитывается в физической области, а не выдаётся за атмосферный закон природы.

**`hurs_native` не форсируется**: средняя почасовая `RH_h = 100 e(q_h,p_h)/e_sat(T_h)` нелинейна и не равна вообще RH из средних дневных переменных. Публикуем `mean(RH_h)−hurs_native` в п.п. и исходный hurs.

## 3. Строгие RH-бounds и fail-closed C2

Для каждого часа коэффициент `RH_h/q_h = 100 p_h/[e_sat(T_h)(epsilon+(1-epsilon)q_h)]` монотонно уменьшается с q. Замена знаменателя на `q_hi` даёт гарантированный **нижний**, на `q_lo` — гарантированный **верхний** коэффициент. Минимизируем/максимизируем соответствующие ЛИНЕЙНЫЕ выражения при той же суточной массе `Σq` и коробочных ограничениях `[q_lo,q_hi]`: оптимально заполняем доступные ёмкости в порядке коэффициентов (жадное решение линейного simplex-knapsack). Это математически **консервативные внешние границы допустимой суточной RH**. Если `hurs_native` вне интервала: строгая несовместимость с заданными T/P/q mass; если внутри: совместимость **НЕ ДОКАЗАНА**.

Если `24 huss_native > Σq_hi` либо ниже численного нижнего предела, исходная суточная huss при данных T/P недостижима. **C2 не создаёт успех**: `status=C2_FAIL_CLOSED_DIAGNOSTIC_ONLY`, `hourly=None`, минимальная необходимая невязка воды `max(0,huss_native−mean(q_hi))` (или нижний аналог) явно записана в журнал. Никакой silently coerced huss, давления или температуры. Никакой EPW из C2.

Метод ограничен насыщением **над жидкой водой**, в том числе при отрицательных температурах; формулировка над льдом и влияние смешанных фаз являются отдельным не пройденным sensitivity-gate. Это НЕ полная метеорологическая валидность.

## 4. Физические source-independent тесты

[GitHub Actions **#39745918655**](https://github.com/dmitrievii/building-energy-tools/actions/runs/39745918655) SUCCESS, **10/10 tests PASS**, включая:
- Давление/T неизменны, суточная q в источнике точно сохранена;
- Нет пересыщения или `Td>T`, инверсия точки росы обратно восстанавливает q;
- Невозможная `huss` даёт только C2, с ненулевой невязкой;
- Внутренний минимум Евклидовой проекции проверен 500+ допустимыми попарными перераспределениями q;
- На 80 допустимых случайных распределениях q строго выполняются выведенные внешние RH-границы;
- Native `hurs` не подгоняется скрыто и выявляется достоверное «outside bound»;
- Отрицательное или неидентифицированное давление блокируется.

## 5. Подлинный оригинальный NASA 2012 — 14 дней, источник проверен до расчёта

[Проспективный протокол 2012](IGE_P9_3B3_JOINT_T_P_Q_RH_PROJECTION_2012_PREREG_RU.md) сохранён до чтения конкретных original 2012 target. Две заранее зарегистрированные недели: 2012-01-10…16 и 2012-07-10…16, всего **14 исходных дней**; оригинальный NASA SHA и два оригинальных ERA5 weather SHA подтверждены. Донор выбирается **первым хронологически** внутри того же месяца и wet/dry режима; это не результат оптимизации влажности. Source original archival 1995–2014 известен ранее; 2012 **не новый независимый полевой источник**.

[GitHub Actions **#39746242812**](https://github.com/dmitrievii/building-energy-tools/actions/runs/39746242812) SUCCESS; [исходный полностью прослеживаемый ledger/JSON artifact #12411591954](https://github.com/dmitrievii/building-energy-tools/actions/runs/39746242812/artifacts/12411591954).

| Original target set | Result |
|---|---:|
| Native days | **14** |
| C1 exact native daily huss with all hourly RH/saturation and unchanged pressure | **11/14** |
| C2 infeasible native huss at fixed T/P and source donor | **3/14** |
| Other failures | 0 |
| Accepted 11 days native hurs mean absolute discrepancy | **5.263 percentage points** |
| Accepted days native hurs maximum absolute discrepancy | **8.022 percentage points** |
| Native hurs PROVEN beyond conservative fixed-T/P + mass RH bound | **6/11 accepted days** |
| Complete native-huss-and-hurs verified simultaneously | **NOT QUALIFIED** |
| Full 2012 8760 EPW / field-based accuracy | **NOT CREATED / NOT VERIFIED** |

Three C2 blocks are 2012-01-10 / 11 / 12. Native q unavoidable deficit (g/kg): **0.0114**, **0.7119**, **0.3311**, respectively. The six C1 cases for which native hurs is mathematically outside conservative envelope: 2012-01-13, 14, 15, 16 and 2012-07-13, 14. Remaining 5 C1 days have nonzero residual but their RH-native joint feasibility is NOT proved or disproved by the conservative bound. The user should never infer that original CanESM5 climate is physically incorrect: this is a SOURCE-PAIRING/TIME-DOWNSCALING diagnostic under an external donor pressure/T.

## 6. Previously known 2014 fails remain fail-closed

The old P9.3A 2014 test had 15 original blocked days (2014 Jan31, Feb9/10, Apr19/20/22, May7/13/15/16, Jun11/12/15, Dec2/16). Older P9.3A posthoc conditional linear program found 478/478 source donor combinations without enough fixed-T/P bounded capacity. **P9.3B3 preserved all 15 blocks** under first chronological same-month wet/dry original ERA5 donor. [GitHub Actions **#39746744404**](https://github.com/dmitrievii/building-energy-tools/actions/runs/39746744404) SUCCESS, [original regression artifact #12411746581](https://github.com/dmitrievii/building-energy-tools/actions/runs/39746744404/artifacts/12411746581); 15/15 C2_DIAGNOSTIC_ONLY, **0 falsely treated as native-water-mass-closed days**. Retrospective **regression only**, not independent validation or improved 2014 performance.

## 7. Qualification and next step

| Criteria | Decision |
|---|---|
| Fixed explicit source pressure + fixed T + native daily huss physically solved for feasible day | **PASS mathematical solver / source tests** |
| Strict water-mass and saturation constraints, no pressure manipulation | **PASS** |
| Explicit C2 physically impossible at fixed T/P and output blocked | **PASS** |
| Rigorously certified conservative RH target outer bounds | **PASS** |
| Source SHA original historical NASA/ERA5 and predeclared 2012 pilot | **PASS; 11/14 feasible** |
| Native `hurs` simultaneously hard exact without large hourly distortion | **NOT QUALIFIED** |
| Native CanESM5 historical/future downscaled pressure ps independently qualified | **UNAVAILABLE** |
| Independent station pressure cross-site prediction AT/DE/CH | **NOT QUALIFIED** |
| Full original 2014 365 days | **STILL 350/365 under previous P9.3A**; new stage does not supersede |
| Hourly multivariate (radiation/wind/cloud/rain) or cross-day weather realistic | **NOT VERIFIED** |
| Production EPW for 8760 / EnergyPlus field qualification | **BLOCKED** |

**Next scientifically justified stage:** P9.3B3B source-independent analytic dual-moment feasibility for `mean q` and `mean RH` together, WITHOUT pressure inversion, unqualified model-orography shifts, or fitted GCM humidity targets. If possible construct a physical dual-hard-state witness, but treat inability to find one as `not proven` unless formally certified. In parallel P9.3B4 should qualify original pressure and station representativeness across a prospectively fixed unused station/year; then consider physically plausible future pressure signal. Subsequent 8760 EPW generation and independent genuine simulations remain separate.

**Research only, no merge to main, all three one-shot workflows frozen to manual.**
