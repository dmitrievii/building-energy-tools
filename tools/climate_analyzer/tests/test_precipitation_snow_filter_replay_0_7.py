from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class PrecipitationSnowFilterReplay07Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_one_global_filter_spec_is_replayed_on_native_precipitation_frame(self) -> None:
        self.assertIn('st.session_state["_active_global_filter_spec"]', self.source)
        self.assertIn("def apply_active_global_filter(df: pd.DataFrame)", self.source)
        self.assertIn(
            "native_precipitation_df = apply_active_global_filter(prepare_historical_native_diagnostic_frame(dataset))",
            self.source,
        )
        self.assertIn("render_precipitation(filtered_df, native_df=native_precipitation_df)", self.source)

    def test_dual_resolution_ui_does_not_reintroduce_second_date_filter(self) -> None:
        self.assertIn("Dual-resolution semantics", self.source)
        self.assertIn("source-record occurrence", self.source)
        self.assertIn("snow-state duration/season indices", self.source)
        self.assertNotIn("Precipitation date range", self.source)
        self.assertNotIn("Snow date range", self.source)


if __name__ == "__main__":
    unittest.main()
