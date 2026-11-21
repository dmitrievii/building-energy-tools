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

    def test_saved_report_no_fixed_chart_count(self):
        from unittest.mock import patch
        entries=[]
        for i in range(150):
            entries,_=r.add_snapshot(entries,{"id":str(i),"figure":"{}"})
        self.assertEqual(len(entries),150)
        duplicate,_=r.add_snapshot(entries,entries[0])
        self.assertEqual(len(duplicate),150)
        with patch.object(r,"MAX_BYTES",300):
            with self.assertRaisesRegex(ValueError,"figure-data budget"):
                r.add_snapshot(entries,{"id":"151","figure":"{}"})

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

    def test_chapter_cover_locator_and_print_font(self):
        from types import SimpleNamespace
        from epw_climate_analyzer import p6_report_structure as s
        state={};df=self.fixture()
        site=SimpleNamespace(latitude=47.08,longitude=15.45,elevation_m=370.)
        r.set_context(state,page="Temperature",source="Graz.epw",location="Graz.Univ, AUT",df=df,site=site,source_id="test",
                      extra={"pressure mode":"normal"})
        c=state[r.CONTEXT_KEY];c["keyed chart settings"]='{"PRIVATE_DIAGNOSTIC_KEY": 12}'
        fig=go.Figure(go.Scatter(x=[1,2],y=[3,4]));fig.update_layout(title="Temperature profile",font_size=27)
        fig.update_xaxes(tickfont_size=8)
        first=r.snapshot(fig,c,"Climate interpretation")
        second=r.snapshot(fig,{**c,"page":"Solar and Radiation","statistics":s.capture_statistics(df,"Solar and Radiation")},"Solar note")
        self.assertEqual([n for n,_ in s.ordered_groups([first,second])],["Temperature","Solar radiation"])
        locator=s.locator_figure(c)
        self.assertEqual(list(locator.data[-1].x),[15.45])
        self.assertEqual(list(locator.data[-1].y),[47.08])
        f=s.report_figure(fig,width_pt=500,height_pt=250)
        self.assertAlmostEqual(f.layout.font.size,11*96/72)
        self.assertAlmostEqual(f.layout.xaxis.tickfont.size,11*96/72)
        self.assertEqual(fig.layout.font.size,27)
        output=r.printable_html([first,second],"Graz","A4","Landscape").decode("utf-8")
        self.assertIn("Climate and station overview",output)
        self.assertIn("Natural Earth",output)
        self.assertIn("Air temperature",output)
        self.assertIn("01 · Temperature",output)
        self.assertIn("02 · Solar radiation",output)
        self.assertIn("Climate interpretation",output)
        self.assertNotIn("PRIVATE_DIAGNOSTIC_KEY",output)
        self.assertNotIn("native interval minutes",output)
        self.assertLess(output.index("Climate and station overview"),output.index("01 · Temperature"))
        pdf=r.pdf_report([first],"Graz","A4","Landscape")
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_report_month_ticks_temperature_palette_and_interpretation(self):
        from epw_climate_analyzer import p6_report_structure as s
        from epw_climate_analyzer.charts import month_hour_heatmap
        from epw_climate_analyzer.interpretations import variable_interpretation
        from epw_climate_analyzer.chart_presentation import ChartPresentationSettings,apply_chart_presentation
        idx=pd.date_range("2026-01-01","2027-01-01",freq="h",inclusive="left")
        df=pd.DataFrame({s.T:15+12*np.sin(2*np.pi*(idx.dayofyear.to_numpy()-90)/365)+4*np.sin(2*np.pi*idx.hour.to_numpy()/24)},index=idx)
        bounds=(17.,25.)
        entry=next(e for e in s.CATALOG if e[0]=="temperature_heatmap")
        fig,note=s.standard_figure(entry,df,{"temperature thresholds":list(bounds)})
        expected=month_hour_heatmap(df,s.T,"test","°C",temperature_thresholds=bounds)
        self.assertEqual(fig.layout.coloraxis.colorscale,expected.layout.coloraxis.colorscale)
        self.assertIn(variable_interpretation(df,s.T,entry[2],"°C",high_threshold=25.,low_threshold=17.),note)
        copy=s.report_figure(fig,width_pt=730,height_pt=350)
        self.assertEqual(copy.layout.coloraxis.colorscale,expected.layout.coloraxis.colorscale)
        bars=go.Figure(go.Bar(x=pd.date_range("2026-01-01",periods=12,freq="MS"),y=np.arange(12)))
        apply_chart_presentation(bars,ChartPresentationSettings())
        self.assertEqual(list(bars.layout.xaxis.ticktext),list(pd.date_range("2026-01-01",periods=12,freq="MS").strftime("%b")))
        self.assertEqual(list(s.report_figure(bars,width_pt=730,height_pt=320).layout.xaxis.ticktext)[-1],"Dec")
        history=go.Figure(go.Scatter(x=pd.date_range("2025-01-01",periods=24,freq="MS"),y=np.arange(24)))
        apply_chart_presentation(history,ChartPresentationSettings())
        self.assertIn("2025",history.layout.xaxis.ticktext[0]);self.assertIn("2026",history.layout.xaxis.ticktext[-1])

    def test_psychrometric_zone_key_and_polar_static_export(self):
        from epw_climate_analyzer import p6_report_structure as s
        from epw_climate_analyzer.charts import psychrometric_chart
        import plotly.io as pio
        df=self.fixture()
        df[s.T]=np.linspace(0,30,len(df));df[s.W]=np.linspace(2,12,len(df))
        df[s.RH]=50.
        df["moist_air_enthalpy_kj_kg"]=1.006*df[s.T]+df[s.W]/1000*(2501+1.86*df[s.T])
        df["month_index"]=df.index.month;df["month_name"]=df.index.strftime("%b");df["hour_of_day"]=df.index.hour
        psych=psychrometric_chart(df,data_mode="Points")
        entries=s.zone_legend_entries(psych)
        self.assertGreaterEqual(len(entries),12)
        f=s.report_figure(psych,width_pt=730,height_pt=325,external_zone_legend=True)
        self.assertEqual(tuple(f.layout.xaxis.domain),(0.,1.))
        self.assertTrue(all(t.showlegend is False for t in f.data if getattr(t,"legend",None)=="legend2"))
        self.assertNotEqual(psych.layout.xaxis.domain,f.layout.xaxis.domain)
        self.assertEqual(len(psych.data),len(f.data))
        self.assertTrue(f.to_image(format="png",scale=1).startswith(b"\x89PNG"))
        item=r.snapshot(psych,{"page":"Humidity and Psychrometrics","source":"Test"},"Full interpretation")
        html=r.printable_html([item],"Test","A4","Landscape").decode("utf-8")
        self.assertIn("Bioclimatic zones",html)
        for _,name,_ in entries:self.assertIn(name,html)
        self.assertTrue(r.pdf_report([item],"Test","A4","Landscape").startswith(b"%PDF"))
        polar=go.Figure()
        for m in range(12):
            polar.add_scatterpolar(theta=np.arange(0,361,10),r=np.linspace(0,90,37),name=f"Month {m+1}",mode="lines")
        polar.add_scatterpolar(theta=[90,180,270],r=[50,60,70],mode="markers",showlegend=False,
             marker=dict(color=[0,300,800],showscale=True,colorscale="Plasma",colorbar=dict(title="DNI [Wh/m²]")))
        polar.update_layout(legend=dict(orientation="h",y=-.08),polar=dict(radialaxis=dict(range=[0,90])))
        figure=s.report_figure(polar,width_pt=730,height_pt=430)
        self.assertEqual(figure.layout.legend.orientation,"v")
        self.assertLess(figure.layout.polar.domain.x[1],1.)
        self.assertTrue(figure.to_image(format="png",scale=1).startswith(b"\x89PNG"))
        self.assertEqual(polar.data[-1].marker.colorscale,figure.data[-1].marker.colorscale)

    def test_map_proportions_and_coordinates(self):
        from epw_climate_analyzer import p6_report_structure as s
        fig=s.locator_figure({"location":"Graz.Univ, AUT","latitude":"47.08","longitude":"15.45"})
        self.assertAlmostEqual(fig.layout.xaxis.scaleratio,np.cos(np.deg2rad(47.08)))
        self.assertEqual(fig.layout.xaxis.scaleanchor,"y")
        self.assertEqual(fig.data[0].fill,"toself")
        self.assertEqual(list(fig.data[-1].x),[15.45])
        self.assertEqual(list(fig.data[-1].y),[47.08])
        f=s.report_figure(fig,width_pt=730,height_pt=205)
        self.assertEqual(f.layout.xaxis.scaleanchor,"y")
        self.assertTrue(f.to_image(format="png",scale=1).startswith(b"\x89PNG"))

    def test_standard_catalog_and_bulk_capture(self):
        from epw_climate_analyzer import p6_report_structure as s
        df=self.fixture();df["hour_of_day"]=df.index.hour;df["month_index"]=df.index.month
        context={"page":"Report","latitude":"47.08","longitude":"15.45"}
        keys={x[0]:x for x in s.available_catalog(df,context)}
        self.assertIn("temperature_profile",keys)
        self.assertIn("nv",keys)
        self.assertNotIn("facade",keys)
        self.assertNotIn("wind_rose",keys)
        for key in ("temperature_profile","temperature_duration","temperature_heatmap","humidity_profile","ghi","rain","nv","degree","daylight"):
            fig,note=s.standard_figure(keys[key],df,context,df)
            self.assertTrue(len(fig.data)>0,key)
            self.assertTrue(note,key)
        monthly=df.iloc[[0]].copy();monthly.attrs["canonical_native_resolution"]="monthly"
        self.assertNotIn("nv",{x[0] for x in s.available_catalog(monthly,context)})
        fig=go.Figure(go.Scatter(y=[1,2]))
        state={"_p6_displayed_charts":[(fig,{"page":"Temperature"},"note","a"),(fig,{"page":"Wind and Ventilation"},"note","b")]}
        r.save_all_displayed(state)
        self.assertEqual(len(state[r.REPORT_KEY]),2)
        r.save_all_displayed(state)
        self.assertEqual(len(state[r.REPORT_KEY]),2)

    def test_routes(self):
        from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES
        from epw_climate_analyzer.historical_capabilities import available_historical_pages
        root=Path(__file__).resolve().parents[1]
        self.assertIn("Report",NAVIGATION_PAGES)
        self.assertIn("Report",available_historical_pages(self.fixture()))
        app=(root/"app.py").read_text("utf-8")
        self.assertGreaterEqual(app.count("        render_report("),3)
        self.assertIn("select_overview(df,render_plot",app)
        for file in ("source_parity_ui.py","source_parity_monthly_canonical.py"):
            s=(root/"epw_climate_analyzer"/file).read_text("utf-8")
            self.assertIn("render_report(",s)
            self.assertIn("select_overview(",s)
        s=(root/"epw_climate_analyzer/chart_presentation.py").read_text("utf-8")
        self.assertIn("capture_control(st,fig",s)

if __name__=="__main__":unittest.main()
