from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame
from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import prepare_historical_analysis_frame
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties


class CanonicalHourlyPipeline065Tests(unittest.TestCase):
    @staticmethod
    def _ten_minute_frame() -> pd.DataFrame:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min", name="timestamp")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
                "relative_humidity_pct": [70.0, 68.0, 66.0, 64.0, 62.0, 60.0],
                "atmospheric_station_pressure_pa": [100000.0] * 6,
                "wind_speed_m_s": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                "wind_direction_deg": [350.0, 355.0, 0.0, 5.0, 10.0, 0.0],
                "global_horizontal_radiation_wh_m2": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
                "liquid_precipitation_depth_mm": [0.0, 0.1, 0.2, 0.0, 0.0, 0.3],
                "snow_depth_cm": [4.0, 4.0, 4.2, 4.2, 4.4, 4.4],
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 10
        frame.attrs["canonical_calendar_mode"] = "historical"
        frame.attrs["canonical_timezone_name"] = "UTC"
        return frame

    @staticmethod
    def _dataset(frame: pd.DataFrame, native_interval_minutes: int = 10) -> CanonicalClimateDataset:
        return CanonicalClimateDataset(
            climate_id="test:hourly",
            display_name="Hourly pipeline fixture",
            data=frame,
            location=ClimateLocation(
                latitude=47.08,
                longitude=15.45,
                elevation_m=366.0,
                city="Graz",
                country="Austria",
                station_id="test",
            ),
            temporal=ClimateTemporalMetadata(
                native_interval_minutes=native_interval_minutes,
                calendar_mode="historical",
                timezone_name="UTC",
                interval_semantics="unknown",
            ),
            provenance=ClimateProvenance(
                provider="test",
                dataset="test measured climate",
                source_format="fixture",
                source_name="hourly fixture",
            ),
        )

    def test_quantity_aware_hourly_reduction_preserves_physical_semantics(self) -> None:
        source = self._ten_minute_frame()
        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=10)

        self.assertEqual(len(hourly), 1)
        self.assertAlmostEqual(float(hourly.iloc[0]["dry_bulb_temperature_c"]), 12.5)
        self.assertAlmostEqual(float(hourly.iloc[0]["wind_speed_m_s"]), 3.5)
        self.assertAlmostEqual(float(hourly.iloc[0]["global_horizontal_radiation_wh_m2"]), 210.0)
        self.assertAlmostEqual(float(hourly.iloc[0]["liquid_precipitation_depth_mm"]), 0.6)
        self.assertAlmostEqual(float(hourly.iloc[0]["snow_depth_cm"]), 4.2)
        direction = float(hourly.iloc[0]["wind_direction_deg"])
        self.assertLess(min(abs(direction), abs(360.0 - direction)), 1.0)
        self.assertEqual(hourly.attrs["canonical_native_interval_minutes"], 60)
        self.assertEqual(hourly.attrs["canonical_source_interval_minutes"], 10)
        self.assertEqual(hourly.attrs["canonical_hourly_expected_source_records"], 6)
        self.assertAlmostEqual(float(hourly.attrs["canonical_hourly_reduction_factor"]), 6.0)

    def test_missing_value_invalidates_only_that_variable_hour(self) -> None:
        source = self._ten_minute_frame()
        source.iloc[2, source.columns.get_loc("dry_bulb_temperature_c")] = float("nan")

        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=10)

        self.assertTrue(pd.isna(hourly.iloc[0]["dry_bulb_temperature_c"]))
        self.assertAlmostEqual(float(hourly.iloc[0]["liquid_precipitation_depth_mm"]), 0.6)
        incomplete = hourly.attrs["canonical_hourly_incomplete_hours_by_variable"]
        self.assertEqual(int(incomplete["dry_bulb_temperature_c"]), 1)
        self.assertEqual(int(incomplete["liquid_precipitation_depth_mm"]), 0)

    def test_missing_timestamp_invalidates_the_incomplete_hour_without_zero_fill(self) -> None:
        source = self._ten_minute_frame().drop(pd.Timestamp("2026-01-01T00:20:00Z"))

        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=10)

        self.assertEqual(len(hourly), 1)
        self.assertTrue(pd.isna(hourly.iloc[0]["dry_bulb_temperature_c"]))
        self.assertTrue(pd.isna(hourly.iloc[0]["liquid_precipitation_depth_mm"]))
        self.assertTrue(pd.isna(hourly.iloc[0]["global_horizontal_radiation_wh_m2"]))

    def test_native_hourly_source_uses_no_resampling_semantic_change(self) -> None:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=3, freq="h", name="timestamp")
        source = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1.0, 2.0, 3.0],
                "liquid_precipitation_depth_mm": [0.0, 2.0, 0.5],
            },
            index=index,
        )
        source.attrs["canonical_native_interval_minutes"] = 60

        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=60)

        pd.testing.assert_frame_equal(hourly, source, check_attrs=False)
        self.assertEqual(hourly.attrs["canonical_source_interval_minutes"], 60)
        self.assertEqual(hourly.attrs["canonical_native_interval_minutes"], 60)
        self.assertEqual(hourly.attrs["canonical_hourly_expected_source_records"], 1)

    def test_misaligned_subhourly_grid_fails_closed(self) -> None:
        source = self._ten_minute_frame().copy()
        source.index = source.index + pd.Timedelta(minutes=5)
        with self.assertRaisesRegex(ValueError, "not aligned"):
            canonical_hourly_analysis_frame(source, source_interval_minutes=10)

    def test_historical_preparation_derives_psychrometrics_after_hourly_reduction(self) -> None:
        source = self._ten_minute_frame()
        dataset = self._dataset(source)
        source_before = dataset.data.copy()

        prepared = prepare_historical_analysis_frame(
            dataset,
            include_psychrometrics=True,
            fallback_pressure_pa=100000.0,
        )

        self.assertEqual(len(prepared), 1)
        self.assertEqual(len(dataset.data), 6)
        pd.testing.assert_frame_equal(dataset.data, source_before)
        self.assertAlmostEqual(float(prepared.iloc[0]["dry_bulb_temperature_c"]), 12.5)
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 60)

        expected_primary = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [12.5],
                "relative_humidity_pct": [65.0],
                "atmospheric_station_pressure_pa": [100000.0],
            },
            index=prepared.index,
        )
        expected = add_psychrometric_properties(expected_primary, fallback_pressure_pa=100000.0)
        self.assertAlmostEqual(
            float(prepared.iloc[0]["humidity_ratio_g_kg"]),
            float(expected.iloc[0]["humidity_ratio_g_kg"]),
            places=9,
        )
        self.assertAlmostEqual(
            float(prepared.iloc[0]["moist_air_enthalpy_kj_kg"]),
            float(expected.iloc[0]["moist_air_enthalpy_kj_kg"]),
            places=9,
        )


if __name__ == "__main__":
    unittest.main()
