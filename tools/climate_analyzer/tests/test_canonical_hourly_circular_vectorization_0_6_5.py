from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame


class CanonicalHourlyCircularVectorization065Tests(unittest.TestCase):
    def test_vectorized_circular_mean_matches_scalar_reference(self) -> None:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min")
        source = pd.DataFrame(
            {"wind_direction_deg": [350.0, 355.0, 0.0, 5.0, 10.0, 0.0]},
            index=index,
        )
        source.attrs["canonical_native_interval_minutes"] = 10

        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=10)
        direction = float(hourly.iloc[0]["wind_direction_deg"])
        self.assertLess(min(abs(direction), abs(360.0 - direction)), 1.0)

    def test_cancelling_circular_resultant_remains_undefined(self) -> None:
        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min")
        source = pd.DataFrame(
            {"wind_direction_deg": [0.0, 180.0, 0.0, 180.0, 0.0, 180.0]},
            index=index,
        )
        source.attrs["canonical_native_interval_minutes"] = 10

        hourly = canonical_hourly_analysis_frame(source, source_interval_minutes=10)
        self.assertTrue(pd.isna(hourly.iloc[0]["wind_direction_deg"]))


if __name__ == "__main__":
    unittest.main()
