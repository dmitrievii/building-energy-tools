# Streamlit Community Cloud deployment handoff

Stage: `WEB-0.8`

This document defines the intended beta deployment coordinates for Climate Analyzer. It is an operational handoff, not publication approval.

## Deployment coordinates

- Repository: `dmitrievii/building-energy-tools`
- Branch: `main`
- Entrypoint: `tools/climate_analyzer/app.py`
- Python: `3.12`
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
4. Open Advanced settings and explicitly select Python `3.12`.
5. Do not add secrets unless a future reviewed feature requires them.
6. Prefer a descriptive custom subdomain. Current candidates are `building-climate-analyzer` and `climate-analyzer`; availability must be checked in the Streamlit UI at deployment time.

The deployment should not be intentionally promoted as public beta until `website/PUBLICATION_CHECKLIST.md` is cleared. The current machine-readable release state remains `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED`.

## Why root configuration matters

Community Cloud executes `streamlit run` from the repository root even when the app entrypoint is in a subdirectory. Streamlit's deployment documentation also requires `.streamlit/config.toml` to remain at repository root. For that reason, the former tool-local configuration was removed in `WEB-0.8`.

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
