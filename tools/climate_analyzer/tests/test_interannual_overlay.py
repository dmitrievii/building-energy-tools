from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.temporal_filtering import (
    CALENDAR_PROFILE,
    CHRONOLOGICAL,
    INTERANNUAL_OVERLAY,
    calendar_profile_slot,
    time_basis,
    with_time_basis,
)
from epw_climate_analyzer.timeseries import (
    OverlaySeries,
    aggregate_interannual_series,
    aggregate_series,
    build_overlay_figure,
)


class InterannualOverlaySemanticsTests(unittest.TestCase):
    def test_time_basis_accepts_third_mode_without_changing_existing_modes(self) -> None:
        index = pd.date_range("2020-01-01", periods=2, freq="h")
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 2.0]}, index=index)
        self.assertEqual(time_basis(with_time_basis(frame, CHRONOLOGICAL)), CHRONOLOGICAL)
        self.assertEqual(time_basis(with_time_basis(frame, CALENDAR_PROFILE)), CALENDAR_PROFILE)
        self.assertEqual(time_basis(with_time_basis(frame, INTERANNUAL_OVERLAY)), INTERANNUAL_OVERLAY)

    def test_no_interannual_averaging_for_monthly_values(self) -> None:
        index = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 10.0]}, index=index)
        frame.attrs["canonical_native_resolution"] = "monthly"
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Monthly",
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2022-01-01"),
        )
        self.assertEqual(result["real_year"].tolist(), [2020, 2021])
        self.assertEqual(result["value"].tolist(), [0.0, 10.0])
        self.assertNotIn(5.0, result["value"].tolist())

    def test_daily_aggregation_is_performed_inside_each_real_year(self) -> None:
        index = pd.DatetimeIndex([
            "2020-07-15 00:00", "2020-07-15 01:00",
            "2021-07-15 00:00", "2021-07-15 01:00",
        ])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 2.0, 10.0, 14.0]}, index=index)
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Daily",
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2022-01-01"),
        ).dropna(subset=["value"])
        values = dict(zip(result["real_year"], result["value"], strict=True))
        self.assertEqual(values, {2020: 1.0, 2021: 12.0})

    def test_leap_day_has_own_calendar_position_and_non_leap_year_has_gap(self) -> None:
        index = pd.DatetimeIndex([
            "2020-02-28", "2020-02-29", "2020-03-01",
            "2021-02-28", "2021-03-01",
        ])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1, 2, 3, 4, 5]}, index=index, dtype=float)
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Daily",
            pd.Timestamp("2020-02-28"),
            pd.Timestamp("2021-03-02"),
        )
        leap = result[result["real_year"] == 2020]
        ordinary = result[result["real_year"] == 2021]
        self.assertIn("29 Feb", leap["calendar_label"].tolist())
        march = ordinary.loc[ordinary["calendar_label"] == "01 Mar"].iloc[0]
        self.assertTrue(bool(march["gap_before"]))
        self.assertEqual(pd.Timestamp(march["calendar_bin"]).month, 3)
        self.assertEqual(pd.Timestamp(march["calendar_bin"]).day, 1)

    def test_missing_daily_bin_remains_missing(self) -> None:
        index = pd.DatetimeIndex(["2020-01-01", "2020-01-03"])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 3.0]}, index=index)
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Daily",
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2020-01-04"),
        )
        jan2 = result.loc[result["calendar_label"] == "02 Jan"]
        self.assertEqual(len(jan2), 1)
        self.assertTrue(pd.isna(jan2.iloc[0]["value"]))

    def test_monthly_keeps_twelve_independent_points_per_complete_year(self) -> None:
        index = pd.DatetimeIndex(
            [pd.Timestamp(year, month, 1) for year in (2020, 2021) for month in range(1, 13)]
        )
        values = [float(year - 2020) * 100.0 + month for year in (2020, 2021) for month in range(1, 13)]
        frame = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)
        frame.attrs["canonical_native_resolution"] = "monthly"
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Monthly",
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2022-01-01"),
        ).dropna(subset=["value"])
        self.assertEqual(result.groupby("real_year").size().to_dict(), {2020: 12, 2021: 12})
        self.assertEqual(float(result.query("real_year == 2020 and calendar_label == 'Jan'")["value"].iloc[0]), 1.0)
        self.assertEqual(float(result.query("real_year == 2021 and calendar_label == 'Jan'")["value"].iloc[0]), 101.0)

    def test_weekly_bins_never_mix_real_years(self) -> None:
        index = pd.date_range("2020-12-27", "2021-01-05", freq="D")
        values = np.arange(len(index), dtype=float)
        frame = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)
        result = aggregate_interannual_series(
            frame,
            "dry_bulb_temperature_c",
            "Weekly",
            pd.Timestamp("2020-12-27"),
            pd.Timestamp("2021-01-06"),
        )
        self.assertEqual(set(result["real_year"].dropna().astype(int)), {2020, 2021})
        for row in result.itertuples(index=False):
            self.assertEqual(pd.Timestamp(row.source_timestamp).year, int(row.real_year))

    def test_chronological_aggregation_path_is_regression_stable(self) -> None:
        index = pd.date_range("2020-01-01", periods=48, freq="h")
        frame = pd.DataFrame({"dry_bulb_temperature_c": np.arange(48, dtype=float)}, index=index)
        result = aggregate_series(
            with_time_basis(frame, CHRONOLOGICAL),
            "dry_bulb_temperature_c",
            "Daily",
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2020-01-03"),
        )
        self.assertEqual(result["value"].tolist(), [11.5, 35.5])
        self.assertEqual(result["interval_start"].tolist(), [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-02")])

    def test_calendar_profile_grouping_semantics_are_regression_stable(self) -> None:
        index = pd.DatetimeIndex(["2020-01-15 14:00", "2021-01-15 14:00"])
        daily = calendar_profile_slot(index, "Daily")
        hourly = calendar_profile_slot(index, "Hourly")
        self.assertEqual(daily.tolist(), ["01-15", "01-15"])
        self.assertEqual(hourly.tolist(), ["01-15 14:00", "01-15 14:00"])

    def test_figure_has_one_trace_per_variable_and_real_year(self) -> None:
        index = pd.DatetimeIndex([
            "2020-01-01", "2020-02-01", "2021-01-01", "2021-02-01"
        ])
        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 1.0, 10.0, 11.0]}, index=index)
        frame.attrs["canonical_native_resolution"] = "monthly"
        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)
        fig, tables = build_overlay_figure(
            frame,
            [OverlaySeries("Temperature", "dry_bulb_temperature_c", "°C", "Monthly")],
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2022-01-01"),
        )
        self.assertEqual([trace.name for trace in fig.data], ["Temperature — 2020", "Temperature — 2021"])
        self.assertEqual([trace.legendgroup for trace in fig.data], ["2020", "2021"])
        self.assertEqual(len(tables), 1)
        self.assertEqual(set(tables[0]["real_year"].astype(int)), {2020, 2021})
        self.assertTrue(all("Year: %{customdata[0]}" in trace.hovertemplate for trace in fig.data))


if __name__ == "__main__":
    unittest.main()
