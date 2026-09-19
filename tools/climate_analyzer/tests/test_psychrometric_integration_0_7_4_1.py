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
    def test_release_tree_contains_no_old_temporary_transport(self) -> None:
        for workflow in (
            "v0741-full-test-diagnostic.yml",
            "v0741-ci-diagnose.yml",
            "v0741-psychrometric-patch.yml",
            "v0741-pressure-fallback-patch.yml",
        ):
            self.assertFalse((REPO_ROOT / ".github" / "workflows" / workflow).exists(), workflow)
        for script in (
            "apply_v0741_psychrometric.py",
            "apply_v0741_pressure_fallback.py",
        ):
            self.assertFalse((ROOT / "scripts" / script).exists(), script)

    def test_runtime_has_no_old_selected_cell_envelope_api(self) -> None:
        runtime = "\n".join(path.read_text(encoding="utf-8") for path in (CHARTS, COMPARISON, DISTRIBUTION))
        self.assertNotIn("PsychrometricOccupancyEnvelope", runtime)
        self.assertNotIn("psychrometric_occupancy_envelope", runtime)
        self.assertNotIn("envelope_polygon_coordinates", runtime)
        self.assertNotIn("selected_tiles", runtime)

    def test_single_climate_ui_exposes_all_three_peer_representations(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)
        self.assertIn('"Outer contour coverage [%]"', source)
        self.assertIn('"Additional contour levels [%]"', source)
        self.assertNotIn('"Show 50% core contour"', source)
        self.assertIn('"All years combined"', source)
        self.assertIn('"Single year"', source)
        self.assertIn('"Compare selected years"', source)

    def test_comparison_ui_uses_one_common_reference_pressure(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('"Psychrometric climate zones"', source)
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)
        self.assertIn('"Reference psychrometric pressure"', source)
        self.assertIn('"Standard atmosphere — 101325 Pa"', source)
        self.assertIn('"Reference climate — {reference_name}"', source)
        self.assertIn("points, grid cells and contours", source.lower())
        self.assertIn("source station-pressure data remain unchanged", source.lower())

    def test_missing_pressure_fallbacks_are_location_specific(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))"), 2)
        self.assertIn("else pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))", source)


if __name__ == "__main__":
    unittest.main()
