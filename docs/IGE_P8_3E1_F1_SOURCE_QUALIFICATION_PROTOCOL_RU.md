# IGE P8.3E1 and P8.3F1 — source qualification & ERA5 residual spatial holdout

**Research branch**: `research/ige-p8-3e1-f1-wind-20261015`. **Status**: implementation submitted for live CI, scientific results not yet confirmed.

## P8.3E1 — exposure and instrument height

Read original MeteoSwiss `ogd-smn_meta_stations.csv` and preserve its unabridged station exposure text. The optional description is NOT a numeric aerodynamic roughness measurement nor a WMO classification. A transparent keyword search produces only *textual clues*. Record station altitude (masl) separately from instrument height (m agl).

SwissMetNet network documentation describes standard 10-m wind measurement, including a specific 10-m mast at Aigle, but this is NOT individually verified evidence for BAS, CHD, GRA, MUB, STG, VIS, PAY or SIO. MeteoSwiss station certification classes are location-specific; no class is invented for these stations. All site-specific log-profile correction is blocked until authenticated instrument height, roughness, exposure geometry and applicability of the neutral profile are independently documented. Explicitly **do not use station elevation as sensor height**.

Scientific gate: source metadata provenance + complete station census + nonempty original descriptions where present, all height corrections disabled. Source-only qualification is not physical closure.

## P8.3F1 — fixed independent ERA5 test

- **Train:** only donor station wind observations and independent `models=era5` 10-m background in calendar **2023**, with monthly scalar speed and vector-component (east/north wind-TO) residuals. Each month requires at least 400 matched usable hours per donor.
- **Candidates:** ABO, BER, PAY, DAV, LUG, GVE, SIO, SMA, WYN, ZER; source qualification may eliminate unavailable candidates. Four qualified donors nearest geographically to each target, distance IDW² weights; do not use target meteorology in selection.
- **Targets:** BAS, GRA, MUB (excluded from all 2023 residual calibration). **Test:** all 8784 UTC nominal hours in leap year **2024**, at least 80% matched observations + ERA5 target + contemporaneous baseline donor availability.
- **Methods:** (a) ERA5 target uncorrected; (b) ERA5 target + seasonally varying donor residual climatology, separately corrected scalar speed (clipped to >=0) and wind-TO vectors converted to wind-FROM azimuth; (c) original P8.3A physical-distance IDW4 with contemporaneous 2024 donor observations on the **same scored timestamps**. The contemporaneous baseline has a different, more informative operational information set and is described as such. This is not yet a same-data comparison with full P8.3D terrain-selecting donor algorithm.
- **Primary metric:** full-year matched-hour MAE wind speed (m/s) for each contender; report signed difference corrected ERA5 − uncorrected ERA5 and corrected ERA5 − station baseline. Negative means improvement. Report bias, RMSE, circular direction error on measured noncalm target hours, direction-coverage and fixed 90° unresolved penalty, plus four seasonal subsets. **Do not silently discard unresolved azimuth to inflate accuracy.**
- **Clock:** pre-fixed same nominal UTC hours. MeteoSwiss hourly mean versus Open-Meteo gateway nominal instantaneous ERA5 is a comparability limitation; do not pick a one-hour shift using test-year outcomes.
- **Qualification:** result must publish performance whether improvement or degradation. No adoption unless improvements survive a larger station set, different years, coherent climate regimes and direct comparison to P8.3D terrain variants.
- **Data handling:** original MeteoSwiss hourly data and full derived wind time series remain runner-private; GitHub artifacts hold aggregate metrics, source digests and selected donors only.
- **Reproducibility:** code uses deterministic spatial weights (no seed), explicit year constants, strict annual-hour clock and units checks. No future wind, no EPW, no Meteonorm 8 verification.

### Known limitations

Preselected sites and 2024 year have already appeared in preceding research, so this is a **target-withheld relative to this F1 fit and train-year/holdout-year evaluation**, not a virgin geographic holdout. Open-Meteo mediates the ERA5 source, not direct ECMWF data. Donor exposures and roughness remain unresolved. The spatial climatological bias cannot reproduce missing contemporaneous synoptic variability. Also 2024 contemporaneous station IDW and calibrated ERA5 are operationally different inputs; interpretation must account for this asymmetry.

### Attribution

MeteoSwiss SwissMetNet Open Data: https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations

SwissMetNet network background: https://www.meteoswiss.admin.ch/dam/jcr%3Ab24af19f-c32f-464d-b2c4-163c72c8f071/SwissMetNetTheMeteoSwissReferenceMonitoringNetwork.pdf

MeteoSwiss certification: https://www.meteoswiss.admin.ch/weather/measurement-systems/land-based-stations/automatic-measurement-network/certification-of-monitoring-stations.html

Open-Meteo Historical ERA5 Gateway: https://open-meteo.com/en/docs/historical-weather-api
