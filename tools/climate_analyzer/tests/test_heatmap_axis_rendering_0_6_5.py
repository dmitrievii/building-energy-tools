from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR
from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, with_time_basis


class HeatmapAxisRendering065Tests(unittest.TestCase):
    @staticmethod
    def _frame(basis: str = CHRONOLOGICAL) -> pd.DataFrame:
        index = pd.to_datetime([
            "2010-01-01T00:00:00Z", "2010-01-01T12:00:00Z",
            "2010-03-01T00:00:00Z", "2010-03-01T12:00:00Z",
            "2018-01-01T00:00:00Z", "2018-01-01T12:00:00Z",
            "2018-03-01T00:00:00Z", "2018-03-01T12:00:00Z",
        ])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 5.0, 10.0, 15.0, 2.0, 7.0, 12.0, 17.0]}, index=index)
        frame["hour_of_day"] = frame.index.hour
        frame.attrs["canonical_native_interval_minutes"] = 60
        return with_time_basis(frame, basis)

    def test_chronological_hour_heatmaps_use_absolute_period_labels(self) -> None:
        frame = self._frame(CHRONOLOGICAL)
        expected = {"day": "2010-01-01", "week": "2009-W53", "month": "2010-01"}
        for period, first_label in expected.items():
            with self.subTest(period=period):
                fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", period, HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")
                x = list(fig.data[0].x)
                self.assertIn(first_label, x)
                self.assertTrue(any(str(value).startswith("2018") for value in x))
                self.assertEqual([int(value) for value in fig.data[0].y], [0, 12])

    def test_calendar_profile_hour_heatmaps_keep_numeric_calendar_axes(self) -> None:
        frame = self._frame(CALENDAR_PROFILE)
        bounds = {"day": (1, 366), "week": (1, 53), "month": (1, 12)}
        for period, (lo, hi) in bounds.items():
            fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", period, HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")
            x = list(fig.data[0].x)
            self.assertTrue(all(isinstance(value, (int, np.integer)) for value in x))
            self.assertGreaterEqual(min(int(value) for value in x), lo)
            self.assertLessEqual(max(int(value) for value in x), hi)

    def test_year_comparison_uses_integer_tick_labels_only(self) -> None:
        frame = self._frame(CALENDAR_PROFILE)
        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean", "test", "°C")
        self.assertEqual(list(fig.layout.yaxis.tickvals), [2010, 2018])
        self.assertEqual(list(fig.layout.yaxis.ticktext), ["2010", "2018"])

    def test_complete_day_hour_heatmap_keeps_all_24_hour_rows(self) -> None:
        index = pd.date_range("2018-07-01T00:00:00Z", periods=24, freq="h")
        frame = pd.DataFrame({"dry_bulb_temperature_c": np.linspace(12.0, 28.0, 24)}, index=index)
        frame["hour_of_day"] = frame.index.hour
        frame.attrs["canonical_native_interval_minutes"] = 60
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")
        self.assertEqual([int(value) for value in fig.data[0].y], list(range(24)))
        self.assertEqual(np.asarray(fig.data[0].z).shape[0], 24)


if __name__ == "__main__":
    unittest.main()
