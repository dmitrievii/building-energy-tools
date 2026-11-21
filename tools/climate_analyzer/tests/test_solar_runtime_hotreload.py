"""Regression for a freshly deployed Streamlit app with stale cached solar imports."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import unittest

from epw_climate_analyzer import runtime_module_guard


class SolarRuntimeHotReloadTests(unittest.TestCase):
    def test_heatmap_stale_signature_refresh_and_stable_reuse(self):
        import inspect
        from epw_climate_analyzer import charts, chart_theme
        try:
            def old_heatmap(df,column,row_group,compare_across,statistic,title,unit):
                raise AssertionError("Stale heat-map API used")
            charts.temporal_heatmap_chart=old_heatmap
            refreshed=runtime_module_guard.ensure_current_heatmap_runtime()
            self.assertIn("matrix_override",inspect.signature(refreshed.temporal_heatmap_chart).parameters)
            current=refreshed.temporal_heatmap_chart
            self.assertIs(runtime_module_guard.ensure_current_heatmap_runtime().temporal_heatmap_chart,current)
            chart_theme._RUNTIME_SOURCE_SHA256="stale"
            self.assertIsNot(runtime_module_guard.ensure_current_heatmap_runtime().temporal_heatmap_chart,current)
        finally:
            importlib.reload(chart_theme)
            importlib.reload(charts)

    def test_shading_calendar_passes_exact_derived_matrix_after_refresh(self):
        import numpy as np
        import pandas as pd
        from epw_climate_analyzer import charts
        from epw_climate_analyzer.shading_calendar import shading_calendar,shading_matrix,shading_frame,AREA,OCCURRENCE
        idx=pd.date_range("2026-06-01",periods=48,freq="h")
        df=pd.DataFrame({"solar_azimuth_deg":180.,"solar_apparent_zenith_deg":45.},index=idx)
        geometry=dict(facade=180.,width=2.,height=2.,overhang=1.,left_fin=0.,right_fin=0.)
        try:
            def old_heatmap(df,column,row_group,compare_across,statistic,title,unit):
                raise AssertionError("Stale heat-map API used")
            charts.temporal_heatmap_chart=old_heatmap
            for metric in (AREA,OCCURRENCE):
                frame=shading_frame(df,geometry=geometry,metric=metric)
                expected,_=shading_matrix(frame,metric,"month","Hour of day","Mean")
                fig=shading_calendar(frame,metric,"month","Hour of day","Mean")
                np.testing.assert_allclose(np.asarray(fig.data[0].z,float),expected.values,equal_nan=True)
        finally:
            importlib.reload(charts)

    def test_current_module_does_not_reload_on_every_rerun(self) -> None:
        solar = runtime_module_guard.ensure_current_solar_runtime()
        original = solar.surface_irradiance_components
        self.assertIs(runtime_module_guard.ensure_current_solar_runtime().surface_irradiance_components, original)
        self.assertIs(runtime_module_guard.ensure_current_solar_runtime(), solar)

    def test_old_solar_without_new_export_gets_reloaded(self) -> None:
        solar = runtime_module_guard.ensure_current_solar_runtime()
        original = solar.source_ground_albedo
        try:
            delattr(solar, "source_ground_albedo")
            solar._RUNTIME_SOURCE_SHA256 = "stale"
            refreshed = runtime_module_guard.ensure_current_solar_runtime()
            self.assertIs(refreshed, solar)
            self.assertTrue(callable(refreshed.source_ground_albedo))
            self.assertNotEqual(refreshed._RUNTIME_SOURCE_SHA256, "stale")
        finally:
            importlib.reload(solar)
        self.assertIsNotNone(original)

    def test_incompatible_legacy_signature_gets_reloaded(self) -> None:
        solar = runtime_module_guard.ensure_current_solar_runtime()
        try:
            def old_orientation_annual_radiation(df, tilt_deg=90.0):
                return None

            solar.orientation_annual_radiation = old_orientation_annual_radiation
            refreshed = runtime_module_guard.ensure_current_solar_runtime()
            self.assertIn("albedo", importlib.import_module("inspect").signature(
                refreshed.orientation_annual_radiation,
            ).parameters)
        finally:
            importlib.reload(solar)

    def test_changed_source_fingerprint_forces_rebindable_module_refresh(self) -> None:
        solar = runtime_module_guard.ensure_current_solar_runtime()
        old_callable = solar.surface_irradiance_series
        try:
            solar._RUNTIME_SOURCE_SHA256 = "previous-release-hash"
            refreshed = runtime_module_guard.ensure_current_solar_runtime()
            self.assertIsNot(refreshed.surface_irradiance_series, old_callable)
            self.assertIs(refreshed, solar)
        finally:
            importlib.reload(solar)

    def test_app_refreshes_all_cached_solar_callables_before_rendering(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        source = app_path.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("current_solar = runtime_module_guard.ensure_current_solar_runtime()", source)
        for binding in (
            "add_solar_position",
            "monthly_orientation_radiation",
            "orientation_annual_radiation",
            "orientation_tilt_matrix",
            "surface_irradiance_series",
        ):
            self.assertIn(f"{binding} = current_solar.{binding}", source)
        self.assertIn(
            "solar_module = ensure_current_solar_runtime()",
            source,
        )
        # The unified façade renderer delegates POA calculations to a shared
        # module. Keep checking the guard at the actual calculation boundary.
        self.assertIn("render_facade_orientation(df, ground_albedo=ground_albedo)", source)
        facade_source = (app_path.parent / "epw_climate_analyzer" / "facade_orientation.py").read_text(encoding="utf-8")
        tree = ast.parse(facade_source)
        summary = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "surface_period_summary")
        guarded_calls = [
            node for node in ast.walk(summary)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "surface_irradiance_components"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "ensure_current_solar_runtime"
        ]
        self.assertEqual(len(guarded_calls), 1)

    def test_facade_summary_refreshes_poa_callable_on_each_request(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        import pandas as pd
        from epw_climate_analyzer.facade_orientation import surface_period_summary, TOTAL

        frame = pd.DataFrame(index=pd.date_range("2025-01-01", periods=2, freq="h"))

        def response(direct):
            return pd.DataFrame({
                "poa_direct_wh_m2": [direct, direct],
                "poa_sky_diffuse_wh_m2": [20., 20.],
                "poa_ground_diffuse_wh_m2": [10., 10.],
                "poa_global_wh_m2": [direct + 30., direct + 30.],
            }, index=frame.index)

        first = Mock(return_value=response(100.))
        second = Mock(return_value=response(200.))
        with patch.object(runtime_module_guard, "ensure_current_solar_runtime",
                          side_effect=[SimpleNamespace(surface_irradiance_components=first),
                                       SimpleNamespace(surface_irradiance_components=second)]) as guard:
            a = surface_period_summary(frame, 90., 180., albedo=.2)
            b = surface_period_summary(frame, 90., 180., albedo=.2)
            self.assertEqual(guard.call_count, 2)
        first.assert_called_once_with(frame, 90., 180., albedo=.2)
        second.assert_called_once_with(frame, 90., 180., albedo=.2)
        self.assertAlmostEqual(a[TOTAL], .26)
        self.assertAlmostEqual(b[TOTAL], .46)
        self.assertEqual(b["valid_intervals"], 2)


if __name__ == "__main__":
    unittest.main()
