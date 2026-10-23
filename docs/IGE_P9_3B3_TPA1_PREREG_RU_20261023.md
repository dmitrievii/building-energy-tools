# P9.3B3-TPA1: давление у T/RH и единое сравнение humidity closure

Регистрация 23.10.2026, до новых solver outcomes. Основание: NV2 audit `544719de…`, roadmap и зарегистрированные P9.3B3/C2 реализации. Новая research-ветка; main, старые алгоритмы, результаты и выборки не меняются. Global validation, merge и production EPW не входят в блок.

## Контракты и семантика

Ввести immutable `DailyClimateConstraints`, `PressureTrajectory` и versioned result schema. Указать SI units, calendar, source/model/member/grid/version/SHA, дату ограничений и отдельно дату источника p/T/q, координаты/высоту/epoch приборов, роли, pressure anchors и provenance. Валидировать совпадение координат и высот T и RH; при несовпадении без отдельного observation operator — SOURCE_BLOCKED. Barometer pressure нельзя подставить как co-located thermo pressure.

Единый thermodynamic policy: Rd=287.05, Rv=461.5, ε=Rd/Rv; Murphy–Koop 2005. RH_source — WATER_ICE: water при T≥273.15 K, ice ниже; RH_water сохраняется отдельной диагностикой. Physical cap q≤qsat_water: ice supersaturation допускается. Это pressure-conditioned gas closure; p фиксировано, исходный вертикальный ERA5 профиль после T/q изменений не реинтегрируется. Полностью coupled hydrostatic модель не заявляется.

Свежие exact CanESM5 v2 headers и time coordinates 2013/2014 сохраняются полностью в новом sidecar. huss/hurs имеют time mean; `tas` comment — derived from downscaled tasmax/tasmin, но `cell_methods` наследует time maximum; tasmin не содержит полного cell_methods. Для зарегистрированного CSV SHA `77ec2e56…` принимается **DERIVED_TAS_MIDRANGE**, обоснованный derived comment и ранее установленным равенством 730 архивных строк в пределах 5e-5 K. Этот выбор и конфликт сохраняются явно. Mean(hourly T)=tas не навязывается. Прочитанные daily noon coordinates не доказывают window; объявленные time_bnds отсутствуют в DDS, у huss/hurs нет bounds attribute. Поэтому 24 uniform UTC nodes — явно условная quadrature, **fully_verified=false**. Источник RH — mean of hourly RH(q,p,T), не RH of mean values. NASA v2 daily hurs cap=105% не заменяет hourly water saturation cap.

## Адаптер NV2

Использовать только model-side sealed products artifact 12489671619, ZIP SHA `dd4bb285…`; observation scores не читать. Primary thermo donors фиксированы по geometry: Graz D2; Berlin/Davos D1. Три pressure variants: P1 isothermal, P1 Γ=.0065, P2 native, на собственных уровнях T/RH. Перенос barometer truth не выполняется. Сохранить Graz D1 rejection и Berlin margin≈0.50594 m; 2 m buffer — sensitivity, не uncertainty.

Для actual source day можно вернуть typed `PressureReference` для существующего generator pressure_by_date. При переносе p/T/q shape из 2021 на NASA 2013/2014 разрешён только явный **DONOR_DATE_SENSITIVITY** режим. Он не является recovered target-day/future/native GCM ps и не может молчаливо экспортироваться как target-day generator input.

## Сравниваемые реализации

Все методы получают одинаковые source daily values, donor prior, gas/formula/phase, quadrature и pressure variant. Daily source и p неизменны на входе; achieved values хранятся отдельно.

