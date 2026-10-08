"""Regression for a freshly deployed Streamlit app with stale cached solar imports."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import unittest

from epw_climate_analyzer import runtime_module_guard


class SolarRuntimeHotReloadTests(unittest.TestCase):
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
        self.assertIn(
            "surface_irradiance_components = ensure_current_solar_runtime().surface_irradiance_components",
            source,
        )


if __name__ == "__main__":
    unittest.main()
