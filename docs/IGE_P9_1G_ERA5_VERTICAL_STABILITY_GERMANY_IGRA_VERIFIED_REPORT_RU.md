# IGE P9.1G — ERA5 Atmospheric Vertical Stability & Independent Regional Validation — Verified Research

**17.10.2026**. Development branch `research/ige-p9-1g-era5-vertical-stability-dwd-20261017` originating from `research/ige-p9-1f-physically-conditioned-terrain-inversion-20261017` head `00dd23f70e700e729433332883450c9285ff8126`. **No main merge.** Entire study qualified as **research only**; `global_arbitrary_point_weather_qualified=false`, `local_snow/inversion_detection_qualified=false`, `production_epw_ready=false`.

## A. Why the original strict German DWD G1 sample FAILED and what we did

Before checking any German heldout meteorological errors, preregistered independent external DWD stations **Potsdam 3987, Rostock-Warnemünde 4271, Oberstdorf 3730, Hohenpeißenberg 2290** and two actual 2019 weeks, **2019 Jan10–16** and **Oct10–16**, 00–23 UTC. Original authentic DWD historical archive filenames and station WGS84 coordinates/altitude are read from DWD public `historical` directory; actual source ZIP CRC, raw ZIP SHA and `STATIONS_ID, MESS_DATUM, QN_9, TT_TU` are authenticated. No invented station coordinates or substituted observational temperatures.

**P9.1G1 stringent source flag QN_9=10 did NOT pass:** originally sampled each 168h series contains only **QN_9=3** automatically checked-and-corrected records (8/8 sites×seasons), **0 original QN_9=10**. No target-station observations were scored under QN10. P9.1G1 remains **SOURCE BLOCKED** (not a climate skill FAIL, and never redefined as green).

**Separately preregistered P9.1G2**, after examining only original provider QC histograms and before computing model error, permits **ONLY historical DWD QN_9=3** as a *lower-tier independent observational research source*. All 8×168 = **1344** original UTC pairs admitted, no missing hour, QN3 not called fully QC10. Excludes QN1/2, −999 and any unsupported states.

## B. ERA5 pressure-level science sourced from genuine original fields

Open-Meteo **Historical Weather ERA5** is explicitly fixed `models=era5`, `elevation=nan`, `cell_selection=nearest`, UTC with 12 authentic original surface variables, no silent best-match blend. The standard Historical Weather API does not supply a complete native pressure-level ERA5 historical variable family; **never substitute forecast API**. We directly read `temperature` in Kelvin and `geopotential` in m²/s² from Google Research ARCO ERA5 37-pressure-level 0.25° source `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3`, sample exact Open-Meteo selected grid center, evaluate the 14 source pressure levels **1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 650, 600 hPa**, explicitly exclude model pressure levels below regular ERA5 surface geopotential height `z_surface/9.80665 + 50m`.

For each original profile, select two lowest physically permissible pressure surfaces ≥200 m vertically apart; actual `dT/dz` in K/km determines free-air warm-upper-than-lower temperature gradient; `dθ/dz` with `θ=T[K](1000/p[hPa])^{0.286}` determines *static stability*. These **are different**: positive θ-gradient is not an actual temperature inversion. Source 2019 sampling **only 00:00 and 12:00 UTC**, 14 true source profiles per site×season, **112 originally measured reanalysis pressure profile samples** across 8 cases, all 112 had two finite geopotential levels above model ground. This sample DOES NOT qualify hourly 8760 local inversion prediction; no values synthesized at missing hours.

An additional direct source height ARCO `geopotential_at_surface` at selected grid center is used for fixed lapse `T_site=T_ERA5−0.0065(z_site−z_ERA5_regular)`. This is processed original Google ARCO 0.25° reanalysis, **not direct native ECMWF CDS GRIB bytes and not proven same internal vertical interpolation as Open-Meteo**.

**Preregistered candidates** L0 raw ERA5; P0 Open-Meteo site-altitude provider black-box; L1 regular ARCO fixed lapse; L2 L1 replaced by raw when the resolved source **T-level upper warmer than lower** plus valley/weather criteria; L3 L1 replaced by raw when **dθ/dz>5K/km** plus same source valley/weather criteria. All fixed threshold/region/hour support before any 2019 German station temp score.

## C. P9.1G2 actual four German stations — original 1344-hour MAE

