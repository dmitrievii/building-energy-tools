from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from epw_climate_analyzer.aggregations import aggregate_summary, aggregate_sum, calendar_matrix, threshold_count_by_period
from epw_climate_analyzer.charts import profile_ribbon_chart, monthly_box_chart
from epw_climate_analyzer.degree_metrics import degree_metric_table
from epw_climate_analyzer.precipitation import aggregate_liquid_precipitation
from epw_climate_analyzer.temporal_filtering import (
    CALENDAR_PROFILE,
    CHRONOLOGICAL,
    TIME_BASIS_ATTR,
    available_years,
    filter_datetime_range,
    filter_year,
    with_time_basis,
)


def frame(index: pd.DatetimeIndex, values: list[float]) -> pd.DataFrame:
    df = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)
    df["month_index"] = df.index.month
    df["month_name"] = df.index.strftime("%b")
    df["hour_of_day"] = df.index.hour
    df["day_of_year"] = df.index.dayofyear
    df["week_of_year"] = df.index.isocalendar().week.to_numpy()
    seasons = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring", 6: "Summer", 7: "Summer", 8: "Summer", 9: "Autumn", 10: "Autumn", 11: "Autumn"}
    df["season"] = pd.Categorical([seasons[m] for m in df.index.month], categories=["Winter", "Spring", "Summer", "Autumn"], ordered=True)
    df.attrs["canonical_native_interval_minutes"] = 60.0
    return df


