# IGE P7B.1 — bounded humid-air feasibility and historical solar distribution validation

**Date:** 2026-10-11. **Branch:** \`research/ige-p7b-1-moisture-and-multiyear-solar-validation-20261011\`. This is **scientific diagnostics**, not a revised or approved hourly EPW and not yet P7C future climate. The immutable P7B 2013 synthetic EPW is preserved unmodified.

## Verified baseline and principal question

P7B synthetic CanESM5 2013 generated 8,760 hours from original NASA NEX-GDDP-CMIP6 365 daily source records with exact native daily mean/min/max dry bulb, daily RH mean, wind mean, precipitation, GHI and longwave source conservation. Source execution: [workflow #38144426555](https://github.com/dmitrievii/building-energy-tools/actions/runs/38144426555), PASS; \`docs/IGE_P7B_CANESM5_2013_ACCEPTED_NUMERICAL_RESULTS.md\`.

**Critical limitation:** native source \`huss\` daily mean is not conserved by the flat daily-RH curve, with maximum error **0.00357085 kg/kg**. This is **not simply a software bug**: huss, hurs and the prescribed intraday temperature time series are independent constraints, and their joint feasibility depends on source pressure, temperature, thermodynamics and RH profile. The source daily pressure is not supplied, and the previous P7B assumed a standard-atmosphere height-based pressure proxy ~97 kPa.

**Scientific premise:** never silently overwrite \`hurs\` to force \`huss\`, invent pressure readings, or claim a valid daily humidity conservation when constraints cannot all be met.

## Test A — explicit bounded family of RH diurnal cycles, native source unchanged

Frozen original data sources:
1. Original 20-year CanESM5 \`historical-1995-2014\` joint DAILY: original GitHub artifact \`ige-p6-CanESM5-historical-1995-2014\`, source input original daily CSV SHA-256 in P7B report.
2. Accepted P7B 2013 original **hourly synthetic** CSV and source audit: [#38144426555](https://github.com/dmitrievii/building-energy-tools/actions/runs/38144426555).
3. P6.3E immutable NASA POWER GHI original 2005–2014 source for a separate solar distribution test.

Fix 24 hourly dry-bulb values to their original P7B synthetic values, define measured/native model day's \`hurs = RHmean\`, \`huss = qmean\`, and adopt previously documented pressure proxy \`p≈97004.74 Pa\`.

Candidate relative humidity for hour i:

\[
RH_i=\overline{RH}+b\,{(\overline T-T_i)\over (T_{\max}-T_{\min})/2},\quad |b|\le25\;\mathrm{percentage\ points}
\]

with zero-mean correction to preserve \`mean(RH_i)=hurs_original\` exactly. Bound \`b\` further so \`0≤RH_i≤100%\`, then calculate:

\[
e_i=\frac{RH_i}{100}e_s(T_i),\qquad q_i=\frac{0.622\,e_i}{p-0.378 e_i}.
\]

The solver tries to match \`mean(q_i)=huss_original\` within 1e−9 kg/kg. If no solution exists within this **pre-registered smooth, bounded RH family**, choose the nearest feasible-family boundary and explicitly report remaining mismatch, **without asserting that all possible physical RH profiles are impossible**.

Outputs record both original and candidate daily RH/q, pointwise bounds, candidate dew point, feasibility mask and original SHA. There is **no replacement EPW**: a diagnostic candidate that is physiologically plausible and conserves daily RH is not the same as a validated/weather-runnable humidity synthesis.

## Test B — source-independent 10-year solar climate comparison, not one-day model event

The 2013 P7B source annual GHI ≈1635.48 kWh/m² versus 2013 P7A NASA POWER ≈1155.02 kWh/m² is **not** a paired observed-weather skill metric: the CanESM5 internal model calendar is a different weather realization. Do not use that single difference alone to calibrate an M0–M3 radiation adjustment.

Compare native CanESM5 daily \`rsds_kwh_m2_day\` versus original independent gridded NASA POWER **hourly** historical GHI for **2005–2014**:
- 3,650 native noleap CMIP6 model days, a full ten-year subset of already frozen source.
- 87,648 NASA original Gregorian hours over the same 2005–2014 era (including 2008 and 2012 leap days).
- Compare **unpaired monthly climatological mean daily irradiation**, annual energy normalized to **365 days** per real calendar year, and multi-year period mean and spread.
- Do **not** calculate same-day model errors, time-correlated paired RMSE, same-year event skill or assimilate NASA radiation to force matching GCM daily events.
- NASA POWER is a separate satellite/reanalysis grid product and may share underlying adjustments with NASA NEX BCSD; **not an independently measured ground pyranometer**. The supplementary station measured GeoSphere daily GHI archive remains a possible further source of truly ground-observed solar climatology.

## Work product and quality gates

Executable: \`research/ige_cmip6/p7b1_moisture_solar_feasibility.py\`.
Test: \`research/ige_cmip6/test_p7b1_moisture_solar_feasibility.py\`.
CI: \`.github/workflows/ige-p7b1-moisture-multiyear-solar.yml\`.

Expected artifact:
- \`p7b1_native_moisture_feasibility_by_day.csv\`, 365 original 2013 GCM days;
- \`p7b1_provisional_hourly_rh_candidate_not_epw.csv\`, 8,760 hourly diagnostics **not** an EPW;
- \`p7b1_10yr_unpaired_solar_annual_distribution.csv\`, 10 years;
- \`p7b1_10yr_unpaired_solar_monthly_climatology.csv\`, 12 months;
- \`p7b1_science_audit.json\`, original immutable source SHA, coverage, feasibility/remaining mismatch, source disclaimers, all output SHA.

If and only if tests and original-source CI succeed, P7B.1 numerical diagnostics can be marked computationally completed. **Full physically validated future EPW remains open.** No merge to \`main\` or publishing original raw source data into public repository without approval.

## Next scientific choice after CI

Decide which *original source constraints* are priorities: conserve daily RH and T while documenting q mismatch, or conserve daily specific humidity and T while allowing RH mean to adjust, or introduce a properly sourced hourly pressure/radiative/latent correlation model. This requires explicit scientific justification rather than an optimizer designed to hide source discrepancies. Separately calibrate 24-hour T/RH/wind/precipitation and shortwave partition against 1995–2014 historical hourly observations/distributions.

The alternative **station-first historical EPW** remains a separate workstream (\`docs/IGE_P7A_S_GEOSPHERE_STATION_FIRST_EPW_BACKLOG.md\`) and should use measured original GeoSphere 10-minute GHI for 2013 rather than unannounced NASA solar substitution.
