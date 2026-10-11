# P6.3F — Verified live open GeoSphere 10-minute solar evidence (Graz 2005–2014)

**2026-10-11**. **Scientific result:** QC-accepted **GHI observational validation** available (primarily 2007–2014); no independently QC-accepted measured **DHI** in the two station identifiers. **DNI** is not included in the requested open variables. **No EPW approval**.

## Authoritative, reproducible evidence (not conversational estimates)

Successful GitHub workflow **[#38134438339](https://github.com/dmitrievii/building-energy-tools/actions/runs/38134438339)**, commit \`911c781d2b6ba410b175c176c57bee4663c67785\`. GitHub Actions artifact ID **11700138103**, artifact name \`ige-p6-3f-open-geosphere-10min-graz-ghi-diffuse-qc-2005-2014\`, 26 members including **20 original saved GeoSphere annual GeoJSON.gz datasets**, original metadata, original input source SHA, hourly and seasonal comparison tables and science report. Original provider endpoint \`https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min\`, parameter list \`cglo,chim,cglo_flag,chim_flag\`, original metadata SHA-256 \`4e26ca5dc4ae875cc7b3e9e31a83d641ca3083de141d342fa587e5f5ee156903\`. All four original science-derived CSV SHA-256 values match the report embedded in the archive. Original source rights provider CC BY 4.0; dataset-specific attribution applies.

All 20 original station-year source downloads succeed. However station metadata reveal **ID 30 type COMBINED** \`Graz Universität/Heinrichstraße\`; **ID 16412 type INDIVIDUAL**, \`group_id=30\`, Graz Universität. **Every UTC timestamp, cglo, chim, cglo_flag and chim_flag source array is identical between IDs 30 and 16412 for all ten years**. Consequently only **one independent observed station time series** is demonstrated, not two geographically independent series, and no averaging/replication across 30 and 16412 is scientifically justified.

## 1. Original source quality (individual Graz original stream)

Flags interpreted using original provider quality legend:
\`0 = ungeprüfte Daten\` (NOT good);
\`10,11,12,20,21,22\` = checked, depending on original automatic/manual/modified/original status.
A period is observed/QC-accepted only with all **6 of 6** ten-minute input values and accepted q21 flags on a single parameter. \`chim\` is not considered approved merely because some original field values are non-null.

| Year | original 10-minute labels | QC-accepted cglo labels | QC-complete GHI hours under start-label hypothesis | QC-accepted chim labels |
|---|---:|---:|---:|---:|
| 2005 | 52,560 | 0 | 0 | 0 |
| 2006 | 52,560 | 20,926 | 3,480 | 0 |
| 2007 | 52,560 | 52,025 | 8,664 | 0 |
| 2008 | 52,704 | 52,136 | 8,688 | 0 |
| 2009 | 52,560 | 52,553 | 8,758 | 0 |
| 2010 | 52,560 | 52,546 | 8,756 | 0 |
| 2011 | 52,560 | 52,537 | 8,755 | 0 |
| 2012 | 52,704 | 52,699 | 8,782 | 0 |
| 2013 | 52,560 | 52,520 | 8,750 | 0 |
| 2014 | 52,560 | 52,560 | 8,760 | 0 |

\`cglo\`: 73,393 fully-qualified **hourly** cells across 2005–2014 (73,393 / 87,648 = 83.736%). Over 2007–2014, 69,913 / 70,128 hours (about **99.69%**) QC-complete. 2005 zero QC-approved source hours; 2006 partial. Qualified 10-minute source counts are explicitly distinct from hourly complete counts.

\`chim\`: **zero** QC-accepted individual ten-minute records over all 2005–2014 source-year windows. Its flag always \`0\` or null; source values sometimes non-null in 2006–2009 but **not authenticated by provider QC**, and are frequently identical to GHI during night/cloudy weather. No valid DHI-vs-NASA ground score can be claimed. The instrument/parameter physical definition \`Himmelsstrahlung\` also needs separate original-source verification.

## 2. NASA POWER original 2005–2014 satellite/reanalysis reference vs observed GHI

Use fixed preregistered NASA POWER point \`graz_station30\` at 47.08°N, 15.45°E. The P6.3E original NASA hourly CSV matches its archived science-report SHA-256. This is a **model/satellite-vs-independent-ground** comparison, not validation against a second ground radiometer, and not two independent stations. Native source timestamps UTC.

| Unresolved ten-minute time support | Paired QC-complete hours | Pearson r | MAE (kWh/m² per hour) | RMSE | Bias POWER minus station |
|---|---:|---:|---:|---:|---:|
| \`record_start\` (working hypothesis) | 73,393 | 0.9393704 | 0.0383689 | 0.0810568 | −0.0114482 |
| \`record_end\` (alternative hypothesis) | 73,384 | 0.9387299 | 0.0388717 | (see source original CSV) | −0.0114505 |

**Do not select record-start simply because it has better r or MAE.** The official interval position (start/end/center) of GeoSphere ten-minute \`Mittelwert\` must be established from provider metadata/documentation. The previous P6.3D \`cglo_j\` daily solar 23–23 UTC quality reference may support a non-independent internal consistency check, not a second observatory validation.

The screened GHI performance may support building-climate historical source-validation claims, but **not** independent DHI/DNI skill, correct partitioning or future EPW scientific closure.

## 3. P6.3F next gates, prioritization

1. **GHI source-instrument time support:** confirm 10-minute averaging label convention through official GeoSphere product documentation; quantify 2007–2014 daytime-only and 10-year metrics, and check QC-approved 10-minute GHI integrated against original daily \`cglo_j\` in its documented UTC 23–23 aggregation window.
2. **DHI source gap:** open \`chim\` cannot be accepted where q21=0 on every record; independently measured DHI still absent. Research alternative original ground radiometry source (ARAD, other public radiometry network, or later source) if the publication needs observed DNI/DHI.
3. **No double-counting:** combined station #30 and individual #16412 original observed arrays are byte-value-identical for the requested four parameters, across ten years; treat as alias, not separate validation.
4. **Paper evidence:** log available historical GHI skill, missing original DHI QC, radiation-partition uncertainty and data-use/licensing limitations explicitly.

**Status:** technical source retrieval PASS, observed historical GHI benchmark PRELIMINARILY PASS under unconfirmed ten-minute time support. Independent DHI and measured DNI validation NOT ACHIEVED; EPW production readiness FALSE. Neither the ARAD contact request nor any other custodian email has been sent.
