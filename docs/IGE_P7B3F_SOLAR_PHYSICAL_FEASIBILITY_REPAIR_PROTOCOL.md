# IGE P7B.3F — Solar Physical Feasibility Repair

**2026-10-11. Research stage, independent branch. Production EPW not approved.**

## 1. Original defect and evidence

P7B.3E used the ad hoc hourly GHI upper bound

\[
C_h^{(0)} = \min\big(E_{0,h},\max(1.25\,G_{\mathrm{Haurwitz},h},\,0.65E_{0,h})\big),
\]

where the TOA horizontal hourly energy `E0,h` is integrated using approximate NOAA solar geometry at 5-minute intervals. This cap is an **engineering hypothesis**, not a validated physical or meteorological ceiling. In the original 2012–2014 eight-GCM experiment, **300 source days** were excluded because the daily model input GHI exceeded the sum of these caps. The P7B.3E archived audit finds **zero** source days in 1995–2014 with daily GHI above integrated TOA. This does NOT mean TOA is an absolute observed hourly solar radiation bound: cloud-enhancement events can exceed ordinary clear-sky irradiance, sometimes even an extraterrestrial-horizontal reference over short intervals. We retain TOA as a *conservative research screening cap*, not an inference about atmospheric radiative transport.

Sources: original GitHub Actions #38168230357 and the SHA-pinned P6.1 NASA NEX-GDDP-CMIP6 historical daily rsds inputs. Solar geometry remains P7B.3E's approximate code; this stage does not solve noleap-calendar mapping into EPW.

## 2. Minimal cap relaxation

For a model day with unchanged corrected original GHI integral `E_d`, the repaired hourly caps are

\[
C_h(\lambda_d)=C_h^{(0)}+\lambda_d(E_{0,h}-C_h^{(0)}),\qquad 0\le\lambda_d\le1,
\]

with

\[
\lambda_d^*=\begin{cases}
0,& E_d\le \sum_h C_h^{(0)},\\
\frac{E_d-\sum_h C_h^{(0)}}{\sum_h E_{0,h}-\sum_h C_h^{(0)}},
& \sum_h C_h^{(0)}<E_d\le\sum_h E_{0,h}.
\end{cases}
\]

A numerical projection slack ≤1e-9 kWh/m²/day is allowed to make the existing finite-bracket projection algorithm stable. This is the smallest **uniform convex envelope relaxation** admitting the daily integral, not the smallest arbitrary per-hour change and **not a physically calibrated atmosphere model**. The historic frozen cap is not changed on already feasible days. If the source GHI exceeds integrated TOA even after this relaxation, the program must fail closed and record the offending original day; it never clips or rescales source daily energy.

The original fixed-alpha M2 analogue selection remains unchanged: Graz station30 QC-approved 2007–2008 observed-day library, alpha=0.75 chosen on 2009, nearest 15 seasonal/clearness analogues, deterministic seed/day hashing. Reuse P7B.3C 0.65 caps and exactly reproduce original hourly output for every previously feasible model-day. The daily-energy projector preserves every daily input with error <1e-9 kWh/m²/day. Erbs-based component closure is algebraic only; it does not independently validate DNI or DHI observations.

## 3. Original-source local research proof

For CanESM5 historical native noleap daily rows 1995–2014 (7,300), **all 7,300** satisfy the conservative TOA integrated daily screen. **174 historical** source days exceed the old frozen cap; 174 were restored. In stress years 2012–14, old model omitted **31 out of 1,095 days**. Repair admits all **1,095 days / 26,280 hours** per seed. Max fractional relaxation `lambda = 0.36497` (20-year original). `lambda` average among only repaired days 0.11823. Across 3 seeds, original-frozen M2 output on all originally feasible days is identical, exact comparison. Max solar-energy closure ~1.776e-15 kWh/m² per day; GHI=DHI+DNI*coszen residual ~1.11e-16 kWh/m² per hour. Source model original SHA-256 `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`.

Results above are **local CanESM5-only**, not an assertion of eight-GCM completion. The full original 8-GCM GitHub Actions run must independently validate original-source QA and each model's counts.

## 4. CI pass and science release gates

- Verify each original 20-year GCM provenance/quality and source `joint_daily_raw.csv` SHA; use P7B.3E's proven artifact selection for 8 models, not unverified archives.
- No original historical day exceeds TOA under the current approximate solar calculation; if one does, stop the research generator (do not declare a valid repair).
- No 2012–2014 model day lost: per-model count exactly equals source native calendar day count, and model hourly count exactly `24*n_days` for each seed.
- Exact bitwise frozen M2 output on **all** days previously feasible (for identical model input, geometry, seed and alpha).
- Restore all days previously rejected **only** by the old cap; test across three seeds, same all-GCM inputs.
- For every repaired model, max source energy residual < 1e-9 kWh/m²/day, component closure residual <1e-10 kWh/m²/h, DNI nonnegative and conservatively capped under Erbs.
- Source provenance and output SHA, structured science audit, example 2013 solar hours, and model-wise counts retained; no raw third-party source in public derived artifact.

## 5. Not yet scientifically validated

P7B.3F is an **engineering feasibility repair**. It does **not** establish validated GHI/DHI/DNI climatology, cloud-enhancement realism, accurate atmospheric turbidity/clear-sky or mountain horizons, correct mapping of native noleap calendars to EPW, predictive accuracy of daily GCM GHI, or building-energy simulation accuracy. **Production EPW stays blocked.** No merge into `main` without explicit instruction. Next work: independent irradiance component observations (e.g., BSRN station/period source quality), rigorous clear-sky/TOA sensitivity, calendar transfer, and full EPW/EnergyPlus assessment with measurements.

### Background references

- Inman et al., *Solar Energy* 130 (2016): cloud enhancement above the modeled clear-sky ceiling, occasionally above horizontal TOA reference, https://doi.org/10.1016/j.solener.2016.02.011.
- NREL solar position & irradiance algorithms, including input-hour interval semantics, https://www.nrel.gov/grid/solar-resource/solpos.html.