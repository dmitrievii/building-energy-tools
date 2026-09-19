#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.catalog_runtime import load_production_station_catalog
from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.climate_sources import download_station_epw
from epw_climate_analyzer.decisions import add_degree_metrics
from epw_climate_analyzer.epw_parser import parse_epw
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties, pressure_from_altitude_m


def _candidate_rows(catalog: pd.DataFrame) -> list[pd.Series]:
    names = catalog["name"].astype("string").str.casefold()
    countries = catalog["country"].astype("string").str.casefold()
    austria = catalog[countries.eq("austria")]
    selected: list[pd.Series] = []
    for needle in ("graz", "wien", "vienna"):
        subset = austria[austria["name"].astype("string").str.casefold().str.contains(needle, na=False)]
        for _, row in subset.head(2).iterrows():
            selected.append(row)
    if not selected:
        for _, row in austria.head(3).iterrows():
            selected.append(row)
    if not selected:
        for _, row in catalog.head(3).iterrows():
            selected.append(row)
    return selected[:4]


def _build_chart(df: pd.DataFrame, pressure_pa: float, chart_type: str) -> int:
    t_min = float(df["dry_bulb_temperature_c"].min())
    t_max = float(df["dry_bulb_temperature_c"].max())
    d_max_default = max(20.0, float(df["humidity_ratio_g_kg"].quantile(0.995)) * 1.1)
    h_min = float(df["moist_air_enthalpy_kj_kg"].quantile(0.005))
    h_max = float(df["moist_air_enthalpy_kj_kg"].quantile(0.995))
    t_limits = (float(max(-40, int(t_min // 5 * 5))), float(min(60, int(t_max // 5 * 5 + 10))))
    d_limits = (0.0, float(min(40.0, d_max_default)))
    h_limits = (float(max(-30, int(h_min // 10 * 10))), float(min(140, int(h_max // 10 * 10 + 20))))

    fig = psychrometric_chart(
        df,
        chart_type=chart_type,
        pressure_pa=pressure_pa,
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
    return len(fig.data)


def main() -> int:
    catalog = load_production_station_catalog()
    evidence: list[dict[str, object]] = []
    failures: list[str] = []

    for row in _candidate_rows(catalog):
        try:
            downloaded = download_station_epw(row)
            epw = parse_epw(downloaded.payload)
            data = add_degree_metrics(epw.data)
            valid_pressure = pd.to_numeric(data["atmospheric_station_pressure_pa"], errors="coerce").dropna()
            fallback_pressure = (
                float(valid_pressure.median())
                if not valid_pressure.empty
                else pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))
            )
            data = add_psychrometric_properties(data, fallback_pressure_pa=fallback_pressure)
            counts = {
                name: int(pd.to_numeric(data[name], errors="coerce").notna().sum())
                for name in (
                    "dry_bulb_temperature_c",
                    "relative_humidity_pct",
                    "atmospheric_station_pressure_pa",
                    "humidity_ratio_g_kg",
                    "moist_air_enthalpy_kj_kg",
                )
            }
            active_pressure = (
                float(pd.to_numeric(data["atmospheric_station_pressure_pa"], errors="coerce").dropna().median())
                if pd.to_numeric(data["atmospheric_station_pressure_pa"], errors="coerce").dropna().size
                else pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))
            )
            figures = {
                chart_type: _build_chart(data, active_pressure, chart_type)
                for chart_type in ("T-d", "i-d")
            }
            evidence.append(
                {
                    "station_id": str(row["station_id"]),
                    "name": str(row["name"]),
                    "dataset": str(row["dataset"]),
                    "epw_name": downloaded.file_name,
                    "rows": len(data),
                    "dtypes": {name: str(data[name].dtype) for name in counts},
                    "counts": counts,
                    "attrs": {key: str(value) for key, value in data.attrs.items()},
                    "active_pressure_pa": active_pressure,
                    "figures": figures,
                }
            )
        except Exception as exc:
            failures.append(
                f"{row.get('station_id')} {row.get('name')} {row.get('dataset')}: {type(exc).__name__}: {exc}"
            )
            evidence.append(
                {
                    "station_id": str(row.get("station_id")),
                    "name": str(row.get("name")),
                    "dataset": str(row.get("dataset")),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            break

    output = Path("artifacts/epw-psychrometric-runtime-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"cases": evidence, "failures": failures}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"cases": evidence, "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise RuntimeError(failures[0])
    if not evidence:
        raise RuntimeError("No EPW candidates were tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
