from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.precipitation import aggregate_precipitation_duration


class PrecipitationSnowEpwCompatibility07Tests(unittest.TestCase):
    def test_missing_rrm_is_a_capability_absence_not_an_error(self) -> None:
        index = pd.date_range("2024-01-01T00:00:00Z", periods=24, freq="h")
        frame = pd.DataFrame({"liquid_precipitation_depth_mm": [0.0] * 24}, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 60
        result = aggregate_precipitation_duration(frame, "Daily")
        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), ["duration_min"])


if __name__ == "__main__":
    unittest.main()
