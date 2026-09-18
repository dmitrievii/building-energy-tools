from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.interpretations import variable_interpretation
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class TemporalUx074Tests(unittest.TestCase):
    def test_temperature_minimum_heatmap_cannot_generate_invalid_colorscale(self) -> None:
        idx = pd.date_range("2025-01-01", periods=48, freq="h")
        df = pd.DataFrame({"dry_bulb_temperature_c": [-15.0] * 24 + [-10.0] * 24}, index=idx)
        df["hour_of_day"] = df.index.hour
        df = with_time_basis(df, CHRONOLOGICAL)
        fig = temporal_heatmap_chart(df, "dry_bulb_temperature_c", "day", "Hour of day", "Minimum", "Minimum", "°C", temperature_thresholds=(18.0, 26.0))
        scale = fig.layout.coloraxis.colorscale
        self.assertTrue(scale)
        self.assertTrue(all(0.0 <= float(stop[0]) <= 1.0 for stop in scale))

    def test_interpretation_explains_middle_90_without_requiring_percentile_knowledge(self) -> None:
        idx = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01"])
        df = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 20.0, 2.0, 24.0]}, index=idx)
        df = with_time_basis(df, CHRONOLOGICAL)
        text = variable_interpretation(df, "dry_bulb_temperature_c", "temperature", "°C")
        self.assertIn("middle 90%", text)
        self.assertIn("only about 5% are lower", text)
        self.assertIn("2024", text)
        self.assertIn("2025", text)
        self.assertIn("annual mean", text)

    def test_ui_uses_plain_language_percentile_labels_and_20c_cooling_limit(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("Middle 90% range with median", source)
        self.assertIn("Lower 5% boundary (P05)", source)
        self.assertIn("Upper 5% boundary (P95)", source)
        self.assertIn("Nighttime hours > 20 °C (20:00–06:59)", source)
        self.assertIn('"Cooling limit [°C]",\n            10.0,\n            35.0,\n            20.0', source)


if __name__ == "__main__":
    unittest.main()
