import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.timeseries import (
    OverlaySeries,
    aggregate_series,
    available_resolution_labels,
    build_overlay_figure,
    circular_mean_deg,
    native_resolution_minutes,
    validate_unit_families,
)


class TimeSeriesOverlayTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2026-01-01 00:00", "2026-02-28 23:00", freq="h")
        self.df = pd.DataFrame(
            {
                "dry_bulb_temperature_c": np.arange(len(self.index), dtype=float) % 24,
                "global_horizontal_radiation_wh_m2": np.ones(len(self.index), dtype=float),
                "wind_direction_deg": np.tile([350.0, 10.0], len(self.index) // 2),
                "relative_humidity_pct": np.full(len(self.index), 50.0),
            },
            index=self.index,
        )

    def test_hourly_source_blocks_finer_resolutions(self):
        self.assertEqual(native_resolution_minutes(self.df.index), 60)
        labels = available_resolution_labels(self.df.index)
        self.assertNotIn("10 min", labels)
        self.assertNotIn("30 min", labels)
        self.assertIn("1 h", labels)
        self.assertIn("Daily", labels)

    def test_monthly_mean_uses_complete_calendar_bin_before_viewport_clip(self):
        # The viewport covers only two days, but the January value must still be
        # the complete January calendar mean.
        start = pd.Timestamp("2026-01-15 00:00")
        end = pd.Timestamp("2026-01-17 00:00")
        table = aggregate_series(self.df, "dry_bulb_temperature_c", "Monthly", start, end)
        expected = self.df.loc["2026-01-01":"2026-01-31", "dry_bulb_temperature_c"].mean()
        self.assertEqual(len(table), 1)
        self.assertAlmostEqual(float(table.iloc[0]["value"]), float(expected))
        self.assertEqual(pd.Timestamp(table.iloc[0]["plot_start"]), start)
        self.assertEqual(pd.Timestamp(table.iloc[0]["plot_end"]), end)

    def test_extensive_hourly_radiation_sums_on_daily_bins(self):
        table = aggregate_series(
            self.df,
            "global_horizontal_radiation_wh_m2",
            "Daily",
            pd.Timestamp("2026-01-02 00:00"),
            pd.Timestamp("2026-01-03 00:00"),
        )
        self.assertEqual(float(table.iloc[0]["value"]), 24.0)
        self.assertEqual(table.iloc[0]["aggregation"], "sum")

    def test_circular_wind_mean_wraps_through_north(self):
        result = circular_mean_deg(pd.Series([350.0, 10.0]))
        self.assertTrue(result < 1.0 or result > 359.0)
        table = aggregate_series(
            self.df,
            "wind_direction_deg",
            "3 h",
            pd.Timestamp("2026-01-01 00:00"),
            pd.Timestamp("2026-01-01 03:00"),
        )
        self.assertEqual(table.iloc[0]["aggregation"], "circular mean")

    def test_upsampling_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Cannot upsample"):
            aggregate_series(
                self.df,
                "dry_bulb_temperature_c",
                "30 min",
                pd.Timestamp("2026-01-01 00:00"),
                pd.Timestamp("2026-01-02 00:00"),
            )

    def test_overlay_uses_one_shared_x_axis_and_at_most_two_y_families(self):
        series = [
            OverlaySeries("Temperature", "dry_bulb_temperature_c", "°C", "Native"),
            OverlaySeries("Solar", "global_horizontal_radiation_wh_m2", "Wh/m²", "3 h"),
        ]
        start = pd.Timestamp("2026-01-01 00:00")
        end = pd.Timestamp("2026-01-02 00:00")
        fig, tables = build_overlay_figure(self.df, series, start, end)
        self.assertEqual(len(fig.data), 2)
        self.assertEqual(fig.data[0].yaxis, "y")
        self.assertEqual(fig.data[1].yaxis, "y2")
        self.assertEqual(pd.Timestamp(fig.layout.xaxis.range[0]), start)
        self.assertEqual(pd.Timestamp(fig.layout.xaxis.range[1]), end)
        self.assertEqual(len(tables), 2)

        too_many = series + [
            OverlaySeries("RH", "relative_humidity_pct", "%", "Native"),
        ]
        with self.assertRaisesRegex(ValueError, "at most two"):
            validate_unit_families(too_many)


if __name__ == "__main__":
    unittest.main()
