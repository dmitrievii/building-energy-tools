# IGE P9.1H — H1B original KNMI source blocked; H2/H3 first independent physics model

**2026-10-17 | Post-registration evidence. Research only.** Original H1 requirements are intact, including the strictly blinded 2021 2×7-day windows. No substitute site or shifted sample.

## H1B: genuine KNMI Cabauw result

Official manually validated Cabauw LB1 `cesar_tower_meteo_lb1_t10/v1.3` at `https://dataplatform.knmi.nl/dataset/cesar-tower-meteo-lb1-t10-v1-3` is the fixed second site. KNMI public access documentation at `https://developer.dataplatform.knmi.nl/open-data-api` publishes a shared anonymous API key and explicitly warns against repeated polling, as well as describing a separate account-bound registered key.

**One original attempt:** [GitHub Actions #39062235255](https://github.com/dmitrievii/building-energy-tools/actions/runs/39062235255) using public anonymous key retrieved directly from official developer page. Authenticated user never supplied credentials. Provider docs body SHA256 `d99e5fddc0a1b279da13cdf288d7c96364ac46e6eede76f88a46bb6275eda237`. Original KNMI dataset file-list request returned **HTTP 429 Too Many Requests** before any 2018 filenames/source meteorological files were acquired; provenance artifact **12112035840** records blocked state. Since the key's rate limit is shared, no claim that the resource itself lacks observations. H1 Cabauw genuine-source gate **ACCESS RATE LIMITED**. Do **not** pretend this is a failed climate-skill score and do not silently select another source or rerun indefinitely.

**H1 scientific qualification remains OPEN** because two independent site×height datasets with native QC and source SHA have not yet been acquired. Hyytiälä 2018 source remains original readback but its sensor QC classification remains open as documented in `IGE_P9_1H1_FIRST_GENUINE_HYYTIALA_2018_PROFILE_SOURCE_READBACK_RU.md`.

## Minimal H2/H3 physically conditioned research candidate

The first candidate (module `research/ige_cmip6/p9_1h23_physical_inversion_candidate.py`) is implemented in isolation from any observed 2018 temperature error score, before any 2021 holdout read. It is a bounded, explainable **cold-air-pooling adjustment of an independently computed 2m baseline**, NOT a free-air pressure-gradient inversion detector. Its predictors are **source-only**: UTC solar altitude computed for requested coordinate/time; cloud cover and wind speed at 10m from native ERA5; morphology-defined 0..1 cold-pool index from independent DEM; optionally separately verified snow cover. No observed tower-temperature predictor can be used at an arbitrary location.

Candidate:
- Solar altitude > -3 degrees: zero correction.
- No DEM cold-pool signal (open flat site): zero correction.
- Missing ERA5 cloud, wind, morphology: zero correction, explicit source-missing status.
- Otherwise radiative-cooling **proxy** `R=(1-C/100)^1.5`, wind mixing `M=1/(1+(u10/3)^2)`, depth/siting `D=DEM_cold_pool_index`; snow factor `S=1.20` only if verified snow, else `S=1.0` (explicit provenance difference). `ΔT = -min(1.25, 1.25 × R × M × D × S)°C`.
- `C` is ERA5 cloud cover percent, **not an actual measured longwave radiative flux**. `R` is a **phenomenological radiative-cooling proxy**, not physical energy-balance closure. Coefficients are frozen physical hypotheses and NOT optimized to German or Finnish temperature labels. A fixed -1.25°C floor is a research safety guard, not evidence of optimum performance.
- Comparison baselines: B0 raw ERA5 T2m, B1 independent ERA5 grid-height to site-height correction at -0.0065 K/m, B2 provider altitude T2m with explicit independent black-box sourcing.
- Scientific validation needs true observed 2m temperatures, valid native source QC, independent DEM morphology and matched ERA5 hourly source. **Hyytiälä 4.2m is NOT a 2m observed comparator**. Its 63m forest-canopy gradient is a separate observational inversion target. Cabauw flatland may produce zero cold-pool temperature correction (a legitimate null prediction, not measured skill). This cannot establish alpine arbitrary-point correction.

**Not done:** source-qualified H1 Cabauw measurements; snow source; validated DEM cold-pool index; true radiation budget; H2/H3 observed model MAE; independent 2021 heldout tests. These remain **BLOCKED/NOT QUALIFIED**. The new module and synthetic physics/unit tests validate contracts only. No production EPW or main merge.

## Minimal next gate

If real KNMI LB1 2018 data become available through an official registered key, verify the exact frozen 2018 source, QC, and profile layers. If source remains blocked, stop and retain H1 negative source-availability finding. Do **not** use 2021 data, broaden stations, or tune this candidate. The code is prepared for independent-source benchmarks, not deployed.
