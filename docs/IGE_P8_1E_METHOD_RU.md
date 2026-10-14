# IGE Climate Engine — P8.1E: Measurement-based inversion diagnostics and Swiss geographic transfer

Date: 2026-10-14. Scope: **research / validation only**, not production EPW.

## Research questions

**RQ-E1.** Do physically observed vertical temperature profiles independently confirm lower-atmosphere inversions and their seasonal/UTC-slot distributions? Does evidence warrant translating P8.1D landform classification into a temperature-correction model?

**RQ-E2.** Does the frozen P8.1B Austrian regional lapse (calibrated on 1991–2010 Austria GeoSphere) improve spatial reconstruction over -6.5 K/km and uncorrected IDW **outside Austria**, using original **MeteoSwiss** station monthly readings in 2011–2020?

## Predeclared independent source contracts

1. NOAA IGRA v2.2 original sounding archives; stations AUM00011035 (Vienna), AUM00011120 (Innsbruck), SZM00006610 (Payerne, Switzerland), GMM00010868 (Oberschleißheim, Germany); 2017–2020, nominal 00 and 12 UTC. NOAA IGRA station list and raw source archive SHA-256 must be recorded. IGRA standard-quality-accepted values, valid reported geopotential heights only.
2. A measured *near-surface temperature inversion diagnostic* is `max(T(z)-T(z0)) >= +0.5 °C` at **reported** sounding levels in <=1200 m above station. Lowest reported level within 150 m of station; at least one other level >=250 m. No interpolation or manufactured shallow profile. True continuous vertical profile shape remains unobserved between discrete radiosonde levels; balloon drift and surface representativeness are explicit limitations.
3. SwissMetNet public metadata and original FULL-SERIES monthly air temperatures (filename `ogd-smn_<site>_m.csv`, no `historical` suffix) discovered via its STAC collection, with source per-station file hashes. External site selection depends only on station coordinates, elevation and file availability, never model error. Train only Austrian historical data 1991–2010, test only Swiss station months 2011–2020. The target Swiss station is always excluded from contemporaneous Swiss donor group. Two spatial buffers 0 and 50 km. All methods compared on identical target-months.
4. NOAA vertical profiles are **not the same thing as climatological valley-floor inversion**: they occur at different locations and have incomplete lower-level resolution. Swiss study evaluates **spatial interpolation**, not ten-year-ahead forecasting, since 2011–2020 donor readings are used in their original months.

## Success criteria and nonconfirmation

- Original IGRA profiles must decode and produce >500 qualified soundings across >=2 sites with valid surface anchors, otherwise E1 stays OPEN.
- MeteoSwiss STAC station inventory must show >20 available sites and external Swiss transfer must yield >=2500 paired predictions in >=18 independent stations, otherwise E2 stays OPEN.
- A successful CI status does not mean scientific gain. Report MAE, RMSE, bias, paired uncertainty, high-elevation and regional failures, and use negative-result protocol. No training on Swiss test truth. No Meteonorm files or original provider time series in public artifacts.
- P8.1C/D already showed DEM/seasonal correction is not universally better. Thus no mandatory production change or speculative inference about 3D inversion climate without direct validation.

Sources: https://www.ncei.noaa.gov/products/weather-balloon/integrated-global-radiosonde-archive ; https://www.ncei.noaa.gov/pub/data/igra/igra2-readme.txt ; https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations ; https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn .