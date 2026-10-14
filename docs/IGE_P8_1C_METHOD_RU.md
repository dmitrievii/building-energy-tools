# IGE Climate Engine — P8.1C: true DEM-based orographic calibration and altitude validation

**Stage:** research experiment, not EPW production; 2026-10-14. **Repo branch:** `research/ige-p8-meteonorm8-batch-automation-20261012`. **Main unchanged.**

## Scientific goal

Separate independent terrain geometry from temperature data. P8.1B only used the elevation of weather stations; P8.1C independently downloads a mosaicked bare-earth DEM and estimates each site's landform position from 49 height samples.

### DEM provenance and explicit limitations

- **Mapzen Terrain Tiles** as AWS public open data (multi-provider terrain mosaic), not a single Copernicus DEM, not a standalone Austrian DGM. AWS dataset registry: https://registry.opendata.aws/terrain-tiles/ ; original attribution requirements: https://github.com/tilezen/joerd/blob/master/docs/attribution.md .
- URL template `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, Z=11. Pixel Terrarium unpacking: `H[m] = 256R + G + B/256 - 32768`.
- Effective pixel size depends on latitude. Sampling uses nearest original raster pixel (not misleadingly claiming 10m or 30m ground DEM accuracy), great-circle ring points at 250m, 1.5km, 5km and 10km, 12 bearings each.
- DEM center height **not substituted** for weather-station elevation. Record center height discrepancy and flag >200m; source elevation datums may differ.
- Compute TPI=DEM center elevation − ring-mean DEM elevation (1.5/5/10km), neighbourhood ruggedness and proxy slope. These are DEM-derived terrain features. They **do not** directly measure inversion strength or cold-air pooling; those interpretations must be tested against station observations.
- Source DEM tile SHA256 manifest is preserved. No original PNG tile bytes or unlicensed Meteonorm EPW are uploaded to GitHub or result artifact.

## Evaluation protocol (prevent weather-data leakage)

1. GeoSphere `klima-v2-1m`: train on 1991–2010 monthly series, validation 2011–2020 (same period separation as P8.1B).
2. Withhold each **target station** from every lapse and DEM regression, and every neighbouring weather donor set. All coefficients are recalculated using *donor-only* observations from 1991–2010.
3. Spatial buffer variants `0km` and `50km`: donor stations closer than the buffer are excluded from both regression and interpolation.
4. For each 2011–2020 target month, contemporaneous temperatures of the eight closest eligible donor stations are used; reconstruct the withheld target observation. This is **hindcast/observed spatial interpolation**, not prospective weather forecasting.
5. Matched sample between methods, no imputation for missing observations, QC acceptance inherited from P8.1B. Preserve original GeoSphere batch-source SHA256 manifest.
6. Baseline methods: IDW raw; IDW −6.5K/km; IDW regional lapse; IDW local lapse. DEM extensions: +1.5km TPI; +1.5km and 5km TPI.
7. Fit monthly TPI coefficients by ridge regression on training-station normals only after residualizing against lat/lon/elevation, keep within ±0.008K/m. Compare methods on identical station-months; evaluate national, high altitude (≥1500m), Sonnblick, region, year and month. Station-cluster bootstrap on paired errors; negative or zero improvement must be reported.

## Scientific acceptance criteria

- Workflow green alone is **not** physical validation. Must verify **actual downloaded DEM data** (tile counts, SHA, station–DEM discrepancies) and GeoSphere sources.
- Report national matched-sample RMSE and MAE, 50km buffer degradation, high-altitude subgroup and Sonnblick in original years, paired bootstrap confidence interval.
- DEM variant accepted for further testing only if supported by positive station-block bootstrap improvement and acceptable high-altitude 50km accuracy. If no improvement, keep simpler P8.1B regional lapse. **Do not conceal regressions.**
- Must acknowledge internal Austrian station network validation is not universal generalization to Greece and that temperature validation does not validate radiation, precipitation, winds or EPW.

## Reproducibility

```sh
python -m pip install numpy pillow
python -m unittest discover -s research/ige_cmip6 -p 'test_p8_1c.py' -v
# Run full experiment through GitHub Actions IGE P8.1C workflow.
```

After workflow: review artifact `ige-p8-1c-dem-original-geosphere-validation`, `temporal_methods.csv`, `temporal_altitude_bands.csv`, `temporal_stations.csv`, `temporal_provenance.json`, `terrain_features.json` and `terrain_summary.json`.