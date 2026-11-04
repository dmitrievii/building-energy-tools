# Real-station historical point-year: development result, 2 November 2026

The existing H1 → S1 method successfully generated a complete 2021 historical
point-year at Graz from four real GeoSphere stations. This closes the first
real-station integration example; it does not establish arbitrary-year
availability or independent interpolation accuracy.

## Result and sources

Target: 47.0707 N, 15.4395 E; nominal target height 375 m; fixed UTC+1;
actual calendar year 2021. Source sensor elevations and common vertical datum
remain unconfirmed proxies. No equations or calibration were fitted or changed.

| Selected real station | ID | Admitted T hours | Admitted RH hours | Admitted absolute-pressure hours |
| --- | --- | ---: | ---: | ---: |
| Graz Universität | 16412 | 8760 | 8760 | 8760 |
| Graz Straßgang | 16413 | 8760 | 8760 | 8760 |
| Laßnitzhöhe | 16511 | 8760 | 8760 | 8760 |
| St. Radegund | 16411 | 8760 | 8760 | 8760 |

Five candidates were checked in the unchanged metadata/distance order. Graz
airport 16400 was rejected: one T/RH hour is missing, despite complete pressure.
No extra selection based on target-weather error was performed. The target is
inside the selected donor hull and altitude envelope; these are geometric
diagnostics, not accuracy or uncertainty estimates.

The exported EPW has 8 headers, 8760 unique calendar hours and 35 fields per row.
SHA256: `889294fc7bd9384d22a482564c4967a83968623ef42bb561e3d37351e2022f25`.
Existing EPW format, bounds and component checks pass. The maximum monthly
vapour reconciliation residual is approximately `7.11e-15 hPa`.

T, pressure, water vapour, RH and dew point use the station interpolation and
active height corrections. Wind, radiation, cloud and liquid rain retain the
original ERA5-derived / NASA POWER background. That background is at 47.0 N,
15.5 E, height 467 m, approximately 9.10 km from the requested point. Its fields
are not station-interpolated or height-corrected. No complete observed
station-only EPW is claimed for any selected donor.

The live run took approximately 107.65 s in this environment: one metadata
response, ten successful original station-data responses, and subsequent
background acquisition, admission, calculation and packaging. This is one
observed runtime, not a latency guarantee.

## Negative cases preserved

| Case | Checked stations | Fully eligible | Result |
| --- | ---: | ---: | --- |
| Disclosed Graz 2023 regression | 20 | 1 | EPW blocked, unchanged |
| New Graz 2025 development request | 20 | 0 | EPW blocked |
| Graz 2021 development request | 5 | 4 | Mixed-source EPW admitted |

For 2023, many stations return null values on 31 December; fresh boundary
responses reproduce that source behaviour. For 2025, year-end observations
exist, but many stations have 24 missing or QC0 observations on 18 December.
These are source availability/quality failures, not an optimizer failure.
Other stations have additional gaps or no pressure measurement. The reports
distinguish numeric, missing, out-of-bounds, missing-QC, rejected-QC and
definition-blocked hours. QC0 was not admitted or converted into reviewed data.

The 2021 year was checked after the 2025 failure and a disclosed availability
probe. This adaptive **development** choice is recorded in the protocol. It is
not a newly preregistered independent validation sample. AT 2018 and IV1 2022
remain unopened; old 2013/2014 examples were not used for tuning.

## Software changes

1. S1 acquires one original catalogue for a search and retains the same bytes
   inside each H1 station packet. Repeated metadata HTTP calls are avoided;
   metadata definitions, units, QC, station identity and replay guards remain.
2. Progress reports the admitted donor count after every completed check.
3. S1 displays each checked station's admitted T/RH/pressure hours and coverage
   blockers. The table and detailed field counts are retained in its JSON/ZIP.
4. A station's ability to provide S1 core inputs is shown separately from its
   ability to provide a complete H1 station-only EPW.
5. The original positive 2021 and negative 2025 inputs have an executable,
   network-free replay. Existing 2023 failures and grid-donor tests remain.

The four-donor rule, nearest-20/100 km/1500 m limits, frozen P8.2F equations,
Buck-water convention, pressure transfer and monthly moisture objective are
unchanged. No automatic R1/B4/P2 promotion or station-gap filling was added.

## Reproduction

From the repository root, install `tools/climate_analyzer/requirements.txt`, then:

```bash
PYTHONPATH=tools/climate_analyzer:research/ige_cmip6 python research/ige_cmip6/at_station_usability_replay.py --out outputs/at-station-replay
```

`research/ige_cmip6/at_station_usability_20261102.json` registers requests and
SHA256 identities. The retained EPW is
`research/ige_cmip6/at_graz2021_point_original_output_20261102.epw`.
Original source packets, background bodies and exploratory probes are stored
alongside it. `deployment/audits/ige-at-station-usability-20261102/` contains
source coverage, the actual 2021 report, replay results and verification receipt.

Replay reproduces the 2021 EPW byte-for-byte in the local pinned environment.
Cross-environment checks use the already established EPW readback precision;
the scientific state constraints and nonthermal/header equality are unchanged.

## Qualification and next gate

59 distinct targeted tests passed across the local runs: existing H1/S1
regressions, source/QC invariance, metadata reuse, actual-source replay, real
point UI/download controls and F1 base/reference guards. Pinned dependencies,
Python compilation and whitespace checks pass. Full GitHub CI remains a
separate pending check.

| Dimension | Status |
| --- | --- |
| Code and source execution | Complete actual-year station acquisition, assembly and offline replay demonstrated |
| Physical admissibility | Existing conditional T/p/e/RH/Td and monthly-mean constraints pass |
| Independent accuracy | Not newly validated; no target-truth accuracy scores published |
| Operational readiness | Restricted historical example; public deployment and generalized availability not qualified here |

The resulting point EPW is accepted as an F1 annual base. A grid-background
climatology is still rejected as a substitute for that point's station-derived
climate reference. The next block is automatic construction/admission of a
compatible multiyear point reference, followed by F1 on that base. That work,
TMY interpolation, independent AT/DE/CH validation and EnergyPlus qualification
are not declared complete by this result.

All work is isolated from `main`. CI is launched for the review branch; long
workflow results are left for the user to request, without polling.
