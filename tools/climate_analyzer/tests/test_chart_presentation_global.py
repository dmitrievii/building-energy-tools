from __future__ import annotations

from pathlib import Path
import unittest

import plotly.graph_objects as go

from epw_climate_analyzer.chart_presentation import (
    CANVAS_AUTO,
    CANVAS_CUSTOM,
    CANVAS_PRESENTATION,
    CANVAS_SQUARE,
    CANVAS_WIDE,
    ChartPresentationSettings,
    apply_chart_presentation,
    merge_plotly_config,
)


ROOT = Path(__file__).resolve().parents[1]
UI_CONTRACT = ROOT / "epw_climate_analyzer" / "ui_contract.py"
PRESENTATION_MODULE = ROOT / "epw_climate_analyzer" / "chart_presentation.py"


class GlobalChartPresentationTests(unittest.TestCase):
    def test_canvas_presets_have_deterministic_dimensions(self) -> None:
        self.assertEqual(
            ChartPresentationSettings(canvas=CANVAS_WIDE).base_dimensions(),
            (1280, 720),
        )
        self.assertEqual(
            ChartPresentationSettings(canvas=CANVAS_PRESENTATION).base_dimensions(),
            (1200, 900),
        )
        self.assertEqual(
            ChartPresentationSettings(canvas=CANVAS_SQUARE).base_dimensions(),
            (900, 900),
        )
        self.assertIsNone(ChartPresentationSettings(canvas=CANVAS_AUTO).base_dimensions())

    def test_custom_canvas_and_display_scale_preserve_aspect_ratio(self) -> None:
        settings = ChartPresentationSettings(
            canvas=CANVAS_CUSTOM,
            width_percent=50,
            custom_width=1400,
            custom_height=700,
        )
        self.assertEqual(settings.base_dimensions(), (1400, 700))
        self.assertEqual(settings.display_dimensions(), (700, 350))

    def test_global_font_and_canvas_are_applied_at_renderer_boundary(self) -> None:
        fig = go.Figure(go.Scatter(x=[1, 2], y=[2, 3]))
        fig.update_layout(title="Example", xaxis_title="X", yaxis_title="Y")
        fig.add_annotation(x=1, y=2, text="Note")
        settings = ChartPresentationSettings(
            canvas=CANVAS_SQUARE,
            font_size=18,
            width_percent=100,
        )
        apply_chart_presentation(fig, settings)
        self.assertEqual(fig.layout.width, 900)
        self.assertEqual(fig.layout.height, 900)
        self.assertEqual(fig.layout.font.size, 18)
        self.assertEqual(fig.layout.title.font.size, 21)
        self.assertEqual(fig.layout.xaxis.tickfont.size, 18)
        self.assertEqual(fig.layout.yaxis.title.font.size, 18)
        self.assertEqual(fig.layout.annotations[0].font.size, 18)

    def test_auto_canvas_does_not_force_dimensions(self) -> None:
        fig = go.Figure(go.Bar(x=["A"], y=[1]))
        apply_chart_presentation(fig, ChartPresentationSettings(canvas=CANVAS_AUTO, font_size=15))
        self.assertIsNone(fig.layout.width)
        self.assertIsNone(fig.layout.height)
        self.assertEqual(fig.layout.font.size, 15)

    def test_export_configuration_preserves_local_options(self) -> None:
        settings = ChartPresentationSettings(
            canvas=CANVAS_WIDE,
            export_scale=3,
        )
        config = merge_plotly_config({"displaylogo": False, "scrollZoom": True}, settings)
        self.assertFalse(config["displaylogo"])
        self.assertTrue(config["scrollZoom"])
        self.assertEqual(
            config["toImageButtonOptions"],
            {"format": "png", "scale": 3, "width": 1280, "height": 720},
        )

    def test_runtime_installation_is_global_not_page_specific(self) -> None:
        ui_source = UI_CONTRACT.read_text(encoding="utf-8")
        presentation_source = PRESENTATION_MODULE.read_text(encoding="utf-8")
        self.assertIn("install_global_chart_presentation()", ui_source)
        self.assertIn("st.plotly_chart", presentation_source)
        self.assertNotIn("Use global canvas settings", presentation_source)
        self.assertNotIn("render_temperature", presentation_source)
        self.assertNotIn("render_solar", presentation_source)
        self.assertNotIn("render_compare", presentation_source)


if __name__ == "__main__":
    unittest.main()
