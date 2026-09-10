# WEB-0.9 — Climate Analyzer runtime performance evidence

Date: **2026-09-10**

Target: `tools/climate_analyzer/app.py`

Scope: reduce the fixed CPU/memory cost of the empty Climate Analyzer landing page on Streamlit Community Cloud without changing scientific equations, thresholds, data transforms or chart semantics.

## Finding

Before WEB-0.9, `app.py` imported the map and scientific analysis stack at module import time. This meant a user arriving at the default **Upload EPW** screen paid the import cost of dependencies that were not yet needed, including Folium / streamlit-folium, Pandas, Plotly, the chart/comparison modules and other scientific modules.

The isolated import profiler identified large individual dependency footprints. These isolated timings are diagnostic only and are **not additive** because imported dependency graphs overlap. Representative pre-remediation observations included approximately:

- `streamlit_folium`: 1.14 s / 151 MiB max RSS;
- `pvlib`: 0.88 s / 171 MiB max RSS;
- `folium`: 0.68 s / 129 MiB max RSS;
- `climate_sources`: 0.56 s / 131 MiB max RSS;
- `charts`: 0.49 s / 120 MiB max RSS;
- `comparison`: 0.47 s / 120 MiB max RSS.

## Remediation

WEB-0.9 introduces explicit lazy dependency boundaries.

### Default landing path

At module scope, `app.py` now imports only the lightweight Python standard-library dependencies, Streamlit and `epw_climate_analyzer.ui_contract` required to render the shell/landing UI.

### Map path

`_ensure_map_dependencies()` loads Pandas, Folium, streamlit-folium, Climate.OneBuilding source helpers and catalog runtime helpers only after the user explicitly selects **Find climate**.

The **Upload EPW** path returns before the map dependency gate is entered.

### Analysis path

`_ensure_analysis_dependencies(...)` loads the general analysis/plotting stack only after an active EPW file exists and an analysis page is being rendered.

Solar support is a separate optional layer and is loaded only for pages whose derivation flags require solar data. The comparison module is loaded only for **Compare Climates**.

`ClimateFilePayload` is imported locally only when an active climate payload has to be created or type-checked; therefore the empty landing page no longer imports `climate_sources` merely to render.

## Measurement method

`deployment/runtime_performance_probe.py` is a reproducible probe executed on GitHub-hosted `ubuntu-24.04` runners with Python 3.12 and the pinned application requirements.

The primary startup metric is `streamlit.testing.v1.AppTest` first render of the default landing page in a fresh Python process. The same child process is run once more to record an ordinary Streamlit rerun. Process `ru_maxrss` records the maximum resident-set footprint observed by that AppTest process.

The probe also measures time until a local Streamlit `/_stcore/health` response. That number is retained as infrastructure evidence but **is not used as the application-render performance claim**, because the server health endpoint can become ready before the Streamlit script has rendered.

GitHub-hosted runners are shared infrastructure and exhibit timing variability. For this reason the result below is based on repeated baseline and optimized measurements rather than a single run.

## Baseline

Baseline commit containing the profiler but still using eager application imports:

`ebf5fff7ccc01ae98748a5b8d6e0f1cb2f8a9e0d`

Workflow run: `34518502394`

| Sample | First render [s] | Second rerun [s] | AppTest max RSS [kB] |
|---|---:|---:|---:|
| baseline 1 | 1.307712 | 0.139233 | 188376 |
| baseline 2 | 1.339853 | 0.145569 | 188516 |
| **median** | **1.323783** | **0.142401** | **188446** |

Observed baseline ranges:

- first render: **1.308–1.340 s**;
- max RSS: **188376–188516 kB**.

Artifacts retained by GitHub Actions at the time of this report:

- artifact `10168683693`, digest `sha256:7e7917d39df3dffaf2e8c0ca12dac35acdd4b837e53837156b32279e8675b681`;
- repeat artifact `10169179584`, digest `sha256:1e4d3e79b69513c761626772f78af1f79576b61084ef95a16bbac59f177f6615`.

