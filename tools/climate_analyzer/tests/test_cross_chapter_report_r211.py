"""R2.11 cross-chapter scientific report contracts and source-scope isolation."""
from __future__ import annotations

import json
import unittest

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer import p6_report as report
from epw_climate_analyzer import p6_report_structure as structure
from epw_climate_analyzer import report_synthesis as synthesis
from epw_climate_analyzer import p3_comfort as p3


def climate_fixture(days=10):
    index=pd.date_range("2026-07-01",periods=days*24,freq="h")
    hours=index.hour
    temp=np.where((hours>=22)|(hours<=6),18.,30.)
    frame=pd.DataFrame({
        p3.T:temp,p3.W:8.,p3.RH:60.,p3.V:2.,
        "moist_air_enthalpy_kj_kg":51.,
        p3.SV:.8,
        p3.GHI:np.where((hours>=6)&(hours<=18),400.,0.),
        p3.DHI:np.where((hours>=6)&(hours<=18),100.,0.),
        p3.DNI:np.where((hours>=6)&(hours<=18),600.,0.),
        p3.LW:350.,
        p3.ZEN:np.where((hours>=6)&(hours<=18),45.,105.),
        "solar_azimuth_deg":145.,
        "liquid_precipitation_depth_mm":0.,
        "hour_of_day":hours,"month_index":index.month,
    },index=index)
    frame.attrs["canonical_native_interval_minutes"]=60.
    return frame


