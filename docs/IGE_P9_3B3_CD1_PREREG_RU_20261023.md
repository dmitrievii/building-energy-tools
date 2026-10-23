# CD1 — диагностика сходимости C2, регистрация 23.10.2026

Основание — TPA1 CI #39938665094 и audit fd12eaba. Новый research branch, без изменения frozen C2, physics, NASA operators, daily targets, pressure, priors, starts, metric и лимита 180 iterations. До новых повторных решений фиксируется [машиночитаемый протокол](../research/ige_cmip6/p9_3b3_cd1_protocol.json).

**Исправление предыдущего аудита.** Frozen C2 и CI artifact уже содержат `selected_optimizer_trial`, `selected_solver_reported_success`, `local_optimality_status`. Заявление предыдущего отчёта об отсутствии выбранного индекса ошибочно. Из 33 modified baseline candidates выбранный trial неуспешен в 8 случаях; в 5 из них неуспешны все три starts. Сохраняются исходные CI outputs и старый отчёт; данное дополнение уточняет их интерпретацию.

Повторить все 63 сохранённых CI inputs: 30 exact strict witnesses передаются из архива, 33 остальные cases используют frozen C2; ожидается 99 soft trials. Для каждого case выполнить unobserved и observed вызовы одного frozen function bytecode. Isolated globals позволяют подставить observer минимизатора без модификации module globals; callback только копирует x. Сравнить все прежние поля и массивы точно. Дополнительные objective/Jacobian/KKT расчёты выполняются после возврата оптимизатора.

Каждый trial сохраняет initial/final x, index/stage, SciPy success/status/message/nit/nfev/njev, исходные QP multipliers, objective(data/shape/total), independent validation/rejection и связь с выбранным state. Каждый callback iterate — hash, objective, primal residual, шаг T/q, phase crossings, distance to freezing. Отдельные категории: strict witness без optimization; admissible candidate при solver success; admissible candidate при solver failure; отсутствие admissible candidate. Эти категории не являются критериями математической минимальности.

Для x=[free T в K, q в g/kg] вводится y=x/D с D_T=2 K, D_q=1000 max(0.001,RMS(qprior)) g/kg. Диагностическая цель f=F/max(1,|Ffinal|); scaling не меняет исходный objective. Cap/slopes/equalities и bounds нормируются по объявленным physical/design scales. Для трёх active tolerances 1e−8/1e−6/1e−4 решить bounded linear LS:

$$
\min_{\lambda\ge0,\nu\in\mathbb R}\|\nabla_y f-A_g^T\lambda+A_h^T\nu\|_2.
$$

Публиковать L2/L∞ stationarity residual, primal infeasibility, complementarity, rank и conditioning активного Jacobian, а также статус LS fit. Включить bound multipliers. Это first-order diagnostic, не second-order, local или global optimality certificate. Вблизи WATER/ICE switch явно указать ограниченную применимость smooth KKT.

Проверить analytic objective gradient и constraint Jacobians конечными разностями при dimensionless шагах 1e−5 и 5e−6: central stencil только внутри bounds и одной phase branch; иначе same-branch one-sided; при невозможности — UNAVAILABLE. Сохранить числа и ошибки, не назначая по новым outcomes acceptance thresholds. Показать discontinuity обеих Murphy–Koop формул на 273.15 K; NASA phase policy не сглаживать.

Зафиксировать correction budget NOT_ESTABLISHED, independent accuracy и operational readiness NOT_QUALIFIED. Модели/параметры не подгонять по 2013/2014. Synthetic warm/cold/freezing fixtures и analytic constrained quadratic oracles проверяют код диагностики; archived cases — уже раскрытые regressions. Приёмка: защищённые SHA неизменны; точное observed/unobserved equivalence; 63 outputs, 99 trial journals, 30 witness paths; validation каждой возвращённой state; корректная связь selected trial и отсутствие ложного optimality claim. Cross-environment bitwise agreement не навязывается.

Ожидается порядок десятков секунд–нескольких минут CPU для парных C2 runs и post-hoc diagnostics; фактические затраты измеряются. Новые ERA5/NASA/station downloads не нужны. Workflow — contracts и полный archived-input replay; после запуска сообщить run ID и не опрашивать CI до следующего запроса пользователя.

Документация используемых численных процедур: [SciPy 1.17 SLSQP](https://docs.scipy.org/doc/scipy-1.17.0/reference/optimize.minimize-slsqp.html) и [bounded linear least squares](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.lsq_linear.html). SLSQP multipliers относятся к QP approximation и не включают bounds; поэтому не подменяют описанную дополнительную проверку.
