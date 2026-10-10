# IGE P6.1 — Seven additional GCMs (Graz, raw synchronized daily CMIP6)

Date: 2026-10-10. This is an **execution protocol**, not a scientific closeout or engineering-validated EPW generator.

## Existing validated baseline

ACCESS-CM2 member r1i1p1f1 has a successful 100-model-year, 900-annual-subset daily extraction across five windows, including 60/60 raw P5 monthly GHI regressions (GitHub run #38067931031). Do not recompute or modify those accepted artifacts. Production main is not part of P6.

## Seven additional CMIP6 GCMs

CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR, MPI-ESM1-2-HR, MRI-ESM2-0 and NorESM2-MM; member r1i1p1f1 only. NASA NEX-GDDP-CMIP6 v2.0, Graz target 46.983 N 15.450 E and model spatial cell expected 46.875 N 15.375 E.

Source availability: CanESM5, EC-Earth3, GFDL-ESM4, MPI-ESM1-2-HR, MRI-ESM2-0 and NorESM2-MM provide nine daily variables (tas, tasmax, tasmin, hurs, huss, pr, rsds, rlds, sfcWind). IPSL-CM6A-LR does NOT provide huss in NASA NEX-GDDP-CMIP6; it is retained with eight source fields. Output preserves the huss column as EMPTY and separately records missing_source_variables=['huss'] without numerical imputation. NASA evidence: https://developers.google.com/earth-engine/datasets/catalog/NASA_GDDP-CMIP6 and https://www.nccs.nasa.gov/wp-content/uploads/2025/06/NEX-GDDP-CMIP6-v2-Tech_Note.pdf . Variables are joined by their native dates **within each model and realization**, and strict time-axis, physical-range, and grid guards apply.

## Staged workflow

Stage 1: seven small source-smoke jobs, each checking historical 2014 and SSP2-4.5 2050 across all nine fields (124 annual NASA NCSS subsets total). A failure blocks the full extraction.

Stage 2: 35 independent jobs for seven models × five twenty-year windows: historical 1995–2014, SSP2-4.5 and SSP5-8.5 × 2040–2059 and 2080–2099. Expected 700 model-years, 6200 annual NASA subsets (6 models x 900 + IPSL x 800), 420 P5 raw-GCM monthly GHI targets. The P5 reference JSON comes from the P5 CLOSED v0.4.0 model_monthly_ghi.csv and stores raw model results rounded to 0.00001 kWh/m²; tolerance = 0.0001 kWh/m² per 20-year mean month. This is **not** the ground-adjusted solar prediction.

Stage 3: independent 35-artifact audit checking 6200 indexed subset SHA values and provenance, 700 annual QA entries, all CSV byte hashes and complete daily date keys, 420 P5 regression comparisons, and within-model calendar consistency. Independent GCMs may legitimately use Gregorian/standard versus 365_day time systems, so the audit preserves rather than silently normalizes these differences.

## Research constraints

No bias correction to local station climate, no independent observed validation of daily fields, no DNI/DHI or wind direction, no hourly synthetic climate generation, and no engineering-ready EPW. After P6.1 source closeout across eight models, P6.2 should quantify multivariate coherence before and after bias correction, using harmonized seasonal/daily metrics and independent station data.

GitHub job successes are necessary but do not themselves establish engineering applicability.
