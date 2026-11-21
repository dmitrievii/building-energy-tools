"""P6 regression: actual snapshots, PDF/HTML export and complete-day dashboard inputs."""
import io
import json
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from PIL import Image
from epw_climate_analyzer import p6_dashboard as d
from epw_climate_analyzer import p6_report as r

class P6Tests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2025-06-01",periods=72,freq="h")
        df=pd.DataFrame({d.T:18.,d.W:7.,d.RH:50.,d.GHI:100.,d.V:2.,d.P:1.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_metrics_missing_coverage(self):
        df=self.fixture();df.loc[df.index[0],d.GHI]=np.nan
        a=d.climate_metrics(df)
        self.assertAlmostEqual(a["temperature"],18.)
        self.assertAlmostEqual(a["ghi"],7.1)
        self.assertEqual(a["precipitation"],72.)
        self.assertTrue(np.isnan(d.climate_metrics(df.drop(columns=d.P))["precipitation"]))

    def test_design_nv_and_complete_days(self):
        df=self.fixture()
        ledger,degree=d.design_ledgers(df,heat_i=20,heat_l=19)
        self.assertEqual(ledger["Natural ventilation"].sum(),72.)
        self.assertAlmostEqual(degree.iloc[:,0].sum(),6.)
        gap=df.drop(df.index[3])
        ledger,degree=d.design_ledgers(gap,heat_i=20,heat_l=19)
        self.assertEqual(ledger["Natural ventilation"].sum(),71.)
        self.assertAlmostEqual(degree.iloc[:,0].sum(),4.)
        self.assertNotIn("Natural ventilation",d.design_ledgers(df.drop(columns=d.W))[0])

    def test_snapshot_immutable_dedup_and_html(self):
        state={};df=self.fixture()
        r.set_context(state,page="Temperature",source="Weather.epw",location="Test",df=df)
        fig=go.Figure(go.Scatter(x=[0,1],y=[10,20]));fig.update_layout(title="Example <test>")
        item=r.snapshot(fig,state[r.CONTEXT_KEY],"A < B")
        fig.data[0].y=[0,0];state[r.CONTEXT_KEY]["source"]="Other.epw"
        self.assertEqual(json.loads(item["figure"])["data"][0]["y"],[10,20])
        self.assertEqual(item["context"]["source"],"Weather.epw")
        entries,_=r.add_snapshot([],item)
        self.assertEqual(len(r.add_snapshot(entries,item)[0]),1)
        html=r.printable_html(entries,"Test","A3","Landscape").decode("utf-8")
        self.assertIn("@page {size:A3 landscape",html)
        self.assertIn("A &lt; B",html)
        self.assertIn("Example &lt;test&gt;",html)
        self.assertIn("Plotly.newPlot",html)
        self.assertEqual(r._script_json("</script>"),'"\\u003c/script\\u003e"')

    def test_pdf_geometry_and_fail_closed(self):
        fig=go.Figure(go.Bar(x=["A","B"],y=[1,2]))
        item=r.snapshot(fig,{"source":"Test.epw"},"Interpretation")
        def renderer(_):
            b=io.BytesIO();Image.new("RGB",(720,450),"white").save(b,format="PNG");return b.getvalue()
        for format in ("A4","A3"):
            for orientation in ("Landscape","Portrait"):
                pdf=r.pdf_report([item], "Test",format,orientation,image_renderer=renderer)
                self.assertTrue(pdf.startswith(b"%PDF"))
                self.assertIn(b"/MediaBox",pdf)
        def bad(_):raise ValueError("No render")
        with self.assertRaises(RuntimeError):r.pdf_report([item],"Test","A4","Landscape",image_renderer=bad)

    def test_static_plotly_pdf_smoke(self):
        fig=go.Figure(go.Scatter(x=[1,2],y=[2,3]))
        item=r.snapshot(fig,{"source":"Synthetic fixture"},"Static renderer smoke")
        self.assertTrue(r.pdf_report([item],"Smoke","A4","Landscape").startswith(b"%PDF"))

    def test_real_streamlit_capture_survives_reruns_and_navigation(self):
        from streamlit.testing.v1 import AppTest
        script = """
import streamlit as st
import plotly.graph_objects as go
from epw_climate_analyzer import p6_report as r
from epw_climate_analyzer.chart_presentation import install_global_chart_presentation
page=st.radio("Page",["Temperature","Report"],key="page")
install_global_chart_presentation(st)
if page=="Report":
    st.session_state.pop(r.CONTEXT_KEY,None)
    r.render_report()
else:
    r.set_context(st.session_state,page=page,source="Test.epw",location="Test")
    # Mirror the production chart key: changes on every rerun.
    st.session_state["counter"]=st.session_state.get("counter",0)+1
    value=st.number_input("Value",value=12.,key="value")
    fig=go.Figure(go.Scatter(x=[0,1],y=[value,value+1]))
    fig.update_layout(title="Actual diagram")
    st.session_state[r.INTERPRETATION_KEY]="Actual interpretation"
    st.plotly_chart(fig,key="plot_"+str(st.session_state["counter"]))
"""
        app=AppTest.from_string(script,default_timeout=30).run()
        self.assertFalse(app.exception)
        capture=lambda a:next(b for b in a.button if b.label=="Add to report")
        first_key=capture(app).key
        capture(app).click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state[r.REPORT_KEY]),1)
        self.assertEqual(capture(app).key,first_key)
        self.assertEqual(json.loads(app.session_state[r.REPORT_KEY][0]["figure"])["data"][0]["y"],[12.,13.])
        self.assertEqual(app.session_state[r.REPORT_KEY][0]["interpretation"],"Actual interpretation")
        capture(app).click().run()
        self.assertEqual(len(app.session_state[r.REPORT_KEY]),1)
        app.number_input(key="value").set_value(20.).run()
        capture(app).click().run()
        self.assertEqual(len(app.session_state[r.REPORT_KEY]),2)
        app.radio(key="page").set_value("Report").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state[r.REPORT_KEY]),2)
        self.assertFalse(any("Your report is empty" in x.value for x in app.info))
        self.assertTrue(any("2 captured diagrams" in x.value for x in app.caption))
        app.radio(key="page").set_value("Temperature").run()
        self.assertEqual(len(app.session_state[r.REPORT_KEY]),2)

    def test_routes(self):
        from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES
        from epw_climate_analyzer.historical_capabilities import available_historical_pages
        root=Path(__file__).resolve().parents[1]
        self.assertIn("Report",NAVIGATION_PAGES)
        self.assertIn("Report",available_historical_pages(self.fixture()))
        app=(root/"app.py").read_text("utf-8")
        self.assertGreaterEqual(app.count("render_report()"),3)
        self.assertIn("select_overview(df,render_plot",app)
        for file in ("source_parity_ui.py","source_parity_monthly_canonical.py"):
            s=(root/"epw_climate_analyzer"/file).read_text("utf-8")
            self.assertIn("render_report()",s)
            self.assertIn("select_overview(",s)
        s=(root/"epw_climate_analyzer/chart_presentation.py").read_text("utf-8")
        self.assertIn("capture_control(st,fig",s)

if __name__=="__main__":unittest.main()
