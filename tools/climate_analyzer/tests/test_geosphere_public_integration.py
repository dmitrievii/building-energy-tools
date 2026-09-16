from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class HistoricalPreparationTests(unittest.TestCase):
    def dataset(self) -> CanonicalClimateDataset:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        data = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1, 2, 3, 4, 5, 6],
                "relative_humidity_pct": [70, 71, 72, 73, 74, 75],
                "atmospheric_station_pressure_pa": [95000, 95010, 95020, 95030, 95040, 95050],
            },
            index=index,
        )
        data.attrs["canonical_native_interval_minutes"] = 10
        return CanonicalClimateDataset(
            climate_id="historical-test",
            display_name="Historical test",
            data=data,
            location=ClimateLocation(47.0, 15.0, 350.0, "Test", "", "Austria", "1"),
            temporal=ClimateTemporalMetadata(10, "historical", "UTC", "unknown"),
            provenance=ClimateProvenance("GeoSphere Austria", "test", "Dataset API JSON", "test"),
        )

    def test_real_utc_timestamps_and_native_cadence_are_preserved(self) -> None:
        prepared = prepare_historical_analysis_frame(self.dataset(), include_psychrometrics=False)
        self.assertEqual(str(prepared.index.tz), "UTC")
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)
        self.assertEqual(prepared.attrs["canonical_calendar_mode"], "historical")

    def test_psychrometric_derivation_uses_canonical_primary_observations(self) -> None:
        prepared = prepare_historical_analysis_frame(self.dataset(), include_psychrometrics=True)
        self.assertIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("dew_point_temperature_c", prepared.columns)
        self.assertIn("wet_bulb_temperature_c", prepared.columns)
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())

    def test_explicit_constant_pressure_replaces_measured_station_pressure(self) -> None:
        prepared = prepare_historical_analysis_frame(
            self.dataset(),
            include_psychrometrics=True,
            pressure_override_pa=101325.0,
        )
        self.assertTrue((prepared["atmospheric_station_pressure_pa"] == 101325.0).all())

    def test_invalid_constant_pressure_override_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            prepare_historical_analysis_frame(
                self.dataset(),
                include_psychrometrics=True,
                pressure_override_pa=5000.0,
            )


class GeoSpherePublicUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_source_selector_exposes_geosphere_and_batched_arbitrary_range(self) -> None:
        self.assertIn('"GeoSphere Austria"', self.source)
        self.assertIn('def render_geosphere_source()', self.source)
        self.assertNotIn('selected_days > 366', self.source)
        self.assertIn('st.markdown("#### Measured variables to load")', self.source)
        self.assertIn('edited_variables = st.data_editor(', self.source)
        self.assertIn('st.column_config.CheckboxColumn("Load"', self.source)
        self.assertNotIn('key="geosphere_provider_parameters"', self.source)
        self.assertIn('There is no fixed one-year UI limit', self.source)
        self.assertIn('plan_geosphere_queries', self.source)
        self.assertIn('fetch_geosphere_station_dataset', self.source)
        self.assertNotIn('required air-temperature parameter `tl`', self.source)

    def test_historical_dataset_uses_existing_analysis_renderers_not_duplicate_provider_pages(self) -> None:
        self.assertIn('render_temperature(filtered_df)', self.source)
        self.assertIn('render_humidity(filtered_df, pressure_pa=active_pressure)', self.source)
        self.assertIn('render_time_series_overlay(full_df)', self.source)
        self.assertNotIn('def render_geosphere_temperature', self.source)
        self.assertNotIn('def render_geosphere_humidity', self.source)

    def test_historical_threshold_routes_are_reenabled_with_duration_semantics(self) -> None:
        self.assertIn('Measured-data threshold hours are integrated from the declared native interval', self.source)
        self.assertIn('Measured-data moisture-threshold hours are integrated from the declared native interval', self.source)
        self.assertIn('render_temperature(filtered_df)', self.source)
        self.assertIn('render_humidity(filtered_df, pressure_pa=active_pressure)', self.source)

    def test_public_intro_no_longer_claims_epw_only_input(self) -> None:
        from epw_climate_analyzer.ui_contract import APP_INTRO

        self.assertIn("measured historical station observations", APP_INTRO)
        self.assertNotIn("Load an EPW weather file to begin", APP_INTRO)

    def test_time_series_localizes_ui_range_to_real_historical_timezone(self) -> None:
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "render_time_series_overlay"
        )
        source = ast.get_source_segment(self.source, function) or ""
        self.assertIn("if index.tz is not None:", source)
        self.assertIn("start = start.tz_localize(index.tz)", source)
        self.assertIn("selected_end = selected_end.tz_localize(index.tz)", source)


if __name__ == "__main__":
    unittest.main()
