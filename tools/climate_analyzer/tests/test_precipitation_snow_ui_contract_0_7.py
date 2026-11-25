from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class PrecipitationSnowUiContract07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_precipitation_page_exposes_scientific_0_7_analysis_families(self) -> None:
        for label in (
            "Precipitation totals",
            "Annual precipitation indices",
            "Precipitation-record occurrence",
            "Measured precipitation duration",
            "Snow-cover duration",
            "Snow-season indices",
        ):
            self.assertIn(label, self.source)

    def test_snow_explorer_and_native_snow_metrics_have_separate_capabilities(self) -> None:
        self.assertIn("hourly_snow_available", self.source)
        self.assertIn("native_snow_available", self.source)
        self.assertIn('if hourly_snow_available:\n        options.append("Snow depth explorer")', self.source)
        self.assertIn(
            'if native_snow_available:\n        options.extend(["Snow-cover duration", "Snow-season indices", "Snow-cover calendar"])',
            self.source,
        )

    def test_rrm_duration_is_explicitly_not_inferred_from_rr(self) -> None:
        self.assertIn('extensive_total_panel(df,render_plot,columns=("precipitation_duration_min",))', self.source)
        from epw_climate_analyzer.residual_findings import extensive_total_figure
        import pandas as pd
        df=pd.DataFrame({"precipitation_duration_min":[10.,20.,float("nan")],"liquid_precipitation_depth_mm":[0.,0.,20.]},index=pd.date_range("2026-01-01",periods=3,freq="h"))
        df.attrs["canonical_native_interval_minutes"]=60
        fig,note=extensive_total_figure(df,"precipitation_duration_min","Daily")
        self.assertAlmostEqual(float(fig.data[0].y[0]),0.5)
        self.assertTrue(note)

    def test_snow_season_and_precipitation_thresholds_are_visible_and_explicit(self) -> None:
        self.assertIn("Wet day ≥ 1 mm/day", self.source)
        self.assertIn("heavy day ≥ 10 mm/day", self.source)
        self.assertIn("very heavy day ≥ 20 mm/day", self.source)
        self.assertIn("Snow seasons use a July–June analysis year", self.source)
        self.assertIn("meaningful-cover day: > 5 cm", self.source)


if __name__ == "__main__":
    unittest.main()
