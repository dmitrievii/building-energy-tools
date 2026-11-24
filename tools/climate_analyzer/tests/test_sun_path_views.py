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
    radiation_sun_path, solar_reference, sun_direction_xyz, sun_path_3d, technical_sun_path,
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
        lines = [trace for trace in fig.data if trace.mode == "lines" and trace.showlegend and trace.legendgroup.startswith("month-")]
        self.assertEqual(len(lines), 12)
        self.assertEqual(tuple(trace.line.color for trace in lines), MONTH_COLORS)
        self.assertEqual(tuple(fig.layout.polar.radialaxis.range), (0, 90))
        self.assertEqual(fig.layout.polar.angularaxis.direction, "clockwise")
        self.assertTrue(any(trace.line.dash == "dot" for trace in fig.data if trace.mode == "lines"))

    def test_radiation_preserves_samples_and_uses_shared_month_geometry(self):
        frame = self.frame.copy()
        frame.loc[frame["is_daylight"], "direct_normal_radiation_wh_m2"] = 0
        fig = radiation_sun_path(frame, hide_zero_radiation=True)
        self.assertEqual(len([trace for trace in fig.data if trace.showlegend and trace.legendgroup.startswith("month-")]), 12)
        original = radiation_sun_path(self.frame)
        points = next(trace for trace in original.data if trace.type == "scatterpolargl")
        self.assertEqual(len(points.r), int(self.frame["is_daylight"].sum()))
        self.assertTrue(np.all(np.asarray(points.marker.color) == 300))
        geometric = [trace for trace in original.data if trace.showlegend and trace.legendgroup.startswith("month-")]
        classic = [trace for trace in classic_sun_path(self.frame).data if trace.showlegend and trace.legendgroup.startswith("month-")]
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

    def test_polar_radiation_is_only_an_optional_overlay(self):
        plain = classic_sun_path(self.frame)
        self.assertEqual(plain.layout.title.text, "2D sun-path diagram")
        self.assertEqual(plain.layout.meta["radiation_field"], "")
        self.assertFalse(any(t.type == "scatterpolargl" for t in plain.data))
        self.assertFalse(plain.layout.annotations)
        self.assertIsNone(plain.layout.coloraxis.colorbar.title.text)
        for field, _ in available_radiation_fields(self.frame):
            enabled = classic_sun_path(self.frame, radiation_field=field)
            self.assertEqual(enabled.layout.title.text, plain.layout.title.text)
            self.assertEqual(enabled.layout.polar.to_plotly_json(), plain.layout.polar.to_plotly_json())
            self.assertEqual(enabled.layout.legend.to_plotly_json(), plain.layout.legend.to_plotly_json())
            reference = [t for t in enabled.data if t.legendgroup != "radiation-overlay"]
            self.assertEqual(len(reference), len(plain.data))
            for a, b in zip(plain.data, reference):
                self.assertEqual(a.name, b.name)
                self.assertEqual(a.legendgroup, b.legendgroup)
                self.assertEqual(a.mode, b.mode)
                self.assertEqual(a.line.to_plotly_json(), b.line.to_plotly_json())
                np.testing.assert_allclose(a.theta, b.theta, equal_nan=True)
                np.testing.assert_allclose(a.r, b.r, equal_nan=True)
            self.assertEqual(enabled.layout.meta["radiation_field"], field)
            points = next(t for t in enabled.data if t.legendgroup == "radiation-overlay")
            self.assertEqual(len(points.r), int(self.frame["is_daylight"].sum()))
        absent = classic_sun_path(self.frame.drop(columns=[c for c, _ in available_radiation_fields(self.frame)]))
        self.assertFalse(absent.layout.annotations)
        self.assertEqual(len(absent.data),len(plain.data))

    def test_rotatable_3d_cube_is_illustrative_and_camera_revision_stable(self):
        visible = sun_path_3d(self.frame, show_cube=True)
        hidden = sun_path_3d(self.frame, show_cube=False)
        self.assertEqual(visible.layout.scene.dragmode, "turntable")
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

    def test_month_colors_and_complete_legend_groups_in_all_four_views(self):
        for factory in (radiation_sun_path, technical_sun_path, classic_sun_path, sun_path_3d):
            with self.subTest(view=factory.__name__):
                fig = factory(self.frame)
                self.assertTrue(fig.layout.showlegend)
                self.assertEqual(fig.layout.legend.groupclick, "togglegroup")
                self.assertEqual(fig.layout.legend.itemclick, "toggle")
                self.assertEqual(fig.layout.legend.itemdoubleclick, "toggleothers")
                for m, color in enumerate(MONTH_COLORS, 1):
                    group = [t for t in fig.data if t.legendgroup == f"month-{m}"]
                    main = [t for t in group if t.showlegend]
                    self.assertEqual(len(main), 1)
                    self.assertEqual(main[0].line.color, color)
                    self.assertEqual(main[0].line.dash, "solid" if m <= 6 else "dash")
                    self.assertTrue(all(t.legendgroup == main[0].legendgroup for t in group))
                    if factory in (radiation_sun_path, classic_sun_path):
                        self.assertEqual(len(group), 3)  # halo, coloured line, text
                    elif factory is not sun_path_3d:
                        self.assertEqual(len(group), 2)
                    else:
                        self.assertEqual(len(group), 1)

    def test_restored_technical_chart_uses_cartesian_axes_and_reference_geometry(self):
        fig = technical_sun_path(self.frame)
        self.assertEqual(fig.layout.xaxis.title.text, "Solar azimuth [deg]")
        self.assertEqual(fig.layout.yaxis.title.text, "Solar elevation [deg]")
        self.assertEqual(len([t for t in fig.data if t.showlegend and t.legendgroup.startswith("month-")]), 12)
        for month,(az,el) in enumerate(solar_reference(self.frame).months,1):
            trace = next(t for t in fig.data if t.legendgroup == f"month-{month}" and t.showlegend)
            mask = np.isfinite(np.asarray(trace.y,dtype=float))
            np.testing.assert_allclose(np.asarray(trace.y,dtype=float)[mask], el[np.isfinite(el)])
            np.testing.assert_allclose(np.asarray(trace.x,dtype=float)[mask], az[np.isfinite(az)])
        from epw_climate_analyzer.charts import sun_position_diagram
        self.assertEqual(sun_position_diagram(self.frame).layout.xaxis.title.text, fig.layout.xaxis.title.text)

    def test_technical_cardinal_labels_are_part_of_axis_and_clear_of_title(self):
        from epw_climate_analyzer.chart_presentation import (
            ChartPresentationSettings, apply_chart_presentation,
        )
        for size in (12, 18, 26):
            fig = technical_sun_path(self.frame)
            apply_chart_presentation(fig, ChartPresentationSettings(font_size=size))
            axis = fig.layout.xaxis
            labels = dict(zip(axis.tickvals, axis.ticktext))
            self.assertEqual(labels[90], "90°<br>East")
            self.assertEqual(labels[180], "180°<br>South")
            self.assertEqual(labels[270], "270°<br>West")
            self.assertEqual(axis.tickfont.size, size)
            self.assertTrue(axis.automargin)
            self.assertGreaterEqual(axis.title.standoff, 18)
            self.assertFalse(any(a.text in {"North", "East", "South", "West"}
                                 for a in fig.layout.annotations))
            self.assertEqual(fig.layout.legend.yref, "container")
            self.assertEqual(fig.layout.legend.yanchor, "bottom")

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
    st.session_state["test_radiation_field"] = (fig.layout.meta or {}).get("radiation_field")
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
        self.assertEqual(chart.options, ["2D sun-path diagram", "Technical sun-path diagram", "3D sun-path diagram"])
        self.assertNotIn("solar_sun_path_show_cube", [w.key for w in app.checkbox])
        self.assertEqual(chart.value, "2D sun-path diagram")
        quantity = app.selectbox(key="solar_sun_path_radiation_quantity")
        self.assertEqual(quantity.options, ["None", "DNI"])
        self.assertEqual(quantity.value, "None")
        self.assertEqual(app.session_state["test_radiation_field"], "")
        self.assertNotIn("solar_path_hide_zero", [w.key for w in app.checkbox])
        quantity.set_value("DNI").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_radiation_field"], "direct_normal_radiation_wh_m2")
        self.assertIn("solar_path_hide_zero", [w.key for w in app.checkbox])
        app.selectbox(key="solar_sun_path_radiation_quantity").set_value("None").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["test_radiation_field"], "")
        app.selectbox(key="solar_sun_path_chart_type").set_value("Technical sun-path diagram").run()
        self.assertFalse(app.exception)
        self.assertNotIn("solar_sun_path_show_cube", [w.key for w in app.checkbox])
        app.selectbox(key="solar_sun_path_chart_type").set_value("2D sun-path diagram").run()
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
        self.assertIn('["2D sun-path diagram", "Technical sun-path diagram", "3D sun-path diagram"]', section)
        self.assertIn('st.checkbox("Show cube", value=True', section)
        self.assertIn("fig = sun_path_3d(df, show_cube=show_cube)",section)
        self.assertIn('render_plot(fig,solar_figure_interpretation(df,fig,"sunpath_view",args=("3D","None")))',section)
        self.assertIn('args=("2D",field or colour,invert_zenith_axis,cold,warm,shading_geometry)',section)
        self.assertIn('args=("Technical",colour,False,cold,warm,shading_geometry)',section)
        from epw_climate_analyzer.solar_findings import solar_figure_interpretation
        text=solar_figure_interpretation(None,None,"sunpath_view",args=("3D","None"))
        self.assertIn("East, North and Up",text)
        text=solar_figure_interpretation(None,None,"sunpath_view",
            args=("2D","Solar benefit / risk",True,15.,28.))
        self.assertIn("horizon lies at the centre",text)
        self.assertIn("15 °C",text)
        self.assertIn("28 °C",text)
        renderer=source[source.index("def render_plot("):source.index("def render_plot(",0)+1400]
        self.assertIn("st.plotly_chart(",renderer)
        self.assertIn("key=next_plot_key()",renderer)
        self.assertEqual(source.count('elif chart_group == "Sun path":'), 2)


if __name__ == "__main__":
    unittest.main()
