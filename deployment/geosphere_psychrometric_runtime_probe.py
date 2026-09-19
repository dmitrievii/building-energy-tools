#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.geosphere import fetch_metadata, fetch_station_dataset, parse_stations
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.psychrometrics import pressure_from_altitude_m
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

STATION_ID = "105"
START = pd.Timestamp("2026-07-15T00:00:00Z")
END = pd.Timestamp("2026-07-18T23:50:00Z")
CANONICAL = (
    "dry_bulb_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
)


def main() -> int:
    metadata = fetch_metadata(timeout_s=60)
    stations = parse_stations(metadata)
    station = next((item for item in stations if str(item.station_id) == STATION_ID), None)
    if station is None:
        raise RuntimeError(f"GeoSphere station {STATION_ID} not found")

    dataset = fetch_station_dataset(
        station=station,
        start=START,
        end=END,
        metadata=metadata,
        canonical_variables=CANONICAL,
        timeout_s=60,
    )
    fallback = pressure_from_altitude_m(float(station.elevation_m or 0.0))
    frame = prepare_historical_analysis_frame(
        dataset,
        include_psychrometrics=True,
        fallback_pressure_pa=fallback,
    )
    frame = with_time_basis(frame, CHRONOLOGICAL)

    required = [
        "dry_bulb_temperature_c",
        "relative_humidity_pct",
        "atmospheric_station_pressure_pa",
        "humidity_ratio_g_kg",
        "moist_air_enthalpy_kj_kg",
    ]
    counts = {name: int(pd.to_numeric(frame[name], errors="coerce").notna().sum()) for name in required}
    if any(value <= 0 for value in counts.values()):
        raise RuntimeError(f"Psychrometric provider frame is incomplete: {counts}")

    t = pd.to_numeric(frame["dry_bulb_temperature_c"], errors="coerce")
    d = pd.to_numeric(frame["humidity_ratio_g_kg"], errors="coerce")
    h = pd.to_numeric(frame["moist_air_enthalpy_kj_kg"], errors="coerce")
    t_range = (float(max(-40, int(t.min() // 5 * 5))), float(min(60, int(t.max() // 5 * 5 + 10))))
    d_range = (0.0, float(min(40.0, max(20.0, float(d.quantile(0.995)) * 1.1))))
    h_range = (float(max(-30, int(h.quantile(0.005) // 10 * 10))), float(min(140, int(h.quantile(0.995) // 10 * 10 + 20))))
    pressure = float(pd.to_numeric(frame["atmospheric_station_pressure_pa"], errors="coerce").median())

    figures = {}
    for chart_type in ("T-d", "i-d"):
        fig = psychrometric_chart(
            frame,
            chart_type=chart_type,
            pressure_pa=pressure,
            show_rh_curves=True,
            show_comfort_zone=True,
            data_mode="Climate zone",
            t_range=t_range,
            d_range=d_range,
            h_range=h_range,
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
        figures[chart_type] = len(fig.data)

    evidence = {
        "station_id": station.station_id,
        "station_name": station.name,
        "rows": len(frame),
        "counts": counts,
        "pressure_pa": pressure,
        "attrs": {key: str(value) for key, value in frame.attrs.items()},
        "figures": figures,
    }
    output = Path("artifacts/geosphere-psychrometric-runtime-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
