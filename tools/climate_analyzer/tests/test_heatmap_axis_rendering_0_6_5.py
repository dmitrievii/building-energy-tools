from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR
from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis


class HeatmapAxisRendering065Tests(unittest.TestCase):
    @staticmethod
    def _frame() -> pd.DataFrame:
        index = pd.to_datetime(
            [
                "2010-01-01T00:00:00Z",
                "2010-01-01T12:00:00Z",
                "2010-03-01T00:00:00Z",
                "2010-03-01T12:00:00Z",
                "2018-01-01T00:00:00Z",
                "2018-01-01T12:00:00Z",
                "2018-03-01T00:00:00Z",
                "2018-03-01T12:00:00Z",
            ]
        )
        frame = pd.DataFrame(
            {"dry_bulb_temperature_c": [0.0, 5.0, 10.0, 15.0, 2.0, 7.0, 12.0, 17.0]},
            index=index,
        )
        frame["hour_of_day"] = frame.index.hour
        frame["month_index"] = frame.index.month
        frame["day_of_year"] = frame.index.dayofyear
        frame["week_of_year"] = frame.index.isocalendar().week.astype(int).to_numpy()
        frame.attrs["canonical_native_interval_minutes"] = 60
        return with_time_basis(frame, CHRONOLOGICAL)

    def test_all_period_by_comparison_heatmaps_render_numeric_period_axes(self) -> None:
        frame = self._frame()
        bounds = {"day": (1, 366), "week": (1, 53), "month": (1, 12)}

        for period in ("day", "week", "month"):
            for comparison in (HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR):
                with self.subTest(period=period, comparison=comparison):
                    fig = temporal_heatmap_chart(
                        frame,
                        "dry_bulb_temperature_c",
                        period,
                        comparison,
                        "Mean",
                        f"{period} × {comparison}",
                        "°C",
                    )
                    x = list(fig.data[0].x)
                    self.assertTrue(x)
                    self.assertTrue(all(isinstance(value, (int, np.integer)) for value in x))
                    lo, hi = bounds[period]
                    self.assertGreaterEqual(min(int(value) for value in x), lo)
                    self.assertLessEqual(max(int(value) for value in x), hi)
                    self.assertFalse(any(isinstance(value, str) and "-" in value for value in x))

                    y = list(fig.data[0].y)
                    if comparison == HEATMAP_COMPARE_HOUR:
                        self.assertTrue(all(0 <= int(value) <= 23 for value in y))
                    else:
                        self.assertEqual(y, [2010, 2018])

    def test_day_hour_does_not_expand_to_one_column_per_absolute_date(self) -> None:
        frame = self._frame()
        fig = temporal_heatmap_chart(
            frame,
            "dry_bulb_temperature_c",
            "day",
            HEATMAP_COMPARE_HOUR,
            "Mean",
            "Day × hour",
            "°C",
        )
        x = [int(value) for value in fig.data[0].x]
        self.assertLessEqual(max(x), 366)
        self.assertNotIn(2010, x)
        self.assertNotIn(2018, x)

    def test_complete_day_hour_heatmap_keeps_all_24_hour_rows(self) -> None:
        index = pd.date_range("2018-07-01T00:00:00Z", periods=24, freq="h")
        frame = pd.DataFrame(
            {"dry_bulb_temperature_c": np.linspace(12.0, 28.0, 24)},
            index=index,
        )
        frame["hour_of_day"] = frame.index.hour
        frame["month_index"] = frame.index.month
        frame["day_of_year"] = frame.index.dayofyear
        frame["week_of_year"] = frame.index.isocalendar().week.astype(int).to_numpy()
        frame.attrs["canonical_native_interval_minutes"] = 60
        frame = with_time_basis(frame, CHRONOLOGICAL)

        fig = temporal_heatmap_chart(
            frame,
            "dry_bulb_temperature_c",
            "day",
            HEATMAP_COMPARE_HOUR,
            "Mean",
            "Day × hour",
            "°C",
        )
        self.assertEqual([int(value) for value in fig.data[0].y], list(range(24)))
        self.assertEqual(np.asarray(fig.data[0].z).shape[0], 24)


if __name__ == "__main__":
    unittest.main()
