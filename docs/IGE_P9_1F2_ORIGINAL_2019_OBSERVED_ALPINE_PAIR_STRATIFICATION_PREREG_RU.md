# IGE P9.1F2 — Original 2019 observed valley–summit station-pair stratification: independent verification protocol

**Registered before first P9.1F2 original 2019 paired-source download**. A scientifically distinct follow-up to P9.1F1, which measures ERA5-and-DEM cold-pool **susceptibility** rather than an actual local vertical inversion.

Four **pre-existing, already identified (P8.1D) spatial pairs**, no choice based on 2019 temperatures: lower→upper GeoSphere original station IDs `119→14305 St. Anton–Galzig`, `28→17005 Galtür–Idalpe`, `66→184 Obergurgl–Pitztaler Gletscher`, `39→196 Innsbruck–Patscherkofel`. Official metadata supplies coordinates and heights, verify upper>lower by at least 150m. Original station source `klima-v2-1h, tl and tl_flag`, only already documented QC `10,11,12,20,21,22`.

**Time periods**: 2019 Jan10–Jan16, Jul10–Jul16, Oct10–Oct16, all 168 UTC hours; local night `22:00–05:59 Europe/Vienna`, daytime `10:00–15:59 Europe/Vienna`. Each pair-season explicitly enumerated even with unavailable original observations, minimum 100 original simultaneously QC-qualified pairs per pair-season, >=20 in an individual night or day category to report time-specific statistics.

**Predefined independent observed metrics**:
- `T_upper−T_lower >0°C` fraction: **warm-above-cold spatial pairing**, which is compatible with a horizontal cross-valley cold-pool regime but **NOT proof of a collocated vertical inversion**, since stations have different lat/lon, aspect, sky view, wind and instrumentation.
- `T_upper−T_lower > −0.0065 × altitude_difference_m`: observed upper warm *relative to a standard lapse* but **not a true inversion** if the upper remains colder overall.
- mean upper-minus-lower ΔT, broken out by night/day and seasons.
- Original GeoSphere response SHA, station metadata SHA, number of exact original UTC simultaneous hours.
- No use of paired target temperatures in P9.1F1 source predictor, its terrain selection, or fixed thresholds; **this is an independent physics diagnostic**, not fitting.

Acceptance is a complete source census with no falsely published pair scores, >=2 scientifically eligible winter pairs, and explicit distinction between conditional exposure/weather regimes and collocated thermodynamic stability. Global production and local universal inversion modelling remain NOT QUALIFIED.
