#!/usr/bin/env python3
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.catalog_runtime import load_production_station_catalog
from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.climate_sources import download_station_epw
from epw_climate_analyzer.decisions import add_degree_metrics
from epw_climate_analyzer.epw_parser import parse_epw
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties, pressure_from_altitude_m


def main() -> int:
    catalog = load_production_station_catalog()
    if catalog.empty:
        raise RuntimeError("Production station catalog is empty")

    row = catalog.iloc[0]
    downloaded = download_station_epw(row)
    epw = parse_epw(BytesIO(downloaded.payload))
    data = add_degree_metrics(epw.data)
    pressure_values = pd.to_numeric(data["atmospheric_station_pressure_pa"], errors="coerce").dropna()
    fallback_pressure = (
        float(pressure_values.median())
        if not pressure_values.empty
        else pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))
    )
    data = add_psychrometric_properties(data, fallback_pressure_pa=fallback_pressure)

    t_min = float(data["dry_bulb_temperature_c"].min())
    t_max = float(data["dry_bulb_temperature_c"].max())
    d_max_default = max(20.0, float(data["humidity_ratio_g_kg"].quantile(0.995)) * 1.1)
    h_min = float(data["moist_air_enthalpy_kj_kg"].quantile(0.005))
    h_max = float(data["moist_air_enthalpy_kj_kg"].quantile(0.995))
    t_limits = (float(max(-40, int(t_min // 5 * 5))), float(min(60, int(t_max // 5 * 5 + 10))))
    d_limits = (0.0, float(min(40.0, d_max_default)))
    h_limits = (float(max(-30, int(h_min // 10 * 10))), float(min(140, int(h_max // 10 * 10 + 20))))
    active_pressure = float(pressure_values.median()) if not pressure_values.empty else fallback_pressure

    traces: dict[str, int] = {}
    for chart_type in ("T-d", "i-d"):
        fig = psychrometric_chart(
            data,
            chart_type=chart_type,
            pressure_pa=active_pressure,
            show_rh_curves=True,
            show_comfort_zone=True,
            data_mode="Climate zone",
            t_range=t_limits,
            d_range=d_limits,
            h_range=h_limits,
            metric_layers=["Dry-bulb temperature", "Humidity ratio", "Relative humidity"],
            shown_bioclimatic_zones=None,
            show_heat_index_overlay=False,
            selected_months=list(range(1, 13)),
            color_metric_column=None,
            color_metric_label="Month",
            color_mode="Month",
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
            show_core_zone=True,
            year_mode="All years combined",
            selected_years=None,
        )
        fig.to_plotly_json()
        traces[chart_type] = len(fig.data)

    result = {
        "station_id": str(row["station_id"]),
        "catalog_name": str(row["name"]),
        "epw_name": downloaded.file_name,
        "epw_location": f"{epw.location.city}, {epw.location.country}",
        "rows": len(data),
        "active_pressure_pa": active_pressure,
        "psychrometric_valid_rows": int(data[["dry_bulb_temperature_c", "humidity_ratio_g_kg", "moist_air_enthalpy_kj_kg"]].dropna().shape[0]),
        "trace_counts": traces,
    }
    output = Path("artifacts/v0742-epw-runtime-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
