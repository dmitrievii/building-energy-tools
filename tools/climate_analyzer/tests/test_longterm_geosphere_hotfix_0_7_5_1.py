from __future__ import annotations

import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.source_parity_longterm_hotfix import (
    chronological_aggregate_summary,
    chronological_period_total,
    populated_hour_axis_range,
    trim_empty_measured_edges,
)
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, TIME_BASIS_ATTR


class LongTermGeoSphereHotfixTests(unittest.TestCase):
    @staticmethod
    def _vienna_year() -> pd.DataFrame:
        # Exact local-civil calendar year 2024 in Vienna.  Both endpoints are CET
        # (UTC+1), so the UTC window is 2023-12-31 23:00 <= t < 2024-12-31 23:00.
        utc = pd.date_range(
            "2023-12-31T23:00:00Z",
            "2024-12-31T23:00:00Z",
            inclusive="left",
            freq="h",
        )
        local = utc.tz_convert(ZoneInfo("Europe/Vienna"))
        frame = pd.DataFrame(
            {"dry_bulb_temperature_c": np.sin(np.arange(len(local)) / 200.0)},
            index=local,
        )
        frame.attrs[TIME_BASIS_ATTR] = CHRONOLOGICAL
        return frame

    def test_daily_weekly_monthly_annual_calendar_grouping_crosses_dst(self) -> None:
        frame = self._vienna_year()
        self.assertEqual(len(frame), 8784)
        self.assertEqual(set(pd.DatetimeIndex(frame.index).year), {2024})
        for aggregation in ("Daily", "Weekly", "Monthly", "Annual"):
            with self.subTest(aggregation=aggregation):
                result = chronological_aggregate_summary(
                    frame,
                    "dry_bulb_temperature_c",
                    aggregation,
                )
                self.assertFalse(result.empty)
                self.assertIsInstance(result.index, pd.DatetimeIndex)
                self.assertIsNone(result.index.tz)

        monthly = chronological_aggregate_summary(
            frame,
            "dry_bulb_temperature_c",
            "Monthly",
        )
        self.assertEqual(len(monthly), 12)
        self.assertIn(pd.Timestamp("2024-03-01"), monthly.index)
        self.assertIn(pd.Timestamp("2024-10-01"), monthly.index)

    def test_october_fallback_preserves_745_physical_hours(self) -> None:
        frame = self._vienna_year()
        index = pd.DatetimeIndex(frame.index)
        october_mask = (index.year == 2024) & (index.month == 10)
        october = frame.loc[october_mask].copy()
        october.attrs.update(frame.attrs)
        self.assertEqual(len(october), 745)

        ones = pd.Series(1.0, index=october.index)
        totals = chronological_period_total(ones, october, "Monthly")
        self.assertEqual(float(totals.loc[pd.Timestamp("2024-10-01")]), 745.0)

        repeated = october.loc[
            (pd.DatetimeIndex(october.index).day == 27)
            & (pd.DatetimeIndex(october.index).hour == 2)
        ]
        self.assertEqual(len(repeated), 2)
        offsets = {stamp.utcoffset().total_seconds() for stamp in repeated.index}
        self.assertEqual(offsets, {3600.0, 7200.0})

    def test_heatmap_hour_axis_uses_only_populated_hours(self) -> None:
        index = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1.0, 2.0, 3.0, 4.0],
                "hour_of_day": [0, 0, 0, 0],
            },
            index=index,
        )
        self.assertEqual(
            populated_hour_axis_range(frame, "dry_bulb_temperature_c"),
            [0.5, -0.5],
        )

        mixed = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [1.0, 2.0, 3.0],
                "hour_of_day": [6, 12, 18],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC"),
        )
        self.assertEqual(
            populated_hour_axis_range(mixed, "dry_bulb_temperature_c"),
            [18.5, 5.5],
        )

    def test_only_empty_outer_tails_are_trimmed(self) -> None:
        index = pd.date_range("1940-12-31T20:00:00Z", periods=10, freq="h")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [
                    np.nan,
                    np.nan,
                    1.0,
                    2.0,
                    np.nan,
                    3.0,
                    np.nan,
                    np.nan,
                    np.nan,
                    np.nan,
                ]
            },
            index=index,
        )
        frame.attrs["canonical_requested_start"] = index[0].isoformat()
        frame.attrs["canonical_requested_end"] = index[-1].isoformat()
        dataset = CanonicalClimateDataset(
            climate_id="test:longterm",
            display_name="Long-term test",
            data=frame,
            location=ClimateLocation(
                latitude=48.25,
                longitude=16.36,
                elevation_m=198.0,
                city="Wien Hohe Warte",
                country="Austria",
                station_id="105",
            ),
            temporal=ClimateTemporalMetadata(
                native_interval_minutes=60,
                calendar_mode="historical",
                timezone_name="UTC",
                interval_semantics="unknown",
            ),
            provenance=ClimateProvenance(
                provider="GeoSphere Austria",
                dataset="test",
                source_format="Dataset API JSON",
                source_name="test station",
            ),
        )

        trimmed = trim_empty_measured_edges(dataset)
        self.assertEqual(len(trimmed.data), 4)
        self.assertEqual(trimmed.data.index[0], index[2])
        self.assertEqual(trimmed.data.index[-1], index[5])
        self.assertTrue(pd.isna(trimmed.data.iloc[2]["dry_bulb_temperature_c"]))
        self.assertEqual(trimmed.data.attrs["canonical_trimmed_empty_edge_rows"], 6)
        self.assertEqual(trimmed.data.attrs["canonical_requested_start"], index[0].isoformat())
        self.assertEqual(trimmed.data.attrs["canonical_requested_end"], index[-1].isoformat())

    def test_all_empty_selected_measurements_fail_closed(self) -> None:
        index = pd.date_range("1940-01-01", periods=3, freq="h", tz="UTC")
        frame = pd.DataFrame({"dry_bulb_temperature_c": [np.nan, np.nan, np.nan]}, index=index)
        dataset = CanonicalClimateDataset(
            climate_id="test:empty",
            display_name="Empty test",
            data=frame,
            location=ClimateLocation(latitude=48.25, longitude=16.36),
            temporal=ClimateTemporalMetadata(
                native_interval_minutes=60,
                calendar_mode="historical",
                timezone_name="UTC",
                interval_semantics="unknown",
            ),
            provenance=ClimateProvenance(
                provider="GeoSphere Austria",
                dataset="test",
                source_format="Dataset API JSON",
                source_name="test station",
            ),
        )
        with self.assertRaisesRegex(ValueError, "no numeric observations"):
            trim_empty_measured_edges(dataset)


if __name__ == "__main__":
    unittest.main()
