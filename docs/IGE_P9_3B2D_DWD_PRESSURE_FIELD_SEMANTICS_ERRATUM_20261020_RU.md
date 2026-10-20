# P9.3B2D — Verified DWD pressure-field semantics correction (2026-10-20)

This correction precedes any use of new German pressure measurements for model skill scoring.

**Authoritative hourly DWD CDC pressure schema (v24.03), page 2:**
https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/DESCRIPTION_obsgermany_climate_hourly_pressure_en.pdf

| DWD product | Station-level absolute pressure | Sea-level pressure (FORBIDDEN as QFE) |
|---|---|---|
| climate/hourly/pressure | `P0` | `P` |
| climate_urban/10_minutes/pressure | `P0_ST_10` | `PP_ST_10` |
| climate/subdaily/pressure | `PP_TER` | not in this product |

Urban/subdaily mappings documented in the DWD parameter catalog as decoded
by https://wetterdienst.readthedocs.io/en/latest/data/provider/dwd/observation/10_minutes.html
and https://wetterdienst.readthedocs.io/en/latest/data/provider/dwd/observation/subdaily.html .
The original source CSV native columns were read source-only in Actions
[#39474460867](https://github.com/dmitrievii/building-energy-tools/actions/runs/39474460867).
For the present original source inputs, these source field names were confirmed:
Urban `QN,P0_ST_10,PP_ST_10`; subdaily `QN_4,PP_TER`.

**ERRATUM to earlier IGE P9.3B2 / B2C reports:** prior assertions that DWD
hourly `P` was station-level and `P0` was sea-level are reversed and wrong.
All German claims of original station-level `P` in the old historical reports
are invalid source semantics, even though in their frozen 2023/24 windows BOTH
P and P0 are missing (therefore no original measured German model skill was
ever calculated). Do not rewrite historical SHA or model results retroactively.
The new adapter must use `P0` for DWD hourly, `P0_ST_10` for urban and
`PP_TER` for subdaily. Add explicit regression tests forbidding `P`/`PP_ST_10`
as station-level pressure in these source families.
