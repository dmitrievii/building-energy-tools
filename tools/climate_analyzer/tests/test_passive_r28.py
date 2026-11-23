"""R2.8 regression: staged outdoor-air screening and night-cooling chronology."""
from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.decisions import (
    natural_ventilation_condition, night_flushing_condition,
)
from epw_climate_analyzer.passive_design_findings import (
    night_flushing_interpretation,
    ventilation_screen_interpretation,
    ventilation_screen_stages,
)


class PassiveDesignR28Tests(unittest.TestCase):
    @staticmethod
    def frame() -> pd.DataFrame:
        idx = pd.date_range("2026-06-01", periods=6, freq="h")
        df = pd.DataFrame({
            "dry_bulb_temperature_c": [15., 18., 20., 22., 24., 27.],
            "humidity_ratio_g_kg": [5., 7., 10., 8., float("nan"), 6.],
            "wind_speed_m_s": [1., 0.2, 2., 3., 4., 5.],
            "hour_of_day": idx.hour,
        }, index=idx)
        df.attrs["canonical_native_interval_minutes"] = 60.
        return df

    def test_stages_decompose_moisture_and_wind(self):
        df = self.frame()
        a = ventilation_screen_stages(
            df, t_min_c=16, t_max_c=26, d_max_g_kg=9,
            wind_min_m_s=.5, wind_max_m_s=6,
        )
        self.assertEqual(a["hours"].tolist(), [4., 2., 1.])
        self.assertTrue(a["hours"].is_monotonic_decreasing)
        expected = natural_ventilation_condition(
            df, 16, 26, 9, wind_min_m_s=.5, wind_max_m_s=6,
        )
        self.assertEqual(a["hours"].iloc[-1], float(expected.sum()))
        note = ventilation_screen_interpretation(
            df, a, t_min_c=16, t_max_c=26, d_max_g_kg=9,
        )
        self.assertIn("removes 2.0", note)
        self.assertIn("1.0 hours", note)

    def test_tropical_humidity_outside_strict_screen(self):
        df = self.frame()
        df["dry_bulb_temperature_c"] = 25.
        df["humidity_ratio_g_kg"] = 18.
        a = ventilation_screen_stages(df)
        self.assertEqual(a["hours"].tolist(), [6., 0.])
        note = ventilation_screen_interpretation(
            df, a, t_min_c=16., t_max_c=26., d_max_g_kg=9.,
        )
        self.assertIn("Moisture is the controlling condition", note)
        self.assertIn("Air-movement and adaptive-comfort assessments", note)

    def test_subhourly_units_and_overnight_occupancy(self):
        df = self.frame().copy()
        df.index = pd.date_range("2026-06-01 21:00", periods=6, freq="30min")
        df["hour_of_day"] = df.index.hour
        df.attrs["canonical_native_interval_minutes"] = 30.
        a = ventilation_screen_stages(
            df, t_min_c=16., t_max_c=26., d_max_g_kg=9.,
            occupied_only=True, occupied_start_hour=22, occupied_end_hour=2,
        )
        self.assertEqual(a["hours"].tolist(), [2., 1., 0.5])
        mask = natural_ventilation_condition(
            df, 16, 26, 9, occupied_only=True,
            occupied_start_hour=22, occupied_end_hour=2,
        )
        self.assertEqual(a["hours"].iloc[-1], mask.sum() * .5)

    def test_unknown_moisture_never_becomes_eligible(self):
        df = self.frame().drop(columns="humidity_ratio_g_kg")
        a = ventilation_screen_stages(df)
        self.assertEqual(a["hours"].tolist(), [4., 0.])

    def test_incomplete_hot_day_does_not_qualify_following_night(self):
        idx = pd.date_range("2026-07-01 00:00", periods=48, freq="h")
        df = pd.DataFrame({
            "dry_bulb_temperature_c": [27.] * 24 + [18.] * 24,
            "hour_of_day": idx.hour,
        }, index=idx)
        df.attrs["canonical_native_interval_minutes"] = 60.
        valid = night_flushing_condition(df)
        self.assertTrue(valid.loc["2026-07-02 00:00"])
        self.assertFalse(valid.loc["2026-07-01 00:00"])
        missing = df.drop(pd.Timestamp("2026-07-01 12:00"))
        invalid = night_flushing_condition(missing)
        self.assertFalse(invalid.loc["2026-07-02 00:00"])
        self.assertFalse(invalid.loc["2026-07-02 06:00"])
        text = night_flushing_interpretation(
            df, valid, hot_day_c=26., night_max_c=20.,
        )
        self.assertIn("night-cooling screen", text)
        self.assertIn("overnight periods", text)

    def test_month_boundary_night_uses_preceding_day(self):
        idx = pd.date_range("2026-08-31", periods=48, freq="h")
        df = pd.DataFrame({
            "dry_bulb_temperature_c": [30.] * 22 + [19.] * 2 + [18.] * 24,
            "hour_of_day": idx.hour,
        }, index=idx)
        df.attrs["canonical_native_interval_minutes"] = 60.
        mask = night_flushing_condition(df)
        self.assertTrue(mask.loc["2026-08-31 22:00"])
        self.assertTrue(mask.loc["2026-09-01 00:00"])
        self.assertFalse(mask.loc["2026-09-01 22:00"])


if __name__ == "__main__":
    unittest.main()
