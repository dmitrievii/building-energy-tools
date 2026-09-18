from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import (
    HEATMAP_COMPARE_HOUR,
    HEATMAP_COMPARE_YEAR,
    aggregate_summary,
    heatmap_default_statistic,
    heatmap_statistic_options,
    temporal_heatmap_matrix,
)
from epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, display_period_labels, with_time_basis


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def frame() -> pd.DataFrame:
    idx = pd.to_datetime(
        [
            "2024-01-01T00:00:00Z", "2024-01-01T12:00:00Z",
            "2024-02-01T00:00:00Z", "2024-02-01T12:00:00Z",
            "2024-02-29T12:00:00Z",
            "2025-01-01T00:00:00Z", "2025-01-01T12:00:00Z",
            "2025-02-01T00:00:00Z", "2025-02-01T12:00:00Z",
        ]
    )
    df = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [0.0, 10.0, 20.0, 30.0, 40.0, 2.0, 12.0, 22.0, 32.0],
            "global_horizontal_radiation_wh_m2": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 40.0],
            "wind_direction_deg": [350.0, 10.0, 90.0, 90.0, 180.0, 350.0, 10.0, 90.0, 90.0],
        },
        index=idx,
    )
    df["hour_of_day"] = df.index.hour
    df["month_index"] = df.index.month
    df["day_of_year"] = df.index.dayofyear
    df["week_of_year"] = df.index.isocalendar().week.astype(int).to_numpy()
    return with_time_basis(df, CHRONOLOGICAL)


