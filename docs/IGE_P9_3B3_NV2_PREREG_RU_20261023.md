# P9.3B3-NV2: допуск колонок по рельефу и парное восстановление давления

23 октября 2026. План регистрируется до новых pressure scores. Основание: roadmap `89ba7efb…`, Work CI 39757573033, NV1 CI 39765492318 и независимый crosscheck `e667f960…`. Старые 2021 дни раскрыты; этот опыт не является независимой квалификацией. Старые результаты и `main` сохраняются.

## Область и заранее принятые решения

Пилот: Graz Universität, Berlin-Alexanderplatz, Davos; 01.02.2021 и 01.08.2021, 24 часа каждого дня, два предыдущих boundary nodes для CH, итого 50 source hours. Native ERA5 Φs/lnsp обрабатываются вместе из исходной SH цепочки, T/q — на согласованных hybrid levels. Основные уровни 124–137; прежняя deep sensitivity 109–137 — только в двух контрольных часах. Лимиты 3 GiB/2000 запросов общие для всего опыта. Новые точки требуют синтеза дополнительных значений, а не дополнительных глобальных T/q chunks.

До T/q и station truth публикуется **полный**, без усечения до пяти точек, геометрический каталог N320 в R≤50 km от каждого из трёх приборов. Сфера Rearth=6371.0088 km. Для каждой точки: индекс, координаты, расстояния, обе контрольные Φs, нижние границы по barometer/temperature/RH_water и отдельная 2 m buffer sensitivity. Эта sensitivity не является геодезической погрешностью.

Фиксированные Graz slots: D1=(46.79155050131955 N,15.6 E), D2=(47.072580762649004 N,16 E). Их поверхности приблизительно 372.5593 и 339.8641 m. D1 допускает barometer 378.8 m, но находится выше T/RH 368.7 m. D2 допускает обе высоты. В DE/CH D1 — ближайшая по расстоянию точка внутри 50 km с поверхностью не выше barometer; ties: latitude, longitude. Выбор фиксируется на первом source control до T/q и не меняется по часам, датам, результатам методов или residuals. Верхняя граница проверяется только после чтения каждого профиля. Нет допустимой колонки — явный отказ.

Для temperature/RH_water сохраняются те же pressure donor slots, но допуск проверяется на собственных координатах и высотах приборов. Молчаливая замена D1 на D2 запрещена. Отсутствие donor, invalid profile, выход за radius, поверхность или top блокируют соответствующий метод/час. Blended sensitivity требует обоих donors: при потере одного нет перенормировки весов.

Исторические provider identities берутся из отдельно сохранённой, ранее независимо проверенной копии метаданных Work. До seal обновляются только WMDR XML и сравниваются датированные семантические поля приборов. DWD ZIP с наблюдениями не загружается ради метаданных до seal. Изменение геометрии/эпохи — источник блокируется; изменение XML bytes при неизменных полях записывается как новый provenance. Значения наблюдений запрещены на входе predictor.

## Одинаковый donor и anchor для P1/P2

В каждом single-donor сравнении фиксируются одна и та же поверхность Φa, native lnpa, target Φ*, timestamp, gas и source target-layer T/q. Здесь Rd=287.05, Rv=461.5, g0=9.80665; Φ*=g0·instrument MSL height — объявленная, не сертифицированная datum approximation.

\[
T_v=T\{1+(R_v/R_d-1)q\},\qquad
\ln p_*=\ln p_a-\int_{\Phi_a}^{\Phi_*}\frac{d\Phi}{R_dT_v(\Phi)}.
\]

P2 использует положительные piecewise constant layer Tv исходного hybrid профиля. Инверсия kernel независимо проверяется суммой слоёв снизу и остатками hydrostatic equations.

P1 isothermal принимает target-layer T*,q* постоянными. P1 lapse принимает T(H)=T*−Γ(H−H*), q=q*, Γ=0.0065 K/m. При ΔH=H*−Ha, F=1+(Rv/Rd−1)q*:

