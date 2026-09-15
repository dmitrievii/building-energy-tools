from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.exporting import (
    dataframe_to_csv_bytes,
    figure_export_stem,
    figure_to_dataframe,
    safe_export_stem,
)


def test_scatter_trace_exports_visible_coordinates():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[10.5, 11.5], name="Air temperature"))
    table = figure_to_dataframe(fig)
    assert table["trace"].tolist() == ["Air temperature", "Air temperature"]
    assert table["x"].tolist() == [1, 2]
    assert table["y"].tolist() == [10.5, 11.5]


def test_heatmap_exports_long_form_cells():
    fig = go.Figure(go.Heatmap(x=["00", "01"], y=["Jan", "Feb"], z=[[1, 2], [3, 4]], name="Heatmap"))
    table = figure_to_dataframe(fig)
    assert len(table) == 4
    assert set(table.columns) >= {"trace", "trace_type", "x", "y", "value"}
    assert table["value"].tolist() == [1, 2, 3, 4]


def test_filtered_dataframe_preserves_datetime_index():
    df = pd.DataFrame({"dry_bulb_temperature_c": [1.0]}, index=pd.DatetimeIndex(["2026-01-01T00:00:00Z"], name="time"))
    csv_text = dataframe_to_csv_bytes(df).decode("utf-8-sig")
    assert "time" in csv_text
    assert "dry_bulb_temperature_c" in csv_text


def test_export_filename_is_safe_and_title_driven():
    fig = go.Figure()
    fig.update_layout(title="<b>Monthly temperature / Graz</b>")
    assert figure_export_stem(fig) == "Monthly_temperature_Graz"
    assert safe_export_stem("Graz weather.epw") == "Graz_weather"


def test_app_places_compact_export_next_to_every_render_plot():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'with st.popover("⇩")' in app
    assert '"Chart data · CSV"' in app
    assert '"Filtered data · CSV"' in app
    assert '"Source weather · EPW"' in app
    assert 'st.session_state["_active_filtered_export_df"] = filtered' in app
    assert "render_chart_export_controls(fig)" in app
