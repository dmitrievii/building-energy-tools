# IGE P9.3A — Final Scientific Audit: Pressure, Temperature and Specific Humidity (RU)

Date: 18 October 2026. Research status: physical implementation verified; genuine original 2014 full-year weather NOT qualified. No main merge.

## Original physical model and source semantics

NASA NEX-GDDP-CMIP6 v2 downscales nine original daily fields including tas, tasmin, tasmax, huss and hurs but DOES NOT provide corresponding native downscaled surface pressure ps. Reference: Thrasher et al. (2022), Scientific Data, https://www.nature.com/articles/s41597-022-01393-4 and NASA technical note https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf. Therefore source-native daily huss, hurs and tas are not guaranteed to correspond to one particular 24h pressure profile.

P9.3A uses original hourly ERA5 donor pressure unchanged and explicitly identifies it as external pressure (Open-Meteo ERA5-derived, not native CanESM5 ps or independent station pressure). It computes water vapour from original native mean specific humidity and applies exact hourly psychrometric relationships, 0 to 100% relative humidity, and source daily tas mean/min/max. If baseline donor source saturation capacity is insufficient, constrained SciPy SLSQP may minimally adjust hourly T by up to 2 C while preserving original native daily T mean/min/max and hourly slope limit; 8 source capacity-ranked candidates are attempted only if no original donor is feasible. No pressure optimization, source vapor clipping, seed sweep or use of measured 2025 station residuals. Native daily hurs only closed if physically attainable; nonzero residual is explicitly labelled. Saturation method remains P9.2B Buck-over-liquid. Subfreezing ice-versus-water treatment is NOT independently validated and is not silently switched.

## Prospective source test and provenance

Full original CanESM5 2014 historical, 365 native original days and required 2013-12-31 UTC boundary, single seed 7313. This year was preregistered before per-day scoring, but the twenty-year original source archive was already known in P7C.3; it is NOT an independent measured observational archive.

Original NASA CanESM5 daily CSV SHA256: 77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef.
Original ERA5 2019, 8760 hourly records, canonical weather SHA256: ac9749eb1cee4d2246b60871f1a139d8920451e30b8ed54ea134431fa0de4c29.
Original ERA5 2020, 8784 hourly records, canonical weather SHA256: 275804a076a81c3c8ae9a572e0359ca524ef9c90627ccca2c6862805093b019c.

An initial P9.3A 2014 CI run #39080160830 rejected a modified original HTTP JSON envelope SHA though the full 12-field canonical selected-grid original hourly ERA5 digest was identical. Corrected to compare canonical meteorological data hash, retaining fresh raw HTTP SHA separately. No original source meteorology, year, seed, model or coefficients changed. Genuine annual run #39080232813 completed successfully as a scientific audit: https://github.com/dmitrievii/building-energy-tools/actions/runs/39080232813 ; artifact https://github.com/dmitrievii/building-energy-tools/actions/runs/39080232813/artifacts/12118553085 .

Offline contracts #39080074865: 43/43 PASS (11 new pressure/T/q, 9 P9.2C, 16 P9.2B, 7 P9.2D), all synthetic unit fixtures, not independent field skill.

## Genuine original 2014 results

| Original source item | Measured from source-linked model run |
|---|---:|
| 2014 native days | 365 |
| Prior-year UTC boundary | 1 |
| Physically conserved native daily targets | 351/366 |
| Physically conserved original 2014 days | 350/365 |
| Original 2014 source days blocked | 15/365 |
| Accepted T-corrected days (within predeclared bound) | 1 |
| Maximum accepted hourly T change | 1.565 C |
| Accepted days simultaneously closing source daily huss and hurs | 264/351 |
| Native hurs above proved maximum under selected hourly donor T/P | 40/351 |
| Native hurs below one constructed low witness, lower bound not proved | 47/351 |
| Maximum accepted-day absolute native hurs residual | 18.839 percentage points |
| Complete original 2014 CET 8760 EPW | NOT GENERATED |
| Genuine 2014 original-source EnergyPlus | NOT EXECUTED |

