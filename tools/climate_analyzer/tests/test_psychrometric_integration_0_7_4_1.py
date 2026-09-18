from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
APP = ROOT / "app.py"
CHARTS = ROOT / "epw_climate_analyzer" / "charts.py"
COMPARISON = ROOT / "epw_climate_analyzer" / "comparison.py"
DISTRIBUTION = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"


class PsychrometricIntegration0741Tests(unittest.TestCase):
    def test_release_tree_contains_no_temporary_diagnostic_or_patch_transport(self) -> None:
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "v0741-full-test-diagnostic.yml").exists())
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "v0741-psychrometric-patch.yml").exists())
        self.assertFalse((ROOT / "scripts" / "apply_v0741_psychrometric.py").exists())

    def test_runtime_has_no_old_selected_cell_envelope_api(self) -> None:
        runtime = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (CHARTS, COMPARISON, DISTRIBUTION)
        )
        self.assertNotIn("PsychrometricOccupancyEnvelope", runtime)
        self.assertNotIn("psychrometric_occupancy_envelope", runtime)
        self.assertNotIn("envelope_polygon_coordinates", runtime)
        self.assertNotIn("selected_tiles", runtime)

    def test_single_climate_ui_is_zone_first_and_year_aware(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('["Climate zone", "Points"]', source)
        self.assertIn('"Zone coverage [%]"', source)
        self.assertIn('"Zone interior"', source)
        self.assertIn('"Show 50% core contour"', source)
        self.assertIn('"All years combined"', source)
        self.assertIn('"Single year"', source)
        self.assertIn('"Compare selected years"', source)

    def test_comparison_ui_is_zone_first_and_reference_grid_pressure_is_explicit(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('"Psychrometric climate zones"', source)
        self.assertIn('["Climate zones", "Points"]', source)
        self.assertIn('"Reference psychrometric grid pressure"', source)
        self.assertIn('"Standard atmosphere — 101325 Pa"', source)
        self.assertIn('"Reference climate — {reference_name}"', source)
        self.assertIn("grid is only a visual psychrometric reference", source)

    def test_epw_missing_pressure_fallback_is_location_specific(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))", source)


if __name__ == "__main__":
    unittest.main()
