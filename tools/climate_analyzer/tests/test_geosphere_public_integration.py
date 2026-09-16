from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import add_historical_calendar_columns, prepare_historical_analysis_frame


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
UI = ROOT / "epw_climate_analyzer" / "ui_contract.py"


def sample_dataset() -> CanonicalClimateDataset:
    index = pd.date_range("2025-07-01T00:00:00Z", periods=12, freq="10min")
    data = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [20.0 + i * 0.1 for i in range(12)],
            "relative_humidity_pct": [55.0] * 12,
            "atmospheric_station_pressure_pa": [96500.0] * 12,
            "global_horizontal_radiation_wh_m2": [0.0] * 12,
        },
        index=index,
    )
    data.attrs["canonical_native_interval_minutes"] = 10
    return CanonicalClimateDataset(
        climate_id="geosphere:test:11240",
        display_name="Graz test — GeoSphere 10 min",
        data=data,
        location=ClimateLocation(47.08, 15.45, 366.0, "Graz/Universitaet", "Steiermark", "Austria", "11240"),
        temporal=ClimateTemporalMetadata(10, "historical", "UTC", "unknown"),
        provenance=ClimateProvenance("GeoSphere Austria", "klima-v2-10min", "Dataset API JSON", "test source"),
    )


class HistoricalPreparationTests(unittest.TestCase):
    def test_real_utc_timestamps_and_native_cadence_are_preserved(self) -> None:
        dataset = sample_dataset()
        prepared = add_historical_calendar_columns(dataset.data)
        self.assertEqual(prepared.index[0], dataset.data.index[0])
        self.assertEqual(str(prepared.index.tz), "UTC")
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)
        self.assertEqual(prepared["hour_of_day"].iloc[0], 0)
        self.assertEqual(prepared["month_index"].iloc[0], 7)

    def test_psychrometric_derivation_uses_canonical_primary_observations(self) -> None:
        prepared = prepare_historical_analysis_frame(sample_dataset(), include_psychrometrics=True, fallback_pressure_pa=96500.0)
        self.assertIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("wet_bulb_temperature_c", prepared.columns)
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)

    def test_explicit_constant_pressure_replaces_measured_station_pressure(self) -> None:
        prepared = prepare_historical_analysis_frame(
            sample_dataset(),
            include_psychrometrics=True,
            fallback_pressure_pa=101325.0,
            pressure_override_pa=101325.0,
        )
        self.assertTrue((prepared["atmospheric_station_pressure_pa"] == 101325.0).all())
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())

    def test_invalid_constant_pressure_override_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "30000...120000 Pa"):
            prepare_historical_analysis_frame(
                sample_dataset(),
                include_psychrometrics=True,
                pressure_override_pa=200000.0,
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
        self.assertIn('"Measured variables to load"', self.source)
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
        self.assertNotIn('render_temperature(filtered_df, interval_count_metrics=False)', self.source)
        self.assertNotIn('render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)', self.source)

    def test_time_series_localizes_ui_range_to_real_historical_timezone(self) -> None:
        self.assertIn('if index.tz is not None:', self.source)
        self.assertIn('start = start.tz_localize(index.tz)', self.source)
        self.assertIn('selected_end = selected_end.tz_localize(index.tz)', self.source)

    def test_public_intro_no_longer_claims_epw_only_input(self) -> None:
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("EPW weather files and measured station data", ui)


if __name__ == "__main__":
    unittest.main()
