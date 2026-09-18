from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame
from epw_climate_analyzer.geosphere import (
    FIELD_SPEC_BY_PROVIDER,
    provider_frame_to_canonical,
    provider_parameters_with_quality_flags,
    quality_flag_column,
)
from epw_climate_analyzer.historical_capabilities import available_historical_pages


class PriorityAGeoSphere073Tests(unittest.TestCase):
    def test_priority_a_provider_fields_have_quantity_correct_canonical_targets(self) -> None:
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["ffx"].canonical_name, "wind_gust_speed_m_s")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["ddx"].canonical_name, "wind_gust_direction_deg")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["so"].canonical_name, "sunshine_duration_s")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tlmin"].canonical_name, "dry_bulb_temperature_min_c")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tlmax"].canonical_name, "dry_bulb_temperature_max_c")

    def test_hourly_extrema_sunshine_and_paired_gust_direction(self) -> None:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min", name="timestamp")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_min_c": [1.0, 0.5, -1.0, 0.0, 0.2, 0.1],
                "dry_bulb_temperature_max_c": [2.0, 2.5, 3.0, 2.2, 2.4, 2.1],
                "sunshine_duration_s": [0.0, 60.0, 120.0, 180.0, 240.0, 300.0],
                "wind_gust_speed_m_s": [5.0, 7.0, 12.0, 9.0, 8.0, 6.0],
                "wind_gust_direction_deg": [10.0, 20.0, 210.0, 40.0, 50.0, 60.0],
            },
            index=index,
        )
        hourly = canonical_hourly_analysis_frame(frame, source_interval_minutes=10)
        self.assertEqual(len(hourly), 1)
        self.assertAlmostEqual(float(hourly.iloc[0]["dry_bulb_temperature_min_c"]), -1.0)
        self.assertAlmostEqual(float(hourly.iloc[0]["dry_bulb_temperature_max_c"]), 3.0)
        self.assertAlmostEqual(float(hourly.iloc[0]["sunshine_duration_s"]), 900.0)
        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_speed_m_s"]), 12.0)
        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_direction_deg"]), 210.0)

    def test_equal_hourly_gust_maxima_choose_earliest_source_pair(self) -> None:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min", name="timestamp")
        frame = pd.DataFrame(
            {
                "wind_gust_speed_m_s": [5.0, 12.0, 12.0, 9.0, 8.0, 6.0],
                "wind_gust_direction_deg": [10.0, 30.0, 220.0, 40.0, 50.0, 60.0],
            },
            index=index,
        )
        hourly = canonical_hourly_analysis_frame(frame, source_interval_minutes=10)
        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_direction_deg"]), 30.0)

    def test_quality_flags_are_requested_and_retained_as_diagnostics(self) -> None:
        metadata = {
            "parameters": [
                {"name": "tl", "unit": "°C"},
                {"name": "tl_flag", "unit": "code"},
                {"name": "ffx", "unit": "m/s"},
                {"name": "ffx_flag", "unit": "code"},
            ]
        }
        query = provider_parameters_with_quality_flags(metadata, ["tl", "ffx"])
        self.assertEqual(query, ("tl", "tl_flag", "ffx", "ffx_flag"))
        index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="10min", name="timestamp")
        provider = pd.DataFrame(
            {"tl": [1.0, 2.0], "tl_flag": [0, 1], "ffx": [5.0, 6.0], "ffx_flag": [0, 0]},
            index=index,
        )
        canonical = provider_frame_to_canonical(
            provider,
            {"tl": FIELD_SPEC_BY_PROVIDER["tl"], "ffx": FIELD_SPEC_BY_PROVIDER["ffx"]},
        )
        self.assertIn(quality_flag_column("tl"), canonical.columns)
        self.assertIn(quality_flag_column("ffx"), canonical.columns)
        self.assertEqual(canonical[quality_flag_column("tl")].tolist(), [0, 1])

    def test_new_measurements_enable_temperature_wind_and_daylight_pages_without_fabrication(self) -> None:
        index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_min_c": [0.0, 1.0],
                "dry_bulb_temperature_max_c": [4.0, 5.0],
                "wind_gust_speed_m_s": [8.0, 9.0],
                "wind_gust_direction_deg": [250.0, 260.0],
                "sunshine_duration_s": [1200.0, 1800.0],
            },
            index=index,
        )
        pages = set(available_historical_pages(frame))
        self.assertIn("Temperature", pages)
        self.assertIn("Wind and Ventilation", pages)
        self.assertIn("Sky and Daylight", pages)
        self.assertNotIn("Solar and Radiation", pages)
        self.assertNotIn("Humidity and Psychrometrics", pages)
        self.assertNotIn("Natural Ventilation", pages)


if __name__ == "__main__":
    unittest.main()
