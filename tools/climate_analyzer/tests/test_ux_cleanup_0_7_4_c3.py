from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
APP = ROOT / "app.py"


def function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[start:end]


class UxCleanup074C3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_overview_does_not_duplicate_temperature_profile(self) -> None:
        overview = function_block(self.source, "render_overview", "render_temperature")
        historical = function_block(self.source, "render_historical_overview", "render_historical_wind")
        self.assertNotIn("Monthly outdoor temperature profile", overview)
        self.assertNotIn("Canonical hourly monthly outdoor temperature", historical)

    def test_sky_daylight_has_one_quantity_explorer_with_quantity_aware_routes(self) -> None:
        block = function_block(self.source, "render_sky_daylight", "render_natural_ventilation")
        self.assertIn('"Sky and daylight explorer"', block)
        self.assertIn('"Quantity"', block)
        self.assertIn('"Measured sunshine duration"', block)
        self.assertIn('"Relative sunshine duration"', block)
        self.assertIn("sum(min_count=1)", block)
        self.assertIn("fixed_variable_label=quantity", block)
        self.assertIn("it is never converted into sky cover, illuminance or DNI", block)

    def test_natural_ventilation_removes_redundant_month_hour_route(self) -> None:
        block = function_block(self.source, "render_natural_ventilation", "render_hvac_passive")
        self.assertNotIn('"Month × hour suitability"', block)
        self.assertIn('compare_options = ["Hour of day"] if time_basis(df_nv) == CHRONOLOGICAL', block)
        self.assertIn("Switch Time basis to Calendar profile", block)

    def test_humidity_is_canonical_for_moisture_thresholds_and_hvac_has_no_duplicate_routes(self) -> None:
        humidity = function_block(self.source, "render_humidity", "render_wind")
        hvac = function_block(self.source, "render_hvac_passive", "render_time_series_overlay")
        self.assertIn('"Moisture thresholds"', humidity)
        self.assertNotIn('"Dehumidification and humidification"', hvac)
        self.assertNotIn('"Outdoor-air enthalpy duration curve"', hvac)
        self.assertNotIn('"Heating and cooling degree-hours"', hvac)
        self.assertIn('"Passive strategy summary"', hvac)
        self.assertIn('["Annual totals", "Monthly stacked bars"]', hvac)

    def test_temporary_c3_transport_is_not_part_of_release_tree(self) -> None:
        self.assertFalse((ROOT / "scripts" / "apply_v074_c3.py").exists())
        for name in ("v074-c3-patch.yml", "v074-c3b-patch.yml", "v074-c3c-patch.yml"):
            self.assertFalse((REPO_ROOT / ".github" / "workflows" / name).exists())


if __name__ == "__main__":
    unittest.main()