## Optimized measurements

The same application lazy-import implementation was measured repeatedly after remediation. The app implementation is already present from commit `b1bf9af77ac8468e33998e8605e5e6651cc73642`; later commits add regression/evidence material without changing that startup implementation.

| Sample | First render [s] | Second rerun [s] | AppTest max RSS [kB] |
|---|---:|---:|---:|
| optimized 1 | 0.445900 | 0.157232 | 71112 |
| optimized 2 | 0.388157 | 0.138512 | 71488 |
| optimized 3 | 0.429831 | 0.153907 | 71280 |
| **median** | **0.429831** | **0.153907** | **71280** |

Observed optimized ranges:

- first render: **0.388–0.446 s**;
- max RSS: **71112–71488 kB**.

Artifacts retained by GitHub Actions at the time of this report:

- artifact `10168989684`, digest `sha256:d964717d03fc1daf2e4fc273c8315e0678b0e9de303e380ab1d0c94e591a8b71`;
- artifact `10169124899`, digest `sha256:7c5e8f8488b97a90da31ea6f9eb19c6fb9295a9b439e5704ef5c9d49cf2c7797`;
- repeat artifact `10169191319`, digest `sha256:88860b827ffb72a464c7d21540747e016f80d41e30289884caed624eb9c50edc`.

## Result

Using the medians of the repeated samples:

| Metric | Baseline median | Optimized median | Change |
|---|---:|---:|---:|
| first landing render | 1.323783 s | 0.429831 s | **−67.5%** |
| AppTest max RSS | 188446 kB | 71280 kB | **−62.2%** |
| second rerun | 0.142401 s | 0.153907 s | +8.1% |

The first-render median is approximately **3.08× faster**. The measured maximum resident-set footprint is approximately **2.64× lower**, a reduction of about **114.4 MiB** using 1024 kB/MiB.

The second-rerun values overlap the same approximately 0.14–0.16 s operating range. WEB-0.9 therefore makes **no claim of rerun-speed improvement**; its verified benefit is reduction of the initial unused dependency load and corresponding landing-page memory footprint.

## Functional regression evidence

The normal Climate Analyzer CI passed on the lazy implementation and includes a dedicated startup dependency contract.

`tools/climate_analyzer/tests/test_startup_dependency_contract.py` verifies that:

1. map/scientific heavy dependencies do not return to module-scope imports;
2. the Upload EPW branch returns before the map dependency gate;
3. the analysis dependency gate is entered before EPW derivation;
4. solar and comparison remain explicit optional dependency layers;
5. a fresh subprocess can load all lazy map, analysis, solar and comparison symbol sets;
6. the same subprocess builds a valid 24-hour EPW fixture and successfully executes `load_epw_from_bytes(..., include_psychrometrics=True, include_solar=True)`.

Current-head CI run `34519658891` completed **SUCCESS**, including compile, scientific/security/catalog/publication regressions, the lazy runtime gate, module-import smoke and repository-root Streamlit health.

## Scientific scope

No scientific equations, constants, passive-strategy thresholds, EPW parsing semantics, psychrometric equations, solar models, comparison calculations or expected scientific regression fingerprints were intentionally changed by WEB-0.9.

The change is execution architecture only: dependencies are loaded when their feature path is first required rather than on every initial application render.

## Operational policy

The full performance profiler installs the complete application environment and performs multiple fresh-process measurements. It is therefore retained as a **manual `workflow_dispatch` diagnostic**, not as a required test on every push.

The deterministic structural/runtime lazy-import regression tests remain part of normal Climate Analyzer CI.

## Deployment status

At the time this evidence was written, WEB-0.9 exists on `web-0.9-runtime-performance` and is **not yet the production `main` deployment**. Streamlit Community Cloud follows `main`, so a post-merge live browser replay is required before claiming the optimization is present on the public URL.