class InterannualHeatmap064Tests(unittest.TestCase):
    def test_month_by_year_mean_and_maximum_preserve_real_years(self) -> None:
        df = frame()
        mean = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        maximum = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Maximum")
        self.assertEqual(mean.index.tolist(), [2024, 2025])
        self.assertEqual(mean.columns.tolist(), list(range(1, 13)))
        self.assertAlmostEqual(float(mean.loc[2024, 1]), 5.0)
        self.assertAlmostEqual(float(mean.loc[2025, 1]), 7.0)
        self.assertAlmostEqual(float(maximum.loc[2024, 2]), 40.0)
        self.assertAlmostEqual(float(maximum.loc[2025, 2]), 32.0)

    def test_year_compare_overrides_calendar_profile_folding(self) -> None:
        df = with_time_basis(frame(), CALENDAR_PROFILE)
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(matrix.index.tolist(), [2024, 2025])
        self.assertAlmostEqual(float(matrix.loc[2024, 1]), 5.0)
        self.assertAlmostEqual(float(matrix.loc[2025, 1]), 7.0)

    def test_week_by_year_uses_numeric_iso_week_and_iso_year_at_calendar_boundary(self) -> None:
        idx = pd.to_datetime([
            "2020-12-31T12:00:00Z",  # ISO 2020-W53
            "2021-01-01T12:00:00Z",  # still ISO 2020-W53
            "2021-01-04T12:00:00Z",  # ISO 2021-W01
        ])
        df = pd.DataFrame({"dry_bulb_temperature_c": [1.0, 3.0, 10.0]}, index=idx)
        df["hour_of_day"] = df.index.hour
        df = with_time_basis(df, CHRONOLOGICAL)
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "week", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(matrix.index.tolist(), [2020, 2021])
        self.assertEqual(matrix.columns.tolist(), list(range(1, 54)))
        self.assertAlmostEqual(float(matrix.loc[2020, 53]), 2.0)
        self.assertAlmostEqual(float(matrix.loc[2021, 1]), 10.0)
        self.assertTrue(pd.isna(matrix.loc[2021, 53]))

    def test_one_year_year_compare_is_a_single_stripe(self) -> None:
        df = frame().loc["2024"].copy()
        df = with_time_basis(df, CHRONOLOGICAL)
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(matrix.index.tolist(), [2024])
        self.assertEqual(matrix.shape[0], 1)

    def test_day_by_year_uses_numeric_leap_neutral_calendar_day(self) -> None:
        df = frame()
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertIn(60, matrix.columns)  # Feb 29 on leap-reference axis
        self.assertAlmostEqual(float(matrix.loc[2024, 60]), 40.0)
        self.assertTrue(np.isnan(matrix.loc[2025, 60]))

        # Mar 1 is always slot 61, both in leap and non-leap source years.
        idx = pd.to_datetime(["2024-03-01T12:00:00Z", "2025-03-01T12:00:00Z"])
        march = pd.DataFrame({"dry_bulb_temperature_c": [4.0, 5.0]}, index=idx)
        march["hour_of_day"] = 12
        march = with_time_basis(march, CHRONOLOGICAL)
        march_matrix = temporal_heatmap_matrix(march, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(march_matrix.columns.tolist(), [61])
        self.assertAlmostEqual(float(march_matrix.loc[2024, 61]), 4.0)
        self.assertAlmostEqual(float(march_matrix.loc[2025, 61]), 5.0)

    def test_hour_compare_preserves_absolute_periods_in_chronological_multiyear_mode(self) -> None:
        df = frame()
        day = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_HOUR, "Mean")
        week = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "week", HEATMAP_COMPARE_HOUR, "Mean")
        month = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_HOUR, "Mean")

        self.assertIn("2024-01-01", day.columns)
        self.assertIn("2025-01-01", day.columns)
        self.assertIn("2024-W01", week.columns)
        self.assertIn("2025-W01", week.columns)
        self.assertIn("2024-01", month.columns)
        self.assertIn("2025-01", month.columns)

    def test_calendar_profile_hour_total_averages_per_year_totals(self) -> None:
        df = with_time_basis(frame(), CALENDAR_PROFILE)
        matrix = temporal_heatmap_matrix(df, "global_horizontal_radiation_wh_m2", "month", HEATMAP_COMPARE_HOUR, "Total")
        # Jan 00:00 totals are 1 (2024) and 10 (2025), so the typical-year cell is 5.5, not 11.
        self.assertAlmostEqual(float(matrix.loc[0, 1]), 5.5)
        self.assertAlmostEqual(float(matrix.loc[12, 1]), 11.0)

    def test_chronological_multiyear_hour_total_keeps_real_year_months_separate(self) -> None:
        df = frame()
        matrix = temporal_heatmap_matrix(df, "global_horizontal_radiation_wh_m2", "month", HEATMAP_COMPARE_HOUR, "Total")
        self.assertAlmostEqual(float(matrix.loc[0, "2024-01"]), 1.0)
        self.assertAlmostEqual(float(matrix.loc[0, "2025-01"]), 10.0)
        self.assertAlmostEqual(float(matrix.loc[12, "2024-01"]), 2.0)
        self.assertAlmostEqual(float(matrix.loc[12, "2025-01"]), 20.0)

    def test_quantity_aware_statistic_options_and_defaults(self) -> None:
        self.assertEqual(heatmap_default_statistic("dry_bulb_temperature_c"), "Mean")
        self.assertIn("Maximum", heatmap_statistic_options("dry_bulb_temperature_c"))
        self.assertEqual(heatmap_default_statistic("global_horizontal_radiation_wh_m2"), "Total")
        self.assertEqual(heatmap_statistic_options("global_horizontal_radiation_wh_m2")[0], "Total")
        self.assertEqual(heatmap_default_statistic("wind_direction_deg"), "Circular mean")
        self.assertEqual(heatmap_statistic_options("wind_direction_deg"), ("Circular mean",))

    def test_circular_mean_wraps_through_north(self) -> None:
        df = frame().loc[[pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T12:00:00Z")]].copy()
        df = with_time_basis(df, CHRONOLOGICAL)
        matrix = temporal_heatmap_matrix(df, "wind_direction_deg", "month", HEATMAP_COMPARE_YEAR, "Circular mean")
        value = float(matrix.loc[2024, 1])
        self.assertTrue(value < 1.0 or value > 359.0)

    def test_annual_aggregation_is_first_class_and_labels_years(self) -> None:
        df = frame()
        annual = aggregate_summary(df, "dry_bulb_temperature_c", "Annual")
        labels = display_period_labels(annual.index, "Annual", CHRONOLOGICAL)
        self.assertEqual(labels, ["2024", "2025"])
        self.assertAlmostEqual(float(annual.iloc[0]["min"]), 0.0)
        self.assertAlmostEqual(float(annual.iloc[0]["max"]), 40.0)


class InterannualHeatmap064UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_generic_heatmap_exposes_orthogonal_controls(self) -> None:
        self.assertIn('st.selectbox("Heat-map aggregation", ["Day", "Week", "Month"]', self.source)
        self.assertIn('compare_options = ["Hour of day"] if time_basis(df) == CHRONOLOGICAL else ["Hour of day", "Year"]', self.source)
        self.assertIn('st.selectbox("Compare across", compare_options', self.source)
        self.assertIn("Chronological heat maps keep every real day, week or month in sequence across years", self.source)
        self.assertIn('"Statistic",\n            statistic_options', self.source)
        self.assertIn("temporal_heatmap_chart(", self.source)

    def test_annual_is_exposed_in_generic_profile_aggregation(self) -> None:
        self.assertIn('["Monthly", "Annual", "Weekly", "Daily", "Hourly", "Seasonal"]', self.source)

    def test_natural_ventilation_heatmap_uses_same_dimensions(self) -> None:
        self.assertIn('row_group = st.radio("Heat-map aggregation", ["Day", "Week", "Month"]', self.source)
        self.assertIn('compare_options = ["Hour of day"] if time_basis(df_nv) == CHRONOLOGICAL else ["Hour of day", "Year"]', self.source)
        self.assertIn('compare_across = st.radio("Compare across", compare_options', self.source)
        self.assertIn("Switch Time basis to Calendar profile", self.source)
        self.assertIn('key="nv_heatmap_statistic"', self.source)


if __name__ == "__main__":
    unittest.main()