\[
\ln(p_*/p_a)=-\frac{g_0\Delta H}{R_dFT_*}\quad(\Gamma=0),
\qquad
\ln(p_*/p_a)=-\frac{g_0}{R_dF\Gamma}\ln\!\left(1+\frac{\Gamma\Delta H}{T_*}\right).
\]

Не требуется совпадение P1/P2 при переменном профиле. Для isothermal профиля P1_iso=P2 — независимый аналитический oracle. Прокси не использует station T/RH.

Graz blend — отдельная P2 sensitivity с обоими D1/D2, фиксированными inverse-distance-squared weights по каждому прибору и одним weighted ln p anchor на общей верхней air boundary. Публикуются веса, m1=Σwj(rj−r*), convex-hull support и разность native ln p donors на **одном Φ***. Два donors не определяют полный 2D gradient; spread не calibrated CI. При разных tops фиксированными остаются donor identities/weights, общий верхний air anchor определяется полными профилями каждого часа.

## Замороженные denominators и observation operators

| Страна | Методы | Score cells для двух дней |
|---|---|---:|
| AT | P1_iso_D1, P1_lapse_D1, P2_D1; то же для D2; P2_fixed_D1_D2_blend | 14 |
| DE | P1_iso_D1, P1_lapse_D1, P2_D1 | 6 |
| CH | P1_iso_D1, P1_lapse_D1, P2_D1 | 6 |

Итого **26** pressure cells, каждый denominator 24 часа, даже при блокировке. Pairwise P1/P2 сравниваются по одному donor и строго одинаковым matched hours, baseline P2_D1 или P2_D2 соответственно. Между donors/blend — отдельно sensitivity comparison с own paired-hour counts, без заявления независимой значимости. Старый G0 bracketing stencil и четыре метода выполняются отдельно, сохраняются все его 24 cells. Новые результаты не заменяют старый JSON.

DE truth — только original P0_ST_10 станции 399 в HH00; PP_ST_10 является приведённым давлением и запрещён. AT — combined 30 и individual 16412 с точным совпадением значений/flags/times; временная поддержка остаётся node proxy с unresolved interval. CH — prestah0 preceding-hour mean; модельный observation operator ½[p(t−1)+p(t)], с обязательным boundary node, без fill. Это приближение интеграла, не точное почасовое среднее модели.

Prediction JSON, geometry, donor table и exported profiles записываются и хешируются до открытия observations. После I/O все hashes повторно проверяются. Scores публикуются с MAE/bias/RMSE/coverage, парными часами, observation provenance и source blockers. Development gate прежний: MAE≤2 hPa, coverage≥90%. Этот gate не выбирает донора и не квалифицирует модель независимо.

## Проверки и интеграционная граница

Unit/property/oracle checks: Graz split admission; full census без truncation; order invariance; фиксированные slots при пропусках; tops/время/gas/units; isothermal и stratified hydrostatic oracles; fixed-lapse analytic solution; blend common-air integral; no donor-drop renormalization; horizontal first moment/convex hull; immutable seal до I/O и после; полные 26/24 score cells и paired denominators; non-overwrite; source-only cache miss; четыре раздельных quality statuses. Повторяются существующие B3/C2, P9.3A, P9.2, B2 и canonical DWD tests. SHA всех 80 прежних scientific Python/protocol/result files заморожены в новом protocol.

Экспорт p/T/q на уровне T/RH — условный native layer state. Давление на уровне thermohygrometer не объявляется измеренной barometer truth. Никакого нового station 2m surface-layer operator или независимой q truth этот блок не создаёт. Saturation/condensate physics не квалифицируется hydrostatic проверкой. Следующий этап — versioned thermodynamic adapter по roadmap, затем исследовательский end-to-end generator и заранее зарегистрированная AT/DE/CH валидация.

CI запускается одним scoped push нового protocol в отдельную NV2 branch; дальнейшие запуски только вручную после review. После получения run ID не выполнять длительный опрос. Успешное выполнение CI подтверждает технические проверки; conditional physics, independent accuracy и operational readiness записываются отдельно. B4, future native CanESM5 ps и production EPW остаются NOT QUALIFIED. Merge не выполняется.
