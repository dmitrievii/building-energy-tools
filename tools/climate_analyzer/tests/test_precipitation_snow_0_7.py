from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame
from epw_climate_analyzer.climate_model import aggregation_semantics_for
from epw_climate_analyzer.geosphere import FIELD_SPEC_BY_PROVIDER
from epw_climate_analyzer.precipitation import (
    aggregate_precipitation_duration,
    annual_native_precipitation_peaks,
    annual_precipitation_indices,
    occurrence_hours,
    snow_season_indices,
)


class PrecipitationSnow07Tests(unittest.TestCase):
    def test_rrm_is_explicit_geosphere_duration_quantity_with_sum_semantics(self) -> None:
        spec = FIELD_SPEC_BY_PROVIDER["rrm"]
        self.assertEqual(spec.canonical_name, "precipitation_duration_min")
        self.assertEqual(spec.expected_units, ("min",))
        self.assertEqual(aggregation_semantics_for("precipitation_duration_min"), "sum")

    def test_hourly_rrm_sum_is_conserved_and_variable_local_missingness_stays_strict(self) -> None:
        index = pd.date_range("2024-06-01T00:00:00Z", periods=12, freq="10min")
        frame = pd.DataFrame(
            {
                "precipitation_duration_min": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 0.0, 1.0, float("nan"), 3.0, 4.0, 5.0],
                "liquid_precipitation_depth_mm": [0.1] * 12,
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 10
        hourly = canonical_hourly_analysis_frame(frame)
        self.assertEqual(len(hourly), 2)
        self.assertAlmostEqual(float(hourly.iloc[0]["precipitation_duration_min"]), 15.0)
        self.assertTrue(pd.isna(hourly.iloc[1]["precipitation_duration_min"]))
        self.assertAlmostEqual(float(hourly.iloc[0]["liquid_precipitation_depth_mm"]), 0.6)
        self.assertAlmostEqual(float(hourly.iloc[1]["liquid_precipitation_depth_mm"]), 0.6)

    def test_annual_precipitation_indices_use_daily_thresholds_and_missing_day_breaks_dry_spell(self) -> None:
        index = pd.date_range("2024-01-01", periods=8, freq="D", tz="UTC")
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [0.0, 0.0, 1.0, float("nan"), 0.0, 12.0, 20.0, 0.0],
                "precipitation_duration_min": [0.0, 0.0, 10.0, float("nan"), 0.0, 20.0, 30.0, 0.0],
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 60
        table = annual_precipitation_indices(frame)
        self.assertEqual(len(table), 1)
        row = table.iloc[0]
        self.assertEqual(int(row["year"]), 2024)
        self.assertAlmostEqual(float(row["precipitation_total_mm"]), 33.0)
        self.assertEqual(int(row["wet_days_ge_1mm"]), 3)
        self.assertEqual(int(row["heavy_days_ge_10mm"]), 2)
        self.assertEqual(int(row["very_heavy_days_ge_20mm"]), 1)
        self.assertAlmostEqual(float(row["max_daily_precipitation_mm"]), 20.0)
        self.assertEqual(int(row["longest_dry_spell_days"]), 2)
        self.assertEqual(int(row["valid_daily_totals"]), 7)
        self.assertAlmostEqual(float(row["measured_precipitation_duration_h"]), 1.0)

    def test_measured_precipitation_duration_is_summed_and_never_inferred_from_depth(self) -> None:
        index = pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="h")
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [5.0, 5.0, 5.0, 5.0],
                "precipitation_duration_min": [5.0, 10.0, 0.0, 15.0],
            },
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 60
        result = aggregate_precipitation_duration(frame, "Daily")
        self.assertAlmostEqual(float(result.iloc[0]["duration_min"]), 30.0)

        without_duration = frame.drop(columns=["precipitation_duration_min"])
        missing = aggregate_precipitation_duration(without_duration, "Daily")
        self.assertTrue(missing.empty)

    def test_native_precipitation_peak_preserves_true_10_minute_extreme(self) -> None:
        index = pd.date_range("2024-07-01T12:00:00Z", periods=6, freq="10min")
        frame = pd.DataFrame(
            {"liquid_precipitation_depth_mm": [0.0, 0.3, 4.2, 1.0, 0.0, 0.0]},
            index=index,
        )
        frame.attrs["canonical_native_interval_minutes"] = 10
        result = annual_native_precipitation_peaks(frame)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(float(result.iloc[0]["max_native_interval_mm"]), 4.2)
        self.assertEqual(pd.Timestamp(result.iloc[0]["max_native_interval_timestamp"]), index[2])
        self.assertAlmostEqual(float(result.attrs["native_interval_minutes"]), 10.0)

    def test_native_snow_cover_duration_integrates_10_minute_state_records(self) -> None:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        frame = pd.DataFrame({"snow_depth_cm": [0.0, 2.0, 3.0, 0.0, float("nan"), 1.0]}, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 10
        result = occurrence_hours(frame, "snow_depth_cm", 0.0, "Daily", inclusive=False)
        self.assertAlmostEqual(float(result.iloc[0]["hours"]), 0.5)

    def test_snow_season_uses_july_to_june_and_keeps_cross_year_first_last_dates(self) -> None:
        index = pd.to_datetime(
            [
                "2024-11-01T00:00:00Z",
                "2025-01-15T00:00:00Z",
                "2025-03-20T00:00:00Z",
                "2025-11-10T00:00:00Z",
            ]
        )
        frame = pd.DataFrame({"snow_depth_cm": [2.0, 8.0, 1.0, 6.0]}, index=index)
        frame.attrs["canonical_native_interval_minutes"] = 10
        table = snow_season_indices(frame)
        first = table[table["season_start_year"] == 2024].iloc[0]
        self.assertEqual(first["season"], "2024/25")
        self.assertEqual(int(first["snow_cover_days"]), 3)
        self.assertEqual(int(first["days_gt_5cm"]), 1)
        self.assertAlmostEqual(float(first["max_snow_depth_cm"]), 8.0)
        self.assertEqual(pd.Timestamp(first["first_snow_date"]), pd.Timestamp("2024-11-01T00:00:00Z"))
        self.assertEqual(pd.Timestamp(first["last_snow_date"]), pd.Timestamp("2025-03-20T00:00:00Z"))
        self.assertEqual(int(first["snow_season_span_days"]), 140)


if __name__ == "__main__":
    unittest.main()
