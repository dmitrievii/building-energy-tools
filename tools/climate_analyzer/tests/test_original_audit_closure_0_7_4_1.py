from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.ground_temperature import AnnualHarmonic, animated_profile_figure, monthly_ground_profile, profile_figure
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
APP = ROOT / "app.py"
DOC = ROOT / "CLIMATE_CORE_0_7_4.md"


def block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[start:end]


class OriginalAuditClosure0741Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_a_temporal_percentile_threshold_and_degree_contracts_remain(self) -> None:
        self.assertIn("Lower 5% boundary (P05)", self.source)
        self.assertIn("Upper 5% boundary (P95)", self.source)
        self.assertIn("Nighttime hours > 20 °C (20:00–06:59)", self.source)
        self.assertIn('"Cooling limit [°C]",\n            10.0,\n            35.0,\n            20.0', self.source)
        self.assertIn("Chronological heat maps keep every real day, week or month in sequence across years", self.source)

        idx = pd.date_range("2025-01-01", periods=48, freq="h")
        frame = pd.DataFrame({"dry_bulb_temperature_c": [-15.0] * 24 + [-10.0] * 24}, index=idx)
        frame["hour_of_day"] = frame.index.hour
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "day", "Hour of day", "Minimum", "Minimum", "°C", temperature_thresholds=(18.0, 26.0))
        self.assertTrue(all(0.0 <= float(stop[0]) <= 1.0 for stop in fig.layout.coloraxis.colorscale))

    def test_b_ground_and_wind_source_neutral_contracts_remain(self) -> None:
        temperature = block(self.source, "render_temperature", "render_humidity")
        wind = block(self.source, "render_wind", "render_precipitation")
        self.assertIn('chart_options.append("Ground temperature")', temperature)
        for label in ("Wind speed", "Wind direction", "Wind gust speed", "Wind gust direction"):
            self.assertIn(label, wind)
        self.assertIn("Maximum gust", wind)

        profile = monthly_ground_profile(AnnualHarmonic(mean_c=10.0, sin_c=8.0, cos_c=2.0, amplitude_c=(68.0 ** 0.5)), [0.0, 1.0, 2.0, 5.0, 10.0, 15.0])
        self.assertEqual(tuple(profile_figure(profile).layout.xaxis.range), tuple(animated_profile_figure(profile).layout.xaxis.range))

    def test_c_overview_precip_overlay_daylight_nv_and_hvac_dedup_contracts_remain(self) -> None:
        overview = block(self.source, "render_overview", "render_temperature")
        humidity = block(self.source, "render_humidity", "render_wind")
        nv = block(self.source, "render_natural_ventilation", "render_hvac_passive")
        hvac = block(self.source, "render_hvac_passive", "render_time_series_overlay")
        daylight = block(self.source, "render_sky_daylight", "render_natural_ventilation")
        overlay = block(self.source, "render_time_series_overlay", "render_data_quality")

        self.assertNotIn("Monthly outdoor temperature profile", overview)
        self.assertIn('"Wet intervals only"', self.source)
        self.assertIn('"All intervals including dry periods"', self.source)
        for label in ("Line style", "Line width", "Line color", "Opacity"):
            self.assertIn(label, overlay)
        self.assertIn('"Measured sunshine duration"', daylight)
        self.assertIn('"Relative sunshine duration"', daylight)
        self.assertNotIn('"Month × hour suitability"', nv)
        self.assertIn('"Moisture thresholds"', humidity)
        self.assertNotIn('"Outdoor-air enthalpy duration curve"', hvac)
        self.assertNotIn('"Heating and cooling degree-hours"', hvac)

    def test_wet_bulb_generic_variable_has_temperature_as_single_home(self) -> None:
        temperature = block(self.source, "render_temperature", "render_humidity")
        humidity = block(self.source, "render_humidity", "render_wind")
        generic_humidity = humidity.split('if chart_group == "Humidity variable explorer":', 1)[1].split('elif chart_group == "Psychrometric chart":', 1)[0]
        self.assertIn('"Wet-bulb temperature"', temperature)
        self.assertNotIn('"Wet-bulb temperature"', generic_humidity)
        # Wet bulb remains available to psychrometric relationships; only the duplicate generic home is removed.
        self.assertIn('"Wet-bulb temperature"', humidity)

    def test_passive_annual_chronological_multiyear_defaults_to_by_year(self) -> None:
        hvac = block(self.source, "render_hvac_passive", "render_time_series_overlay")
        self.assertIn('chronological_multiyear = time_basis(df) == CHRONOLOGICAL and len(available_years(df)) > 1', hvac)
        self.assertIn('"Annual summary"', hvac)
        self.assertIn('["By year", "Selected-period summary"]', hvac)
        self.assertIn('index=0', hvac)
        self.assertIn('filter_year(df, int(year))', hvac)
        self.assertIn('title="Passive and HVAC strategy hours by year"', hvac)

    def test_compare_climates_uses_current_zone_contract_not_selected_cells(self) -> None:
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', self.source)
        self.assertIn('"Reference psychrometric pressure"', self.source)
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("duration-weighted two-dimensional density field", doc)
        self.assertIn("former 1 °C × 5 %RH selected-cell mosaic", doc)
        self.assertIn("no longer the release contract", doc)
        self.assertIn("Wet-bulb temperature has one generic variable home", doc)
        self.assertIn("By year", doc)

    def test_temporary_original_audit_patch_transport_is_not_in_release_tree(self) -> None:
        self.assertFalse((ROOT / "scripts" / "apply_v0741_original_audit_closure.py").exists())
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "v0741-original-audit-closure-patch.yml").exists())


if __name__ == "__main__":
    unittest.main()
