from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import wind_rose_chart
from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class SourceNeutralUi074Tests(unittest.TestCase):
    def test_ground_temperature_is_nested_under_temperature_navigation(self) -> None:
        self.assertIn("Temperature", NAVIGATION_PAGES)
        self.assertNotIn("Ground Temperature", NAVIGATION_PAGES)
        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        ground_only = pd.DataFrame({"ground_temperature_0_10m_c": [4.0, 4.1]}, index=idx)
        pages = available_historical_pages(ground_only)
        self.assertIn("Temperature", pages)
        self.assertNotIn("Ground Temperature", pages)
        source = APP.read_text(encoding="utf-8")
        self.assertIn('chart_options.append("Ground temperature")', source)

    def test_wind_rose_accepts_gust_pair_without_mean_wind_columns(self) -> None:
        idx = pd.date_range("2026-07-01", periods=4, freq="h", tz="UTC")
        df = pd.DataFrame({
            "wind_gust_speed_m_s": [4.0, 6.0, 8.0, 10.0],
            "wind_gust_direction_deg": [0.0, 90.0, 180.0, 270.0],
        }, index=idx)
        df.attrs["canonical_native_interval_minutes"] = 60
        fig = wind_rose_chart(
            df, "Gust rose",
            speed_column="wind_gust_speed_m_s",
            direction_column="wind_gust_direction_deg",
        )
        represented = sum(sum(float(v) for v in trace.r) for trace in fig.data if getattr(trace, "r", None) is not None)
        self.assertAlmostEqual(represented, 4.0)

    def test_common_wind_renderer_contains_mean_and_gust_variables(self) -> None:
        source = APP.read_text(encoding="utf-8")
        start = source.index("def render_wind")
        end = source.index("def render_precipitation", start)
        body = source[start:end]
        for label in ("Wind speed", "Wind direction", "Wind gust speed", "Wind gust direction"):
            self.assertIn(label, body)
        self.assertIn("Maximum gust", body)
        self.assertIn("Wind dataset", body)


if __name__ == "__main__":
    unittest.main()
