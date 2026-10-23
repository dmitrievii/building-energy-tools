# P9.3B3-TPA1: давление у T/RH и сравнение трёх closure

Реализован зарегистрированный 23.10.2026 блок в ветке `research/ige-p9-3b3-thermo-pressure-adapter-20261023`. Регистрация: commit `70382453e517c9f3d66f69d4469fdd43b39373c9`, [протокол](../research/ige_cmip6/p9_3b3_tpa_protocol.json) и [первоначальная постановка](IGE_P9_3B3_TPA1_PREREG_RU_20261023.md). Новые алгоритмы и результаты добавлены отдельно; 109 прежних научных файлов проверены по SHA и не изменены. Main и старые ветки не изменялись, merge не выполнялся.

Локальная реализация прошла **360 тестов** и полный расчёт **63 случаев / 189 результатов**. Отдельный скалярный аудит повторно проверил **153 полученных состояния, 60 KKT-решений q-only и 36 сертификатов несовместимости**. Это проверка вычислений и условной физической согласованности. Новая независимая станционная точность здесь не оценивается.

## 1. Давление на правильном уровне

`p9_3b3_tpa_pressure.py` читает шесть запечатанных model-side продуктов NV2 run `39925504607`, artifact `12489671619`, ZIP SHA `dd4bb285c22cc081deba891c33ec2aafff549e53028103cfd09c2736ca0727ea`. Файлы observation scores не открываются. Проверяются ZIP, шесть внутренних seals, совпадение геометрии T/RH, исторический epoch датчиков, допуск колонки, роль `THERMO_SENSOR`, исходные anchors и B3 gas formulation. Используется абсолютное давление в Pa, вычисленное у T/RH; давление барометра или sea-level pressure не подставляется.

| Страна | Донор | Высота T/RH, MSL m | Минимум T/RH минус поверхность ERA5, m | Буфер 2 m |
|---|---|---:|---:|---|
| AT, Graz | D2 | 368,70 | 28,835917 | PASS |
| DE, Berlin | D1 | 37,80 | 0,505942 | FAIL |
| CH, Davos | D1 | 1593,93 | 387,110841 | PASS |

Graz D1 по фактическому sealed source остаётся `SOURCE_BLOCKED`: его поверхность выше термогигрометра. Высоты барометров 378,80 / 82,50 / 1595,58 m не используются как высоты T/RH. Берлинский положительный номинальный зазор 0,506 m не квалифицирует двухметровый observation operator. Преобразование MSL в geopotential height через постоянное g₀ остаётся объявленной, не сертифицированной аппроксимацией.

У всех трёх вариантов p одни и те же source chain и геометрия. Их гидростатическая основа:

$$
\ln p(\Phi)=\ln p_a-\int_{\Phi_a}^{\Phi}\frac{d\Phi'}{R_dT_v(\Phi')},\qquad
T_v=T[1+(1/\epsilon-1)q],\quad\epsilon=R_d/R_v.
$$

P1 isothermal, P1 Γ=0,0065 K/m и P2 native различаются аппроксимацией этого интеграла. Адаптер использует проверенные sealed расчёты NV2; новый вертикальный алгоритм в TPA1 не вводился. Максимум |p_variant−p_P2| у T/RH на двух исходных днях: AT 0,3603 Pa для isothermal и 0,3107 Pa для Γ; DE около машинной точности и 0,0000397 Pa; CH 34,0382 и 16,4092 Pa. Это чувствительность к методу, не ошибка относительно наблюдений.

`PressureTrajectory` отдельно хранит source date, target date, 24 исходные UTC timestamps, координаты/высоту/роль и provenance. Для фактического совпадающего дня `generation_reference()` возвращает typed `PressureReference`, совместимый с существующим `pressure_by_date`. При переносе 2021 p на NASA 2013/2014 допускается только `DONOR_DATE_SENSITIVITY`; экспорт такого p в target-day generator вызывает ошибку. Native target-day/future CanESM5 pressure этим не восстановлено.

## 2. Общие определения NASA и физики