Full-hour independent German site×season means, original DWD QN3:

| German station | Jan raw °C | Jan provider °C | Jan regular lapse °C | Oct raw °C | Oct provider °C | Oct regular lapse °C |
|---|---:|---:|---:|---:|---:|---:|
| Potsdam | 0.486 | **0.289** | 0.304 | 0.765 | **0.634** | 0.643 |
| Rostock-Warnemünde | 0.486 | 0.507 | **0.471** | 0.575 | 0.588 | **0.571** |
| Oberstdorf | 1.685 | 1.238 | **1.237** | **1.443** | 2.315 | 2.349 |
| Hohenpeißenberg | 2.348 | 1.779 | **1.770** | **3.732** | 4.067 | 4.067 |
| **Macro station×season MAE** | **1.4402** | **1.4269** | **1.4265** | | | |

In last macro row values are averaged over all 8 site×season cases (4 sites×2 seasons), not just January. Improvements in winter valleys do **not** automatically generalize to autumn: Oberstdorf October worsen from 1.443 to 2.349°C; Hohenpeißenberg October raw 3.732 better than altitude 4.067°C. This is a **genuinely different country observational source** from Austrian GeoSphere but still only one European country, eight weeks of station×season and QN3 automated quality.

## D. Pressure-derived stability as 112-hour *distinct sparse* sample

| Method (equal site×season macro on 14 source hours each) | MAE °C |
|---|---:|
| L0 raw ERA5 | 1.37500 |
| P0 provider altitude | **1.27946** |
| L1 physically fixed regular ARCO height | 1.28122 |
| L2 ERA5 free-air warm-upper-than-lower plus valley/calm/clear/night guard | 1.28122 |
| L3 ERA5 θ gradient >5K/km plus same regime guard | **1.25940** |

**Crucial counter of effective events (latest original source QA)**: 112 complete ERA5 vertical profiles; **6/112** profiles exhibited warm-upper-than-lower *in model free atmosphere*, but **0/112** caused L2 model switching under the other source-only conditions. θ stability criterion caused **exactly 1/112** model switch, at **Oberstdorf January**. Hence all L3 apparent MAE improvement **0.02182°C** vs L1 comes from a **single selected pressure-profile hour**, not demonstrable generalizable model efficacy. Never claim 112 independent meteorological regimes; 00/12UTC source days and local weather are temporally correlated.

Observed inversion immediately above a valley floor not verified. The same winter valley false-positive problem from P9.1F remains unsolved. Do not deploy L2/L3 for future EPW.

## E. P9.1G3 — genuinely independent observed pressure-level thermodynamic structure

Preregistered before actual radiosonde decoding: genuine NOAA NCEI **IGRA v2.2 station `GMM00010393` Lindenberg, Germany**, original metadata ground lat/lon 52.2085°N, 14.1180°E, original official station height returned from IGRA, **Jan10–16 and Oct10–16 2019** at nominal 00/12 UTC. Original `GMM00010393-data.txt.zip`, hash **`81099c2a1d42fc3c21581bbb309fc9d374f03cc6bef1ed78`**. Source **28/28 soundings**, **28/28** direct reported 925 and 850hPa temperature & geopotential heights, **56/56 original IGRA temperature flags B**, no missing or quality-deleted filling.

Matched nearest regular 0.25° ARCO ERA5 source air-column temperatures and geopotential at exact 925/850 hPa, two true above-ground levels. Quantitatively measured, no fit to the radiosonde:

| Original IGRA observed vs ARCO ERA5 model | Result |
|---|---:|
| Temperature 925 hPa MAE | **0.3735°C** |
| Temperature 850 hPa MAE | **0.6708°C** |
| Actual 925→850 temperature gradient MAE | **0.8403 K/km** |
| Potential-temperature gradient MAE | **0.8678 K/km** |
| Stability classification (`dθ/dz>5K/km`) agreement | **23/28 = 82.14%** |
| Free-air positive `dT/dz` sign classification agreement | **28/28 = 100%**, but **only 1/28** positive sounding in both IGRA and ERA5 — this rare-class agreement is not proof of sensitivity to frequent inversion events |

