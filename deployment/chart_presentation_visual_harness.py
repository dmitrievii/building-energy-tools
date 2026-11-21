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

if st.query_params.get("p2") == "1":
    from epw_climate_analyzer.directional_climate import directional_table,directional_figure
    from epw_climate_analyzer.sky_distribution import cumulative_sky,sky_figure
    from epw_climate_analyzer.architectural_underlay import prepare_underlay,apply_underlay
    from PIL import Image
    from io import BytesIO
    idx=pd.date_range("2025-06-21 08:00",periods=8,freq="h")
    df2=pd.DataFrame({"wind_speed_m_s":np.arange(1.,9.),"wind_direction_deg":np.arange(0.,360.,45.),
                      "dry_bulb_temperature_c":np.arange(15.,31.,2.),
                      "solar_apparent_zenith_deg":np.linspace(60.,25.,8),
                      "solar_azimuth_deg":np.linspace(90.,270.,8),
                      "direct_normal_radiation_wh_m2":500.,"diffuse_horizontal_radiation_wh_m2":100.},index=idx)
    df2.attrs["canonical_native_interval_minutes"]=60.
    rose2=directional_figure(directional_table(df2,colour="Temperature"),"Hours","Temperature","P2 Wind Wheel")
    st.plotly_chart(rose2,key="p2_rose")
    table2=cumulative_sky(df2,mf=1)
    st.plotly_chart(sky_figure(table2,"Total"),key="p2_sky2d")
    st.plotly_chart(sky_figure(table2,"Total","3D dome"),key="p2_sky3d")
    from epw_climate_analyzer.chart_presentation import BACKGROUND_TRANSPARENT,KEY_BACKGROUND
    image_bytes=BytesIO()
    Image.new("RGB",(240,240),"#33aa77").save(image_bytes,format="PNG")
    underlay=directional_figure(directional_table(df2,colour="Temperature"),"Hours","Temperature","P2 Architectural underlay")
    # Exercise actual image layer; shared wrapper ordinarily applies this after presentation.
    from epw_climate_analyzer.chart_presentation import apply_chart_presentation,settings_from_state
    apply_chart_presentation(underlay,settings_from_state(st.session_state))
    apply_underlay(underlay,prepare_underlay(image_bytes.getvalue()),scale=.8)
    # Direct original is appropriate here: this fixture has already passed the shared presentation boundary.
    st._climate_analyzer_original_plotly_chart(underlay,key="p2_underlay")
    st.stop()

if st.query_params.get("duration") == "1":
    from epw_climate_analyzer.charts import duration_chart
    from epw_climate_analyzer.extended_visualization import probability_figure, amplitude_figure
    for year in (2025,2024):
        idx=pd.date_range(f"{year}-01-01",f"{year+1}-01-01",freq="h",inclusive="left")
        data=pd.DataFrame({"dry_bulb_temperature_c":10.+12.*np.sin(np.arange(len(idx))*2*np.pi/8760)},index=idx)
        data.attrs["canonical_native_interval_minutes"]=60
        st.plotly_chart(duration_chart(data,"dry_bulb_temperature_c",f"Physical hours {year}","°C"),key=f"duration_{year}")
    st.plotly_chart(probability_figure(data,"dry_bulb_temperature_c","°C"),key="probability")
    st.plotly_chart(amplitude_figure(data,"dry_bulb_temperature_c","Monthly","Dry-bulb temperature"),key="amplitude")
    st.stop()

if st.query_params.get("monthly") == "1":
    from epw_climate_analyzer.monthly_radiation import monthly_radiation_chart
    monthly = pd.DataFrame(
        {"GHI": [34,51,94,132,173,180,189,166,109,72,38,27],
         "DHI": [24,35,57,73,90,92,82,74,60,44,28,19],
         "DNI": [34,41,69,95,119,120,148,135,81,58,32,29]},
        index=pd.Index(range(1,13),name="Month"))
    style = st.selectbox("Chart type", ["Bar chart","Line chart","Monthly rose"])
    rose_style = st.selectbox("Rose style", ["Sectors","Lines"]) if style == "Monthly rose" else "Sectors"
    st.plotly_chart(monthly_radiation_chart(monthly, style=style, rose_style=rose_style),
                    use_container_width=True, key="monthly_spacing_test")
    st.stop()

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
