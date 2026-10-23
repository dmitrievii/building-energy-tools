# CD2 — координаты и независимый алгоритм той же задачи

Регистрация 23.10.2026 до новых CD2 решений. Родитель: CD1 `b6772d02f44604967779ebc1d8f4500e774dc280`; отдельная ветка `research/ige-p9-3b3-cd2-scaled-independent-20261023`. [Машиночитаемый протокол](../research/ige_cmip6/p9_3b3_cd2_protocol.json), canonical SHA-256 `0ef3801ca9dc181d11b47f9d0386eb73e248b1c68e60a3faf0ff851f8a436f37`.

## Проверенное основание CD1

[CI #39961593449](https://github.com/dmitrievii/building-energy-tools/actions/runs/39961593449) завершён SUCCESS 23.10.2026, оба задания. Логи подтверждают 308+14+50+8=380 tests, 130 контрольных SHA, 63 случая и 99 trials; артефакт содержит 63 полных журнала. Все 99 trial states валидны в прежнем физическом смысле; у 8/33 выбранных modified candidates solver failure, в 5 случаях неуспешны все старты. Replay CI занял 32.47 s. Это подтверждает полноту CD1, а не оптимальность, независимую точность или production readiness.

Оригинальный CD1 CI ZIP: artifact 12504114915, 2967325 bytes, SHA-256 `81cbfee41a6fe269bbe819b2ada0cc6afe9bb76471d7b2427eefc841df9255d2`. Он сохраняется отдельно от старых результатов. Для CD2 139 прежних научных файлов защищены SHA-256; прежние реализации и отчёты не редактируются.

## Гипотезы и четыре варианта

Нужно проверить, изменяются ли допустимый конечный профиль, исходный objective и first-order residual при эквивалентной замене координат и алгоритма. Не устанавливается гипотеза о превосходстве P2, B4 или независимой station accuracy.

| Вариант | Переменные | Ограничения | Алгоритм |
|---|---|---|---|
| FROZEN_C2 | исходные x | исходные c(x) | исходный SLSQP |
| SLSQP_SCALED_X | центрированные y | исходные c(c+Dy) | SLSQP |
| SLSQP_SCALED_XC | те же y | c(c+Dy)/s, s>0 | SLSQP |
| COBYQA_SCALED_XC | те же y | те же c(c+Dy)/s | COBYQA |

Это позволяет отдельно исследовать масштаб переменных, масштаб ограничений и смену алгоритма. Исходная задача:

$$
\min_{x\in[l,u]} F(x)=\tfrac12r(x)^TM^{-1}r(x)+0.01S(x),\qquad
g(x)\ge0,\quad h(x)=0,
$$

где r=(Δq [г/кг], ΔRH [п.п.]), M=diag(1²,5²), S — frozen prior формы и шероховатости. Физика, формулы и все параметры F берутся непосредственно из frozen C2. Ни нормировка F, ни новый penalty в objective не вводятся. Масштабы M не объявляются ковариацией ошибок NASA.

Для x=[free T[K], q[g/kg]]:

$$
x=c+Dy,\quad c=(T_{0,\mathrm{free}},0),\quad
D=\operatorname{diag}(2K,\;1000\max(0.001,\mathrm{RMS}(q_0))),\quad
\nabla_yF=D\nabla_xF,\quad J_yc=J_xcD.
$$

Все диагонали D положительны: преобразование взаимно однозначно, bounds переходят в (l−c)/D, (u−c)/D. Для SCALED_XC cap делится на Dq, slopes на прежнюю slope scale; mean T/q/RH при наличии — на 2 K, Dq, 0.05 RH fraction. Положительное масштабирование не меняет точного допустимого множества, но может менять численные stopping criteria. Проверяются именно исходные функции после обратного преобразования, без клиппинга результата.

## Источник, фазы и воспроизводимость

Повторяются все 63 сохранённых TPA1 inputs: 30 exact strict witnesses и 33 modified cases по три прежних старта. Для четырёх вариантов ожидаются 252 method results и 396 optimizer trials; неуспехи включаются в итог. Во всех вариантах работает тот же frozen strict-first function bytecode; подменяется только вызываемый минимизатор через isolated globals. Давление на уровне T/RH, NASA operators, priors, target diagnostics, starts и правило выбора минимального **исходного F** среди независимо валидированных конечных кандидатов сохраняются. Solver success не становится дополнительным фильтром. Точные witnesses не оптимизируются задним числом. Для FROZEN_C2 проверяется точное равенство observed/unobserved в одной среде на всех случаях.

CanESM5 v2 tas midrange, WATER_ICE source RH и WATER physical saturation cap сохраняются. Метаданные tas и native time bounds остаются не полностью подтверждёнными. Абсолютное DWD pressure не подменяется reduced pressure. p фиксировано; новая гидростатическая интеграция после изменения T/q не заявляется.

COBYQA выбран как независимый от analytic derivatives численный путь. Он строит quadratic interpolation models и соблюдает box bounds при вычислениях: [SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html), [документация COBYQA](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-cobyqa.html), [первоисточник алгоритма](https://arxiv.org/abs/2210.12018). Точный SciPy 1.17.0 wrapper проверен по установленному исходному коду. Тот же F вычисляется с прежней WATER_ICE ветвью в каждой точке. Фазовые границы не сглаживаются, новые phase bounds не добавляются. Отсутствие производных у оптимизатора не устраняет разрыв F и не даёт гарантии сходимости на нём; smooth first-order checks ограничены одной ветвью.

## Лимиты до просмотра результатов

Все варианты имеют maxiter=180. SLSQP: прежний ftol=1e−11. COBYQA: maxfev=2000, initial_tr_radius=1, final_tr_radius=1e−6, feasibility_tol=1e−9, scale=False; без дополнительного автоматического масштабирования. Это заранее фиксированный bounded comparison. Одинаковый maxiter не означает одинаковой работы или эквивалентных stopping criteria. Исчерпание этого бюджета не доказывает, что алгоритм не способен решить задачу при другом бюджете. Результат не используется для подбора maxiter, радиуса, весов или параметров физики.

Измеряются wall/CPU, nfev/njev, calls и число итераций каждого trial; не объявляется универсальный победитель по одной частоте success. Начальные профили не выбираются по новым результатам, CD1 optimum не используется как warm start. Ожидаемый порядок затрат полного replay — 2–15 CPU min, фактическое время публикуется. NumPy 2.3.5 / SciPy 1.17.0, один BLAS/OMP поток. Новые source downloads кроме уже завершённого CD1 archive не нужны.

## Проверки и критерии выводов

До полного archived replay — analytic quadratic/equality/bound oracles, независимый scalar thermodynamic optimum, chain rule и проверка границы WATER_ICE, одинаковые starts и функции, сохранение strict witness, удержание rejected/error trials. Затем неизменённые прежние suites и 139 protected SHA.

Для каждого конечного кандидата — прежняя независимая физическая валидация и CD1 stationarity/primal/complementarity/rank/condition при τ=1e−8,1e−6,1e−4; branch-local FD при h=1e−5,5e−6. Все initial/final states и trace diagnostics сохраняются. Нефинитные и rejected endpoints не превращаются в пригодные состояния; ошибка алгоритма не объявляется физической несовместимостью источника.

Сравниваются F/data/shape, profile differences T/q, source corrections, first-order residuals, phase crossings, все старты и выбранный trial, затраты. Для табличного различения F ниже/выше/практически равно заранее вводится только numerical tie tolerance 1e−10 max(1,|Fcontrol|). Это не научный correction budget и не допуск независимой точности. Нет требования «новый алгоритм должен выиграть», иначе неуспех оказался бы скрыт устройством приёмки.

Приёмка реализации: неизменность защищённых SHA; oracle tests PASS; одинаковая математическая задача и starts; сохранение 30 witnesses на вариант; полный census 63/252/396 с сохранением ошибок; независимая перепроверка выбранного состояния и исходного F. Small first-order residual и успешный LS fit не являются local/global optimum certificate. Новый scientific acceptance threshold по раскрытым данным не устанавливается.

2013/2014 и 2021 остаются раскрытыми регрессиями/чувствительностью. Независимая станционная валидация — отдельная будущая регистрация только AT/DE/CH. Глобальные исследования отложены до научной публикации. Correction budget NOT_ESTABLISHED; B4, независимая точность, operational/production EPW readiness и native future GCM pressure NOT_QUALIFIED. Main и прежние ветки не меняются, merge не выполняется.

После публикации реализации запускается отдельный CI; сообщить run ID и не опрашивать его до следующего запроса пользователя.
