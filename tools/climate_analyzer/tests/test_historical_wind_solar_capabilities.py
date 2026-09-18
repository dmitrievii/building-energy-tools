from __future__ import annotations

import ast
import math
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import wind_rose_chart
from epw_climate_analyzer.historical_capabilities import (
    available_historical_pages,
    has_numeric_observations,
    horizontal_irradiance_frame,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def sample_frame() -> pd.DataFrame:
    index = pd.date_range("2025-07-01T12:00:00Z", periods=6, freq="10min")
    df = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [25.0] * 6,
            "relative_humidity_pct": [50.0] * 6,
            "wind_speed_m_s": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "wind_direction_deg": [0.0, 45.0, 90.0, 135.0, 180.0, 225.0],
            "global_horizontal_radiation_wh_m2": [100.0] * 6,
            "diffuse_horizontal_radiation_wh_m2": [25.0] * 6,
            "month_index": [7] * 6,
            "hour_of_day": [12] * 6,
        },
        index=index,
    )
    df.attrs["canonical_native_interval_minutes"] = 10
    return df


class HistoricalCapabilityTests(unittest.TestCase):
    def test_pages_are_enabled_only_by_actual_numeric_observations(self) -> None:
        df = sample_frame()
        pages = available_historical_pages(df)
        self.assertIn("Solar and Radiation", pages)
        self.assertIn("Wind and Ventilation", pages)
        self.assertIn("Temperature", pages)
        self.assertIn("Humidity and Psychrometrics", pages)

        missing = df.copy()
        missing["wind_speed_m_s"] = float("nan")
        missing["wind_direction_deg"] = float("nan")
        missing["global_horizontal_radiation_wh_m2"] = float("nan")
        missing["diffuse_horizontal_radiation_wh_m2"] = float("nan")
        missing_pages = available_historical_pages(missing)
        self.assertNotIn("Solar and Radiation", missing_pages)
        self.assertNotIn("Wind and Ventilation", missing_pages)
        self.assertFalse(has_numeric_observations(missing, "wind_speed_m_s"))

    def test_horizontal_irradiance_uses_declared_native_interval(self) -> None:
        converted = horizontal_irradiance_frame(sample_frame())
        self.assertTrue((converted["global_horizontal_irradiance_w_m2"] == 600.0).all())
        self.assertTrue((converted["diffuse_horizontal_irradiance_w_m2"] == 150.0).all())
        self.assertEqual(converted.attrs["canonical_native_interval_minutes"], 10)

    def test_wind_rose_integrates_physical_hours(self) -> None:
        fig = wind_rose_chart(sample_frame(), "Historical wind rose")
        total_hours = sum(sum(float(v) for v in trace.r) for trace in fig.data if getattr(trace, "r", None) is not None)
        self.assertTrue(math.isclose(total_hours, 1.0, abs_tol=1e-9))

    def test_historical_ui_exposes_measured_wind_and_horizontal_solar_only(self) -> None:
        source = APP.read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("def render_historical_wind", source)
        self.assertIn("canonical wind UI is source-neutral", source)
        self.assertIn('("Wind gust speed", "wind_gust_speed_m_s")', source)
        self.assertIn('("Wind gust direction", "wind_gust_direction_deg")', source)
        self.assertIn('st.selectbox("Wind dataset"', source)
        self.assertIn("def render_historical_solar", source)
        self.assertIn("available_historical_pages(dataset.data)", source)
        self.assertIn("Measured horizontal solar radiation", source)
        self.assertIn("Global horizontal irradiance", source)
        self.assertIn("DNI and plane-of-array", source)
        self.assertIn("routes remain intentionally unavailable", source)
        self.assertIn('elif page == "Solar and Radiation":', source)
        self.assertIn('elif page == "Wind and Ventilation":', source)

        solar_start = source.index("def render_historical_solar")
        solar_end = source.index("def render_canonical_climate_analysis", solar_start)
        solar_body = source[solar_start:solar_end]
        self.assertNotIn("direct_normal_radiation", solar_body)
        self.assertNotIn("orientation_annual_radiation", solar_body)
        self.assertNotIn("sun_path_chart", solar_body)


if __name__ == "__main__":
    unittest.main()
