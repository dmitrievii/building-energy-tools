# CLIMATE-GEOSPHERE-0.1 — GeoSphere Austria historical station adapter

## Scope

This stage adds a provider adapter for GeoSphere Austria's public, quality-checked historical station dataset:

- API host: `https://dataset.api.hub.geosphere.at`
- API version: `v1`
- resource: `klima-v2-10min`
- type/mode: `station/historical`
- native temporal resolution: 10 minutes
- provider timezone: UTC
- dataset DOI: `https://doi.org/10.60669/8fya-7x87`
- licence: Creative Commons Attribution 4.0 International

The legacy `klima-v1-10min` resource is deliberately not used. It stopped receiving updates in 2024. The raw/near-real-time TAWES endpoint is also not used as the historical source because this stage targets the quality-checked `klima-v2-10min` archive.

This is an **adapter stage**, not yet a public UI/map stage.

## Supported provider quantities

The adapter resolves exact parameter names from the provider metadata and verifies the expected units before using a field. Current supported mappings are:

| GeoSphere | Meaning | Provider unit | Canonical field | Conversion |
|---|---|---:|---|---|
| `tl` | air temperature 2 m | °C | `dry_bulb_temperature_c` | identity |
| `rf` | relative humidity | % | `relative_humidity_pct` | identity |
| `p` | station pressure | hPa | `atmospheric_station_pressure_pa` | × 100 |
| `ffam` | 10 m wind speed, arithmetic mean | m/s | `wind_speed_m_s` | identity |
| `dd` | wind direction | ° | `wind_direction_deg` | identity |
| `rr` | precipitation sum | mm | `liquid_precipitation_depth_mm` | identity |
| `sh` | total snow depth | cm | `snow_depth_cm` | identity |
| `cglo` | mean global radiation | W/m² | `global_horizontal_radiation_wh_m2` | × 10/60 h |
| `chim` | mean sky/diffuse radiation | W/m² | `diffuse_horizontal_radiation_wh_m2` | × 10/60 h |

The radiation conversion is required because the canonical extensive quantities are interval irradiation in Wh/m², whereas GeoSphere publishes the 10-minute mean irradiance in W/m².

DNI is not synthesized from the available station fields in this stage. Dew point, wet-bulb temperature, humidity ratio and enthalpy are likewise not claimed as provider measurements; they can be derived later by the existing psychrometric layer when the required primary observations are available.

## Provider metadata is authoritative

The code does not treat the mapping table alone as sufficient. `supported_parameter_mapping()` checks the current metadata response for each supported provider parameter and validates its unit. If GeoSphere changes the semantic unit of a mapped field, the adapter fails closed.

Station metadata are normalized to:

- provider station ID;
- station name;
- WGS84 latitude/longitude;
- elevation;
- Austrian state/region;
- provider validity interval.

## Request boundaries

The public adapter:

- accepts only HTTPS on `dataset.api.hub.geosphere.at`;
- does not follow provider redirects;
- bounds response size;
- estimates requested datapoints before a network call;
- uses a conservative local request cap of 200,000 datapoints;
- currently requests one station per canonical dataset;
- preserves missing values rather than treating them as zero.

The official API's request-size accounting is based on parameters × time steps × stations. A later UI stage may batch long ranges, but batching must preserve these same limits and provider rate limits.

## Time semantics

GeoSphere historical timestamps are parsed as timezone-aware UTC and are never rewritten to the EPW typical-year calendar. The canonical dataset is therefore marked:

- `calendar_mode="historical"`;
- `native_interval_minutes=10`;
- `timezone_name="UTC"`.

Because the dataset contains a mix of instantaneous/state, mean and accumulated quantities, the dataset-wide timestamp interval semantic is left provider-specific/unknown rather than making a false universal claim. Quantity-specific aggregation semantics remain defined by the canonical variable registry.

## Provenance

Every returned `CanonicalClimateDataset` records:

- GeoSphere Austria as provider;
- `klima-v2-10min` dataset identity;
- station ID and name;
- exact request reference when data were downloaded;
- retrieval timestamp;
- CC BY 4.0 attribution and dataset DOI;
- the radiation unit conversion note.

## Next stage

After this adapter is qualified, the next stage can add a GeoSphere station-selection experience and request batching for year-scale ranges. Detailed Year and Historical Comparison should consume the canonical dataset rather than introduce a second provider-specific analysis path.
