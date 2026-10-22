# IGE P9.3B2D — German Absolute Station Pressure: Corrected Source Parsing, Prospective 2021 Holdout, and 2023/24 Erratum

**22 October 2026.** Separate branch `research/ige-p9-3b2d-dwd-pressure-availability-20261022`, started at P9.3B2C commit `b793d2f0`. Original research AT/DE/CH; main unchanged. Scientific verdict: **source recovery and a truly prospective single German station 2021 benchmark COMPLETE; universal pressure correction NOT QUALIFIED; GCM future atmospheric closure/annual EPW still BLOCKED.**

## A. Found an important original DWD source parsing defect, not merely lack of measured pressure

Original hourly DWD ZIP `produkt_p0_stunde` CSV headers are **`"STATIONS_ID", "MESS_DATUM", "QN_8", "   P", "  P0", "eor"`**, not unpadded `"P"` and `"P0"`. Previous P9.3B2 and P9.3B2C code verified a set of **stripped header names** but retrieved rows by **raw unstripped keys**, producing misleading null / key errors.

Corrected source logic now normalizes `csv.DictReader.fieldnames` BEFORE reading records, with separate 2/2 regression tests on whitespace and BOM, exact station ID and UTC, original source ZIP SHA. Original `P` is absolute station-level pressure and `P0` is sea-level pressure; never substitute `P0` for `P`. DWD original publication: https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/ .

