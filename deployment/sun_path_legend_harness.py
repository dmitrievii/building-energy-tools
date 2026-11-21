"""Exercise the production sun-path factories through actual Streamlit Plotly charts."""
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "climate_analyzer"))
from epw_climate_analyzer.chart_presentation import install_global_chart_presentation
from epw_climate_analyzer.solar import add_solar_position_for_site
from epw_climate_analyzer.sun_path_views import (
    classic_sun_path, technical_sun_path, sun_path_3d,
)

st.set_page_config(layout="wide")
install_global_chart_presentation(st)
st.title("Sun path legend regression")
index = pd.date_range("2025-06-01", periods=24*5, freq="h", tz="Europe/Vienna")
frame = add_solar_position_for_site(
    pd.DataFrame({"direct_normal_radiation_wh_m2": 300., "month_index": index.month,
                  "hour_of_day": index.hour}, index=index),
    latitude=48.2, longitude=16.4, elevation_m=200.,
)
view = st.query_params.get("view", "polar")
factory = {"radiation": lambda df: classic_sun_path(df, radiation_field="direct_normal_radiation_wh_m2"),
           "technical": technical_sun_path, "polar": classic_sun_path, "3d": sun_path_3d}[view]
st.plotly_chart(factory(frame), use_container_width=True,
                config={"displaylogo": False, "scrollZoom": True}, key="sun_path_legend_test")
