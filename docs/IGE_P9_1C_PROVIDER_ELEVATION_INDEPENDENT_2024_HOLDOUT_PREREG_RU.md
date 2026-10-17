# IGE P9.1C — Exploratory altitude source ablation, independent 2024 original-station holdout

Protocol written **after** seeing P9.1B's 2023 three-site temperature errors, and **before** viewing any original 2024 paired-temperature comparisons. Therefore **candidate method choice is exploratory**, not a blind preregistered confirmatory test of improvement.

Test **fixed, unretuned** response variants on **2024-01-10..16 and 2024-07-10..16**, for GeoSphere original stations ID 30 Graz Universität, 39 Innsbruck Universität and 196 Patscherkofel; station coordinates and independent original station elevation from GeoSphere metadata. Same provider/model/time/nearest point `models=era5, cell_selection=nearest, timezone=GMT`; variants:
- `ERA5_GRID_NO_DOWNSCALING`: `elevation=nan` **pure grid-scale Open-Meteo delivered ERA5**, provider height unreliable.
- `OPEN_METEO_PROVIDER_SITE_ELEVATION_DOWNSCALING`: `elevation=<original GeoSphere station altitude>`; provider's own statistical method explicitly enabled. This is **not** independently implemented physical lapse-rate, not native ECMWF GRIB, and cannot be claimed universal physics.

Pair exactly the same UTC GeoSphere QC `tl` hours and native Open-Meteo `temperature_2m`; no target observation values used to choose elevations, source variable flags, or algorithm parameters. Report six paired season×station MAE/RMSE/bias raw and downscaled, relative improvement, response source sha, model selected grid center and differences. Holdout **different year** from P9.1B 2023, though same stations; not a fully spatially independent set of sites.

A method is not automatically qualified globally if it improves in Innsbruck. Need new continents, independently verified grid native orography, surface roughness/coastal exposure, and diverse elevation-regime holdouts before production. **Scientific acceptance:** all source QC and matched observations available + transparent improvement/harm. Do not optimize lapse rate or switch provider according to heldout performance. Main unaffected.
