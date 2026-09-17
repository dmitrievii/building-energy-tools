# Climate Analyzer 0.7.1 — GeoSphere Precipitation/Snow Live Smoke

Status: implementation branch

## Goal

Add provider-backed operational validation for the 0.7 precipitation/snow route without making the core Climate Analyzer CI depend on GeoSphere availability.

The existing general live browser audit verifies deployment propagation, catalog identity, map behaviour, responsive layout and uncaught browser errors. It does not load a measured GeoSphere interval or exercise the `Precipitation and Snow` page. 0.7.1 closes that validation gap with a separate workflow.

## Isolation contract

The smoke workflow is deliberately separate from `Climate Analyzer CI` and `Climate Analyzer Live Browser Audit`.

A GeoSphere outage, provider timeout or transient public-network failure may make this operational smoke red, but it does not change scientific unit/regression results and is not part of the core deployment gate.

The workflow runs:

- when its own smoke implementation changes in a pull request;
- after relevant Climate Analyzer changes land on `main`;
- on manual dispatch;
- once per week as a provider-health sentinel.

## Provider probe

`deployment/geosphere_precip_snow_provider_probe.py` uses the production GeoSphere adapter against the official `klima-v2-10min` API.

It:

1. validates live resource metadata and units;
2. prefers the existing Graz/Universitaet integration station (`11240`), then falls back to a bounded list of recent active stations;
3. requests a small recent provider interval for only `rr`, `rrm` and `sh`;
4. requires numeric native observations for all three quantities;
5. requires at least one strict-complete canonical hour for all three quantities;
6. verifies annual precipitation and snow-season calculations are non-empty;
7. writes a transient JSON fixture containing station identity and the same default 30-day UI interval used by the public application.

No measured provider values are committed as golden data.

## Browser smoke

`deployment/geosphere_precip_snow_live_smoke.mjs` opens the deployed Community Cloud application and performs a real user route:

1. open `GeoSphere Austria`;
2. filter to the provider-probed station;
3. load the measured interval through the public UI;
4. wait for `Precipitation and Snow` to become available;
5. open the page and verify the dual-resolution caption;
6. verify all expected 0.7 analysis families are available;
7. exercise annual precipitation indices;
8. exercise independently measured precipitation duration;
9. exercise native precipitation-record occurrence;
10. exercise native snow-cover duration;
11. exercise July–June snow-season indices.

The smoke fails on missing functionality or uncaught browser page errors. Browser HTTP 4xx/5xx responses are recorded as evidence rather than treated generically as fatal because Streamlit itself may emit unrelated platform requests; the functional route is the governing assertion.

## Evidence

Each run uploads:

- `provider-fixture.json`;
- `geosphere-precip-snow-live-smoke.json`;
- `LIVE_SMOKE.md`;
- final or failure screenshot.

Evidence retention is 14 days.