**Retrospective correction to previously published results** [CI #39743979768](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743979768), [original source artifact #12409334885](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743979768/artifacts/12409334885):

| Original, already examined cohort | Corrected original absolute P h | Original P0 (sea-level) h | Scientific correction |
|---|---:|---:|---|
| Oberstdorf DWD 03730 Jan 2024 | **0 / 168** | 168 / 168 | Station P genuinely unavailable; prior description incorrectly said P0 also absent |
| Oberstdorf DWD 03730 Jul 2024 | **0 / 168** | 168 / 168 | Same |
| Potsdam DWD 03987 Jan 2023 | **168 / 168** | 168 / 168 | Previously reported absence of absolute P **FALSE: parser defect** |
| Potsdam DWD 03987 Jul 2023 | **168 / 168** | 168 / 168 | Same |

Both sites original measured source `QN_8=3` in both weeks (automatically checked quality tier). This is source/QC classification, not selection on ERA5 error. **Retract prior P9.3B2C Potsdam 0/336 absolute pressure gate and its no-German-source inference.** Preserve historical report as audit trail; the present science document supersedes the affected claims.

## B. Frozen availability-only DWD census BEFORE accessing any 2021 pressure observation

[Pre-registration, commit `c587eb04`](IGE_P9_3B2D_DWD_2020_PRESSURE_CENSUS_2021_HOLDOUT_PREREG_RU.md): eight predefined regional city anchors × two closest available original station pressure archives, candidate order independent of source values or ERA5 errors; source completeness-only inspected two fixed **2020** weeks Jan10–16 and Jul10–16. **16/16 original DWD sources** have all original 168 station `P` each week, total **5,376 original P pressure samples** in the census. `QN_8=3` on all, not strict `QN_8=10`; therefore algorithm chose first source-qualified automatic QC station by predefined geographical order: **Berlin-Tempelhof DWD 00433**, height **48 m**, coordinates **52.4676°N, 13.4020°E**. Absolutely **no 2021 observed station pressure or model prediction errors read during selection**.

[Actual 2020 source-only CI #39743327312](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743327312) SUCCESS, [original 2020 station census artifact #12409928415](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743327312/artifacts/12409928415). Earlier transient jobs #39742686588 (duplicated HTML link archive text), #39742795286 and #39743041161 (unstripped native CSV field/KeyError) are **invalid or incomplete intermediate software diagnostics, not physical missingness results**. Fixed prior to valid source qualification.

## C. One genuine independently selected German station holdout: 2021 Berlin-Tempelhof

After freezing 2020 source selection, a **separate immutable GitHub Actions** job downloaded its original result by exact source-run ID, verified station ID 00433, published original station coordinate/altitude and exact original compressed ZIP SHA, and **only then read the original 2021 `P` measurements**. [Independent 2021 original pressure CI #39743815919](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743815919) SUCCESS; [source original 2021 measurements aggregate artifact #12409789640](https://github.com/dmitrievii/building-energy-tools/actions/runs/39743815919/artifacts/12409789640).

Two frozen original periods 2021-01-10..16 and 2021-07-10..16, each exact UTC 168 hours. Both have **168/168 source original true station `P`** and `QN_8=3`; **336/336** exact original measured station vs ERA5-derived source hours. Forecast inputs were unmodified Open-Meteo ERA5 historical `models=era5,elevation=nan,cell_selection=nearest,timezone=GMT` original `surface_pressure,temperature_2m,dew_point_2m`, no station P used to fit. Source reference B4 height `H=geopotential_at_surface/g0` from original ARCO-ERA5 regular 0.25° corresponding exact selected grid center, source coordinate/height checked vs provider returned 1 m. ARCO is remapped ERA5-derived, not native ECMWF CDS GRIB, and QN8=3 is automatic QC.

| Same source-original 168h per season, MAE hPa | January 2021 | July 2021 |
|---|---:|---:|
| B0 — original ERA5 grid surface pressure uncorrected | **6.4518** | **5.8750** |
| B3 — original ERA5 pressure + isothermal virtual-T hydrostatic source provider height | 6.1998 | 5.6432 |
| B4 — same pressure + independently source-certified ARCO ERA5 geopotential surface H | **6.1669** | **5.6129** |

Both predeclared source corrections improved compared with B0 but only by 0.23–0.28 hPa. Original 2021 residuals remain several hPa, **not a general pressure accuracy qualification**, not source pressure assimilated to station, not a full-year annual score, and not native CanESM5 daily pressure.

## D. Retrospective correction to previously frozen Potsdam 2023 station test

Since native `P` actually exists at Potsdam 03987, the original P9.3B2C frozen Jan/Jul 2023 source experiment was rerun solely as a retrospective correction **without switching site, dates, model, source pressure or any constant**. [Corrected original Potsdam CI #39744242445](https://github.com/dmitrievii/building-energy-tools/actions/runs/39744242445), [artifact #12410970729](https://github.com/dmitrievii/building-energy-tools/actions/runs/39744242445/artifacts/12410970729).

| Same original 168h per season, MAE hPa | January 2023 | July 2023 |
|---|---:|---:|
| B0 — original ERA5 grid pressure | **5.1321** | **4.8720** |
| B3 — ERA5 height as Open-Meteo returned | 10.2305 | 9.7305 |
| B4 — original ARCO ERA5 geopotential height | 10.2861 | 9.7835 |

**Important negative result:** The hydrostatic elevation correction **worsens** original station pressure MAE roughly 2× for Potsdam, while improving it modestly at Berlin-Tempelhof and previously strongly at Davos. This disproves that a single universal correction selected only from pressure-grid orography necessarily improves all German station pressure values. Cannot tune a site-specific pressure offset based on seen 2023, 2021 or Graz/Davos data and claim independent generalization.

Potsdam is the previously fixed/seen diagnostic year, **not an additional independent validation**. Main branch and P9.3B2C historical code are left unchanged; this report is a transparent science erratum.

## E. Release and next science decisions

| Gate | Status |
|---|---|
| Correct source field parsing, true station P vs sea-level P0, code regression | PASS (2/2 tests) |
| Original-source-only 2020 16-station completeness census | PASS (5376/5376) at QN8=3 |
| Prespecified 2021 original German station evaluation without selection on its weather errors | PASS as **measurement-based pilot**, 336 hours at QN8=3 |
| Previously misclassified original Potsdam pressure source restored and re-evaluated | PASS, negative result for correction |
| Original Oberstdorf true station P available for old 2024 dates | NO, but original P0 available and intentionally rejected |
| Native ERA5 original geopotential model surface provenance at 0.25° remapped grid | PASS from P9.3B2C, native CDS byte-identity not verified |
| Single hydrostatic pressure correction demonstrably improves all original AT/DE/CH sites | **FAIL; source-target spatial representativeness not solved** |
| Complete independent pressure multi-site / cross-year field generalization | NOT QUALIFIED |
| Native downscaled CanESM5 historical/future native `ps` available or reconciled with NASA NEX daily T/huss/hurs | NO |
| Physically qualified 8760 EPW, real future climate EnergyPlus and publication-grade multivariate skill | BLOCKED |

**Next required scientific stage before reintroducing pressure into joint P9.3B3:** original station pressure vs co-located grid pressure **spatial representativeness**, signed bias/temporal residual diagnostics, ensemble cross-site validation using a newly preregistered independent cohort (not the already-seen Berlin 2021/Potsdam 2023) and separately a pressure-consistent treatment of NASA GCM downscaled daily T and humidity. Source-oriented comparison should distinguish model-grid effective reference height from actual station elevation and nearby sub-grid terrain; do not optimize missing GCM ps backwards from RH.

**Do not merge to main. P9.3B2D CI workflows manual only after closure.**
