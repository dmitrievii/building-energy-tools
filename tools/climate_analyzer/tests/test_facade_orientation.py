"""Regression: unified façade components, solar rose and widget controls."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.facade_orientation import (
    COMPONENTS, TOTAL, orientation_period_components, orientation_components_chart,
    surface_period_summary,
)
from epw_climate_analyzer.solar import orientation_annual_radiation, surface_irradiance_components


def fixture():
    idx = pd.date_range("2025-06-01T12:00:00Z", periods=5, freq="h")
    return pd.DataFrame({
        "solar_apparent_zenith_deg": [35., 45., 55., 70., 80.],
        "solar_azimuth_deg": [90., 135., 180., 225., 270.],
        "direct_normal_radiation_wh_m2": [600., 650., 700., 600., 400.],
        "global_horizontal_radiation_wh_m2": [600., 580., 500., 350., 250.],
        "diffuse_horizontal_radiation_wh_m2": [100., 120., 140., 160., 180.],
    }, index=idx)


class FacadeOrientationTests(unittest.TestCase):
    def test_same_physics_components_close_and_match_legacy_totals(self):
        frame = fixture()
        frame.iloc[0, frame.columns.get_loc("direct_normal_radiation_wh_m2")] = np.nan
        for tilt in (0, 30, 90):
            for albedo in (0.2, 0.5, pd.Series(.3,index=frame.index)):
                data, flat = orientation_period_components(frame, tilt, albedo=albedo)
                old = orientation_annual_radiation(frame, tilt_deg=tilt, albedo=albedo)
                np.testing.assert_allclose(data[TOTAL], old["annual_kwh_m2"], atol=1e-12)
                np.testing.assert_allclose(data[TOTAL], data[[c[0] for c in COMPONENTS]].sum(axis=1), atol=1e-12)
                roof = surface_irradiance_components(frame, 0, 0, albedo=albedo)
                self.assertAlmostEqual(flat[TOTAL], roof["poa_global_wh_m2"].sum()/1000)
                self.assertEqual(flat["valid_intervals"], 4)
                self.assertEqual(flat["ground_reflected_kwh_m2"], 0)
                if tilt == 0:
                    np.testing.assert_allclose(data[TOTAL], flat[TOTAL], atol=1e-12)

    def test_both_chart_styles_have_identical_component_values(self):
        data, flat = orientation_period_components(fixture())
        for selected in ((), ("direct_kwh_m2",), ("direct_kwh_m2","sky_diffuse_kwh_m2"),
                         tuple(c[0] for c in COMPONENTS)):
            bar = orientation_components_chart(data, flat, tilt_deg=90, selected=selected)
            rose = orientation_components_chart(data, flat, tilt_deg=90, style="Solar rose", selected=selected)
            b = [t for t in bar.data if t.type == "bar"]
            r = [t for t in rose.data if t.type == "barpolar"]
            self.assertEqual(len(b), len(selected) or 1)
            self.assertEqual(len(r), len(b))
            self.assertEqual(tuple(rose.layout.polar.angularaxis.ticktext), ("N","NE","E","SE","S","SW","W","NW"))
            self.assertEqual(rose.layout.polar.angularaxis.direction, "clockwise")
            self.assertEqual(rose.layout.polar.barmode, "stack")
            self.assertIn("Flat roof", rose.layout.annotations[0].text)
            for bt, rt, key in zip(b,r,selected or (TOTAL,)):
                np.testing.assert_allclose(bt.y, data[key])
                np.testing.assert_allclose(rt.r, data[key])
                np.testing.assert_allclose(rt.theta, data["azimuth_deg"])
                self.assertIsNone(rt.base)
            self.assertEqual(rose.layout.meta["displayed_components"], list(selected or (TOTAL,)))
            self.assertAlmostEqual(rose.layout.meta["flat_roof_total_kwh_m2"], flat[TOTAL])

    def test_missing_data_are_not_zero_irradiation(self):
        frame = fixture()
        frame["direct_normal_radiation_wh_m2"] = np.nan
        data, flat = orientation_period_components(frame)
        self.assertTrue(data[TOTAL].isna().all())
        self.assertTrue(np.isnan(flat[TOTAL]))
        fig = orientation_components_chart(data, flat, tilt_deg=90, style="Solar rose")
        self.assertIn("No data", fig.layout.annotations[0].text)

    def test_custom_azimuth_uses_same_poa_model(self):
        frame = fixture()
        summary = surface_period_summary(frame, 45, 62, albedo=.3)
        poa = surface_irradiance_components(frame,45,62,albedo=.3)
        self.assertAlmostEqual(summary[TOTAL],poa["poa_global_wh_m2"].sum()/1000)

    def test_ui_unifies_facade_routes(self):
        source = (Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        target = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=="render_solar")
        body = ast.get_source_segment(source,target)
        self.assertNotIn('"Plane-of-array components"', body)
        self.assertIn("render_facade_orientation(df, ground_albedo=ground_albedo)", body)

    def test_actual_chart_type_and_checkboxes(self):
        from streamlit.testing.v1 import AppTest
        source = (Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        target = next(n for n in ast.parse(source).body
                      if isinstance(n, ast.FunctionDef) and n.name == "render_facade_orientation")
        script = """
import streamlit as st
import pandas as pd
def render_plot(fig, text):
    st.plotly_chart(fig, key="facade_chart")
df = pd.DataFrame({
    "solar_apparent_zenith_deg":[45.,50.],
    "solar_azimuth_deg":[120.,180.],
    "direct_normal_radiation_wh_m2":[500.,600.],
    "global_horizontal_radiation_wh_m2":[400.,450.],
    "diffuse_horizontal_radiation_wh_m2":[100.,120.],
},index=pd.date_range("2025-01-01",periods=2,freq="h"))
"""
        app = AppTest.from_string(script+"\n"+ast.get_source_segment(source,target)+
                                  "\nrender_facade_orientation(df)",default_timeout=45).run()
        self.assertFalse(app.exception)
        menu = app.selectbox(key="solar_facade_chart_type")
        self.assertEqual(menu.label,"Chart type")
        self.assertEqual(menu.options,["Bar chart","Solar rose"])
        menu.set_value("Solar rose").run()
        self.assertFalse(app.exception)
        app.checkbox(key="solar_facade_direct_kwh_m2").set_value(True).run()
        self.assertFalse(app.exception)
        app.checkbox(key="solar_facade_sky_diffuse_kwh_m2").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.checkbox(key="solar_facade_direct_kwh_m2").value)


if __name__ == "__main__":
    unittest.main()
