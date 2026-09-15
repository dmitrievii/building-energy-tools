from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.interpretations import (
    hvac_interpretation,
    natural_ventilation_interpretation,
    psychrometric_interpretation,
    sky_interpretation,
    solar_interpretation,
    temperature_interpretation,
    variable_interpretation,
    wind_interpretation,
)


def ten_minute_frame() -> pd.DataFrame:
    index = pd.date_range("2025-07-01T00:00:00Z", periods=6, freq="10min")
    df = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [10.0, 10.0, 30.0, 30.0, 22.0, 22.0],
            "humidity_ratio_g_kg": [2.0, 2.0, 11.0, 11.0, 5.0, 5.0],
            "moist_air_enthalpy_kj_kg": [40.0, 40.0, 60.0, 60.0, 50.0, 50.0],
            "global_horizontal_radiation_wh_m2": [0.0, 0.0, 400.0, 400.0, 0.0, 0.0],
            "diffuse_horizontal_radiation_wh_m2": [0.0, 0.0, 100.0, 100.0, 0.0, 0.0],
            "wind_speed_m_s": [0.5, 0.5, 9.0, 9.0, 3.0, 3.0],
            "total_sky_cover_tenths": [1.0, 1.0, 9.0, 9.0, 5.0, 5.0],
            "global_horizontal_illuminance_lux": [12000.0, 12000.0, 0.0, 0.0, 0.0, 0.0],
            "month_index": [7] * 6,
        },
        index=index,
    )
    df.attrs["canonical_native_interval_minutes"] = 10
    return df


class CadenceAwareInterpretationTests(unittest.TestCase):
    def test_temperature_hours_are_physical_duration(self) -> None:
        text = temperature_interpretation(ten_minute_frame(), 18.0, 26.0)
        self.assertIn("0.33 hours below 18 °C", text)
        self.assertIn("0.33 hours above 26 °C", text)
        self.assertNotIn("2 hours below", text)

    def test_generic_variable_reports_records_and_observed_hours(self) -> None:
        text = variable_interpretation(
            ten_minute_frame(),
            "dry_bulb_temperature_c",
            "temperature",
            "°C",
            high_threshold=26.0,
            low_threshold=18.0,
        )
        self.assertIn("6 valid source records representing 1 observed hours", text)
        self.assertIn("0.33 hours exceed 26 °C", text)
        self.assertIn("0.33 hours are below 18 °C", text)
        self.assertNotIn("valid hourly values", text)

    def test_psychrometric_wind_solar_sky_and_hvac_hours_are_scaled(self) -> None:
        df = ten_minute_frame()
        psych = psychrometric_interpretation(df)
        self.assertIn("0.33 very dry hours", psych)
        self.assertIn("0.33 humid hours", psych)
        self.assertIn("0.33 hours exceed 55 kJ/kg", psych)

        wind = wind_interpretation(df)
        self.assertIn("0.33 calm hours", wind)
        self.assertIn("0.33 strong-wind hours", wind)

        solar = solar_interpretation(df)
        self.assertIn("0.33 hours with GHI above 300 Wh/m²", solar)

        sky = sky_interpretation(df)
        self.assertIn("0.33 clear-sky hours", sky)
        self.assertIn("0.33 overcast hours", sky)
        self.assertIn("for 0.33 hours", sky)

        hvac = hvac_interpretation(df)
        self.assertIn("heating is indicated for 0.33 hours", hvac)
        self.assertIn("cooling for 0.33 hours", hvac)
        self.assertIn("0.33 hours exceed 10 g/kg", hvac)
        self.assertIn("0.33 hours are below 3 g/kg", hvac)

    def test_natural_ventilation_duration_and_monthly_peak_are_scaled(self) -> None:
        df = ten_minute_frame()
        mask = pd.Series([True, True, True, False, False, False], index=df.index)
        text = natural_ventilation_interpretation(df, mask)
        self.assertIn("suitable for 0.5 hours (50.0%", text)
        self.assertIn("month is 7 with 0.5 suitable hours", text)

    def test_hourly_epw_wording_and_counts_remain_legacy_compatible(self) -> None:
        index = pd.date_range("2025-01-01", periods=3, freq="h")
        df = pd.DataFrame(
            {
                "dry_bulb_temperature_c": [10.0, 20.0, 30.0],
                "wind_speed_m_s": [0.5, 3.0, 9.0],
            },
            index=index,
        )
        df.attrs["canonical_native_interval_minutes"] = 60
        text = variable_interpretation(df, "dry_bulb_temperature_c", "temperature", "°C")
        self.assertIn("3 valid hourly values", text)
        wind = wind_interpretation(df)
        self.assertIn("1 calm hours", wind)
        self.assertIn("1 strong-wind hours", wind)

    def test_timestamp_gap_does_not_inflate_interpretation_duration(self) -> None:
        df = ten_minute_frame().iloc[[0, 1, 5]].copy()
        df.index = pd.DatetimeIndex([
            "2025-07-01T00:00:00Z",
            "2025-07-01T00:10:00Z",
            "2025-07-02T12:00:00Z",
        ])
        df.attrs["canonical_native_interval_minutes"] = 10
        text = variable_interpretation(df, "dry_bulb_temperature_c", "temperature", "°C")
        self.assertIn("3 valid source records representing 0.5 observed hours", text)
        self.assertNotIn("36", text)


if __name__ == "__main__":
    unittest.main()
