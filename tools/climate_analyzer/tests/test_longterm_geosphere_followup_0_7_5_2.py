from __future__ import annotations

import unittest
from datetime import date

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import HEATMAP_COMPARE_HOUR, temporal_heatmap_matrix
from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.source_parity_longterm_followup import (
    compare_options_with_year,
    documented_coverage_warning,
    empty_measured_variable_table,
    heatmap_frame_from_index,
    index_populated_hour_axis_range,
    selected_variable_state,
    temperature_gradient_colorscale,
)
from epw_climate_analyzer.source_parity_longterm_hotfix import trim_empty_measured_edges
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, TIME_BASIS_ATTR


class LongTermGeoSphereFollowupTests(unittest.TestCase):
    def test_measured_variables_start_unchecked_and_state_tracks_only_user_selection(self) -> None:
        source = pd.DataFrame(
            {
                "Selected": [True, True],
                "Quality flag": [False, False],
                "Provider": ["tl", "so_h"],
                "Canonical field": ["dry_bulb_temperature_c", "sunshine_duration_s"],
            }
        )
        empty = empty_measured_variable_table(source)
        self.assertEqual(empty["Selected"].tolist(), [False, False])
        self.assertEqual(source["Selected"].tolist(), [True, True])

        empty.loc[1, "Selected"] = True
        state = selected_variable_state(empty, resource_id="klima-v2-1h", station_id="105")
        self.assertEqual(state["providers"], ("so_h",))
        self.assertEqual(state["canonicals"], ("sunshine_duration_s",))

    def test_documented_1941_warning_is_nonblocking_and_variable_specific(self) -> None:
        warning = documented_coverage_warning(
            "klima-v2-1h",
            date(1890, 1, 1),
            ["dry_bulb_temperature_c"],
        )
        self.assertIsNotNone(warning)
        self.assertIn("1941", str(warning))
        self.assertIn("not a station-specific cutoff", str(warning))

        self.assertIsNone(
            documented_coverage_warning(
                "klima-v2-1h",
                date(1890, 1, 1),
                ["sunshine_duration_s"],
            )
        )
        self.assertIsNone(
            documented_coverage_warning(
                "klima-v2-1h",
                date(1950, 1, 1),
                ["dry_bulb_temperature_c"],
            )
        )

    def test_heatmap_hour_coordinate_is_derived_from_index_not_stale_helper_column(self) -> None:
        index = pd.date_range("2024-01-01T00:00:00Z", periods=48, freq="h")
        frame = pd.DataFrame(
            {
                "dry_bulb_temperature_c": np.arange(48, dtype=float),
                # Reproduce the production defect: a stale helper collapsed all
                # observations to midnight even though the timestamp index did not.
                "hour_of_day": np.zeros(48, dtype=int),
            },
            index=index,
        )
        frame.attrs[TIME_BASIS_ATTR] = CHRONOLOGICAL
        repaired = heatmap_frame_from_index(frame)
        self.assertEqual(sorted(repaired["hour_of_day"].unique().tolist()), list(range(24)))
        self.assertEqual(frame["hour_of_day"].unique().tolist(), [0])

        for group in ("day", "week", "month"):
            with self.subTest(group=group):
                matrix = temporal_heatmap_matrix(
                    repaired,
                    "dry_bulb_temperature_c",
                    row_group=group,
                    compare_across=HEATMAP_COMPARE_HOUR,
                    statistic="Mean",
                )
                self.assertEqual(matrix.index.tolist(), list(range(24)))

        self.assertEqual(
            index_populated_hour_axis_range(repaired, "dry_bulb_temperature_c"),
            [23.5, -0.5],
        )

    def test_temperature_cold_band_is_a_gradient_not_one_blue(self) -> None:
        cold = temperature_gradient_colorscale(np.array([-20.0, -10.0, 0.0, 10.0]), (18.0, 26.0))
        self.assertGreaterEqual(len(cold), 3)
        self.assertGreaterEqual(len({str(stop[1]) for stop in cold}), 3)
        self.assertEqual(float(cold[0][0]), 0.0)
        self.assertEqual(float(cold[-1][0]), 1.0)

        mixed = temperature_gradient_colorscale(np.array([-15.0, 10.0, 20.0, 30.0, 36.0]), (18.0, 26.0))
        positions = [float(stop[0]) for stop in mixed]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(positions[0], 0.0)
        self.assertEqual(positions[-1], 1.0)
        self.assertGreaterEqual(len({str(stop[1]) for stop in mixed}), 5)

    def test_year_compare_is_available_without_changing_global_time_basis(self) -> None:
        self.assertEqual(
            compare_options_with_year(["Hour of day"]),
            ["Hour of day", "Year"],
        )
        self.assertEqual(
            compare_options_with_year(["Hour of day", "Year"]),
            ["Hour of day", "Year"],
        )

    def test_empty_temperature_head_does_not_trim_valid_earlier_sunshine(self) -> None:
        index = pd.date_range("1890-01-01T00:00:00Z", periods=8, freq="h")
        frame = pd.DataFrame(
            {
                "sunshine_duration_s": [0.0, 0.0, 600.0, 0.0, 1200.0, np.nan, np.nan, np.nan],
                "dry_bulb_temperature_c": [np.nan, np.nan, np.nan, np.nan, 5.0, 6.0, np.nan, np.nan],
            },
            index=index,
        )
        dataset = CanonicalClimateDataset(
            climate_id="test:mixed-coverage",
            display_name="Mixed coverage",
            data=frame,
            location=ClimateLocation(latitude=48.25, longitude=16.36, station_id="105"),
            temporal=ClimateTemporalMetadata(
                native_interval_minutes=60,
                calendar_mode="historical",
                timezone_name="UTC",
                interval_semantics="unknown",
            ),
            provenance=ClimateProvenance(
                provider="GeoSphere Austria",
                dataset="klima-v2-1h",
                source_format="Dataset API JSON",
                source_name="Wien Hohe Warte",
            ),
        )
        trimmed = trim_empty_measured_edges(dataset)
        # 0.0 sunshine is a valid measured value.  The early rows therefore
        # remain even though temperature has not started yet.
        self.assertEqual(trimmed.data.index[0], index[0])
        self.assertEqual(trimmed.data.index[-1], index[5])
        self.assertTrue(pd.isna(trimmed.data.loc[index[0], "dry_bulb_temperature_c"]))
        self.assertEqual(float(trimmed.data.loc[index[0], "sunshine_duration_s"]), 0.0)


if __name__ == "__main__":
    unittest.main()
