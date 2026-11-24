"""R2: graph-to-interpretation identity across website, report, PDF/HTML, Atlas.

The scientific narrative is generated once for each displayed graph and
replayed verbatim by all exports. No recomputation on formatting/export.
"""
from __future__ import annotations

import io
import unittest

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image

from epw_climate_analyzer.figure_interpretation_contract import (
    BINDING_KEY,bind_figure_interpretation,validate_figure_interpretation,
)
from epw_climate_analyzer.p6_report import snapshot,printable_html,pdf_report
from epw_climate_analyzer.p6_report_structure import standard_figure,CATALOG
from epw_climate_analyzer.p66_catalogue import catalogue,FULL
from epw_climate_analyzer.p66_render import make_figure


class FigureInterpretationContractR2(unittest.TestCase):
    def setUp(self):
        idx=pd.date_range("2026-06-01",periods=72,freq="h")
        self.frame=pd.DataFrame({
            "dry_bulb_temperature_c":pd.Series(range(72),index=idx,dtype=float)*.1+10.,
            "dew_point_temperature_c":pd.Series(range(72),index=idx,dtype=float)*.05+2.,
            "relative_humidity_pct":50.,
            "humidity_ratio_g_kg":6.,
            "hour_of_day":idx.hour,
            "month_index":idx.month,
        },index=idx)
        self.frame.attrs["canonical_native_interval_minutes"]=60.

    def test_binding_reuses_figure_and_preserves_existing_physics_metadata(self):
        fig=go.Figure(go.Scatter(x=[0,1],y=[10,20]))
        fig.update_layout(meta={"physical_model":"source observations","reference_temperature":20.})
        self.assertIs(bind_figure_interpretation(fig,"Scientific text."),fig)
        before=dict(fig.layout.meta)
        bind_figure_interpretation(fig,"Scientific text.")
        self.assertEqual(dict(fig.layout.meta),before)
        self.assertEqual(fig.layout.meta["physical_model"],"source observations")
        self.assertEqual(fig.layout.meta["reference_temperature"],20.)
        self.assertTrue(validate_figure_interpretation(fig,"Scientific text.",require_binding=True))
        self.assertEqual(len(fig.layout.meta[BINDING_KEY]),64)
        with self.assertRaises(ValueError):
            bind_figure_interpretation(fig,"A revised interpretation.")
        with self.assertRaises(ValueError):
            validate_figure_interpretation(fig,"A revised interpretation.")
        self.assertEqual(list(fig.data[0].y),[10,20])

    def test_snapshot_freezes_exact_interpretation_not_recomputed_on_export(self):
        text="Dew point reaches saturation after cooling at fixed vapour content and pressure."
        fig=go.Figure(go.Scatter(x=["June"],y=[11.],name="Dew point"))
        bind_figure_interpretation(fig,text)
        item=snapshot(fig,{"page":"Humidity and Psychrometrics",
                           "source":"fixture","location":"test"},text)
        self.assertEqual(item["interpretation"],text)
        self.assertTrue(validate_figure_interpretation(pio.from_json(item["figure"]),text,require_binding=True))
        html=printable_html([item],"Test","A4","Landscape",use_osm=False).decode("utf-8")
        self.assertIn(text,html)
        self.assertEqual(html.count(f"<p>{text}</p>"),1)
        modified=dict(item,interpretation="Reworded independently.")
        with self.assertRaises(ValueError):
            printable_html([modified],"Test","A4","Landscape",use_osm=False)
        with self.assertRaises(ValueError):
            pdf_report([modified],"Test","A4","Landscape",image_renderer=self.image_renderer)
        self.assertTrue(pdf_report([item],"Test","A4","Landscape",
                                   image_renderer=self.image_renderer).startswith(b"%PDF"))

    @staticmethod
    def image_renderer(fig):
        width=max(1,int(fig.layout.width or 400))
        height=max(1,int(fig.layout.height or 250))
        output=io.BytesIO()
        Image.new("RGB",(width,height),"white").save(output,format="PNG")
        return output.getvalue()

    def test_standard_report_and_atlas_bind_exact_narrative(self):
        entry=next(x for x in CATALOG if x[0]=="temperature_profile")
        fig,note=standard_figure(entry,self.frame,{})
        self.assertTrue(note)
        self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))
        copied=pio.from_json(pio.to_json(fig))
        self.assertTrue(validate_figure_interpretation(copied,note,require_binding=True))
        candidates=[x for x in catalogue(self.frame,{},FULL)
                    if x.status=="available" and x.column=="dew_point_temperature_c"
                    and x.kind=="time_series" and x.args==("Hourly","Observed values")]
        self.assertTrue(candidates)
        atlas_fig,atlas_note=make_figure(candidates[0],self.frame,{})
        self.assertTrue(atlas_note)
        self.assertTrue(validate_figure_interpretation(atlas_fig,atlas_note,require_binding=True))
        self.assertIn("dew point",atlas_note.lower())

    def test_legacy_saved_charts_remain_replayable(self):
        historical=go.Figure(go.Bar(x=["Jun"],y=[2.]))
        self.assertFalse(validate_figure_interpretation(historical,"Original text"))
        with self.assertRaises(ValueError):
            validate_figure_interpretation(historical,"Original text",require_binding=True)


if __name__=="__main__":
    unittest.main()
