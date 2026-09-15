from pathlib import Path
import unittest

import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.exporting import (
    dataframe_to_csv_bytes,
    figure_export_stem,
    figure_to_dataframe,
    safe_export_stem,
)


class LocalChartExportTests(unittest.TestCase):
    def test_scatter_trace_exports_visible_coordinates(self):
        fig = go.Figure(go.Scatter(x=[1, 2], y=[10.5, 11.5], name="Air temperature"))
        table = figure_to_dataframe(fig)
        self.assertEqual(table["trace"].tolist(), ["Air temperature", "Air temperature"])
        self.assertEqual(table["x"].tolist(), [1, 2])
        self.assertEqual(table["y"].tolist(), [10.5, 11.5])

    def test_heatmap_exports_long_form_cells(self):
        fig = go.Figure(go.Heatmap(x=["00", "01"], y=["Jan", "Feb"], z=[[1, 2], [3, 4]], name="Heatmap"))
        table = figure_to_dataframe(fig)
        self.assertEqual(len(table), 4)
        self.assertTrue({"trace", "trace_type", "x", "y", "value"}.issubset(set(table.columns)))
        self.assertEqual(table["value"].tolist(), [1, 2, 3, 4])

    def test_filtered_dataframe_preserves_datetime_index(self):
        df = pd.DataFrame(
            {"dry_bulb_temperature_c": [1.0]},
            index=pd.DatetimeIndex(["2026-01-01T00:00:00Z"], name="time"),
        )
        csv_text = dataframe_to_csv_bytes(df).decode("utf-8-sig")
        self.assertIn("time", csv_text)
        self.assertIn("dry_bulb_temperature_c", csv_text)

    def test_export_filename_is_safe_and_title_driven(self):
        fig = go.Figure()
        fig.update_layout(title="<b>Monthly temperature / Graz</b>")
        self.assertEqual(figure_export_stem(fig), "Monthly_temperature_Graz")
        self.assertEqual(safe_export_stem("Graz weather.epw"), "Graz_weather")

    def test_app_places_compact_export_next_to_every_render_plot(self):
        app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertIn('with st.popover("⇩")', app)
        self.assertIn('"Chart data · CSV"', app)
        self.assertIn('"Filtered data · CSV"', app)
        self.assertIn('"Source weather · EPW"', app)
        self.assertIn('st.session_state["_active_filtered_export_df"] = filtered', app)
        self.assertIn("render_chart_export_controls(fig)", app)


if __name__ == "__main__":
    unittest.main()
