# EPB Results Visualizer 0.1.0 — Stage V1 source candidate

A **read-only Streamlit visualization application** for native IVANCALC EPB Rhino `Result Export` ZIP bundles. The application is a sibling of `tools/climate_analyzer`, not an alternative calculation engine. It follows Climate Analyzer's Streamlit navigation, Plotly chart styling, physical-quantity colours, presentation controls, and science/UX separation.

## Run locally

Python 3.12 is recommended. From the repository root:

```bash
python -m pip install -r tools/epb_results_visualizer/requirements.txt
cd tools/epb_results_visualizer
streamlit run app.py
```

Running from the tool directory picks up its `.streamlit/config.toml` (100 MB uploads). Streamlit Cloud launched from repository root uses **repository-root** `.streamlit/config.toml`; the existing Climate Analyzer config limits uploads to 10 MB. Deploy as a separate Streamlit app with an appropriate root config and validate hosting/privacy before making it public. No existing Climate Analyzer configuration was changed.

## Grasshopper workflow

1. Connect `EPB Model` to `Calculate`. For broad dynamic signals, enable a bounded **Validation Trace Settings** (e.g. controls or full validation) and connect it to Calculate's `Trace Settings` input. There is no automatic capture of unrequested solver internals.
2. Connect `Calculate → Result` to `Result Export → Result`.
3. Choose `ZIP Evidence Bundle`, the export path, then `Run=true`.
4. **Optional but recommended:** connect `Calculate → Validation Trace` to the new trailing `Result Export → Validation Trace` input. Trace and Result must have the same exact calculation fingerprint. This appended input does not move any existing slots.
5. Upload the generated `eaw-evidence-bundle.zip` to Streamlit. Existing exports without schema v1 can also be imported through the native `result.json` fallback, although they lack the optional captured trace.

**Important:** native source changes have not been compiled against .NET SDK 8 and Rhino/Grasshopper in this environment. This package is a *source candidate*, not a verified production GHA. Do not replace the installed GHA until native validation is complete.

## ZIP schema v1

| ZIP entry | Purpose |
|---|---|
| `manifest.json` | Existing native release / calculation fingerprint |
| `result.json` | Existing full native evidence (unchanged) |
| `visualization/manifest.json` | Stable schema, scope, semantic and temporal metadata |
| `visualization/monthly-thermal.csv` | Zone-native monthly useful demand in kWh |
| `visualization/hourly-thermal.csv` | Zone reporting hours, initialized samples removed, W/°C/% |
| `visualization/zone-metadata.json` | Native ZoneId metadata |
| `visualization/validation-trace.csv` | **Optional** captured validation samples including CO₂, air flow, controls, surfaces, humidity, equipment where actually recorded |
| `visualization/validation-trace-manifest.json` | Trace fingerprint, temporal basis, variable registry |
| `monthly-metrics.csv`, `carrier-ledger.csv` | Existing native national monthly metrics and energy ledger |
| `hourly-*-research*.csv` | Existing native system-level, explicitly non-additive physical evidence |

Import does not extract archives to disk, follows a size/member budget, requires a manifest, rejects duplicate/path-traversing members, validates hour/zone uniqueness and heating/cooling signs, and never executes uploaded content. Limits are designed for Streamlit Community Cloud; larger production models need resource profiling and possibly binary columnar storage before support can be claimed.

## Analysis pages

- **Overview:** study fingerprint, completeness, summary, original zone monthly thermal needs.
- **Thermal balance:** hourly/daily/monthly/annual thermal loads, temperatures, humidity, solar gains where present; chronological, heatmap and duration plots; zone comparison and physically valid additive building-scope power.
- **Energy systems:** original source, storage, distribution and CHP/DHW research CSVs, by SystemId.
- **Validation Trace:** arbitrary recorded controls/ventilation/surface/node/system quantities and categorical state transitions, with original timestamps.
- **National indicators:** original H505x monthly metrics and quantities; unit-mixing blocked.
- **Carrier ledger:** monthly national carrier/use/source reporting, with import/export separation.
- **Data quality:** per-bundle availability and known limitations.

Presentation: 16:9 / 4:3 / square / custom canvas; scale, font size, legend placement, line width, built-in Plotly zoom; browser SVG export and CSV of displayed intervals.

## Physics & temporal policy

- Hourly signed thermal power (W): positive heating, negative cooling; heating and cooling are separated before aggregation. The one-hour energy integral is `P[W] × 1 h / 1000 = kWh`.
- Temperatures, humidity and CO₂ are never summed across zones. State quantities are mean/peak by interval, not energy.
- Nonadditive EN 15316 research ledgers are **never added to the national H5050 carrier ledger** in this viewer.
- `hour_index` is a relative annual step; unless an authoritative source calendar is available, graphs display **reference year 2001** (or 2000 for 8784 hours), explicitly labeled synthetic. Native trace timestamps are preserved and plotted in UTC. No EPW date or climatic year is invented.
- Monthly-only calculation has no synthetic hourly reconstruction. The native monthly results remain available.
- Missing/blocked solver outputs are not presented as zero. Coverage depends on available `Result` and the selected validation capture mode.

## Validation

```bash
cd tools/epb_results_visualizer
python -m pytest -q tests/test_bundle.py
python tests/build_demo.py
```

The generated `SYNTHETIC_DEMO_NOT_CERTIFICATION.zip` is test data, **not** a Rhino output or certified building energy calculation.

## Follow-up production gates

1. Compile modified .NET 8 solution with Rhino/Grasshopper references, run existing integration regressions, and perform a real Rhino ZIP export/reimport round trip.
2. Confirm source timestamp and native month-index alignment for real EPW/non-EPW climatic time bases, including DST and leap years.
3. Add dedicated graphs for ventilation CO₂ mass balance, AHU psychrometrics/heat-recovery, adaptive façade and shading, lighting, and multiservice generator/source ownership when source events are available.
4. Benchmark realistic 100+ thermal-zone archives and implement chunked Arrow/Parquet if memory bounds are reached.
5. Deploy independent Streamlit service with independent security, upload-size, privacy and storage controls.


## V2 — Multi-ZIP comparison

Upload two to eight independent EPB Rhino Result Export ZIP archives at once. A new Compare buildings / variants section overlays thermal profiles, native national monthly indicators, and carrier ledger import versus export. Select the baseline ZIP to obtain absolute differences or percent differences; undefined percent differences are not imputed. Choose Hour, Day, Month, or Year for ISO 52016 thermal series. Optional user-entered conditioned floor areas enable kWh/m² comparisons. Zone temperatures and relative humidity require explicit zone selection and are never summed. The viewer reports differing or undocumented weather and calculation profiles and does not normalize climate, rerun calculations, or merge independent energy accounts.

The upload control allows 100 MiB per ZIP; the session limits comparisons to 8 ZIPs, 240 MiB compressed, and 700 MiB uncompressed. Duplicate identical archives are ignored. The new Python module is epb_results_visualizer/multi_compare.py. Tests run through the EPB Visualizer CI GitHub Actions workflow.