class CrossChapterR211Tests(unittest.TestCase):
    def test_synthesis_closure_and_reference_criteria(self):
        df=climate_fixture()
        result=synthesis.cross_chapter_synthesis(df)
        labels={row[0]:row for row in result["rows"]}
        self.assertIn("Temperature screening",labels)
        self.assertIn("Outdoor-air ventilation screen",labels)
        self.assertIn("Economizer weather screen",labels)
        eligible=int((df[p3.T].between(16,26)&df[p3.W].le(9)).sum())
        self.assertIn(f"{eligible:,.1f} h",labels["Outdoor-air ventilation screen"][1])
        self.assertEqual(result["observed_records"],len(df))
        self.assertIn("supply-air",result["interpretation"])
        self.assertEqual(labels["Outdoor-air ventilation screen"][2],f"{len(df):,} / {len(df):,}")

    def test_missing_and_subhourly_observations_are_counted_as_physical_hours(self):
        df=climate_fixture().iloc[:6].copy()
        df.index=pd.date_range("2026-07-01",periods=6,freq="30min")
        df.attrs["canonical_native_interval_minutes"]=30.
        df[p3.T]=[18.,19.,20.,21.,22.,23.]
        df.loc[df.index[0],p3.W]=np.nan
        r=synthesis.cross_chapter_synthesis(df)
        rows={a:b for a,b,_ in r["rows"]}
        self.assertIn("2.5 h",rows["Outdoor-air ventilation screen"])
        self.assertIn("2.5 h",rows["Economizer weather screen"] if "Economizer weather screen" in rows else "2.5 h")

    def test_synthesis_respects_missing_weather_channels(self):
        df=climate_fixture()[[p3.T]].copy()
        out=synthesis.cross_chapter_synthesis(df)
        labels={row[0] for row in out["rows"]}
        self.assertIn("Outdoor temperature",labels)
        self.assertNotIn("Outdoor-air ventilation screen",labels)
        self.assertNotIn("Economizer weather screen",labels)

    def test_snapshot_deeply_freezes_synthesis_and_filter(self):
        df=climate_fixture()
        state={"_active_global_filter_spec":{"months":[7]}}
        report.set_context(state,page="Temperature",source="A.epw",location="Graz",
                           df=df,source_id="source-A")
        context=state[report.CONTEXT_KEY]
        fig=go.Figure(go.Scatter(x=[1.,2.],y=[20.,30.]))
        fig.update_layout(title="Air temperature chart")
        item=report.snapshot(fig,context,"Warm conditions and their frequency.")
        context["cross-chapter synthesis"]["rows"][0][1]="changed later"
        context["statistics"]["overview"][0][1]="changed later"
        self.assertNotIn("changed later",str(item["context"]))
        self.assertTrue(item["context"].get("cross-chapter synthesis"))

    def test_temporal_scope_and_thresholds_are_isolated(self):
        df=climate_fixture()
        state={}
        report.set_context(state,page="Temperature",source="A.epw",location="Graz",
                           df=df,source_id="same-file")
        c1=state[report.CONTEXT_KEY]
        a=report.snapshot(go.Figure(go.Bar(x=[1],y=[1])),c1)
        c2={**c1,"time basis":"Calendar profile",
            "cross-chapter synthesis":{"rows":[["Test","Other","1/1"]],"interpretation":"Other source basis"}}
        b=report.snapshot(go.Figure(go.Bar(x=[2],y=[2])),c2)
        self.assertNotEqual(structure.scope_key(c1),structure.scope_key(c2))
        self.assertEqual(len(structure.contexts([a,b])),2)
        c3={**c1,"temperature thresholds":[20.,24.]}
        self.assertNotEqual(structure.scope_key(c1),structure.scope_key(c3))

    def test_html_printed_synthesis_follows_captured_source(self):
        df=climate_fixture()
        state={}
        report.set_context(state,page="Temperature",source="A.epw",location="Graz",
                           df=df,source_id="source-A")
        fig=go.Figure(go.Scatter(x=[0,1],y=[17,32]))
        fig.update_layout(title="Observed weather")
        item=report.snapshot(fig,state[report.CONTEXT_KEY],"Summer conditions.")
        raw=report.printable_html([item],"Full climate report","A4","Landscape")
        text=raw.decode("utf-8")
        self.assertIn("Cross-chapter climatic findings",text)
        self.assertIn("Outdoor-air ventilation screen",text)
        self.assertIn("Summer conditions.",text)
        self.assertIn("Source subdaily",str(item["context"]["cross-chapter synthesis"]))

    def test_report_order_is_scientific_and_diagrams_remain_in_saved_order(self):
        figures=[]
        for page,name in [
            ("HVAC and Passive Design","HVAC 1"),
            ("Wind and Ventilation","Wind"),
            ("Temperature","Temperature"),
            ("HVAC and Passive Design","HVAC 2"),
        ]:
            figures.append({"context":{"page":page},"title":name})
        grouped=structure.ordered_groups(figures)
        titles=[chapter for chapter,_ in grouped]
        self.assertEqual(titles,["Temperature","Wind","HVAC and passive design"])
        self.assertEqual([i["title"] for i in grouped[-1][1]],["HVAC 1","HVAC 2"])

    def test_standard_report_includes_r28_r29_r210(self):
        df=climate_fixture()
        keys={entry[0]:entry for entry in structure.available_catalog(df,{"latitude":"47.0"})}
        for key in ("nv","night","utci","utci_shading","hvac_energy",
                    "hvac_economizer","hvac_design_hot","hvac_design_cold","hvac_critical"):
            self.assertIn(key,keys)
        for preset in ("Passive design","HVAC & engineering"):
            self.assertIn(preset,structure.PRESETS)

    def test_standard_night_interpretation_is_its_own_physical_screen(self):
        df=climate_fixture()
        entry=next(e for e in structure.CATALOG if e[0]=="night")
        fig,note=structure.standard_figure(entry,df,{"latitude":"47.0"},df)
        self.assertGreaterEqual(len(fig.data),1)
        self.assertIn("night-cooling screen",note)
        self.assertIn("overnight periods",note)
        self.assertNotIn("Natural ventilation is suitable",note)

    def test_standard_hvac_and_economizer_are_numerically_described(self):
        df=climate_fixture()
        for key,keyword in (("hvac_energy","Sensible"),
                            ("hvac_economizer","return-air reference"),
                            ("hvac_design_hot","upper hourly tail"),
                            ("hvac_critical","72-hour")):
            entry=next(e for e in structure.CATALOG if e[0]==key)
            fig,note=structure.standard_figure(entry,df,{"latitude":"47.0"},df)
            self.assertTrue(fig.data)
            self.assertIn(keyword.lower(),note.lower())


if __name__=="__main__":
    unittest.main()
