# IGE Climate Engine — P8.1D Independent Scientific Results

**Дата:** 2026-10-14  
**GitHub branch:** `research/ige-p8-meteonorm8-batch-automation-20261012`  
**Workflow:** https://github.com/dmitrievii/building-energy-tools/actions/runs/38548051509  
**CI:** 3/3 jobs SUCCESS (contracts, historical temporal holdout, original hourly pair pilot).  
**Scientific decision:** experimental stage successfully executed. P8.1D **not approved for production**; new regime correction does not establish a robust superiority over previous P8.1B/C and degrades Sonnblick. Direct true inversion-profile modelling remains open.

## 1. Scientific comparison protocol

- **Source:** independent GeoSphere Austria `klima-v2-1m`; independent DEM-derived station features from Mapzen/Tilezen with source provenance.
- **Temporal split:** 1991–2010 calibration strictly donor-only, 2011–2020 target test observations withheld. Observations from donor stations in test months are available to the spatial reconstruction; this is NOT a 10-year-ahead meteorological forecast.
- **Stations:** 183 qualified of 189 common-period DEM-index stations.
- **Sample:** 21,859 matched station-months × two buffers (0 km / 50 km), five methods scored identically; 218,590 per-method predictions, no original temperature series distributed.
- **Reference:** regional IDW (P8.1B), local IDW (P8.1B), two-scale DEM TPI (P8.1C), P8.1D winter-only morphology, P8.1D all-season morphology.
- **Model:** five fixed categories derived from DEM, temperature corrections fitted to 1991–2010 donor-only climatology by season, partialling geographic/altitude trend and using ridge regularisation; correction bounded ±1 °C.

## 2. Whole-station error statistics

| Spatial buffer | Method | MAE °C | RMSE °C |
|---:|---|---:|---:|
| 0 km | P8.1B regional IDW | 0.57293 | 0.83450 |
| 0 km | P8.1B local IDW | **0.56075** | **0.80986** |
| 0 km | P8.1C multiscale DEM | 0.56970 | 0.82650 |
| 0 km | P8.1D all-season regime | 0.5696 | 0.8289 |
| 50 km | P8.1B regional IDW | 0.61415 | 0.84640 |
| 50 km | P8.1B local IDW | 0.63718 | 0.88409 |
| 50 km | P8.1C multiscale DEM | **0.60466** | **0.82914** |
| 50 km | P8.1D all-season regime | 0.6084 | 0.8366 |

P8.1D seasonal improves IDW regional by only 0.0035 °C (0 km), 0.0059 °C (50 km) in mean station errors. Station-cluster bootstrap 95% intervals **include zero**, respectively [-0.00525, 0.01122] and [-0.00053, 0.01163] °C. Therefore there is **no statistically conclusive all-station improvement**.

### Regime-specific diagnostics at 50 km

| Regime | Stations | Regional IDW MAE | P8.1D seasonal MAE |
|---|---:|---:|---:|
| Enclosed valley | 72 | 0.6190 | 0.6103 |
| Open lowland | 50 | 0.5390 | 0.5370 |
| Slope transition | 49 | 0.5959 | 0.5954 |
| Alpine crest | 9 | 1.0773 | 1.0573 |
| Ridge | 3 | 0.6799 | 0.6363 |

Only the enclosed-valley **exploratory** 50 km subgroup has a nominally positive station-cluster CI for P8.1D seasonal improvement: +0.00867 °C, 95% interval [0.00027, 0.01757] °C. This subgroup result is very small, subject to multiple comparisons and repeated model development; **it is not a confirmatory result**. Only three ordinary ridge sites were available, unsuitable for statistical generalisation.

### Sonnblick (3109 m) — negative transfer

| Buffer | P8.1B regional MAE | P8.1D seasonal MAE |
|---|---:|---:|
| 0 km | **1.56934 °C** | 1.96390 °C |
| 50 km | **1.22937 °C** | 1.51188 °C |

