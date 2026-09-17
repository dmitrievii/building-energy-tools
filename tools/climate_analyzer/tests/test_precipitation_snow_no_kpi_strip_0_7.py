from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class PrecipitationSnowNoKpiStrip07Tests(unittest.TestCase):
    def test_precipitation_renderer_does_not_add_page_specific_metric_strip(self) -> None:
        source = APP.read_text(encoding="utf-8")
        start = source.index("def render_precipitation(")
        end = source.index("\ndef render_sky_daylight", start)
        block = source[start:end]
        self.assertNotIn("st.metric(", block)
        self.assertNotIn(".metric(", block)
        self.assertNotIn("st.columns(4)", block)


if __name__ == "__main__":
    unittest.main()
