# IGE P9.1H — Amendment B: regional Alpine-Central-European scope (Austria, Germany, Switzerland)

**2026-10-17. User-directed scope change, prospective and decisive.** Supersedes Amendment A's choice of Finland and Netherlands as *active research cohorts*. Original H1 preregistration, A, and failure reports are historical and remain available unmodified. This is a distinct new frozen regional qualification task, not retroactive relabeling of previously inspected 2018/2021 cohorts.

## Scientific objective

Finish the **current regional version** of physically conditional 2 m temperature reconstruction based on ERA5 + geophysical orography + an explicitly bounded near-surface cold-pooling approximation, restricted to **Austria (AT), Germany (DE), Switzerland (CH)**. No international source expansion, no unrestricted arbitrary-location/global performance claim, and no worldwide validation during active software development. Reserve worldwide climatic-zone and geographic generalization exclusively for an independent **publication-stage research paper**, with its own preregistration, novel holdouts and assessment of extrapolation errors.

**Retired from active P9.1H testing:** KNMI Cabauw/NL (single provider HTTP 429 retained in archived report), SMEAR II Hyytiälä/FI (original source readback retained, QC not fully established), DOE ARM/US, any additional country or mast hunt. No more retries to these sources. Neither 2018 Nordic source sample nor planned 2021 Nordic holdout is relabeled as a successful AT/DE/CH trial; preserve its untouched status.

## Three providers already supported in this repository

| Region | Native provider and prior IGE evidence | Qualified temperature role and explicit caution |
|---|---|---|
| AT | GeoSphere Austria `klima-v2-1h`; P9.1B/D/F original station metadata, `tl`, `tl_flag`; actual hourly QC at registered sites | Development/reference + 2022 regional model evidence, site/day overlap with P9.1D acknowledged |
| DE | DWD CDC historical hourly air temperature `STATIONS_ID`, `MESS_DATUM`, `TT_TU`, `QN_9`; P9.1G original 2019/QN=3 results | **Fresh frozen 2022** benchmark, with each observation quality tier checked; QN3 != QN10, original G1 QN10 SOURCE BLOCKED remains unchanged |
| CH | MeteoSwiss SwissMetNet OGD STAC `ch.meteoschweiz.ogd-smn` hourly `h` historical and station metadata; P8.1E / F Swiss monthly sources already implemented | Fresh frozen **hourly 2022** station T2m if original UTC, identifier and QC semantics pass. Previously validated monthly 2011–2020 series does **NOT** validate hourly inversion |

Official sources: `https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h`; `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/`; `https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn`.

MeteoSwiss station sensor temperature is `tre200h0` only if confirmed by original provider parameter inventory (do **not** infer by analogy with 10-minute `tre200s0` or monthly `tre200m0`). Swiss 150–230m mast source is optional only if existing provider files are immediately accessible and is not a prerequisite; a station T2m residual is **not** a collocated vertical inversion measurement.

## Frozen minimal regional evaluation

- Only **2022-01-10..16** and **2022-07-10..16**, UTC, 336 nominal station-hours per site. These are new regional evaluation windows registered by this amendment **before any P9.1H23 regional 2022 new-model error calculation**.
- Up to **three stations per country**, selected on **provider metadata + altitude + independently derived terrain morphology and coverage**, never by target temperature or model residual. Target strata: a plain/lowland, a valley/basin, a plateau/high station *where source geography permits*. Up to 9 source-site series, **not** a nationwide station census.
- AT 2022 *may overlap previously inspected P9.1D 2022 data*, so identify as **historical reference / not novel blind**. DE 2019 previously scored is context only, do not rescore it as new independent holdout. DE/CH 2022 regional candidate outcomes are first-read only if these sites/years are genuinely unscored for this candidate. Never claim strict world-scale holdout.
- Freeze B0 ERA5 native grid temperature; B1 6.5 K/km independent ARCO regular-grid orography; B2 Open-Meteo altitude-adjusted black-box; H first fixed physically guarded P9.1H23 candidate. No more model search, donor tuning, feature ablation or coefficient fit on 2022 outcome. No 2021 untouched Nordic holdout access.
- Same original QC-qualified observations/timestamps for **all** methods. Each country×season reports number of paired hours, MAE, RMSE, bias and worst-group deterioration from best baseline. Classify negative results **FAIL/NOT ESTABLISHED**; never drop a problematic station after seeing the result.
- Physically actual `T(z_upper)>T(z_lower)` is called inversion **only when simultaneous collocated or properly documented vertical levels are available**. Spatial low/high station-temperature contrast supports **terrain-associated temperature structure**, not an observed local inversion classification.

## Definition of done and strict stop

A single historical benchmark report with all admitted AT/DE/CH source tiers, the frozen model-vs-baseline comparison, station/season-level negative outcomes and region-limited conclusion. In case Swiss or German native hourly QC/API is blocked, state region BLOCKED and finish the limited experiment as inconclusive, without scouting elsewhere. Regional claim may be as weak as **not established**. No more test variants and no global work.

Use one contract CI and one source-verified regional benchmark only; no automatic re-runs for each commit, no background retries. Existing P9.1H source/algorithm scripts stay for provenance; inactive old foreign workflows must not be invoked.

**Mandatory status:** `regional_AT_DE_CH_qualified=false` until actual measured comparative score passes; `near_surface_inversion_model_qualified=false`; `global_arbitrary_point_weather_qualified=false`; `production_epw_ready=false`. No main merge without explicit user permission.