P8.1D worsens Sonnblick even after assigning its alpine-crest regime. It is not acceptable to introduce this correction for arbitrary mountain locations. A physics-based mountain-atmosphere and vertical-profile approach remains necessary.

## 3. Independent ORIGINAL hourly observations: warm-above-cold stratification pilot

Provider: GeoSphere Austria `klima-v2-1h`, QC-screened original source. Two winter months (Jan 2015 and Jan 2018) and two summer months (Jul 2015 and Jul 2018). Four fixed lower–upper station pairs: St. Anton–Galzig, Galtür–Ischgl-Idalpe, Obergurgl–Pitztaler Gletscher, Innsbruck Universität–Patscherkofel. Local time Europe/Vienna, night 22:00–05:59 and day 10:00–15:59. Pairs differ horizontally; this is NOT a co-located vertical sounding.

| Season/daypart | Qualified pair-hours | Upper warmer, count | Upper warmer, percent | Mean ΔT (upper − lower) |
|---|---:|---:|---:|---:|
| Winter night | 1984 | 435 | **21.93%** | −3.245 °C |
| Winter day | 1488 | 165 | 11.09% | −4.652 °C |
| Summer night | 1951 | 158 | **8.10%** | −4.532 °C |
| Summer day | 1461 | 1 | 0.07% | −8.309 °C |

Total **6,884** qualified pair-hours. St. Anton–Galzig and Galtür–Idalpe show 34.3% and 34.1% of upper-warmer cases in winter nights, respectively. These are observations of **horizontal mountain-station stratification**; they are *not* direct temperature-inversion frequency measurements for a collocated atmospheric column. Only four months, not climatological frequency; hours are temporally correlated, so no independent-hour confidence interval is claimed.

## 4. Physics interpretation, limitations, next gates

The winter cooling/inversion hypothesis is physically plausible in valleys (radiative cooling, gravity drainage, weak mixing), but the tested **monthly mean correction** is not sufficiently predictive. Mean fitted winter valley coefficient is only approximately −0.023 K versus −0.042 K for the warm-season term; therefore P8.1D does not demonstrate that the gains arise specifically from nocturnal inversions. Comparing hourly temperature observations at separated sites supports seasonal stratification but cannot calibrate the true vertical inversion depth.

**Research conclusion:** P8.1D COMPUTATIONAL CLOSURE **PASS**, INVERSION PROFILE PHYSICS **NOT VALIDATED**, BROAD IMPROVEMENT **NOT CONFIRMED**, HIGH-ALTITUDE SONNBLICK **FAIL**, PRODUCTION READINESS **NO**.

Recommended next step: independent inversion profile data (co-located multi-height thermometers, radiosonde, ceilometer/remote sensing where relevant), meteorological drivers (wind/cloud cover/snow/clear-sky nighttime radiation), site-regime conditional models calibrated on a disjoint station region, and an external geographical holdout not reused in model selection. Retain P8.1B regional/local and P8.1C as research references; do not make P8.1D default or silently blend it into EPW.

## 5. Reproducibility, integrity and source policy

- GitHub run: https://github.com/dmitrievii/building-energy-tools/actions/runs/38548051509
- Archived Action artifact `ige-p8-1d-historical-regime-holdout`, ID `11885835570`, SHA256 `24da0abd8873a0679d21f49225760061b91926326f60bff193d00374402b369f`.
- Archived Action artifact `ige-p8-1d-observed-hourly-stratification-pilot`, ID `11885795678`, SHA256 `09eca9206a348c63c4ef2578e043cf2c7acdc10843308519e519fd9373780d5f`.
- Scripts, synthetic fixtures, workflow configuration and experimental protocol are committed to the research branch only.
- Raw Meteonorm hourly weather, proprietary files, raw GeoSphere time series and raw DEM PNGs are **not** included in the public results.

**Background scientific references:** Lundquist et al., JGR-Atmospheres (2008), DOI:10.1029/2008JD009879; Pagès et al., Meteorological Applications (2017), DOI:10.1002/met.1630; GeoSphere Austria station data; Mapzen Terrain Tiles provider attribution.