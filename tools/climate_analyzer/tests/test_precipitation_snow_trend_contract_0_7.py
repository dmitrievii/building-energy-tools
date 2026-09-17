from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.precipitation import annual_precipitation_indices, snow_season_indices


class PrecipitationSnowTrendContract07Tests(unittest.TestCase):
    def test_annual_precipitation_indices_keep_real_years(self) -> None:
        index = pd.to_datetime(["2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z"])
        frame = pd.DataFrame({"liquid_precipitation_depth_mm": [10.0, 20.0]}, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 60
        table = annual_precipitation_indices(frame)
        self.assertEqual(table["year"].tolist(), [2023, 2024])

    def test_snow_season_trends_keep_real_season_start_years(self) -> None:
        index = pd.to_datetime(["2023-12-01T00:00:00Z", "2024-12-01T00:00:00Z"])
        frame = pd.DataFrame({"snow_depth_cm": [2.0, 3.0]}, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 10
        table = snow_season_indices(frame)
        self.assertEqual(table["season_start_year"].tolist(), [2023, 2024])


if __name__ == "__main__":
    unittest.main()