1. **STRICT_JOINT_T_Q_FIXED_P**: min/max/derived tas, mean q и mean RH — hard. Общий frozen affine T prior, ±2 K и прежние slopes/extrema; source-preserving witness, sound conditional infeasibility certificate или UNRESOLVED. Reuse frozen C2 `ProjectionProblem` geometry, constraints и independent validator; soft projection здесь не выполняется. Local failure не является сертификатом.
2. **Q_ONLY_FIXED_T_P**: T=affine donor, p fixed; единственная строго convex задача \(\min\frac12\sum_h(q_h-q_{0h})^2\), \(\sum_hu_hq_h=Q\), \(0\le q_h\le q_{sat,h}\). KKT: \(q_h=clip(q_{0h}+\lambda u_h,0,q_{sat,h})\). RH — диагностическая; её невоспроизведение записывается явно. При unequal u нельзя применять безусловный constant shift, соответствующий другому objective.
3. **C2_BOTH_SOFT_STRICT_FIRST**: frozen C2 project_day с общим strict witness, если он найден, сохраняет exact source first. Иначе локальная физическая проекция q/RH diagnostics при тех же hard T/domain/p. Прежние dimensional scales q=1 g/kg, RH=5 pp, λshape=.01; это metric sensitivity, не error covariance и не acceptance budget. Budget NOT_ESTABLISHED. Modified candidate — research only, global optimum не заявляется.

Публиковать journal всех пяти daily diagnostics (tasmin/tasmax/tas/huss/hurs): requested/achieved/signed delta/unit/constraint role, weights/phase fingerprints, причина, budget и pressure provenance. Отдельно T/q shape changes относительно prior. Не считать сохранение mean q сохранением полной column water mass. Корректность кода, conditional physical admissibility, independent accuracy и operational readiness — четыре отдельных статуса.

## Фиксированная comparison выборка

- 6 **CONTROL_RH60**: AT/DE/CH × 01.02/01.08.2021. T из NV2 thermo source, q_control сконструирована через RH_source=60% при P2 pressure; это synthetic consistency control, не оригинальная NASA/станционная влажность.
- 6 **CONTROL_Q90CAP_RH20**: те же T и prior; Q=.9·mean(qsat_water) и RHmean=20%. Это объявленный synthetic conflict stress; невозможность не предполагается без сертификата.
- 9 **NASA_2013_2014_REVEALED_SENSITIVITY** для Graz: 01.02/01.08 обоих лет и прежние blocked 08/19/20/26.01.2013, 02.12.2014. Данные — exact registered CSV. Donor source day — 01.02.2021 для ноября–марта, иначе 01.08.2021, D2. Ни даты, ни prior, ни scales по solver outcomes не меняются.

Все targets и q priors строятся **один раз по P2 baseline**, затем неизменно используются для всех трёх pressure variants. Итого 21 base case ×3 pressure variants =**63 cases**, ×3 метода =**189 results**, включая SOURCE_BLOCKED/INFEASIBLE/UNRESOLVED. 2013/2014 — regression/sensitivity, не holdout; old certificates относятся к старым T/p/operators и не переписываются.

Отдельно CI вызывает frozen 2013/2014 C2 regression path и проверяет прежние **727 exact +5 certified**, с прежним source CSV, donor canonical SHA, seed и immutable repair artifact. Новые 9 sensitivity cases не обязаны повторять их статусы при другой p/T-prior постановке.

## Приёмка и затраты

Tests: units/roles/epochs/timestamps/calendar, all-source seal, observation-pressure leakage, blocked D1 и co-location mismatch; unequal/zero weights KKT и endpoint capacity; water/ice/freezing source diagnostics; независимые scalar residuals; no mean T constraint for midrange; scopes fixed-T vs joint infeasibility; strict witness reuse; C2 ledger/budget; date sensitivity cannot become target-day generation; no overwrite и 189-result census. Все прежние B3/P9.2/P9.3A/B2 tests и protected scientific hashes сохраняются.

Использовать existing NV2 artifact (~1.3 MB), NASA archive и зафиксированный metadata sidecar. Повторная загрузка 2.2 GB native fields не нужна. Новые 63 comparison cases ограничены 180 iterations/2 strict starts/3 C2 starts; p50/p95/total CPU/RSS измеряются, заранее не объявляются. Полный frozen legacy regression — отдельный CI job с 35-minute cap; comparison — 20-minute cap. До получения CI ID — один scoped workflow/protocol push, затем не опрашивать CI без запроса пользователя.