Blocked original dates: 2014-01-31; 2014-02-09,10; 2014-04-19,20,22; 2014-05-07,13,15,16; 2014-06-11,12,15; 2014-12-02,16.

All 15 had baseline water-vapor saturation-capacity rejections across same-month and matching wet/dry ERA5 source profiles. All frozen 8 numerical repair candidates per blocked date had SLSQP nonconvergence. This alone does NOT prove infeasibility, hence a separate diagnosis followed with no weather model changes.

## Post-hoc saturation-capacity source diagnosis

A CONVEX SATURATION CHORD upper-bound linear program (LP) was calculated for ALL original ERA5 same-month wet/dry donor candidates on exactly those 15 known blocked dates. For each donor, source P_h is fixed, native T mean/min/max are fixed, the predeclared +/−2 C bound and hourly slope constraints are retained. The saturation-capacity qsat(T_h,P_h) upper envelope is the chord between each hour's allowed temperature bounds; maximize the sum of chords with linear-programming constraints. If source huss is higher even than the LP upper envelope, that donor CANNOT preserve source vapour mass under those specified bounds. The mathematical result is conditional on the tested Buck-over-liquid saturation convexity on hourly allowed intervals and the ERA5 donor pressure; it is NOT a statement about the original atmosphere or all possible true GCM pressure.

- 478/478 source donor cases: native huss ABOVE the source fixed-P and native-T-bound hourly saturation upper bound.
- 15/15 blocked dates: EVERY original wet/dry same-month donor incompatible with that restricted model.
- Zero candidates classified numerically unresolved and zero above source-mean vapor cases with sufficient LP upper capacity.
- Deficit relative to best donor upper bound ranges 0.000329–0.449 g/kg between blocked dates.
- This is retrospective source-causal analysis, NOT independent station validation or evidence that the original NASA GCM is physically erroneous.

The first LP CI #39080530450 had a real diagnostic aggregation defect: NumPy boolean objects incorrectly classified using Python object identity comparisons. Its zero-count summary is INVALID. Fixed Python boolean conversion, added exhaustive donor-count invariant; no original weather values, T/P bound or seed modified. FINAL valid LP CI #39080609064: 3/3 source-independent mathematical tests PASS and all 478 donors classified. https://github.com/dmitrievii/building-energy-tools/actions/runs/39080609064 ; original source artifact https://github.com/dmitrievii/building-energy-tools/actions/runs/39080609064/artifacts/12118812031 .

## Explicit scientific qualification and next research decision

- Original source lineage and ERA5 hourly pressure provenance: PASS (with provenance warning).
- Physical coupled T/q/P solver for accepted day: finite numerical PASS.
- Original 2014 full native year: FAIL-CLOSED (15/365).
- Universal native huss+hurs simultaneity: NOT QUALIFIED (264/351).
- Native CanESM5 GCM downscaled pressure ps: UNAVAILABLE.
- Actual original 2014 8760 EPW and native original annual EnergyPlus: NOT CREATED / NOT EXECUTED.
- Original measured independent precipitation, cloud cover, solar and LW multivariate validation AT/DE/CH: NOT QUALIFIED.
- Original licensed 28 P7C.5B EPW source-byte and EnergyPlus P8.5/P8.6: BLOCKED.
- Production EPW and world arbitrary-point generator: BLOCKED.

Do not retune temperature bound, solver iterations, original source P or seed against the known 15 failed 2014 days. The next scientifically defensible step is to obtain independently source-certified near-surface pressure (native GCM ps or separately justified physically consistent pressure baseline/altitude transform), ensure daily source aggregation compatibility and preregister a different unexamined future validation year. For observed field quality, independently verify pressure, T and RH in AT/DE/CH plus radiation, rainfall and cloud/LW as previous P8.5/P8.6 gates. Never merge into main without explicit permission. All new workflows manual only after this closure.
