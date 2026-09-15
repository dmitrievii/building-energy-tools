from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.aggregations import native_interval_hours, threshold_count_by_period


class CadenceAwareThresholdDurationTests(unittest.TestCase):
    @staticmethod
    def frame(index: pd.DatetimeIndex, native_minutes: int | None) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "month_index": index.month,
                "hour_of_day": index.hour,
                "season": ["Winter"] * len(index),
            },
            index=index,
        )
        if native_minutes is not None:
            df.attrs["canonical_native_interval_minutes"] = native_minutes
        return df

    def test_hourly_epw_identity_is_preserved(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=3, freq="h")
        df = self.frame(index, 60)
        condition = pd.Series([True, True, True], index=index)
        result = threshold_count_by_period(df, condition, "Daily", label="hours")
        self.assertAlmostEqual(float(result["hours"].iloc[0]), 3.0)
        self.assertAlmostEqual(native_interval_hours(df), 1.0)

    def test_six_ten_minute_records_equal_one_hour(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        df = self.frame(index, 10)
        condition = pd.Series(True, index=index)
        daily = threshold_count_by_period(df, condition, "Daily", label="hours")
        hourly = threshold_count_by_period(df, condition, "Hourly", label="hours")
        self.assertAlmostEqual(float(daily["hours"].iloc[0]), 1.0)
        self.assertEqual(len(hourly), 1)
        self.assertAlmostEqual(float(hourly["hours"].iloc[0]), 1.0)

    def test_three_of_six_ten_minute_records_equal_half_hour(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        df = self.frame(index, 10)
        condition = pd.Series([True, False, True, False, True, False], index=index)
        result = threshold_count_by_period(df, condition, "Daily", label="hours")
        self.assertAlmostEqual(float(result["hours"].iloc[0]), 0.5)

    def test_historical_timestamp_gap_does_not_create_fictitious_duration(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2025-01-01T00:00:00Z",
                "2025-01-01T00:10:00Z",
                "2025-01-01T03:00:00Z",
            ]
        )
        df = self.frame(index, 10)
        condition = pd.Series(True, index=index)
        result = threshold_count_by_period(df, condition, "Daily", label="hours")
        self.assertAlmostEqual(float(result["hours"].iloc[0]), 0.5)

    def test_seasonal_duration_uses_same_physical_weight(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=12, freq="10min")
        df = self.frame(index, 10)
        condition = pd.Series(True, index=index)
        result = threshold_count_by_period(df, condition, "Seasonal", label="hours")
        self.assertAlmostEqual(float(result.loc["Winter", "hours"]), 2.0)

    def test_legacy_frame_without_declared_cadence_uses_observed_median(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=4, freq="30min")
        df = self.frame(index, None)
        self.assertAlmostEqual(native_interval_hours(df), 0.5)
        condition = pd.Series(True, index=index)
        result = threshold_count_by_period(df, condition, "Daily", label="hours")
        self.assertAlmostEqual(float(result["hours"].iloc[0]), 2.0)


if __name__ == "__main__":
    unittest.main()
