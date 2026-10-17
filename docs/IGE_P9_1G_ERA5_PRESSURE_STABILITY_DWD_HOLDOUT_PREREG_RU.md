# IGE P9.1G — Atmospheric Vertical Stability & Independent Regional Validation

**Pre-registration: 2026-10-17; before any source DWD observed 2019 hourly temperature or vertical ERA5 2019 field is read or scored.** Parent P9.1F head `00dd23f70e700e729433332883450c9285ff8126`. P9.1F negative result permanently frozen.

## Hypothesis and boundary

ERA5 0.25° vertical **pressure-level** temperature and geopotential height may identify some warm-over-cold *resolved atmospheric layers* and explain when pure topographic lapse corrections are harmful. This is NOT a collocated near-surface inversion detector: 0.25°+pressure levels resolve free atmosphere rather than actual 2–200m cold-air pool. Below-ground pressure levels must be **excluded before analysis**. Never fabricate below-ground temperatures by interpolation.

Full original ARCO ERA5 `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3` at exact Open-Meteo selected 0.25° grid center, parameters `temperature` (K, `level` hPa), `geopotential` (m² s⁻², pressure levels) and `geopotential_at_surface` (m² s⁻²). Compare 2019-01-10..16 and 2019-10-10..16. These are **Google ARCO regridded, not native CDS GRIB bytes nor independent radiosonde validation**. Independently verify source axes, pressure levels, units, static surface height and SHA of extracted original values; same location/UTC as 12-variable Open-Meteo `models=era5,elevation=nan` surface source. Do NOT use Open-Meteo Historical Forecast API (its distinct model/availability semantics would break provenance).

Independent **German geographic holdout**, four frozen original DWD CDC hourly historical air temperature series:
- DWD 03987 Potsdam — flat inland; 
- DWD 04271 Rostock-Warnemünde — maritime/coastal;
- DWD 03730 Oberstdorf — Alpine valley;
- DWD 02290 Hohenpeißenberg — elevated exposed station.
DWD original metadata geographic coords/height and original archive filename resolved strictly by pinned station IDs, no manual coordinates fabricated. Files come only from `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/`. File `stundenwerte_TU_<ID>_*_hist.zip` must cover original 2019. Source ZIP sha256, member name, station metadata source sha256; no raw hourly station series republished. Parse original `produkt_tu_stunde` CSV UTC `MESS_DATUM`, original temp `TT_TU` °C and quality `QN_9` **only QC=10** (complete formal corrections, stringent after 1980); reject `-999`, duplicate station-hours, altered timestamps. Min 120 accepted matched source hours per station-season. DWD `QN=3` automated QC is not silently counted as final quality.

Four **preregistered methods** applied to *same DWD observations* (no target fitting):
- L0 `RAW_GRID`.
- P0 `PROVIDER_HEIGHT`, same ERA5+ Open-Meteo altitude=original DWD site altitude (provider's black-box).
- L1 `ARCO_REGULAR_0065`, T2m −0.0065K/m×(site altitude − regular ERA5 surface geopotential height).
- L2 `RESOLVED_PROFILE_GUARD`: L1, but use RAW if all conditions from SOURCE ONLY: site at least 150m below regular ERA5 grid surface; source nighttime shortwave GHI ≤10 W/m², 10m ERA5 wind<2.5m/s, total cloud <60%, and **at least two pressure levels >50m above model surface**, vertical separation 200..3000m and source pressure-level temperature gradient **dT/dz >0K/km** (a model-resolved, free-atmospheric warm-over-cold sign). If profile invalid/levels below surface, guard must NOT activate and must be labeled insufficient profile resolution.
- L3 `RESOLVED_THETA_STABILITY_GUARD`: L1, same site/weather conditions as L2 except **θ upper-lower >5 K/km**, using Kelvin T and `θ=T(1000/p)^0.286`; corresponds to static stability, **not a literal temperature inversion**. This is an alternative sensitivity screen, not tuned on 2019 and might be activated at many hours.

Pressure level pair **deterministic** from ordered `[1000,975,950,925,900,875,850,825,800,775,750,700,650,600]`, choose **two lowest above-grid geopotential-height levels** with model `z_level−z_model_surface>=50m`, separation ≥200m, ≤3000m; else profile insufficient and no guard. Do not treat a below-ground high-pressure level as observed atmosphere.

**Primary gate**: source data real; 4×2 stationary holdout at least 6/8 eligible site-seasons, original provider SHA; physical profile no unit/altitude/time mismatch; 4 methods (plus separate θ screen) real original DWD same-hour MAE, RMSE, bias and worst-harm; report separately geographic macro, no post-hoc score-based selection. A scientifically negative result passes experiment execution but blocks universal physical inversion hypothesis and release. **Do not claim global generalization** from 4 stations in one country. Strict production flags false.

References: [Google ARCO original pressure-level and regular ERA5 documentation](https://github.com/google-research/arco-era5); [DWD historical qualified hourly temperature](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/DESCRIPTION_obsgermany_climate_hourly_air_temperature_en.pdf); [DWD historical directory](https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/); [Open-Meteo ERA5 source model taxonomy](https://github.com/open-meteo/open-data).
