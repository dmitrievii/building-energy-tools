# IGE P9.3B3 Work completion follow-up — native Graz valley air-domain coverage on original ERA5 N320

**Original date of source-only audit: 22 October 2026.** Source Work branch: `research/ige-p9-3b3-native-completion-audit-20261022`, original completely executed Work CI [#39757573033](https://github.com/dmitrievii/building-energy-tools/actions/runs/39757573033), at source SHA `aebdc005505d2789940fe3f5f7eb14e5d31b788e`. This separate geometry research branch is intentionally based on that exact source commit, **NOT merged** with our independently evolved `research/ige-p9-3b3-joint-tpq-water-projection-20261022` or main.

## 1. SCIENTIFIC SCI/ENG distinction confirmed from original 2021 Work artifact

Native P1/P2 Work run source completion now **50/50 profile hours**, previous 39/50 and summer 13/24 no longer valid. Both jobs SUCCESS, 285 source-independent tests logged (213+14+50+8); original execution downloaded 2.194 GB in 1661 source requests; peak RSS ~467 MiB within newly provisioned 3 GiB. Surface `z/lnsp` original GRIB-to-CO exact float32 at two control UTC hours, historical dated sensor descriptions available all AT/DE/CH. **Observation scoring: 24 planned country/day/method cells; 16 fully scored DE/CH, 8 AT source-blocked.** Native 48-hour DE/CH results are **already revealed**, not new independent held-out year; no method independent accuracy certification and B4/production EPW false.

| MAE (hPa), each 24 paired original station hours | Germany 2021-02-01 | Germany 2021-08-01 | Switzerland 2021-02-01 | Switzerland 2021-08-01 |
|---|---:|---:|---:|---:|
| P1 isothermal same column | .158924 | .268548 | .951103 | **.261718** |
| P1 fixed lapse 6.5 K/km same column | .159454 | .268114 | **.768642** | .307035 |
| P2 native single | .158928 | **.267863** | .856827 | .337574 |
| P2 native up to four | .214894 | .286384 | .856827 | .337574 |

The numerical P2 single edge in Germany (~0.001 hPa) is negligible; P2 does not outperform the best P1 in CH. P2 4-column worsens DE; CH P2-4 equals single exactly because only one original native column reaches the barometer (other terrain above). No scientific model selection by 2021 outcomes.

## 2. New preregistered source-only original native ERA5 N320 Graz valley test

**Pre-specified before extended orography source read**, [preregistration](IGE_P9_3B3_NATIVE_AT_VALLEY_SOURCE_ONLY_GEOMETRY_PREREG_20261022_RU.md), initial commit `27a47ca17603bd0e6969ba8f9706f922591cff31`. Frozen historic barometer: Graz Universität WSI `0-20000-0-11290`, N 47.0777777778°, E 15.4488888889°, instrument height 378.8 m MSL valid for original 2021 observation, original historical WMO XML SHA256 `d58aa5a6c37fb030d9b8a3bcd8c7c3c1cf0964a2609acf43c1408cba9f13b788`. It is **an approximate mapping to native model geopotential height using constant g0, not certified geoid datum conversion**.

One-time [GitHub Actions source-only #39765492318](https://github.com/dmitrievii/building-energy-tools/actions/runs/39765492318) SUCCESS; [original resulting source-only JSON artifact #12419308583](https://github.com/dmitrievii/building-energy-tools/actions/runs/39765492318/artifacts/12419308583). **6/6 deterministic geometric tests PASS.** Original ECMWF param129 SH T639 GRIB `z` from exactly `2021-02-01T00:00` and `2021-08-01T00:00` agrees byte-equivalently after float32 cast with native CO z SH coefficients **410240 values each control UTC hour**. Native model source `z/g0` across both tested hours identical, maximum surface H difference 0.0 m. Native original reduced N320 grid geometry used; no SRTM, no station P/T/RH values accessed, no model pressure/T/q field loaded or fit; only spectrum z and grid geographic lat/lon.

| Fixed radial cutoff from 2021 barometer | All native grid points | Native ground H ≤378.8m, air domain reaches barometer |
|---:|---:|---:|
| 25 km | 2 | **0** |
| 50 km | 8 | **2** |
| 75 km | 19 | **5** |
| 100 km | 32 | **9** |

Original work pilot four nearest native grid points:
- 47.07258076265 N, 15.6 E, 11.4579 km, **surface H 395.1281m** (ground +16.33 m above barometer); source-blocked at 378.8m.
- 47.07258076265 N, 15.2 E, 18.8567 km, H 664.5871m.
- 47.35361102203 N, 15.6 E, 32.7259 km, H 839.2078m.
- 47.35361102203 N, 15.2 E, 35.9735 km, H 943.1442m.

**Two source-only potentially admissible native N320 columns within 50km**, including nominal 2m vertical source margin:
1. 46.79155050132 N, 15.6 E, **33.8319 km**, source surface H **372.5593 m** (barometer 6.2407m above native surface).
2. 47.07258076265 N, 16.0 E, **41.7384 km**, source surface H **339.8641 m** (barometer 38.9359m above native surface).

R ≥75km also has source H~234.36m around 52.57km and other 5/9 possible columns; they are increasingly remote and should not be treated as locally accurate by construction.

**Main scientific conclusion:** AT `NO_NATIVE_NEIGHBOR_AIR_DOMAIN` was an implementation **four-nearest-column source geometry restriction**, not an inability to find any regional native ERA5 air column reaching barometer H. **No pressure score, model comparison, station T/RH prediction, or independent quality is established by this geometry-only test**. Remote model-grid donor error must be assessed against blind site/cross-year observations, not inferred from 2021 already scored diagnostic.

## 3. Critical original instrument-height separation (not yet an hourly humidity validation)

Previously verified original historical dated WMO WMDR records, source Work 2021 run:
- **AT Graz:** barometer **378.8m**; T and RH sensor **368.7m**, ~10.1m difference; co-geolocated in 2021.
- **DE Berlin-Alexanderplatz:** barometer **82.5m**, T/RH **37.8m**; ~44.7m difference and ~266m horizontal separation between pressure and temperature sensors. Do NOT pass measured hourly surface T at 37.8m as if it were at 82.5m pressure anchor.
- **CH Davos:** barometer **1595.58m**, T/RH **1593.93m**, ~1.65m difference.

All three MSL instrument histories are epoch-aware, but native ERA5 vertical datum transform is explicitly approximated only. Thermodynamics must distinguish co-location/height and sensor-specific observation operators before comparing multi-variable T/RH and `huss`; native ERA5 atmospheric moisture `q` source is not stationary future CanESM5 `ps`.

## 4. Recommended next sealed source-science sequence (NOT yet accomplished)

1. **NV2 — Pre-registered expanded-region column admission method**, source-only: predefine geometry candidate set R≤50km and rank by great-circle distance (primary) and a sensitivity by air-domain/terrain representativeness. Explicitly require source H at least 2m below nominal barometer to expose MSL/geopotential vertical uncertainty. Never select candidate based on P error.
2. Read original native ERA5 **T, q, z, lnsp** for each 24h 2021 season at only fixed admissible points; P1/P2 variants must use the **same source anchor** and separately label horizontal representativeness. Produce 24/24 AT source-complete predictions only if hourly atmospheric coverage and cohort support pass.
3. Keep 2021 AT/DE/CH as **revealed development**; commit all predictions and source SHAs before any newly preregistered sealed AT/DE/CH **new site/year** observation read. Existing 2021 scores are not reusable to qualify independent accuracy.
4. Before user-facing climate model field release, assess independent subgrid pressure representativeness, height datum, timed sensors T/RH, high-resolution terrain/valley gradients, and **natively absent NASA downscaled CanESM5 ps**. Do not merge `main`, do not claim B4 or production EPW.

**Research state:** Work native source completeness **PASS**, source-only Graz 100km original geometry **PASS**, observational model skill **NOT QUALIFIED**, `B4` **NOT QUALIFIED**, native GCM future pressure **NOT recovered**, full EPW **BLOCKED**.
