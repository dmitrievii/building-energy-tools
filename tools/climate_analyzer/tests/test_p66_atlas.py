"""P6.6 catalogue and export qualification: deterministic IDs and explicit coverage."""
import csv
import io
import unittest
import zipfile
import numpy as np
import pandas as pd
from PIL import Image
from epw_climate_analyzer import p66_catalogue as c
from epw_climate_analyzer.p66_render import make_figure,NotApplicable
from epw_climate_analyzer.p66_export import generate_atlas,manifest_csv,PDF_MODES

class AtlasTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2026-01-01",periods=96,freq="h")
        t=np.sin(np.arange(len(idx))*2*np.pi/24)*2+18.
        df=pd.DataFrame({c.T:t,c.RH:60.,c.W:7.,c.V:2.,c.WD:270.,c.P:np.where(np.arange(len(idx))%24==0,1.,0.)},index=idx)
        df["hour_of_day"]=idx.hour;df["month_index"]=idx.month;df.attrs["canonical_native_interval_minutes"]=60.
        return df
    def test_full_catalogue_explicit_aggregations(self):
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        self.assertEqual(len(rows),len({d.id for d in rows}))
        temp=[d for d in rows if d.column==c.T and d.status=="available"]
        for kind in ("profile","percentile"):
            self.assertEqual({d.args[0] for d in temp if d.kind==kind},set(c.PERIODS))
        self.assertEqual(len([d for d in temp if d.kind=="heatmap"]),13)
        self.assertEqual(len([d for d in temp if d.kind=="heatmap" and d.args[0]=="day"]),1)
        self.assertEqual(len([d for d in temp if d.kind=="diurnal"]),12)
        self.assertEqual(len([d for d in temp if d.kind=="duration"]),4)
        self.assertGreater(len(rows),len(c.catalogue(df,{},c.REP)))
        self.assertTrue(any(d.kind=="not_registered" for d in rows))
    def test_monthly_source_no_hourly_invention(self):
        df=self.fixture().iloc[[0]].copy();df.attrs["canonical_native_resolution"]="monthly"
        rows=c.catalogue(df,{},c.FULL)
        self.assertFalse(any(d.status=="available" and d.kind in ("heatmap","duration","degree","utci","nv_special","wind_mean") for d in rows))
        self.assertTrue(any(d.kind=="native" and d.status=="available" for d in rows))
    def test_core_chart_families_execute(self):
        df=self.fixture();rows=[d for d in c.catalogue(df,{},c.FULL) if d.status=="available"]
        types=("profile","percentile","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude","total","degree","temp_threshold","temp_events","day_indicators","wind_mean","wind_classes","wetdry","rolling","cumulative","freeze_days","eligibility_map","eligibility_total","nv_special","design_tail","tail_curve","critical_windows","correlation","joint")
        cache={}
        for k in types:
            rows_k=[d for d in rows if d.kind==k]
            self.assertTrue(rows_k,k)
            for d in rows_k[:1]:
                with self.subTest(kind=k):
                    fig,note=make_figure(d,df,{},df,cache)
                    self.assertTrue(len(fig.data)>0)
                    self.assertTrue(note)
    def test_export_all_outcomes_and_pdf_layouts(self):
        df=self.fixture();rows=c.catalogue(df,{},c.REP)
        selected=[next(d for d in rows if d.kind=="profile" and d.status=="available"),
                  next(d for d in rows if d.kind=="not_registered")]
        context={"source":"Test.epw","location":"Synthetic fixture"}
        def png(fig):
            result=io.BytesIO();Image.new("RGB",(int(fig.layout.width),int(fig.layout.height)),"white").save(result,format="PNG");return result.getvalue()
        for mode in PDF_MODES:
            data,manifest,metadata=generate_atlas(selected,df,context,mode=mode,image_renderer=png,per_page=2)
            self.assertEqual(metadata["counts"]["generated"],1)
            self.assertEqual(metadata["counts"]["unsupported"],1)
            if mode=="Single PDF":self.assertTrue(data.startswith(b"%PDF"))
            else:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    self.assertIn("coverage.csv",z.namelist())
                    self.assertIn("atlas_metadata.json",z.namelist())
                    self.assertTrue(any(n.endswith(".html" if "HTML" in mode else ".pdf") for n in z.namelist()))
    def test_complete_html_atlas_exceeds_pdf_batch_limit(self):
        from unittest.mock import patch
        import plotly.graph_objects as go
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        selected=[d for d in rows if d.status=="available"][:61]
        self.assertEqual(len(selected),61)
        selected.append(next(d for d in rows if d.kind=="not_registered"))
        f=go.Figure(go.Scatter(x=[1,2],y=[3,4]))
        with patch("epw_climate_analyzer.p66_export.make_figure",return_value=(f,"Interpretation")) as render:
            data,manifest,metadata=generate_atlas(selected,df,{},mode=PDF_MODES[2])
        self.assertEqual(render.call_count,61)
        self.assertEqual(metadata["counts"]["generated"],61)
        self.assertEqual(metadata["counts"]["unsupported"],1)
        self.assertEqual(len(manifest),62)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn("index.html",z.namelist())
            self.assertEqual(z.namelist().count("plotly.min.js"),1)
            index=z.read("index.html").decode()
            for name in metadata["html_files"]:
                self.assertIn(name,index)
                self.assertIn("src='plotly.min.js'",z.read(name).decode())
            self.assertEqual(sum(z.read(n).count(b"Plotly.newPlot(") for n in metadata["html_files"]),61)

    def test_batches_cover_all_admitted_and_guard(self):
        from unittest.mock import patch
        from epw_climate_analyzer.p66_export import catalogue_batches
        from epw_climate_analyzer.p66_memory import require_headroom,MIB
        rows=c.catalogue(self.fixture(),{},c.FULL)
        batches=catalogue_batches(rows,20)
        self.assertEqual([d.id for batch in batches for d in batch],
                         [d.id for d in rows if d.status=="available"])
        self.assertTrue(all(len(batch)<=20 for batch in batches))
        with patch("epw_climate_analyzer.p66_memory.container_memory",return_value=(490*MIB,512*MIB)):
            with self.assertRaisesRegex(MemoryError,"Container memory pressure"):require_headroom()
        with patch("epw_climate_analyzer.p66_export.require_headroom",return_value=None):
            with self.assertRaisesRegex(ValueError,"bounded export batch"):
                generate_atlas([d for d in rows if d.status=="available"][:51],self.fixture(),{})
        with patch("epw_climate_analyzer.p66_export.require_headroom",side_effect=MemoryError("low memory")):
            with self.assertRaises(MemoryError):generate_atlas(batches[0],self.fixture(),{})

    def test_zero_event_timeline_and_distribution_status(self):
        df=self.fixture();rows=c.catalogue(df,{},c.FULL)
        timeline=next(d for d in rows if d.kind=="temp_events" and d.args==("max",True,"timeline"))
        dist=next(d for d in rows if d.kind=="temp_events" and d.args==("max",True,"duration"))
        fig,note=make_figure(timeline,df,{},df)
        self.assertEqual(len(fig.data),2)
        with self.assertRaises(NotApplicable):make_figure(dist,df,{},df)

if __name__=="__main__":unittest.main()
