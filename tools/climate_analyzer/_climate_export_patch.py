from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
EXPORTING = ROOT / "tools" / "climate_analyzer" / "epw_climate_analyzer" / "exporting.py"
TEST = ROOT / "tools" / "climate_analyzer" / "tests" / "test_local_chart_export.py"

app = APP.read_text(encoding="utf-8")

old_render = '''def render_plot(fig, text: str) -> None:\n    \"\"\"Render a Plotly figure and its automatic interpretation.\"\"\"\n    st.plotly_chart(\n        fig,\n        use_container_width=True,\n        config={\"displaylogo\": False, \"scrollZoom\": True},\n        key=next_plot_key(),\n    )\n    render_interpretation(text)\n'''

new_render = '''def render_chart_export_controls(fig) -> None:\n    \"\"\"Render a compact local export control without reducing chart width.\"\"\"\n    from epw_climate_analyzer.exporting import (\n        dataframe_to_csv_bytes,\n        figure_export_stem,\n        figure_to_csv_bytes,\n        safe_export_stem,\n    )\n\n    # Keep the chart itself full-width. The tiny control occupies its own row\n    # immediately above the figure instead of stealing horizontal chart space.\n    _, export_col = st.columns([24, 1], gap=\"small\")\n    with export_col:\n        with st.popover(\"⇩\"):\n            st.caption(\"Export this chart\")\n            stem = figure_export_stem(fig)\n            chart_csv = figure_to_csv_bytes(fig)\n            if chart_csv:\n                st.download_button(\n                    \"Chart data · CSV\",\n                    data=chart_csv,\n                    file_name=f\"{stem}.csv\",\n                    mime=\"text/csv\",\n                    use_container_width=True,\n                )\n            else:\n                st.caption(\"No tabular trace data are available for this figure.\")\n\n            # A comparison figure can combine several independent EPW files, so\n            # offering one arbitrary active source/filtered table there would be\n            # misleading. Its trace-level CSV remains available above.\n            if st.session_state.get(NAVIGATION_KEY) != \"Compare Climates\":\n                filtered = st.session_state.get(\"_active_filtered_export_df\")\n                if hasattr(filtered, \"to_csv\"):\n                    st.download_button(\n                        \"Filtered data · CSV\",\n                        data=dataframe_to_csv_bytes(filtered),\n                        file_name=f\"{stem}_filtered.csv\",\n                        mime=\"text/csv\",\n                        use_container_width=True,\n                    )\n\n                active = get_active_climate_file()\n                if active is not None:\n                    source_name = safe_export_stem(active.name, default=\"source_weather\")\n                    st.download_button(\n                        \"Source weather · EPW\",\n                        data=active.payload,\n                        file_name=f\"{source_name}.epw\",\n                        mime=\"application/octet-stream\",\n                        use_container_width=True,\n                    )\n\n\ndef render_plot(fig, text: str) -> None:\n    \"\"\"Render a Plotly figure, local export control and interpretation.\"\"\"\n    render_chart_export_controls(fig)\n    st.plotly_chart(\n        fig,\n        use_container_width=True,\n        config={\"displaylogo\": False, \"scrollZoom\": True},\n        key=next_plot_key(),\n    )\n    render_interpretation(text)\n'''

if old_render not in app:
    raise SystemExit("render_plot contract not found; aborting fail-closed")
app = app.replace(old_render, new_render, 1)

old_sidebar = '''    months = [MONTHS[m] for m in selected_month_names]\n    hours = list(range(selected_hours[0], selected_hours[1] + 1))\n    return filter_by_months_and_hours(df, months=months, hours=hours)\n'''
new_sidebar = '''    months = [MONTHS[m] for m in selected_month_names]\n    hours = list(range(selected_hours[0], selected_hours[1] + 1))\n    filtered = filter_by_months_and_hours(df, months=months, hours=hours)\n    # Export uses exactly the dataframe after the active global filters. Keeping\n    # it in transient Streamlit session state avoids duplicating filter logic in\n    # every chart renderer.\n    st.session_state[\"_active_filtered_export_df\"] = filtered\n    return filtered\n'''
if old_sidebar not in app:
    raise SystemExit("sidebar_filters contract not found; aborting fail-closed")