class TemporalFiltering063Tests(unittest.TestCase):
    def test_available_years_and_year_filter_use_actual_source_years(self) -> None:
        idx = pd.to_datetime(["2021-01-10 00:00", "2023-06-01 12:00", "2023-07-01 12:00"])
        df = frame(idx, [1.0, 2.0, 3.0])
        self.assertEqual(available_years(df), [2021, 2023])
        selected = filter_year(df, 2023)
        self.assertEqual(len(selected), 2)
        self.assertTrue((selected.index.year == 2023).all())
        with self.assertRaises(ValueError):
            filter_year(df, 2022)

    def test_custom_datetime_range_is_inclusive_and_timezone_safe(self) -> None:
        idx = pd.date_range("2024-01-01 00:00", periods=6, freq="h", tz="UTC")
        df = frame(idx, list(range(6)))
        selected = filter_datetime_range(df, "2024-01-01 01:00", "2024-01-01 03:00")
        self.assertEqual(list(selected.index.hour), [1, 2, 3])

    def test_chronological_monthly_default_keeps_year_months_distinct(self) -> None:
        idx = pd.to_datetime(["2023-01-15", "2023-02-15", "2024-01-15", "2024-02-15"])
        df = with_time_basis(frame(idx, [1.0, 2.0, 11.0, 12.0]), CHRONOLOGICAL)
        summary = aggregate_summary(df, "dry_bulb_temperature_c", "Monthly")
        self.assertEqual(len(summary), 4)
        self.assertEqual(len(set(summary.index.to_period("M"))), 4)
        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Monthly", "Temperature", "°C")
        labels = list(fig.data[0].x)
        self.assertEqual(labels, ["Jan 2023", "Feb 2023", "Jan 2024", "Feb 2024"])
        self.assertEqual(len(labels), len(set(labels)))

    def test_calendar_profile_monthly_aligns_same_month_across_years(self) -> None:
        idx = pd.to_datetime(["2023-01-15", "2023-02-15", "2024-01-15", "2024-02-15"])
        df = with_time_basis(frame(idx, [0.0, 10.0, 20.0, 30.0]), CALENDAR_PROFILE)
        summary = aggregate_summary(df, "dry_bulb_temperature_c", "Monthly")
        self.assertEqual(list(summary.index), [1, 2])
        self.assertAlmostEqual(float(summary.loc[1, "mean"]), 10.0)
        self.assertAlmostEqual(float(summary.loc[1, "min"]), 0.0)
        self.assertAlmostEqual(float(summary.loc[1, "max"]), 20.0)
        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Monthly", "Temperature", "°C")
        self.assertEqual(list(fig.data[0].x), ["Jan", "Feb"])

    def test_calendar_profile_extensive_monthly_averages_year_totals(self) -> None:
        idx = pd.to_datetime(["2023-01-01", "2023-01-02", "2024-01-01", "2024-01-02"])
        df = with_time_basis(frame(idx, [0.0, 0.0, 0.0, 0.0]), CALENDAR_PROFILE)
        df["liquid_precipitation_depth_mm"] = [1.0, 3.0, 10.0, 20.0]
        totals = aggregate_liquid_precipitation(df, "Monthly")
        self.assertEqual(list(totals.index), [1])
        # 2023 January = 4 mm, 2024 January = 30 mm -> typical January = 17 mm.
        self.assertAlmostEqual(float(totals.loc[1, "precipitation_mm"]), 17.0)

        summed = aggregate_sum(df, "liquid_precipitation_depth_mm", "Monthly")
        self.assertAlmostEqual(float(summed.loc[1, "sum"]), 17.0)
        self.assertAlmostEqual(float(summed.loc[1, "min"]), 4.0)
        self.assertAlmostEqual(float(summed.loc[1, "max"]), 30.0)

    def test_threshold_hours_respect_calendar_profile_and_native_cadence(self) -> None:
        idx = pd.to_datetime(["2023-01-01 00:00", "2023-01-01 00:10", "2024-01-01 00:00", "2024-01-01 00:10"])
        df = with_time_basis(frame(idx, [0.0, 0.0, 0.0, 0.0]), CALENDAR_PROFILE)
        df.attrs["canonical_native_interval_minutes"] = 10.0
        mask = pd.Series([True, True, True, False], index=idx)
        result = threshold_count_by_period(df, mask, "Monthly", label="hours")
        # 2023 = 20 min, 2024 = 10 min -> average January duration = 15 min.
        self.assertAlmostEqual(float(result.loc[1, "hours"]), 0.25)

    def test_chronological_multiyear_heatmap_rows_keep_year(self) -> None:
        idx = pd.to_datetime(["2023-01-01 00:00", "2024-01-01 00:00"])
        df = with_time_basis(frame(idx, [1.0, 2.0]), CHRONOLOGICAL)
        matrix = calendar_matrix(df, "dry_bulb_temperature_c", row_group="month")
        self.assertEqual(list(matrix.index), ["2023-01", "2024-01"])

    def test_monthly_box_chart_keeps_distinct_year_month_categories(self) -> None:
        idx = pd.to_datetime(["2023-01-01", "2023-01-02", "2024-01-01", "2024-01-02"])
        df = with_time_basis(frame(idx, [1.0, 2.0, 3.0, 4.0]), CHRONOLOGICAL)
        fig = monthly_box_chart(df, "dry_bulb_temperature_c", "Monthly distribution", "°C")
        self.assertEqual(set(fig.data[0].x), {"Jan 2023", "Jan 2024"})

    def test_degree_metrics_calendar_profile_annual_is_mean_typical_year(self) -> None:
        idx = pd.to_datetime(["2023-01-01 12:00", "2024-01-01 12:00"])
        df = with_time_basis(frame(idx, [10.0, 14.0]), CALENDAR_PROFILE)
        result = degree_metric_table(
            df,
            heating_indoor_c=20.0,
            heating_limit_c=18.0,
            cooling_indoor_c=20.0,
            cooling_limit_c=26.0,
            metric="Degree-hours",
            aggregation="Annual",
        )
        self.assertEqual(list(result.index), ["Annual"])
        # (10 K.h + 6 K.h) / two source years.
        self.assertAlmostEqual(float(result.iloc[0]["Heating degree-hours (HGT)"]), 8.0)

    def test_app_contract_uses_one_global_temporal_filter(self) -> None:
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        for token in [
            '"All available", "Year", "Custom"',
            '"Time basis"',
            "filter_datetime_range",
            "render_historical_overview(dataset, filtered_df)",
            "render_time_series_overlay(filtered_df)",
        ]:
            self.assertIn(token, source)
        self.assertNotIn('if page in {"Time Series and Overlay", "Overview", "Data Quality"}', source)
        self.assertNotIn('if page == "Time Series and Overlay":\n        # This page owns an exact date/hour/minute viewport.', source)


if __name__ == "__main__":
    unittest.main()
