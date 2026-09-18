from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.timeseries import OverlaySeries, build_overlay_figure

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
APP = ROOT / "app.py"


class TimeSeriesStyling074C2Tests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        index = pd.date_range("2026-01-01", periods=24, freq="h")
        return pd.DataFrame(
            {
                "dry_bulb_temperature_c": [float(i) for i in range(24)],
                "dew_point_temperature_c": [float(i) - 3.0 for i in range(24)],
            },
            index=index,
        )

    def test_explicit_series_style_reaches_plotly_trace(self) -> None:
        frame = self._frame()
        spec = OverlaySeries(
            "Outdoor temperature",
            "dry_bulb_temperature_c",
            "°C",
            "Native",
            color="#123456",
            dash="dashdot",
            width=3.5,
            opacity=0.55,
        )
        fig, _tables = build_overlay_figure(
            frame,
            [spec],
            frame.index.min(),
            frame.index.max() + pd.Timedelta(hours=1),
        )
        trace = fig.data[0]
        self.assertEqual(trace.line.color, "#123456")
        self.assertEqual(trace.line.dash, "dashdot")
        self.assertEqual(float(trace.line.width), 3.5)
        self.assertAlmostEqual(float(trace.opacity), 0.55)

    def test_unstyled_series_keep_legacy_automatic_dash_cycle(self) -> None:
        frame = self._frame()
        specs = [
            OverlaySeries("Dry bulb", "dry_bulb_temperature_c", "°C", "Native"),
            OverlaySeries("Dew point", "dew_point_temperature_c", "°C", "Native"),
        ]
        fig, _tables = build_overlay_figure(
            frame,
            specs,
            frame.index.min(),
            frame.index.max() + pd.Timedelta(hours=1),
        )
        self.assertEqual(fig.data[0].line.dash, "solid")
        self.assertEqual(fig.data[1].line.dash, "dash")

    def test_ui_exposes_independent_style_controls_for_each_series(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('f"Series {i + 1} style"', source)
        self.assertIn('"Line style"', source)
        self.assertIn('"Line width"', source)
        self.assertIn('"Line color"', source)
        self.assertIn('"Opacity"', source)
        self.assertIn('"Dash-dot"', source)

    def test_temporary_c2_patch_transport_is_not_part_of_release_tree(self) -> None:
        self.assertFalse((ROOT / "scripts" / "apply_v074_c2.py").exists())
        self.assertFalse((REPO_ROOT / ".github" / "workflows" / "v074-c2-patch.yml").exists())


if __name__ == "__main__":
    unittest.main()