Scope — конкретный зарегистрированный **CanESM5 historical r1i1p1f1 v2, grid 46,875° N / 15,375° E**, а не все NEX модели. В новом sidecar сохранены полные 30 ответов DAS/DDS/time для пяти переменных 2013/2014, их SHA и повторно разобранные атрибуты. NASA [v2 technical note](https://www.nccs.nasa.gov/wp-content/uploads/2025/06/NEX-GDDP-CMIP6-v2-Tech_Note.pdf) описывает изменения обработки; exact headers сохранены в [новом source evidence](../research/ige_cmip6/p9_3b3_tpa_nasa_semantics_20261023.json).

Существенный metadata conflict сохранён явно: `tas.comment` говорит derived from downscaled tasmax & tasmin, но `cell_methods` наследует `time: maximum`; у tasmin нет полного cell_methods. Все 730 архивных строк удовлетворяют tas=(tasmin+tasmax)/2 с максимальной разницей **1,52587890625·10⁻⁵ K**. Поэтому применяется `DERIVED_TAS_MIDRANGE`; mean(hourly T)=tas не навязывается. Такое разрешение конфликта не объявлено полным подтверждением source semantics.

У huss/hurs — time mean; RH header задаёт water выше 0°C / ice ниже. На ровно 273,15 K объявлена water branch. Все десять time axes — 365 последовательных noleap noon labels. Объявленные у температур time_bnds отсутствуют в DDS; у huss/hurs bounds attribute отсутствует. Noon label не определяет окно усреднения. Поэтому 24 равновесных UTC-узла — условная численная quadrature, **native bounds unresolved, fully_verified=false**.

Используются R_d=287,05, R_v=461,5, g₀=9,80665 и Murphy–Koop 2005. Для каждого узла:

$$
e_h=\frac{p_hq_h}{\epsilon+(1-\epsilon)q_h},\qquad
q_h=\frac{\epsilon e_h}{p_h-(1-\epsilon)e_h},\qquad
RH_h^{src}=100\frac{e_h}{e_s^{water/ice}(T_h)}.
$$

Физический envelope — 0≤q≤q_sat,water(T,p), e<p. Ice supersaturation допустима, water supersaturation запрещена. NASA v2 daily hurs cap=105% не заменяет hourly water cap. Отдельно сохраняется RH_water.

Суточные операторы всех методов:

$$
\min_hT_h=T_{min},\quad\max_hT_h=T_{max},\quad
tas=\frac{\min_hT_h+\max_hT_h}{2},\qquad
\widehat Q=\sum_hu_hq_h,\quad\widehat R=\sum_hv_hRH_h^{src}.
$$

В эксперименте u=v=1/24. Контракты и тесты разрешают разные неотрицательные нормированные веса, включая нулевой support. Mean RH(q,p,T) не заменяется RH(mean q,mean p,mean T). Mean q не является сохранением полной массы воды в колонке.

После изменения T/q фиксированный p **не реинтегрируется** по новой колонке. Результат — условно допустимое дискретное газовое состояние на заданном уровне при внешнем p, а не полное coupled hydrostatic решение.

## 3. Математические различия реализаций

Общий T prior — affine преобразование исходного source T с заданными extrema. В strict/C2 разрешено отклонение до ±2 K, ограниченное Tmin/Tmax; индексы исходных extrema закреплены. Допуск скорости изменения — max(6 K/h, максимальная скорость affine prior). Численные hard допуски q=10⁻⁹ kg/kg, RH=10⁻⁴ pp; temperature checks сохраняют frozen validator tolerances.

**Strict joint T/q, fixed p.** Требует всех пяти суточных операторов. Приоритет — валидный исходный prior, затем другой проверенный witness, затем два локальных SLSQP старта, не более 180 iterations. Feasibility witness не является гарантией глобально оптимальной hourly формы. Неудача локального поиска даёт UNRESOLVED.

Несовместимость устанавливается только исключающей внешней границей объявленного T-domain. При C_h=q_sat,water(U_h,p_h), a_h=100p_h/min_[L,U] e_s и b=1−ε верхняя двойственная граница имеет вид

$$
R_{upper}(\lambda)=\lambda Q^++\sum_h\max_{0\le q\le C_h}
\left[\frac{v_ha_hq}{\epsilon+bq}-\lambda u_hq\right],\qquad\lambda\ge0.
$$

Для k_h=v_h100p_h/[(ε+bC_h)max_[L,U]e_s] нижняя граница:

$$
R_{lower}(\mu)=\max\{0,\mu Q^-+\sum_h\min[0,(k_h-\mu u_h)C_h]\},\qquad\mu\ge0.
$$

Q± расширены на численный q tolerance. При переходе через freezing включены обе односторонние ветви saturation. Границы вычисляются float64 с явным guard, не directed-rounding interval arithmetic. Сертификат относится к конкретным p, фазе, весам и T-prior; он не доказывает невозможность всех атмосферных состояний или некорректность NASA целиком. Отдельный аудитор повторно вычисляет duals из scalar saturation, не вызывая bound engine.

**Q-only, fixed T/p.** Решает строго выпуклую задачу

$$
\min_q\frac12\sum_h(q_h-q_{0h})^2,\qquad
u^Tq=Q,\quad0\le q_h\le q_{sat,water}(\widetilde T_h,p_h).
$$

Уникальное KKT-решение: q_h=clip(q₀h+λu_h,0,C_h); λ находится bisect. Constant shift при разных u соответствует другому objective. На узлах с u=0 сохраняется ближайший допустимый q₀. RH диагностическая и может существенно отличаться от source hurs. Сертификат недостаточной q-capacity действует только при фиксированном T, не исключая более широкий joint T-domain; это проверено явным контрпримером с joint witness.

**C2 BOTH_SOFT, strict first.** Повторно использует frozen C2. Если strict нашёл admissible witness, C2 сохраняет те же массивы. Иначе минимизирует локально

$$
\frac12[(1000(\widehat Q-Q))^2/1^2+(\widehat R-R)^2/5^2]+0{,}01J_{shape}
$$

при тех же hard T/physical/p constraints; три projection starts, не более 180 iterations. J_shape — frozen нормированные T/q отклонения и roughness; T scale=2 K, q scale≥1 g/kg. Это dimensional sensitivity metric; covariance ошибок и correction budget не установлены. Глобальный optimum и статистическая предпочтительность не заявляются.

Причины несовместимости могут включать нелинейность средних, раздельную обработку суточных переменных, фазу RH, несовпадающие временные окна, другое давление/высоту и узость T-prior. Эксперимент различает эти определения и показывает условную несовместимость; он не идентифицирует единственную причину для NASA без дополнительных первичных данных.

## 4. Фиксированный эксперимент и фактические результаты

Targets и q priors строятся один раз по P2 и сохраняются для всех трёх p variants. Это исключает переопределение target при замене p, но **synthetic controls по построению связаны с P2 и не оценивают его точность**.

- 6 CONTROL_RH60: AT/DE/CH × 01.02/01.08.2021, q сконструирована через source RH=60%.
- 6 CONTROL_Q90CAP_RH20: те же priors, Q=0,9·mean(qsat_water), source RH=20%; synthetic stress.
- 9 раскрытых NASA дат: четыре сезонных и пять прежних blocked 2013/2014; Graz D2, winter/summer pressure source 2021 по зарегистрированному правилу. Это donor-date sensitivity, не восстановление погоды этих лет.

Каждый base case имеет три p variants и три closure methods. Отказы остаются в знаменателе.

| Семейство | Strict | Q-only | C2 |
|---|---|---|---|
| RH60, 18 p-cases | 18 source-preserving в допусках | 18 с точной mean q; все diagnostics в допусках в 14 | 18 без изменения strict state |
| Q90cap/RH20, 18 p-cases | 18 certified infeasible | 18 mean-q solutions, все с изменённой RH | 18 physical projections с изменёнными diagnostics |
| NASA, 27 p-cases | 12 source-preserving, 15 certified infeasible | 24 mean-q solutions, 3 fixed-T capacity failures | 12 strict states, 15 modified projections |

Четыре сезонных NASA дня дали strict witness для каждого p variant. Все пять прежних blocked дат остались исключены в новой условной постановке. Старые сертификаты и результаты при прежних priors не переписываются.

| Выборка и метод | Максимальное абсолютное Δq, g/kg | Максимальное абсолютное ΔRH, pp |
|---|---:|---:|
| NASA q-only, 24 состояния | 1,74·10⁻¹⁵ | 23,32193 |
| NASA C2, 27 состояний | 0,422791 | 0,626808 |
| Synthetic stress q-only, 18 | 1,74·10⁻¹⁵ | 73,38604 |
| Synthetic stress C2, 18 | 5,693181 | 23,16157 |

Это не таблица ошибок относительно истины: Δ — achieved минус входной суточный diagnostic. У C2 изменены обе цели; у q-only одна цель остаётся hard. Их нельзя ранжировать по независимой точности на основании этих невязок.

Из 36 сертификатов: 30 joint RH dual exclusions, 3 joint-box q-capacity exclusions, 3 fixed-T q-capacity exclusions. Минимальный RH separation 4,27494 pp, минимальный q-capacity separation 3,32653·10⁻⁵ kg/kg — значительно выше численных guards. Все 153 возвращённых состояния проходят независимый scalar validator; C2 повторяет 30 strict состояний без изменения массивов. Глобальная optimality q-only проверена KKT; аналогичная гарантия для joint/C2 не заявляется.

## 5. Изменения Python и воспроизводимость

Добавлены пять исследовательских Python-модулей:

- `p9_3b3_tpa_contracts.py`: immutable source/operator/pressure contracts, единицы, даты и запреты подмены ролей.
- `p9_3b3_tpa_pressure.py`: sealed NV2 → thermo-level pressure.
- `p9_3b3_tpa_compare.py`: strict, convex q-only, frozen C2 и общий пятистрочный daily ledger.
- `p9_3b3_tpa_audit.py`: независимый scalar replay states/KKT/duals.
- `p9_3b3_tpa_run.py`: frozen guards, source audit, 21×3×3 census, полные replay inputs/results и измерение затрат.

Четыре новых test modules дают 37 тестов; все B3 — 288, P9.3A — 14, P9.2 — 50, B2 — 8; итого **360/360**, без skips. Дополнительно прошёл canonical DWD semantic script: station P0/urban P0_ST_10 не заменены приведённым давлением. Проверены SI/phase/calendar/time/epochs, co-location, sealed input leakage, uneven/zero weights, analytic KKT, cold RH>100 при water-unsaturated state, warm RH=101 rejection, no mean-T constraint, domain-specific certificates, local failure status, journal tamper, unchanged p и date-sensitivity generator gate.

Каждый результат хранит requested/achieved/signed delta/unit/operator/weights/phase/constraint role/reason/correction acceptance для tasmin/tasmax/tas/huss/hurs, отдельные T/q изменения prior, source/pressure fingerprints и четыре quality статуса. C2 budget явно NOT_ESTABLISHED. Выходной каталог создаётся с запретом перезаписи.

Полные локальные inputs, все 189 результатов, scalar audit, source audit, summary и test hashes сохранены в [replay bundle](../research/ige_cmip6/p9_3b3_tpa1_verified_local_replay_20261023.json.gz). Размер 634 259 bytes, SHA **9784d83affb01f89925e635289f31c5f48cea2e059bd90cdd2d6fa735a30e046**. Каждая запись содержит исходный UTF-8 JSON и SHA; roundtrip и повторный scalar replay из gzip прошли. Это позволяет изучить данный experiment после истечения CI artifacts. Новая загрузка ERA5 или открытие station truth для replay не нужны. Повторная проверка:

```python
import gzip, hashlib, json, sys
sys.path.insert(0, 'research/ige_cmip6')
from p9_3b3_tpa_audit import audit_comparison
path = 'research/ige_cmip6/p9_3b3_tpa1_verified_local_replay_20261023.json.gz'
with gzip.open(path, 'rt') as f:
    bundle = json.load(f)
for record in bundle['files'].values():
    assert hashlib.sha256(record['utf8'].encode()).hexdigest() == record['sha256']
data = {name: json.loads(record['utf8']) for name, record in bundle['files'].items()}
print(audit_comparison(data['comparison_inputs.json'], data['comparison_results.json']))
```

Читаемый [JSON summary](../research/ige_cmip6/p9_3b3_tpa1_verified_local_summary_20261023.json) содержит затраты, группы, hashes кода/tests, geometry sensitivities и признаки qualification. Local run выполнен до publication commit; `git_head` указывает preregistration parent, а фактически исполненный код идентифицирован SHA всех новых Python файлов. Этот код проверен на совпадение с сохранёнными test hashes перед публикацией.

## 6. Затраты, CI и интеграционные границы

Локально: 26,656 s wall / 26,651 s CPU, peak Linux RSS 130 436 KiB ≈127,4 MiB, один BLAS/OMP thread. 63 strict решения: 1,750 s суммарно, p95=0,170 s; q-only: 0,0427 s, p95=0,00099 s; C2: 14,944 s, p95=0,636 s. Остальное — seals, source/JSON, fingerprinting и независимый replay. Входы — NV2 ZIP 1 288 373 bytes и NASA ZIP 890 758 bytes; прежние 2,2 GB native fields заново не загружаются. Тесты прошли за 19,66 s. Это измерения данного запуска, не performance guarantee.

Новый branch-scoped workflow имеет три jobs: contracts/109 frozen hashes; полный 63/189 comparison; отдельный вызов **неизменённого** C2 regression path с прежними 2019/2020 donors, seed и immutable baseline, ожидающий **727 exact +5 certified**. Последний полный rerun локально в TPA1 не заявляется выполненным: он вынесен в CI. Источники и donor canonical SHA в том job проверяются старым кодом. CI timeouts — 20/20/35 min; стоимость regression job определяется прежними источниками и полным повторным решением, не новым малым pilot.

| Уровень заключения | Состояние после локального TPA1 |
|---|---|
| Корректность кода | 360 tests PASS, seals/hashes и независимый numeric replay PASS; удалённый CI отдельно |
| Физическая допустимость | Conditional discrete gas closure при фиксированном thermo p и объявленном T-domain |
| Независимая точность | NOT ASSESSED: synthetic/revealed, не новая AT/DE/CH holdout выборка |
| Эксплуатация | NOT QUALIFIED: native windows, height datum/2m operator, correction budget и future pressure не закрыты |

Следующая интеграция допустима как research path с явными method/pressure/operator metadata. Перед научным выбором метода нужны раздельные проверка source time bounds и correction budget, заранее зарегистрированная новая AT/DE/CH выборка с p/T/RH на сопоставимых уровнях и корректный observation operator. GCM климатические последовательности нельзя оценивать как синхронный hourly прогноз погоды. P2 superiority, B4 qualification, production EPW и native future GCM ps не установлены. Глобальная валидация отложена до публикации. Main не интегрируется этим блоком.
