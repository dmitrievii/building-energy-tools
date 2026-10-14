# P8.1F — Event-Based Inversion Prediction & Spatially Independent Terrain Validation

**Scientific pre-result protocol (frozen 2026-10-14).** No claim about predictive skill is made until original source verification and held-out tests complete.

## H1: prospective inversion events, NOT retrospective diagnosis

- Reference: NOAA IGRA v2.2 vertical temperature and geopotential-height profiles from single launches, stations Vienna Hohe Warte, Payerne, Innsbruck, Oberschleißheim; period 2017–2020.
- Label: same-sounding lower-1.2km inversion with >=0.5 K measured warming above lowest QC-valid temperature below 150m AGL; require measured level >=250m AGL. This is the preexisting P8.1E algorithm (shallow layers may be missed).
- Predictors available BEFORE the event: nominal target hour/season, 10–26 hour preceding launch inversion indicator and strength, near-surface temperature, wind and dew point depression, time since preceding launch. Current target sounding must never supply predictors.
- Train on 2017–2018 launches from sites other than target. Test 2019–2020 on entire excluded target radiosonde site. Models L2 logistic regression with training-set-only median imputation and z-scoring; baseline station-independent, same-hour/season climatological probability, and prior-inversion persistence. No externally downloaded meteorological analysis or weather forecast is used; predictions are `prior-sounding conditioned`, not operational local-EPW forecasting.
- Primary endpoint: paired station-held-out Brier score relative to training-only hour-season climatology, plus logloss. Missing/sparse stations explicitly reported. No adoption on worse Brier.
- Controls: strict chronological timestamp, >=10h and <=26h gap, availability of previous good sounding; no target station data in fitted coefficients, no post-2018 data anywhere in fitting. Nominal 00/12 UTC is not necessarily exact balloon release, reported forecast horizon approximate.

## H2: external entire-region terrain validation

- Source MeteoSwiss SwissMetNet monthly mean T (`tre200m0`) original 2011–2020, STAC metadata-driven station selection; Austria GeoSphere 1991–2010 sole source of lapse calibration; **frozen** exploratory P8.1D terrain coefficients precomputed from Austrian folds and stored with provenance checksum. No Swiss temperatures fit any coefficient.
- Swiss groups fixed *before observing results*: western longitude <7.5°E, central 7.5 to <9.0°E, eastern >=9.0°E.
- In each fold all Swiss stations from target's longitude block are excluded from donor list, not just target station; regions are entire geography holdouts. Contemporaneous donors outside heldout region supply **observed** monthly temperatures, so this is spatial hindcast, *not forecasting future weather*.
- Real Mapzen Terrain Tiles DEM sampled at every Swiss station, radial 250m,1.5km,5km,10km. Terrain feature coefficients frozen from Austria P8.1D; station height from MeteoSwiss metadata, never overwritten by DEM; corrupt raster points fail closed.
- Models: nearest-eight IDW raw; IDW constant -6.5K/km; monthly Austria-frozen regional lapse; regional lapse plus Austria-frozen 4-feature cold/warm ridge/valley correction bounded ±1K. Matched target-months, 0/50km donor-radius exclusions, same 350km max distance. Report station, region, topology, height, MAE/RMSE, station-paired bootstrap; three regional blocks too few for valid independent regional bootstrap CI.

## Decision rules

1. Both independent source pipelines must complete for full phase closure.
2. Operational inversion forecast **not validated** just by correctly detecting measured profiles or positive score at 2 sites.
3. No terrain-production promotion without significant reproducible region-blocked transfer benefit; prefer P8.1B if no gain.
4. No retrospective selection of sites, region thresholds, feature set or coefficients in response to held-out performance. Fixes to upstream schema and transport permitted only with documented changes.
5. Original observation archives and raw DEM tiles not committed or published: only independent derived aggregate statistics, SHA-256 and source URL provenance.

## Data source attribution

NOAA IGRA v2.2: https://www.ncei.noaa.gov/pub/data/igra/ ; format https://www.ncei.noaa.gov/pub/data/igra/igra2-data-format.txt
MeteoSwiss STAC: https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn
Terrain Tiles/Tilezen: https://registry.opendata.aws/terrain-tiles/; mosaic attribution https://github.com/tilezen/joerd/blob/master/docs/attribution.md
Original Austrian station normals CC BY 4.0; origin documented P8.1A/B.