**External radiosonde classification details (independently verified original-sounding sample):** 12/28 observed IGRA profiles have `dθ/dz>5K/km` vs 11/28 ERA5. Confusion matrix: **9 true stable, 14 true nonstable, 3 missed stable (IGRA-only), 2 false stable (ERA5-only)**. Accuracy 23/28=82.1%; for this frozen 5K/km threshold **sensitivity 9/12=75%**, **specificity 14/16=87.5%**, but only one station and two weeks. Both IGRA and ERA5 showed **1/28 actual positive free-air dT/dz**; the apparently perfect 28/28 sign agreement is dominated by negative cases. There is **no evidence here of skill recognizing frequent near-surface inversions**.

**Critical representativeness limits:** IGRA source nominal 00/12-hour not necessarily exact balloon *release* or measurement at 925/850hPa timestamp, and ERA5 grid-center is horizontally separated from radiosonde station. One radiosonde station/two weeks cannot qualify real nighttime site-scale inversion or worldwide spatial skill.

NOAA IGRA documented temperature deleted-QA sentinel `-8888`, missing `-9999`; reported flags B are a strong source QA tier. All original source values temperature/height and individual radiosonde profiles are **not published** in CI, only original ZIP SHA, QA histogram and observational aggregate. Independent physics source original **not reanalysis-derived**.

## F. Scientific decision and steps remaining

| Gate | Status |
|---|---|
| Real independent German DWD site/hour sources exist and source authenticity | **PASS** for automatic-QN3 tier, `QN10` stricter original **BLOCKED** |
| Real regular ERA5 925/850hPa and multiple valid above-ground pressure levels | **PASS** |
| Four new German regions temperature baseline skill | **PASS as bounded 2019 source-quality exploratory** |
| NOAA IGRA direct independently observed ERA5 free-air pressure T and θ | **PASS as single-site two-week validation** |
| Physical vertical stability θ screening genuinely helps ERA5 site lapse | **NOT ESTABLISHED** — one switch only |
| Actual *local* 2–200m valley inversion detection from observations | **NOT VALIDATED** |
| Independently validated multi-year worldwide arbitrary-site future EPW engine | **NOT READY** |

**Next proposed P9.1H:** physically appropriate *near-ground* stability measurements (IGRA free air is not a substitute for sonic/surface-mast 2–200m profiles), climate-regime-dependent DEM terrain and independent climate site QC holds across more geographic regions and years; rigorous temporal sounding timestamps and pressure observational bias; then independent 12-weather-variable joint EPW generator validation (P9.2). Do not tune to Germany+Austria test set after seeing negative results.

## GitHub verifications and source artifacts

- [P9.1G1 frozen strict original source protocol](IGE_P9_1G_ERA5_PRESSURE_STABILITY_DWD_HOLDOUT_PREREG_RU.md) (**scientifically BLOCKED 0/8 QN10**, original failure not hidden).
- [P9.1G2 qualified lower-tier QN3 source protocol](IGE_P9_1G2_DWD_QN3_AUTOMATICALLY_QC_2019_PRE_REG_RU.md), original 2019 Germany sources: [GitHub Actions #39057001755](https://github.com/dmitrievii/building-energy-tools/actions/runs/39057001755) **2/2 SUCCESS**; [G2 source SHA and original 1344 h DWD vs ARCO/ERA5 report](https://github.com/dmitrievii/building-energy-tools/actions/runs/39057001755/artifacts/12109449651).
- [P9.1G3 independent observed radiosonde pre-registration](IGE_P9_1G3_IGRA_LINDENBERG_OBSERVED_VERTICAL_SOUNDING_PREREG_RU.md); actual 2019 soundings: [GitHub Actions #39057329578](https://github.com/dmitrievii/building-energy-tools/actions/runs/39057329578) **2/2 SUCCESS, 10/10 physical IGRA source tests**; [Original NOAA IGRA vs ARCO scientific artifact](https://github.com/dmitrievii/building-energy-tools/actions/runs/39057329578/artifacts/12110326354).
- P9.1G1 original model physical/QC tests **19/19 PASS** even though original strict DWD QN10 observation gate BLOCKED. Together tests **29/29 PASS** for model/provenance contracts. An additional independent audit of archived source results should confirm exact counts and quality before marking final closure.

**Bottom line:** external observed vertical pressure T/θ is demonstrably more credible than pure source-only "stability" labels, but **the actual P9.1G pressure-conditioned temperature correction is still not justified for production**. Main unchanged.
