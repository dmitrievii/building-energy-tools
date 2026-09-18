from __future__ import annotations

import unittest
from io import BytesIO

import numpy as np
import pandas as pd
from PIL import Image

from epw_climate_analyzer.daylight import daylight_duration_hours, monthly_daylight_sunshine_summary
from epw_climate_analyzer.ground_temperature import AnnualHarmonic, animated_profile_gif_bytes, fit_annual_harmonic, monthly_ground_profile
from epw_climate_analyzer.geosphere import FIELD_SPEC_BY_PROVIDER
from epw_climate_analyzer.historical_capabilities import available_historical_pages


class DaylightGround073Tests(unittest.TestCase):
    def test_equinox_daylight_is_about_twelve_hours(self) -> None:
        hours = float(daylight_duration_hours(47.0, np.array([80]))[0])
        self.assertAlmostEqual(hours, 12.0, delta=0.25)

    def test_relative_sunshine_uses_measured_duration_not_fabricated_sky_cover(self) -> None:
        index = pd.date_range("2026-06-01", periods=48, freq="h", tz="UTC")
        frame = pd.DataFrame({"sunshine_duration_s": [1800.0] * 48}, index=index)
        summary = monthly_daylight_sunshine_summary(frame, 47.0)
        june = summary[summary["month_index"] == 6].iloc[0]
        self.assertEqual(int(june["sunshine_days"]), 2)
        self.assertGreater(float(june["relative_sunshine_pct"]), 0.0)
        self.assertLess(float(june["relative_sunshine_pct"]), 100.0)

    def test_incomplete_sunshine_day_is_excluded_from_relative_ratio(self) -> None:
        index = pd.date_range("2026-06-01", periods=48, freq="h", tz="UTC")
        values = pd.Series([1800.0] * 48, index=index)
        values.iloc[5] = np.nan
        frame = pd.DataFrame({"sunshine_duration_s": values}, index=index)
        summary = monthly_daylight_sunshine_summary(frame, 47.0)
        june = summary[summary["month_index"] == 6].iloc[0]
        self.assertEqual(int(june["sunshine_days"]), 1)
        self.assertGreater(float(june["observed_daylight_h"]), 0.0)

    def test_ground_profile_matches_user_reference_workbook_formula(self) -> None:
        harmonic = AnnualHarmonic(
            mean_c=10.506769406392662,
            sin_c=-2.372946578715855,
            cos_c=-10.933894896364142,
            amplitude_c=11.188428534435795,
        )
        profile = monthly_ground_profile(harmonic, np.array([0.0, 0.25, 15.0]), 2.0, 2000.0, 1000.0)
        self.assertAlmostEqual(float(profile.loc[0.0, "Jan"]), -0.5337866745508535, places=9)
        self.assertAlmostEqual(float(profile.loc[0.25, "Jul"]), 20.710435720735227, places=9)
        self.assertAlmostEqual(float(profile.loc[15.0, "Oct"]), 10.409625038969944, places=9)

    def test_harmonic_fit_recovers_synthetic_annual_cycle(self) -> None:
        index = pd.date_range("2025-01-01", periods=8760, freq="h", tz="UTC")
        phase = 2.0 * np.pi * ((index.dayofyear.to_numpy() - 1.0) + index.hour.to_numpy() / 24.0) / 365.0
        values = 10.5 - 2.3 * np.sin(phase) - 10.9 * np.cos(phase)
        fitted = fit_annual_harmonic(pd.Series(values, index=index))
        self.assertAlmostEqual(fitted.mean_c, 10.5, places=6)
        self.assertAlmostEqual(fitted.sin_c, -2.3, places=6)
        self.assertAlmostEqual(fitted.cos_c, -10.9, places=6)

    def test_ground_harmonic_rejects_short_seasonal_window(self) -> None:
        index = pd.date_range("2026-01-01", periods=90 * 24, freq="h", tz="UTC")
        values = pd.Series(5.0 + np.sin(np.arange(len(index)) / 100.0), index=index)
        with self.assertRaisesRegex(ValueError, "300 represented calendar days"):
            fit_annual_harmonic(values)


    def test_ground_profile_gif_is_infinite_twelve_frame_loop(self) -> None:
        harmonic = AnnualHarmonic(mean_c=10.5, sin_c=-2.3, cos_c=-10.9, amplitude_c=11.14)
        profile = monthly_ground_profile(harmonic, np.linspace(0.0, 15.0, 61), 2.0, 2000.0, 1000.0)
        payload = animated_profile_gif_bytes(profile, duration_ms=500, width=640, height=480)
        self.assertTrue(payload.startswith((b"GIF87a", b"GIF89a")))
        image = Image.open(BytesIO(payload))
        self.assertEqual(image.n_frames, 12)
        self.assertEqual(int(image.info.get("loop", -1)), 0)

    def test_geosphere_ground_fields_are_canonical_and_pages_are_exposed(self) -> None:
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tb10"].canonical_name, "ground_temperature_0_10m_c")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tb20"].canonical_name, "ground_temperature_0_20m_c")
        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tb50"].canonical_name, "ground_temperature_0_50m_c")
        index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
        frame = pd.DataFrame({
            "dry_bulb_temperature_c": [5.0] * 24,
            "sunshine_duration_s": [0.0] * 24,
            "ground_temperature_0_10m_c": [4.0] * 24,
        }, index=index)
        pages = set(available_historical_pages(frame))
        self.assertIn("Temperature", pages)
        self.assertNotIn("Ground Temperature", pages)
        self.assertIn("Sky and Daylight", pages)


if __name__ == "__main__":
    unittest.main()