app = app.replace(old_sidebar, new_sidebar, 1)
APP.write_text(app, encoding="utf-8")

EXPORTING.write_text(r'''"""Tabular export helpers for Plotly charts and filtered climate data."""

from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd


_HTML_RE = re.compile(r"<[^>]+>")
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_export_stem(value: object, default: str = "climate_chart") -> str:
    """Return a conservative file-name stem suitable for browser downloads."""
    text = html.unescape(str(value or ""))
    text = _HTML_RE.sub(" ", text).strip()
    text = text.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if text.lower().endswith(".epw"):
        text = text[:-4]
    text = _SAFE_RE.sub("_", text).strip("._-")
    return text[:120] or default


def figure_export_stem(fig: Any) -> str:
    """Derive a readable CSV filename from the Plotly title when available."""
    title = ""
    try:
        title = fig.layout.title.text or ""
    except Exception:
        pass
    return safe_export_stem(title, default="climate_chart_data")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return list(value)
    except TypeError:
        return [value]


def _trace_name(trace: Any, index: int) -> str:
    name = getattr(trace, "name", None)
    if name:
        return str(name)
    return f"trace_{index + 1}"


def figure_to_dataframe(fig: Any) -> pd.DataFrame:
    """Convert common Plotly trace types to a stable long-form table.

    The export represents the data carried by the rendered Plotly traces. For
    heatmaps the Z matrix is flattened to x/y/value rows; for Cartesian, polar
    and categorical traces the native coordinates are retained. This avoids
    guessing at a page-specific upstream dataframe or aggregation.
    """
    rows: list[dict[str, Any]] = []
    for trace_index, trace in enumerate(getattr(fig, "data", ())):
        trace_type = str(getattr(trace, "type", trace.__class__.__name__))
        trace_name = _trace_name(trace, trace_index)

        z = getattr(trace, "z", None)
        if z is not None:
            matrix = _as_list(z)
            if matrix and not isinstance(matrix[0], (list, tuple)):
                matrix = [matrix]
            xs = _as_list(getattr(trace, "x", None))
            ys = _as_list(getattr(trace, "y", None))
            for row_index, matrix_row in enumerate(matrix):
                values = _as_list(matrix_row)
                y_value = ys[row_index] if row_index < len(ys) else row_index
                for column_index, value in enumerate(values):
                    x_value = xs[column_index] if column_index < len(xs) else column_index
                    rows.append(
                        {
                            "trace": trace_name,
                            "trace_type": trace_type,
                            "x": x_value,
                            "y": y_value,
                            "value": value,
                        }
                    )
            continue

        coordinate_pairs = (
            ("x", "y"),
            ("theta", "r"),
            ("labels", "values"),
        )
        exported = False
        for first_name, second_name in coordinate_pairs:
            first = _as_list(getattr(trace, first_name, None))
            second = _as_list(getattr(trace, second_name, None))
            if not first and not second:
                continue
            count = max(len(first), len(second))
            for point_index in range(count):
                rows.append(
                    {
                        "trace": trace_name,
                        "trace_type": trace_type,
                        "point": point_index,
                        first_name: first[point_index] if point_index < len(first) else None,
                        second_name: second[point_index] if point_index < len(second) else None,
                    }
                )
            exported = True
            break
        if exported:
            continue

        y_values = _as_list(getattr(trace, "y", None))
        if y_values:
            for point_index, value in enumerate(y_values):
                rows.append(
                    {
                        "trace": trace_name,
                        "trace_type": trace_type,
                        "point": point_index,
                        "y": value,
                    }
                )

    return pd.DataFrame(rows)


def figure_to_csv_bytes(fig: Any) -> bytes:
    """Return Plotly trace data as Excel-friendly UTF-8 CSV bytes."""
    table = figure_to_dataframe(fig)
    if table.empty:
        return b""
    return table.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Return the currently filtered analysis dataframe as UTF-8 CSV bytes."""
    out = df.copy()
    if not isinstance(out.index, pd.RangeIndex):
        index_name = out.index.name or "timestamp"
        out = out.reset_index(names=index_name)
    return out.to_csv(index=False).encode("utf-8-sig")
''', encoding="utf-8")

TEST.write_text(r'''from pathlib import Path

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
''', encoding="utf-8")

print("CLIMATE-EXPORT-0.1 patch applied")
