# P9.3B3: независимая проверка Work completion и NV1 перед NV2

Проверены [Work CI 39757573033](https://github.com/dmitrievii/building-energy-tools/actions/runs/39757573033), tested SHA `aebdc005505d2789940fe3f5f7eb14e5d31b788e`, и [NV1 CI 39765492318](https://github.com/dmitrievii/building-energy-tools/actions/runs/39765492318), tested SHA `bd6f200d13a7e8888791323c28e6b73a9fefc2b7`. Получены оригинальные ZIP, логи и API metadata. Выводы предоставленного отчёта о полноте и сравнении MAE подтверждены. Для NV2 выявлены дополнительные ограничения: разные допустимые множества для барометра и T/RH, фактический stencil Work и неидентифицируемый двумерный горизонтальный перенос по двум донорам.

Эта проверка сохраняется в отдельной ветке `research/ige-p9-3b3-work-nv1-crosscheck-20261022` от NV1 release `a8f9c35878c58394a54910cd6db969bb313b6bfb`. Исходные Work/NV1 ветки, main, прежние научные отчёты и результаты не переписываются; merge не выполняется. Модель NV2 здесь **не реализована**.

## 1. Work: техническая полнота и независимый пересчёт метрик

| Проверка | Результат |
|---|---|
| Jobs / tests | 2/2 SUCCESS; 285 PASS =213 B3 +14 P9.3A +50 P9.2 +8 B2 |
| Primary source profiles | 50/50; source blockers отсутствуют; оба CH boundary nodes сохранены |
| Sensor histories | AT/DE/CH 3/3; national MSL→geopotential mapping остаётся аппроксимацией |
| Score cells | 24/24 сохранены: 16 заполненных DE/CH, 8 геометрически заблокированных AT |
| Уникальные station hours | 96/144 совпавших часов; четыре метода не увеличивают число независимых наблюдений |
| Protected scientific files | 58/58 SHA совпали с tested git blobs и checkout |
| Source cost | 2,194,174,739 HTTP-body bytes ≈2.0435 GiB; 1661 requests; runner 138.87 s, peak RSS 478232 KiB ≈467 MiB |
| ZIP digest | `2545012a7ace42d851ee2b418f50e2c3c30452202097fde4d9b2d6ae4bed3027` совпал с GitHub |

Проверены семь JSON-файлов ZIP, фактические implementation/protocol hashes, связь prediction seal с manifest и scores, и порядок «predictions sealed → station products opened». Исходный native protocol сохранён: resource completion изменил только phase, byte cap и отдельный journal; scientific settings не изменились.

Дополнительно отдельно получены **шесть исходных pressure products**, побайтно совпавших с SHA CI: четыре GeoSphere запроса combined/individual за две даты, original DWD ZIP и MeteoSwiss CSV. Независимый код, без production observation/scoring helpers, повторно разобрал данные и пересчитал все 24 cells. У 16 заполненных cells MAE, bias, RMSE и max error совпали с максимальным расхождением **1.111·10⁻¹⁶ hPa**. AT combined 30 и individual 16412 вновь совпали; hPa проверены в каждом исходном GeoJSON product. DWD truth — только **P0_ST_10**, native QN=3 на 48 часах; PP_ST_10 не использовался. Raw observations не включены в публичный audit.

Независимая bottom-up гидростатика проверила 696 layer equations и 16 контрольных P1/P2 results: residual ≤1.001·10⁻¹¹ m²/s² и pressure discrepancy ≤3.493·10⁻¹⁰ Pa. Повторный разбор наблюдений проверяет воспроизводимость вычисления ошибок; **новым независимым holdout он не является**.

### Полные сутки, MAE hPa

| Метод | DE февраль | DE август | CH февраль | CH август |
|---|---:|---:|---:|---:|
| P1 isothermal | 0.158924 | 0.268548 | 0.951103 | 0.261718 |
| P1 Γ=0.0065 K/m | 0.159454 | 0.268114 | 0.768642 | 0.307035 |
| P2 single | 0.158928 | 0.267863 | 0.856827 | 0.337574 |
| P2 до четырёх колонок | 0.214894 | 0.286384 | 0.856827 | 0.337574 |

Каждая заполненная cell содержит 24/24 часа. Все 16 проходят ранее объявленный development gate MAE≤2 hPa и coverage≥90%, но это два раскрытых дня. 96 matched hours относятся к четырём station-days; почасовая и пространственная корреляция не позволяет считать их 96 iid примерами. Устойчивого преимущества P2 нет: multi-column ухудшает DE MAE в обоих днях; для CH single=multi, поскольку допустима одна колонка. Сезонный выбор «выигравшего» P1 по этим результатам был бы подгонкой.

На общих с предыдущим CI 39 source hours сверены 312 pressure values. 307 совпали побитно, пять отличаются максимум на **1.455·10⁻¹¹ Pa**. Из 1425 общих source objects 1423 побайтно совпали; изменились XML SHA WMDR AT/DE. Все извлечённые высоты, координаты, определения и эпохи датчиков совпали после исключения provenance hashes. Причину XML byte changes без архивированных исходных XML устанавливать нельзя. Observation-product provenance полностью совпало; whole prediction JSON по этой причине не объявляется побитно идентичным.

## 2. NV1: что подтверждено и что уточняется

NV1 — 1/1 job SUCCESS, **6/6 отдельных геометрических tests PASS**. Это не запуск полной Work test suite на NV1 commit. ZIP SHA `0bc868fc1beaf5b54ac787689898d6a90d736bde1904686922279883bdcebc09` совпал с GitHub. Scientific source/test files одинаковы в tested commit и release `a8f9c358`; preregistration file одинаков в `27a47ca…`, tested и release commits. Protocol SHA совпадает с Work completion.

Original GRIB z controls за оба часа используют те же source SHA/A–B fingerprint, что проверенный Work. 410240 коэффициентов каждого поля совпали после float32 cast; source H checksum одинаков для двух часов. Новых T/q/lnsp/p profiles и station scores NV1 не вычислял.

В source artifact зарегистрированы количества nominal barometer candidates 0/2/5/9 при R=25/50/75/100 km. Независимый scalar audit пересчитал расстояния опубликованных точек, margins и новые ограничения ниже. **Полный census 32 точек независимо заново не рассчитан:** artifact публикует ближайшие пять допустимых колонок, а не полный каталог всех 32 исходных точек. Поэтому 9/32 не выдаётся здесь за отдельное независимое повторение всего source census.

### Разные нижние границы для pressure и T/RH

| Native donor | Расстояние km | Surface H m | Barometer 378.8−H m | T/RH 368.7−H m |
|---|---:|---:|---:|---:|
| 46.7915505 N, 15.6 E | 33.831919 | 372.559296 | +6.240704 | **−3.859296** |
| 47.0725808 N, 16.0 E | 41.738449 | 339.864083 | +38.935917 | +28.835917 |

Обе точки проходят **нижнюю геометрическую границу барометра**. Из них только вторая проходит границу T/RH датчиков. Первую нельзя продолжать вниз на 3.86 m под model surface, чтобы получить T/q/p у thermohygrometer. Полная hourly air-domain admission ещё требует T/q/p profiles, проверки верхней границы и временной полноты. Nominal 2m buffer из NV1 — design sensitivity, **не сертифицированная uncertainty datum/height**.

### Work использовал окружающий stencil, не четыре ближайшие точки

`GaussianGrid.neighbors` выбирает две latitude rings по разные стороны станции и две longitude sides на каждой ring. Это четыре **bracketing cells**. Обнаруженный NV1 donor на 33.831919 km ближе включённой в старый stencil точки на 35.973479 km. Следовательно, формулировка «четыре ближайшие» математически неверна. Основной вывод NV1 сохраняется: региональная native air candidate существует за пределами прежнего окружающего stencil.

### Два донора не определяют горизонтальное поле в Graz

Обе R≤50 km точки восточнее и южнее станции. Станция находится вне их выпуклой оболочки; неотрицательные weights с суммой 1 не воспроизводят её горизонтальные координаты. При старой inverse-square-distance формуле веса ≈0.603492/0.396508, а первый пространственный момент в локальной tangent-plane аппроксимации составляет **(+23.453 km east, −19.436 km north)**, норма ≈30.460 km.

Для scalar field f=ln p на **одном физическом уровне Φ**:

\[
\mathbf m_1=\sum_jw_j(\mathbf r_j-\mathbf r_*),\qquad
\sum_jw_j f(\mathbf r_j)-f(\mathbf r_*)
=\nabla_h f(\mathbf r_*)\cdot\mathbf m_1+O(R^2).
\]

Здесь m1≠0: смешивание не устраняет даже общий линейный горизонтальный gradient. Два pressure values дают rank 2 для трёх неизвестных двумерного affine field (intercept, east gradient, north gradient). Полный 2D gradient и значение в станции этими двумя донорами не идентифицированы. Поэтому перенос следует обозначать как **условную региональную донорскую модель**, с явным gradient assumption/interval; геометрия не удостоверяет локальную точность. Если независимо задана граница ||∇h ln p||≤L, первый порядок даёт |δln p|≤L||m1||. L нельзя подбирать по ошибке Graz.

## 3. Как уточнить NV2 до реализации

1. Сохранить G0/старый stencil как заблокированный regression baseline. Зафиксировать R≤50 km и отдельно объяснить source-only выбор этого радиуса по NV1. Не менять радиус/соседей по pressure residual.
2. Определить разные множества I_P(t), I_T(t), I_RH(t) по собственным координатам и Φ датчиков:

\[
I_s(t)=\{j:d(\mathbf r_j,\mathbf r_s)\le R,
\ \Phi_{sj}\le\Phi_s\le\Phi_{top,j}(t),
\ \text{complete valid }T_j,q_j,p_j\}.
\]

   Для thermohygrometer Graz из двух опубликованных barometer candidates остаётся одна. Её state на 28.84 m над model terrain также не является автоматически измерением 2m над реальным грунтом станции.
3. Сначала построить два отдельных barometer reconstructions по одним и тем же исходным колонкам: P1 isothermal, P1 fixed lapse и P2 layer integration для каждой геометрии. Для каждого парного сравнения использовать одинаковые anchor p/Φ, target и time operator. Различия вертикального closure отделить от смены горизонтального донора.
4. Two-column blend — отдельный кандидат с заранее заданными weights и common-air anchor, явным m1 и неидентифицированной частью horizontal gradient. Без внешних gradient bounds или дополнительных неколлинеарных воздушных колонок его sensitivity не объявляется calibrated uncertainty interval.
5. Reconstruct co-located p,T,q у T/RH приборов отдельно от barometer validation; учитывать DE 44.7 m / около 266 m разнесения и CH 1.65 m. RH_water, q definition и временное усреднение сохранять явно; не клиппировать состояния молча.
6. Seal source-only predictions до доступа к observations, публиковать все coverage cells и отрицательные сравнения. Даты 2021 и прежние 2013/2014 остаются development/regression. Новая независимая AT/DE/CH выборка регистрируется отдельно после фиксации модели; глобальные исследования отложены.

Согласованность pressure-only reference затем возвращается в NASA daily T–p–q–RH closure с отдельными temporal operators. Суточные средние RH не равны RH от средних T/q/p; pressure у барометра не заменяет pressure у thermohygrometer. C2 correction journal, старый Davos donor certificate и native future CanESM5 ps этим аудитом не закрываются.

## 4. Воспроизводимость и статусы

Добавлены только два offline audit scripts, два machine-readable reports и этот документ. Исходные prediction/scoring/geometry modules и workflows не менялись. Work audit сохраняет full cells/provenance и результат независимого raw-score replay; NV1 audit сохраняет source geometry report и новые sensor/spatial checks.

- [Work verified audit](../research/ige_cmip6/p9_3b3_native_completion_verified_CI_39757573033.json), [script](../research/ige_cmip6/audit_p9_3b3_native_CI_39757573033.py).
- [NV1 sensor/spatial crosscheck](../research/ige_cmip6/p9_3b3_NV1_sensor_admission_crosscheck_20261022.json), [script](../research/ige_cmip6/audit_p9_3b3_NV1_sensor_admission.py).

```bash
python research/ige_cmip6/audit_p9_3b3_native_CI_39757573033.py \
  --evidence-dir /path/to/work-completion-evidence \
  --previous-evidence-dir /path/to/previous-work-evidence \
  --private-observation-dir /path/to/sha256-named-pressure-products \
  --out /path/to/new-work-audit.json

python research/ige_cmip6/audit_p9_3b3_NV1_sensor_admission.py \
  --nv1-evidence-dir /path/to/nv1-evidence \
  --work-verified-audit research/ige_cmip6/p9_3b3_native_completion_verified_CI_39757573033.json \
  --out /path/to/new-nv1-audit.json
```

Work evidence содержит `artifact.zip`, распакованные `artifact/*.json`, `contracts.log`, `pilot.log`, `api_evidence.json`; previous Work — ZIP и `artifact/`. NV1 evidence — ZIP, `artifact/`, `job.log`, `api_evidence.json`. Private products именуются `<CI SHA256>.bin`. Выходные audit-файлы не перезаписываются. При отсутствии private products raw-score replay явно не выполняется.

| Уровень | Итог |
|---|---|
| Корректность кода / выполнения | Work 285 PASS, 50/50 source hours; NV1 6 PASS; independent raw-score arithmetic reproduced |
| Физическая допустимость | Условная hydrostatic gas column; sensor-specific lower boundary и horizontal support требуют учёта; surface layer, datum и saturation не квалифицированы |
| Независимая точность | NOT QUALIFIED: раскрытые два дня; NV1 новых predictions не давал; преимущество P2 не установлено |
| Эксплуатация | FALSE; B4 NOT QUALIFIED; production EPW FALSE; native future CanESM5 pressure не восстановлено |
