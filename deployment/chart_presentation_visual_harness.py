"""Local visual-smoke harness for the global Climate Analyzer chart renderer.

This is not a production page.  CI launches it with Streamlit and a real browser
so the single presentation layer is exercised against representative line,
heatmap, psychrometric and polar/wind charts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CLIMATE_ROOT = ROOT / "tools" / "climate_analyzer"
if str(CLIMATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIMATE_ROOT))

from epw_climate_analyzer.chart_presentation import install_global_chart_presentation
from epw_climate_analyzer.charts import (
    profile_ribbon_chart,
    psychrometric_chart,
    temporal_heatmap_chart,
    wind_rose_chart,
)
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties


st.set_page_config(page_title="Chart presentation visual harness", layout="wide")
install_global_chart_presentation(st)
st.title("Chart presentation visual harness")
st.caption("Representative production chart families rendered through the shared global presentation boundary.")

index = pd.date_range("2025-01-01", periods=24 * 31, freq="h")
hours = np.arange(len(index), dtype=float)
season = np.sin(2.0 * np.pi * hours / (24.0 * 31.0))
diurnal = np.sin(2.0 * np.pi * (hours % 24.0) / 24.0 - np.pi / 2.0)

df = pd.DataFrame(
    {
        "dry_bulb_temperature_c": 8.0 + 5.0 * season + 6.0 * diurnal,
        "relative_humidity_pct": np.clip(68.0 - 18.0 * diurnal + 7.0 * season, 28.0, 96.0),
        "atmospheric_station_pressure_pa": np.full(len(index), 101325.0),
        "wind_speed_m_s": np.clip(3.2 + 2.0 * np.sin(hours / 11.0) + 0.8 * np.cos(hours / 5.0), 0.1, None),
        "wind_direction_deg": np.mod(hours * 17.0 + 35.0 * np.sin(hours / 13.0), 360.0),
        "month_index": index.month,
        "month_name": index.strftime("%b"),
        "hour_of_day": index.hour,
        "day": index.day,
    },
    index=index,
)
df.attrs["canonical_native_interval_minutes"] = 60.0
df.attrs["canonical_analysis_interval_minutes"] = 60.0
df = add_psychrometric_properties(df)

line = profile_ribbon_chart(
    df,
    "dry_bulb_temperature_c",
    "Hourly",
    "Line chart presentation smoke",
    "°C",
)
heatmap = temporal_heatmap_chart(
    df,
    "dry_bulb_temperature_c",
    row_group="day",
    compare_across="Hour of day",
    statistic="Mean",
    title="Heatmap presentation smoke",
    unit="°C",
    temperature_thresholds=(10.0, 20.0),
)
psychrometric = psychrometric_chart(
    df,
    chart_type="T-d",
    data_mode="Points",
    show_rh_curves=True,
    show_comfort_zone=False,
    metric_layers=["Relative humidity"],
    color_mode="Month",
)
wind = wind_rose_chart(df, title="Wind rose presentation smoke")

st.subheader("Line")
st.plotly_chart(line, use_container_width=True, config={"displaylogo": False}, key="presentation_smoke_line")
st.subheader("Heatmap")
st.plotly_chart(heatmap, use_container_width=True, config={"displaylogo": False}, key="presentation_smoke_heatmap")
st.subheader("Psychrometric")
st.plotly_chart(psychrometric, use_container_width=True, config={"displaylogo": False}, key="presentation_smoke_psychrometric")
st.subheader("Wind rose")
st.plotly_chart(wind, use_container_width=True, config={"displaylogo": False}, key="presentation_smoke_wind")
