from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.interannual_profiles import (
    interannual_minmax_figure,
    interannual_percentile_figure,
    interannual_profile_table,
)
from epw_climate_analyzer.temporal_filtering import INTERANNUAL_OVERLAY, with_time_basis


class InterannualProfileTests(unittest.TestCase):
    def _monthly_frame(self) -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [pd.Timestamp(year, month, 1) for year in (2020, 2021, 2022) for month in range(1, 13)]
        )
        values = [float((year - 2020) * 100 + month) for year in (2020, 2021, 2022) for month in range(1, 13)]
        frame = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)
        frame.attrs["canonical_native_resolution"] = "monthly"
        return with_time_basis(frame, INTERANNUAL_OVERLAY)

    def test_monthly_profile_table_preserves_year_before_envelope(self) -> None:
        table = interannual_profile_table(self._monthly_frame(), "dry_bulb_temperature_c", "Monthly")
        observed = table.dropna(subset=["value"])
        self.assertEqual(observed.groupby("real_year").size().to_dict(), {2020: 12, 2021: 12, 2022: 12})
        january = observed.loc[observed["calendar_bin"].dt.month == 1]
        self.assertEqual(january["value"].tolist(), [1.0, 101.0, 201.0])

    def test_minmax_chart_keeps_each_real_year_trace_and_adds_envelope_afterwards(self) -> None:
        fig = interannual_minmax_figure(
            self._monthly_frame(),
            "dry_bulb_temperature_c",
            "Monthly",
            "Temperature",
            "°C",
        )
        names = [trace.name for trace in fig.data]
        self.assertEqual(names[:3], ["2020", "2021", "2022"])
        self.assertIn("Interannual minimum", names)
        self.assertIn("Interannual maximum", names)
        self.assertIn("Interannual mean", names)
        yearly = [trace for trace in fig.data if trace.name in {"2020", "2021", "2022"}]
        self.assertTrue(all(trace.legendgroup == trace.name for trace in yearly))

    def test_percentile_chart_uses_year_preserving_input(self) -> None:
        fig = interannual_percentile_figure(
            self._monthly_frame(),
            "dry_bulb_temperature_c",
            "Monthly",
            "Temperature",
            "°C",
        )
        names = [trace.name for trace in fig.data]
        self.assertEqual(names[:3], ["2020", "2021", "2022"])
        self.assertIn("Interannual P05", names)
        self.assertIn("Interannual P95", names)
        self.assertIn("Interannual median", names)

    def test_missing_month_remains_gap_in_year_trace(self) -> None:
        frame = self._monthly_frame().drop(pd.Timestamp("2021-07-01"))
        frame.attrs["canonical_native_resolution"] = "monthly"
        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)
        fig = interannual_minmax_figure(frame, "dry_bulb_temperature_c", "Monthly", "Temperature", "°C")
        trace = next(trace for trace in fig.data if trace.name == "2021")
        july_position = pd.Timestamp("2000-07-01")
        pairs = list(zip(trace.x, trace.y, strict=False))
        self.assertTrue(any(pd.Timestamp(x) == july_position and y is None for x, y in pairs if x is not None))

    def test_daily_years_are_not_pooled_before_profile(self) -> None:
        index = pd.DatetimeIndex([
            "2020-07-15 00:00", "2020-07-15 12:00",
            "2021-07-15 00:00", "2021-07-15 12:00",
        ])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 2.0, 10.0, 14.0]}, index=index)
        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)
        table = interannual_profile_table(frame, "dry_bulb_temperature_c", "Daily").dropna(subset=["value"])
        values = dict(zip(table["real_year"], table["value"], strict=True))
        self.assertEqual(values, {2020: 1.0, 2021: 12.0})


if __name__ == "__main__":
    unittest.main()
