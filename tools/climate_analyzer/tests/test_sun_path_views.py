"""Shared sun-path geometry, radiation provenance and 3D display regression."""
from __future__ import annotations

from pathlib import Path
import ast
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.exporting import figure_to_dataframe
from epw_climate_analyzer.solar import add_solar_position_for_site
from epw_climate_analyzer.sun_path_views import (
    MONTH_COLORS, available_radiation_fields, classic_sun_path,
    radiation_sun_path, solar_reference, sun_direction_xyz, sun_path_3d,
)


class SunPathViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A measured June-only sample must still have 12 annual reference paths.
        idx = pd.date_range("2025-06-02", periods=48, freq="h", tz="Europe/Vienna")
        cls.frame = add_solar_position_for_site(
            pd.DataFrame({"direct_normal_radiation_wh_m2": 300.0,
                          "global_horizontal_radiation_wh_m2": 200.0,
                          "month_index": idx.month, "hour_of_day": idx.hour}, index=idx),
            latitude=48.2, longitude=16.4, elevation_m=200,
        )

    def test_full_reference_independent_of_weather_and_filters(self):
        ref = solar_reference(self.frame)
        self.assertEqual(ref.year, 2025)
        self.assertEqual(ref.utc_offset_hours, 1.0)
        self.assertEqual(len(ref.months), 12)
        self.assertTrue(all(len(a) > 0 for a, _ in ref.months))
        self.assertIs(ref, solar_reference(self.frame.iloc[:1]))
        self.assertGreater(np.nanmax(ref.months[5][1]), 60)
        self.assertLess(np.nanmax(ref.months[11][1]), 25)
        for az, el in (*ref.months, *ref.hours):
            finite = np.isfinite(el)
            self.assertTrue((el[finite] >= 0).all())
            self.assertTrue((el[finite] <= 90).all())
            self.assertTrue(((az[finite] >= 0) & (az[finite] < 360)).all())

    def test_classic_polar_and_month_gradient(self):
        fig = classic_sun_path(self.frame)
        lines = [trace for trace in fig.data if trace.mode == "lines" and trace.showlegend]
        self.assertEqual(len(lines), 12)
        self.assertEqual(tuple(trace.line.color for trace in lines), MONTH_COLORS)
        self.assertEqual(tuple(fig.layout.polar.radialaxis.range), (0, 90))
        self.assertEqual(fig.layout.polar.angularaxis.direction, "clockwise")
        self.assertTrue(any(trace.line.dash == "dot" for trace in fig.data if trace.mode == "lines"))

    def test_radiation_preserves_samples_and_uses_shared_month_geometry(self):
        frame = self.frame.copy()
        frame.loc[frame["is_daylight"], "direct_normal_radiation_wh_m2"] = 0
        fig = radiation_sun_path(frame, hide_zero_radiation=True)
        self.assertEqual(len([trace for trace in fig.data if trace.showlegend]), 12)
        original = radiation_sun_path(self.frame)
        points = next(trace for trace in original.data if trace.type == "scatterpolargl")
        self.assertEqual(len(points.r), int(self.frame["is_daylight"].sum()))
        self.assertTrue(np.all(np.asarray(points.marker.color) == 300))
        geometric = [trace for trace in original.data if trace.showlegend]
        classic = [trace for trace in classic_sun_path(self.frame).data if trace.showlegend]
        for a, b in zip(geometric, classic):
            np.testing.assert_allclose(a.theta, b.theta, equal_nan=True)
            np.testing.assert_allclose(a.r, b.r, equal_nan=True)
        self.assertEqual(original.layout.meta["radiation_field"], "direct_normal_radiation_wh_m2")
        inverted = radiation_sun_path(self.frame, invert_zenith_axis=True)
        self.assertEqual(tuple(inverted.layout.polar.radialaxis.range), (90, 0))
        self.assertEqual(inverted.layout.polar.radialaxis.ticktext, original.layout.polar.radialaxis.ticktext)
        horizontal = self.frame.drop(columns="direct_normal_radiation_wh_m2")
        self.assertEqual(available_radiation_fields(horizontal), [("global_horizontal_radiation_wh_m2", "GHI")])
        self.assertEqual(radiation_sun_path(horizontal).layout.meta["radiation_field"],
                         "global_horizontal_radiation_wh_m2")

    def test_rotatable_3d_cube_is_illustrative_and_camera_revision_stable(self):
        visible = sun_path_3d(self.frame, show_cube=True)
        hidden = sun_path_3d(self.frame, show_cube=False)
        self.assertEqual(visible.layout.scene.dragmode, "orbit")
        self.assertEqual(visible.layout.scene.uirevision, hidden.layout.scene.uirevision)
        self.assertEqual(visible.layout.scene.camera, hidden.layout.scene.camera)
        self.assertEqual(len(visible.data), len(hidden.data))
        for name in ("Illustrative cube", "Cube edges"):
            self.assertTrue(next(t for t in visible.data if t.name == name).visible)
            self.assertFalse(next(t for t in hidden.data if t.name == name).visible)
        paths = [t for t in visible.data if t.showlegend is not False and t.name.endswith("21")]
        self.assertEqual(len(paths), 12)
        for trace, (az, el) in zip(paths, solar_reference(self.frame).months):
            x,y,z = sun_direction_xyz(az, el)
            np.testing.assert_allclose(trace.x, x, equal_nan=True)
            np.testing.assert_allclose(trace.y, y, equal_nan=True)
            np.testing.assert_allclose(trace.z, z, equal_nan=True)
            np.testing.assert_allclose(x*x+y*y+z*z, np.where(np.isfinite(z), 1.0, np.nan), atol=1e-12)
        table = figure_to_dataframe(visible)
        jan = table[table["trace"] == "Jan 21"]
        np.testing.assert_allclose(jan["x"], paths[0].x, equal_nan=True)
        np.testing.assert_allclose(jan["y"], paths[0].y, equal_nan=True)
        np.testing.assert_allclose(jan["z"], paths[0].z, equal_nan=True)
        self.assertNotIn("Illustrative cube", set(figure_to_dataframe(hidden)["trace"]))
        x,y,z = sun_direction_xyz(np.array([0.,90.,180.,270.,0.]), np.array([0.,0.,0.,0.,90.]))
        np.testing.assert_allclose(x, [0,1,0,-1,0], atol=1e-12)
        np.testing.assert_allclose(y, [1,0,-1,0,0], atol=1e-12)
        np.testing.assert_allclose(z, [0,0,0,0,1], atol=1e-12)

    def test_no_invented_path_in_polar_night(self):
        frame = self.frame.copy()
        frame.attrs["solar_geometry_site"] = {**frame.attrs["solar_geometry_site"], "latitude": 80.0}
        ref = solar_reference(frame)
        self.assertEqual(len(ref.months[11][0]), 0)
        self.assertGreater(len(ref.months[5][0]), 0)

    def test_real_chart_type_widget_and_cube_toggle(self):
        from streamlit.testing.v1 import AppTest

        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        target = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.FunctionDef) and node.name == "render_sun_path")
        widget_source = ast.get_source_segment(source, target)
        prefix = """
import streamlit as st
import pandas as pd
from epw_climate_analyzer.solar import add_solar_position_for_site
def render_plot(fig, text):
    st.plotly_chart(fig, key="test_sun_2d")
def render_chart_export_controls(fig):
    pass
def render_interpretation(text):
    pass
index = pd.date_range("2025-06-02", periods=24, freq="h", tz="UTC")
df = add_solar_position_for_site(pd.DataFrame({"direct_normal_radiation_wh_m2": 300.}, index=index),
                                  latitude=48.2, longitude=16.4)
"""
        app = AppTest.from_string(prefix + "\n" + widget_source + "\nrender_sun_path(df)", default_timeout=45).run()
        self.assertFalse(app.exception)
        chart = app.selectbox(key="solar_sun_path_chart_type")
        self.assertEqual(chart.label, "Chart type")
        self.assertEqual(chart.options, ["Sun path with radiation", "2D sun-path diagram", "3D sun-path diagram"])
        self.assertNotIn("solar_sun_path_show_cube", [w.key for w in app.checkbox])
        chart.set_value("2D sun-path diagram").run()
        self.assertFalse(app.exception)
        self.assertNotIn("solar_sun_path_show_cube", [w.key for w in app.checkbox])
        app.selectbox(key="solar_sun_path_chart_type").set_value("3D sun-path diagram").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.checkbox(key="solar_sun_path_show_cube").value)
        app.checkbox(key="solar_sun_path_show_cube").set_value(False).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.checkbox(key="solar_sun_path_show_cube").value)

    def test_merged_ui_contract(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        section = source[source.index("def render_sun_path("):source.index("def render_solar(")]
        self.assertIn('st.selectbox("Chart type", chart_types', section)
        self.assertIn('["Sun path with radiation", "2D sun-path diagram", "3D sun-path diagram"]', section)
        self.assertIn('st.checkbox("Show cube", value=True', section)
        self.assertIn('key="solar_sun_path_3d_plot"', section)
        self.assertEqual(source.count('elif chart_group == "Sun path":'), 2)


if __name__ == "__main__":
    unittest.main()
