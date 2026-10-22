# IGE P9.3B3 — Joint Temperature–Pressure–Specific Humidity Closure: Source-Frozen Scientific Protocol

**22 October 2026, preregistered before original 2012 source-day tests.** Isolated research branch from verified P9.3B2D commit `2be099e5`. Production EPW remains blocked, no main merge.

## Scope and physically distinct source semantics

The NASA NEX-GDDP-CMIP6 v2 daily CanESM5 `tas/tasmin/tasmax/huss/hurs` has **no corresponding fine-grid native `ps`**. The 2019/2020 original ERA5 hourly donor `surface_pressure` is an **explicitly external prescribed pressure trajectory**. P9.3B2C found source ERA5 `geopotential_at_surface/g0` consistent with provider elevation on four selected grid cells; P9.3B2D found historical station pressure errors (Berlin-Tempelhof QN8=3 2021 B4 MAE ~6.17 and 5.61 hPa; Potsdam 2023 retrospective B4 ~10.29 and 9.78 hPa, worse than B0). **No station-pressure accuracy guarantee and no native future GCM ps.** Do NOT optimize P to attain prescribed q or RH.

Use unchanged P9.2B `sat_pa/q_of_e/e_of_q/qsat/dewpoint_of_q/source_hourly_mean_temperature` and official externally fixed original source pressure. P9.2B Buck-over-liquid saturation is a stated conventional formula, not an independently validated over-ice formulation below 0°C. Hard daily `tasmean/tasmin/tasmax` from exact source; prescribed hourly donor T shape; source pressure 24 values unchanged (hPa -> Pa). Source donors must be complete original 24-hour records with no target-year leakage. Same-month and same wet/dry source eligibility; select **first chronological** ERA5 source donor, not a donor selected to satisfy difficult humidity or observed accuracy.

## Source-original physical projection C1

The 24 original ERA5 hourly donor moisture samples `q0_h` are derived from source dew point and source pressure. Project onto source-specified daily `huss` while enforcing `q_lo(P_h) <= q_h <= q_sat(T_h,P_h)(1−2e−9)`, `sum(q_h) = 24*huss` using a deterministic **Euclidean projection onto a capped affine simplex**:
`min_q 0.5 sum_h (q_h - q0_h)^2`
subject to `sum q = 24 huss`, box/physical caps. Unique convex solution satisfies `q_h=clip(q0_h+lambda,q_lo_h,q_hi_h)`. Find scalar lambda by monotone bisection, and verify *exact* hard mass closure (1e-10 kg/kg daily mean), RH ≤100, no supersaturation, dewpoint ≤T, unchanged P/T. No SciPy or stochastic optimizer needed. q lower floor corresponds to stated `sat_pa(-90 °C)` for stable dewpoint inversion; a below-floor input fails closed. Note the daily average hurs `mean(RH_h)` is **nonlinear and need not equal the NASA native `hurs`** after mass closure, so report residual rather than silently fitting q to target RH.

## Scientifically rigorous humidity feasibility C1 and C2

- **C1 feasible** iff target total `q_mass` within the *given fixed-source-pressure + fixed-hourly-temperature* 24-hour `q_lo` and `q_hi` sum. This is necessary and sufficient only for moisture existence at fixed T/P, not a guarantee donor shapes/cloud are meteorologically accurate.
- **C2 projection diagnostic, only when C1 infeasible**: compute minimum unavoidable mean daily vapor deficit `max(0,huss−mean(q_hi))` or low-humidity excess `max(0,mean(q_lo)−huss)`. Show hypothetical physically allowed q at a boundary with all corrections measured against native `huss`. Explicitly label **DIAGNOSTIC_ONLY / native GCM daily water mass VIOLATED**. Do NOT treat it as a generated acceptable native day, never export EPW from it, no pressure or T morphing.
- **RH bounds:** At each hour the nonlinear source `RH_h(q)=100[e_of_q(q,P_h)/sat_pa(T_h)]` is monotone/concave in q. Construct analytically valid conservative daily bounds by bounding its coefficient `RH_h/q_h` at q_low and q_high, then optimize the implied linear forms with exactly fixed water mass and hourly bounds via deterministic greedy allocations. If target `hurs` falls outside this interval, it's **PROVEN incompatible with fixed T/P and q mass**; if inside, joint feasibility is **NOT PROVEN**. No falsely exact RH claim. Output measured original `hurs` target residual for the actual C1 unique projection.
- No change to original NASA `huss,hurs,tas` and no retroactively raising ±2°C temperature bounds, source P calibration, or year-specific seeds.

## Predeclared genuine new original-source test (2012 diagnostic, not station measurement)

Original registered NASA NEX-GDDP-CMIP6 v2, same historical 1995–2014 source archive, registered original CSV SHA256 `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`. Source CanESM5 `r1i1p1f1/historical` on native downscaled grid (46.875N,15.375E); donor original 2019 and 2020 ERA5 source with existing canonical full-year SHA registry. Freeze **2012-01-10..2012-01-16** and **2012-07-10..2012-07-16**, 14 days total. The calendar year 2012 is *new for this paired original model experiment*, but comes from an already-known original full twenty-year archive: **NOT an independent newly sourced/field-observed climate validation**. Donor matching same month and wet/dry, first chronological eligible, no learned parameters. Hard all-14 census including fail-closed days and source SHA. Do not switch year/day/donor after results. NASA model daily mean properties and original ERA5 water mass conservation are the only source gates. Produce per-day source names/status, no generated 8760 or high-stakes temperature/humidity skill claims.

## Acceptance and release

- Offline source-independent synthetic: source q/p/temperature self-consistency, exact mass projection, pressure immutability, no invented ps, C1 feasibility/infeasibility, physically meaningful C2 logging, mathematically valid RH bounds (brute-force tiny dimensional sampling in test), no source leakage, original hurs not stealth-imposed.
- 2012 original source 14/14-day *census*, original source metadata/CVS SHA and fixed independent donor hash, no undisclosed rejections or substitutions. A GitHub Actions SUCCESS is a successful audit even if scientific per-day constraints fail.
- Full native 2014 annual physical closure is still 350/365 under prior P9.3A. The new C1 does NOT fix physical mass above saturation for those 15 days; it must preserve failure. P9.3B3 source reconciler is not an EPW engine until 8760 and independent measured validation pass.
- No source original ECMWF CDS native GRIB byte equivalence or future CanESM5 `ps` qualified; no station-based P accuracy improved by this stage.
