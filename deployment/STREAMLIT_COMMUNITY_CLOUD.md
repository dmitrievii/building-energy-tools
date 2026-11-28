# Streamlit Community Cloud deployment handoff

Stage: `WEB-0.8`

This document defines the intended beta deployment coordinates for Climate Analyzer. It is an operational handoff, not publication approval.

## Deployment coordinates

- Repository: `dmitrievii/building-energy-tools`
- Branch: `main`
- Entrypoint: `tools/climate_analyzer/app.py`
- Existing production Python (observed 2026-11-28): `3.14.10`; Python `3.12` remains the legacy CI baseline.
- R2.21 HF1 production admission requires clean Python 3.14 wheel installation, import, scientific/report regression and browser qualification. Do not infer live deployment success from CI alone.
- Dependency file: `tools/climate_analyzer/requirements.txt`
- Streamlit configuration: `.streamlit/config.toml` at repository root

The app must be launched from the repository root for local cloud-parity checks:

```bash
streamlit run tools/climate_analyzer/app.py
```

## Community Cloud setup

In Streamlit Community Cloud:

1. Create a new app from the GitHub repository.
2. Select branch `main`.
3. Set the entrypoint to `tools/climate_analyzer/app.py`.
4. For a new deployment, select a qualified interpreter explicitly. Preserve the existing production application's Python 3.14 configuration and URL during HF1 recovery.
5. Do not add secrets unless a future reviewed feature requires them.
6. Prefer a descriptive custom subdomain. Current candidates are `building-climate-analyzer` and `climate-analyzer`; availability must be checked in the Streamlit UI at deployment time.

The deployment should not be intentionally promoted as public beta until `website/PUBLICATION_CHECKLIST.md` is cleared. The current machine-readable release state remains `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED`.

## Why root configuration matters

Community Cloud executes `streamlit run` from the repository root even when the app entrypoint is in a subdirectory. Streamlit's deployment documentation also requires `.streamlit/config.toml` to remain at repository root. For that reason, the former tool-local configuration was removed in `WEB-0.8`.

## R2.21 HF1 dependency recovery

The 2026-11-28 server log identified Python 3.14.10 and source builds of NumPy 1.26.4 and ContourPy 1.3.2. The exact missing module in the subsequent Plotly traceback was redacted. Keep Python 3.12 pins unchanged and use NumPy 2.3.5 and ContourPy 1.3.3 on Python 3.13 or newer. The Python 3.14 gate allows the pure-Python PsychroLib sdist, requires wheels for remaining packages, records the resolved inventory, exercises imports, UTCI, contour generation, PDF/PNG exports, the regression suite and Chromium charts. These checks are a candidate qualification, not evidence that the actual Community Cloud build has succeeded.

## Post-deployment evidence to collect

Record the following before any public promotion:

- final `*.streamlit.app` URL;
- deployment date and deployed Git SHA;
- Python version shown by the deployment configuration;
- build-log result;
- `/ _stcore/health` availability where applicable;
- visible beta/version/disclaimer text;
- actual network destinations observed in browser developer tools;
- cookies and local/session storage entries;
- OpenStreetMap attribution rendering;
- Climate.OneBuilding source/provenance rendering;
- mobile/tablet/desktop screenshots;
- keyboard-only navigation observations;
- responsive overflow defects;
- accessibility findings and unresolved exceptions.

## Promotion rule

A successful Streamlit build is necessary but not sufficient for publication. Technical deployment readiness and publication clearance are separate gates.

References reviewed for this handoff: Streamlit Community Cloud documentation on file organization, app dependencies, deployment, sharing/indexability, app settings and Python-version selection (reviewed 2026-09-10).
