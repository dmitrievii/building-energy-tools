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

The first provider-backed run demonstrated that recent September intervals expose numeric `rr` and `rrm` but `sh` is entirely missing at the sampled stations. The smoke therefore must not assume that the current/default UI period is a valid snow fixture.

The revised probe:

1. validates live resource metadata and units;
2. tries a bounded set of familiar stations and then active/high-elevation candidates;
3. searches short recent **historical winter** windows inside each station's published validity interval;
4. requests only `rr`, `rrm` and `sh`;
5. requires numeric provider-native observations for all three quantities;
6. requires at least one strict-complete canonical hour for `rr` and `rrm`;
7. records whether strict-complete hourly `sh` exists, but does **not** require it because 0.7 intentionally allows native snow metrics without an hourly snow explorer;
8. verifies annual precipitation and native snow-season calculations are non-empty;
9. writes the exact selected winter dates into a transient JSON fixture for the browser smoke.

The search is capped by station and total-interval limits so a provider problem cannot turn the smoke into an unbounded API crawl.

No measured provider values are committed as golden data.

## Browser smoke

`deployment/geosphere_precip_snow_live_smoke.mjs` opens the deployed Community Cloud application and performs a real user route:

1. open `GeoSphere Austria`;
2. filter to the provider-probed station;
3. explicitly set `From date (UTC)` and `Through date (UTC)` to the validated winter fixture;
4. load the measured interval through the public UI;
5. wait for `Precipitation and Snow` to become available;
6. open the page and verify the dual-resolution caption;
7. verify all native precipitation/snow analysis families are available;
8. require `Snow depth explorer` only when the provider probe found strict-complete hourly `sh`;
9. exercise annual precipitation indices;
10. exercise independently measured precipitation duration;
11. exercise native precipitation-record occurrence;
12. exercise native snow-cover duration;
13. exercise July–June snow-season indices.

The smoke fails on missing functionality or uncaught browser page errors. Browser HTTP 4xx/5xx responses are recorded as evidence rather than treated generically as fatal because Streamlit itself may emit unrelated platform requests; the functional route is the governing assertion.

## Evidence

Each run uploads:

- `provider-fixture.json`, including failures when provider fixture selection itself fails;
- `geosphere-precip-snow-live-smoke.json`;
- `LIVE_SMOKE.md`;
- final or failure screenshot.

Evidence retention is 14 days.
