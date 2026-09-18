from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.ground_temperature import (
    AnnualHarmonic,
    animated_profile_figure,
    monthly_ground_profile,
    profile_figure,
    shared_temperature_range,
)
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
APP = ROOT / "app.py"


class UxCleanup074C1Tests(unittest.TestCase):
    def _ground_profile(self):
        harmonic = AnnualHarmonic(mean_c=10.0, sin_c=9.0, cos_c=2.0, amplitude_c=float(np.hypot(9.0, 2.0)))
        depths = np.arange(0.0, 15.25, 0.25)
        return monthly_ground_profile(harmonic, depths)

    def test_ground_profile_and_animation_use_one_fixed_annual_temperature_range(self) -> None:
        profile = self._ground_profile()
        expected = shared_temperature_range(profile)
        static = profile_figure(profile)
        animated = animated_profile_figure(profile)
        self.assertEqual(tuple(float(v) for v in static.layout.xaxis.range), expected)
        self.assertEqual(tuple(float(v) for v in animated.layout.xaxis.range), expected)
        self.assertEqual(static.layout.height, 650)
        self.assertEqual(animated.layout.height, 650)
        for month in profile.columns:
            self.assertGreaterEqual(float(profile[month].min()), expected[0])
            self.assertLessEqual(float(profile[month].max()), expected[1])

    def test_precipitation_heatmap_zero_is_white_and_domain_is_anchored_at_zero(self) -> None:
        index = pd.date_range("2026-01-01", periods=48, freq="h")
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [0.0] * 24 + [2.0] * 24,
                "hour_of_day": list(range(24)) * 2,
            },
            index=index,
        )
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = temporal_heatmap_chart(
            frame,
            "liquid_precipitation_depth_mm",
            "day",
            "Hour of day",
            "Total",
            "Precipitation",
            "mm",
        )
        self.assertEqual(float(fig.layout.coloraxis.cmin), 0.0)
        scale = fig.layout.coloraxis.colorscale
        self.assertEqual(str(scale[0][1]).lower(), "#ffffff")
        self.assertNotEqual(str(scale[0][1]), str(scale[-1][1]))

    def test_ground_multiyear_and_precipitation_distribution_controls_are_explicit(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('"Ground-profile year"', source)
        self.assertIn("Chronological multi-year mode", source)
        self.assertIn("Calendar profile multi-year mode", source)
        self.assertIn('"Distribution basis"', source)
        self.assertIn('"Wet intervals only"', source)
        self.assertIn('"All intervals including dry periods"', source)
        self.assertIn("precipitation depth > 0 mm", source)

    def test_temporary_c1_patch_transport_is_not_part_of_release_tree(self) -> None:
        self.assertFalse((ROOT / "scripts" / "apply_v074_c1.py").exists())
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "v074-c1-patch.yml").exists())


if __name__ == "__main__":
    unittest.main()
