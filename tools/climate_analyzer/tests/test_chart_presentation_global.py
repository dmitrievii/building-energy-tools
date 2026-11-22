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
    DEFAULT_FONT_SIZE, KEY_FONT, ensure_default_state, reset_state, settings_from_state,
    apply_chart_presentation,
    BACKGROUND_TRANSPARENT, BACKGROUND_WHITE, KEY_BACKGROUND, TRANSPARENT_COLOR,
    merge_plotly_config,
)


ROOT = Path(__file__).resolve().parents[1]
UI_CONTRACT = ROOT / "epw_climate_analyzer" / "ui_contract.py"
PRESENTATION_MODULE = ROOT / "epw_climate_analyzer" / "chart_presentation.py"


class GlobalChartPresentationTests(unittest.TestCase):
    def test_default_font_is_18_and_existing_custom_choice_is_preserved(self) -> None:
        self.assertEqual(DEFAULT_FONT_SIZE, 18)
        self.assertEqual(ChartPresentationSettings().font_size, 18)
        state = {}
        ensure_default_state(state)
        self.assertEqual(state[KEY_FONT], 18)
        state[KEY_FONT] = 14
        ensure_default_state(state)
        self.assertEqual(settings_from_state(state).font_size, 14)
        reset_state(state)
        self.assertEqual(state[KEY_FONT], 18)

    def test_global_background_default_reset_and_persistence(self) -> None:
        state = {}
        ensure_default_state(state)
        self.assertEqual(state[KEY_BACKGROUND], BACKGROUND_WHITE)
        state[KEY_BACKGROUND] = BACKGROUND_TRANSPARENT
        ensure_default_state(state)
        self.assertTrue(settings_from_state(state).transparent)
        reset_state(state)
        self.assertFalse(settings_from_state(state).transparent)
        state[KEY_BACKGROUND] = "invalid"
        self.assertEqual(settings_from_state(state).background, BACKGROUND_WHITE)

    def test_background_applies_to_cartesian_polar_3d_subplots_and_legends(self) -> None:
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=1, cols=4, specs=[[{"type":"xy"},{"type":"polar"},
                                                    {"type":"polar"},{"type":"scene"}]])
        fig.add_trace(go.Scatter(x=[1,2], y=[2,3], fill="tozeroy",
                                 fillcolor="rgba(20,30,40,0.4)"), row=1,col=1)
        fig.add_trace(go.Barpolar(theta=[0,90],r=[1,2]),row=1,col=2)
        fig.add_trace(go.Scatterpolar(theta=[0,90],r=[2,3]),row=1,col=3)
        fig.add_trace(go.Scatter3d(x=[0,1],y=[0,1],z=[0,1]),row=1,col=4)
        fig.update_layout(legend=dict(bgcolor="pink"),legend2=dict(bgcolor="blue"))
        fig.add_shape(type="rect", x0=0,x1=1,y0=0,y1=1,fillcolor="yellow")
        for choice,color in ((BACKGROUND_TRANSPARENT,TRANSPARENT_COLOR),(BACKGROUND_WHITE,"white")):
            apply_chart_presentation(fig, ChartPresentationSettings(background=choice))
            self.assertEqual(fig.layout.paper_bgcolor,color)
            self.assertEqual(fig.layout.plot_bgcolor,color)
            self.assertEqual(fig.layout.polar.bgcolor,color)
            self.assertEqual(fig.layout.polar2.bgcolor,color)
            self.assertEqual(fig.layout.scene.bgcolor,color)
            self.assertEqual(fig.layout.scene.zaxis.backgroundcolor,color)
            self.assertEqual(fig.layout.legend.bgcolor,color)
            self.assertEqual(fig.layout.legend2.bgcolor,color)
            self.assertEqual(fig.data[0].fillcolor,"rgba(20,30,40,0.4)")
            self.assertEqual(fig.layout.shapes[0].fillcolor,"yellow")
        implicit=go.Figure(go.Barpolar(theta=[0],r=[1]))
        apply_chart_presentation(implicit,ChartPresentationSettings(background=BACKGROUND_TRANSPARENT))
        self.assertEqual(implicit.layout.polar.bgcolor,TRANSPARENT_COLOR)

    def test_turntable_is_default_for_all_3d_scenes_and_preserves_camera(self) -> None:
        from plotly.subplots import make_subplots
        fig=make_subplots(rows=1,cols=3,specs=[[{"type":"scene"},{"type":"scene"},{"type":"xy"}]])
        fig.add_trace(go.Surface(z=[[0,1],[2,3]]),row=1,col=1)
        fig.add_trace(go.Scatter3d(x=[0,1],y=[0,1],z=[0,1]),row=1,col=2)
        fig.add_trace(go.Scatter(x=[0,1],y=[1,2]),row=1,col=3)
        fig.update_layout(dragmode="select",scene=dict(dragmode="orbit",uirevision="dome",
            camera=dict(eye=dict(x=2,y=-3,z=1),center=dict(x=0,y=0,z=.1),projection=dict(type="orthographic"))),
            scene2=dict(dragmode="pan"))
        apply_chart_presentation(fig,ChartPresentationSettings())
        self.assertEqual(fig.layout.dragmode,"select")
        for scene in (fig.layout.scene,fig.layout.scene2):
            self.assertEqual(scene.dragmode,"turntable")
            self.assertEqual(scene.camera.up.to_plotly_json(),{"x":0,"y":0,"z":1})
        self.assertEqual(fig.layout.scene.camera.eye.to_plotly_json(),{"x":2,"y":-3,"z":1})
        self.assertEqual(fig.layout.scene.camera.center.z,.1)
        self.assertEqual(fig.layout.scene.camera.projection.type,"orthographic")
        self.assertEqual(fig.layout.scene.uirevision,"dome")
        implicit=go.Figure(go.Mesh3d(x=[0,1,0],y=[0,0,1],z=[0,1,0]))
        apply_chart_presentation(implicit,ChartPresentationSettings())
        self.assertEqual(implicit.layout.scene.dragmode,"turntable")
        two_d=go.Figure(go.Scatter(x=[0,1],y=[1,2]))
        apply_chart_presentation(two_d,ChartPresentationSettings())
        self.assertNotIn("scene",two_d.layout.to_plotly_json())

    def test_transparent_export_preserves_png_and_svg_and_rejects_jpeg(self) -> None:
        settings=ChartPresentationSettings(background=BACKGROUND_TRANSPARENT)
        for fmt,expected in (("jpeg","png"),("png","png"),("svg","svg")):
            result=merge_plotly_config({"toImageButtonOptions":{"format":fmt}},settings)
            self.assertEqual(result["toImageButtonOptions"]["format"],expected)

    def test_additional_global_controls_preserve_data_and_limit_axis_rotation(self) -> None:
        fig=go.Figure(go.Scatter(x=[1,2],y=[3,4],mode="lines",line=dict(width=3)))
        fig.update_layout(title="Title",yaxis_title="Temperature [°C]",xaxis_title="Time")
        apply_chart_presentation(fig,ChartPresentationSettings(show_title=False,show_legend=False,
            show_grid=False,line_scale=2.,axis_title="Temperature [°C]",axis_min=-5,axis_max=40))
        self.assertEqual(fig.layout.title.text,"")
        self.assertFalse(fig.layout.showlegend)
        self.assertFalse(fig.layout.xaxis.showgrid)
        self.assertEqual(fig.data[0].line.width,6.)
        self.assertEqual(tuple(fig.layout.yaxis.range),(-5,40))
        self.assertEqual(tuple(fig.data[0].y),(3,4))
        for compass in (False,True):
            fig=go.Figure(go.Barpolar(theta=[0,90],r=[1,2]))
            fig.update_layout(meta={"compass_polar":compass},polar=dict(angularaxis=dict(rotation=90)))
            apply_chart_presentation(fig,ChartPresentationSettings(north_rotation=30))
            self.assertEqual(fig.layout.polar.angularaxis.rotation,60 if compass else 90)
        cfg=merge_plotly_config(None,ChartPresentationSettings(export_format="SVG"))
        self.assertEqual(cfg["toImageButtonOptions"]["format"],"svg")

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

    def test_presentation_does_not_create_marker_or_colorbar_on_plain_scatter(self) -> None:
        fig = go.Figure(
            go.Scatter(
                x=["Jan", "Feb", "Mar"],
                y=[1.0, 2.0, 3.0],
                mode="lines+markers",
                name="Mean",
            )
        )
        before = fig.to_plotly_json()["data"][0]
        self.assertNotIn("marker", before)

        apply_chart_presentation(
            fig,
            ChartPresentationSettings(canvas=CANVAS_AUTO, font_size=20),
        )

        after = fig.to_plotly_json()["data"][0]
        self.assertNotIn("marker", after)
        self.assertNotIn("colorbar", after)

    def test_existing_trace_colorbar_font_is_updated_without_changing_visibility(self) -> None:
        fig = go.Figure(
            go.Scatter(
                x=[1, 2],
                y=[2, 3],
                mode="markers",
                marker=dict(
                    color=[1.0, 2.0],
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="Scale"),
                ),
            )
        )
        apply_chart_presentation(
            fig,
            ChartPresentationSettings(canvas=CANVAS_AUTO, font_size=19),
        )
        marker = fig.to_plotly_json()["data"][0]["marker"]
        self.assertTrue(marker["showscale"])
        self.assertEqual(marker["colorbar"]["tickfont"]["size"], 19)
        self.assertEqual(marker["colorbar"]["title"]["font"]["size"], 19)

    def test_bottom_horizontal_legend_reserves_axis_and_font_dependent_space(self) -> None:
        for size in (12,18,26):
            fig = go.Figure([go.Bar(x=["Jan","Feb"],y=[1,2],name=n) for n in ("GHI","DHI","DNI")])
            fig.update_layout(xaxis_title="Month", margin=dict(b=45),
                              legend=dict(orientation="h", y=-.16))
            apply_chart_presentation(fig, ChartPresentationSettings(font_size=size))
            self.assertTrue(fig.layout.xaxis.automargin)
            self.assertGreaterEqual(fig.layout.xaxis.title.standoff,size)
            self.assertEqual(fig.layout.legend.yref,"container")
            self.assertEqual(fig.layout.legend.yanchor,"bottom")
            self.assertGreater(fig.layout.margin.b,45)
            self.assertEqual(fig.layout.font.size,size)
        fig=go.Figure(go.Scatter(x=[1,2],y=[2,3],name="Internal"))
        fig.update_layout(legend=dict(orientation="h",y=.8))
        apply_chart_presentation(fig,ChartPresentationSettings())
        self.assertEqual(fig.layout.legend.y,.8)

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
