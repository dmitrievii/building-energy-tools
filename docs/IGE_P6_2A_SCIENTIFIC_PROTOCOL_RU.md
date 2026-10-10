# IGE Independent Climate Engine — P6.2A: observed residuals and multivariate coherence

**Started:** 2026-10-10. **Stage:** source-preserving diagnostics. **Status:** only PASS once the live GitHub observation/projection job passes. Production Climate Analyzer main untouched.

## Non-negotiable scientific premise

NASA NEX-GDDP-CMIP6 v2.0 is already bias-corrected and statistically downscaled using a BCSD method. Its historical reference forcing data (GMFD/PGF) cover 1960–2014. We must NOT automatically apply an additional quantile mapping or historic mean adjustment to all variables: this could double correct the baseline, alter relative trends, and break temperature/humidity/solar/precipitation dependence.

NASA technical note: https://www.nccs.nasa.gov/wp-content/uploads/2025/06/NEX-GDDP-CMIP6-v2-Tech_Note.pdf (Sections 3.2.2–3.2.3); GeoSphere Austria Station Data-v2 hourly: https://data.hub.geosphere.at/en/dataset/klima-v2-1h?lang=en .

## P6.2A executable pilot

**Model:** ACCESS-CM2 r1i1p1f1, Graz 46.983 N, 15.450 E; NASA sampled 0.25-degree cell 46.875 N, 15.375 E.

**NASA windows (original P6.1 20-year artifacts):** historical 1995–2014 and SSP5-8.5 2080–2099, retrieved by GitHub Actions from successful run 38067931031. Both preserve complete raw daily nine-variable sequences. No model simulation year is paired to a specific observed historical weather year.

**Daily diagnostics:** all daily CF dates, units (K, W/m2, kg/m2/s), temperatures in tasmin<=tas<=tasmax, nonnegative rain/irradiance/wind, original RH>100 anomalies, 20-year mean annual precipitation and GHI, seasonal quantiles, wet-day incidence and six within-season daily Pearson dependence coefficients. Report future-vs-historical changes per same model/member. Do NOT apply changes to raw values.

**Observation bridge:** GeoSphere historical monthly dataset klima-v2-1m, station 30 Graz Universität/Heinrichstraße (47.08 N, 15.448056 E, 366 m), January 1995–December 2014, parameters tl_mittel and rr with live metadata validation, 240 monthly time points. Compare 12 observed 20-year monthly climatology means to NASA monthly raw model climatology and report their differences. Preserve raw provider response SHA, NASA CSV SHA, URL and metadata. These are residual spatial+metric differences, **not unambiguously 'model error'**: tl_mittel is computed from observation times and extrema rather than the same statistic as NASA tas; the station is more than 20 km north of the NASA grid center. NASA's already-BCSD-corrected reference forcing can include geographically overlapping station records; this is independent *source*, NOT guaranteed temporally or statistically independent holdout.

**Missing information:** independent daily station validation, local model pressure, near-surface huss for IPSL, wind direction, DNI/DHI and hourly EPW are not available from these particular P6.2A inputs. Relative/specific humidity consistency cannot be certified without pressure and temporal averaging treatment.

## P6.2B decision gates (NOT YET CLAIMED)

1. Acquire quality-flagged GeoSphere v2 hourly observations and build strict UTC day/month aggregation with per-parameter semantics (mean, sum, instantaneous).
2. Quantify complete historical statistical distribution residuals per variable/model and assign source-coverage confidence. Use temporal blocked cross-validation wherever independent observations permit, and compare uncorrected locally vs candidate adjustments.
3. Only where a substantial, demonstrated residual exists, fit *site-specific, trend-preserving* transfer functions on calibration data and report uncertainty. Never apply corrections twice to previously adjusted or combined P5 ensemble outputs.
4. Test cross-variable correlations, day-sequence/temperature extremes, relative/specific humidity physical closure, radiation cloudiness, rainfall wet-day fraction and change-signal preservation, and reject adjustments that degrade multivariate realism.

Status P6.2A source reproducibility must pass before claiming observations validated; P6.2B calibrated local weather/engineering ready are explicitly OUT OF SCOPE.
