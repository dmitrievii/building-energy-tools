"""P1 scientific and visualization invariants."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.extended_visualization import (
    T,P,diurnal_statistics,diurnal_figure,occurrence_table,probability_figure,
    climate_summary_table,climate_summary_figure,walter_precip_scale,
    ground_depth_heatmap,daylight_envelope,compatible_types,daily_amplitude,
    sunshine_hour_heatmap,
)
from epw_climate_analyzer.timeseries import OverlaySeries,build_meteogram_figure

def sample():
    idx=pd.date_range("2025-01-01","2025-02-01",freq="h",inclusive="left")
    df=pd.DataFrame({T:idx.hour.astype(float),P:1.,"sunshine_duration_s":1800.},index=idx)
    df.attrs["canonical_native_interval_minutes"]=60.
    return df

class ExtendedTests(unittest.TestCase):
    def test_diurnal_and_missing(self):
        df=sample();table=diurnal_statistics(df,T,[1])
        self.assertEqual(len(table),24)
        np.testing.assert_allclose(table["mean"],np.arange(24))
        for style in ("Overlay","Small multiples"):
            self.assertEqual(len(diurnal_figure(table,T,"°C",representation=style).data),3)
        df.loc[df.index.hour==8,T]=np.nan
        self.assertTrue(np.isnan(diurnal_statistics(df,T,[1]).loc[(1,8),"mean"]))
        self.assertFalse(compatible_types(df,"wind_direction_deg"))
    def test_distributions(self):
        df=sample()
        for basis,expected in (("Hours",744.),("Days",31.),("Percentage",100.)):
            self.assertAlmostEqual(occurrence_table(df,T,[5,15],basis=basis).sum(axis=1).iloc[0],expected)
        df.iloc[0,0]=np.nan
        self.assertAlmostEqual(occurrence_table(df,T,[5,15],basis="Days").sum(axis=1).iloc[0],30.)
        self.assertEqual(daily_amplitude(df).dropna().iloc[0],23.)
        self.assertEqual(probability_figure(df,T,"°C").data[0].x[-1],100.)
    def test_summary_complete_paired_periods(self):
        df=sample();table=climate_summary_table(df)
        self.assertAlmostEqual(table.loc[1,P],744.)
        self.assertAlmostEqual(table.loc[1,T],11.5)
        self.assertTrue(np.isnan(table.loc[2,P]))
        np.testing.assert_allclose(walter_precip_scale([0,100,300]),[0,50,60])
        for style in ("Climograph","Walter–Lieth","Temperature–precipitation loop"):
            self.assertTrue(climate_summary_figure(table,style).data)
        from epw_climate_analyzer.exporting import figure_to_dataframe
        exported=figure_to_dataframe(climate_summary_figure(table,"Walter–Lieth"))
        self.assertEqual(exported.loc[exported["trace"]=="Precipitation","y"].iloc[0],744.)
        self.assertEqual(len(figure_to_dataframe(climate_summary_figure(table,"Temperature–precipitation loop"))),12)
        self.assertTrue(climate_summary_table(df.iloc[1:]).empty)
        monthly=pd.DataFrame({T:[2.],P:[83.]},index=pd.to_datetime(["2025-01-01"]))
        monthly.attrs["canonical_native_resolution"]="monthly"
        self.assertFalse(compatible_types(monthly,T))
        self.assertEqual(climate_summary_table(monthly).loc[1,P],83.)
    def test_interpretation_amplitude_and_duration_endpoints(self):
        from epw_climate_analyzer.extended_visualization import climate_summary_interpretation, amplitude_figure
        from epw_climate_analyzer.charts import duration_chart
        table=pd.DataFrame({T:[25.,5.],P:[10.,80.]},index=[7,1])
        result=climate_summary_interpretation(table,"Walter–Lieth diagram")
        self.assertIn("Jul",result)
        self.assertIn("dryness",result)
        self.assertIn("No annual total",result)
        df=sample()
        self.assertEqual(amplitude_figure(df,T,"Daily","Temperature").data[0].y[0],23.)
        self.assertEqual(amplitude_figure(df,T,"Monthly","Temperature").data[0].y[0],23.)
        self.assertEqual(probability_figure(df,T,"°C").layout.xaxis.tickvals[-1],100)
        idx=pd.date_range("2025-01-01",periods=8760,freq="h")
        annual=pd.DataFrame({T:np.arange(len(idx))},index=idx)
        fig=duration_chart(annual,T,"Duration","°C")
        self.assertEqual(fig.layout.xaxis.tickvals[-1],8760)
        self.assertEqual(duration_chart(df,T,"Duration","°C").layout.xaxis.tickvals[-1],744)
    def test_duplicate_export_buttons_and_scoped_explorers(self):
        import ast
        from pathlib import Path
        from streamlit.testing.v1 import AppTest
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        def extract(name):
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            return ast.get_source_segment(source,node)
        preamble="""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from types import SimpleNamespace
NAVIGATION_KEY="page"
st.session_state[NAVIGATION_KEY]="Sky and Daylight"
st.session_state["_active_filtered_export_df"]=pd.DataFrame({"T":[1.,2.]})
st.session_state["_plotly_element_counter"]=0
def get_active_climate_file():
    return SimpleNamespace(name="test.epw",payload=b"same EPW for both charts")
"""
        script=preamble+"\n"+extract("next_plot_key")+"\n"+extract("render_chart_export_controls")+"""
fig=go.Figure(go.Scatter(x=[1,2],y=[3,4]))
fig.update_layout(title="Identical title")
render_chart_export_controls(fig)
render_chart_export_controls(fig)
"""
        app=AppTest.from_string(script,default_timeout=45).run()
        self.assertFalse(app.exception)
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("Temperature quantity family",extract("render_temperature"))
        self.assertIn('"Amplitude"',extract("render_generic_variable_page"))
        self.assertIn('"Temperature–precipitation diagrams"',extract("render_precipitation"))
        self.assertNotIn("render_climate_summary_charts",extract("render_overview"))
        self.assertNotIn("render_climate_summary_charts",extract("render_historical_overview"))
        self.assertIn('["Walter–Lieth diagram","Climograph","Temperature–precipitation loop"]',extract("render_climate_summary_charts"))
        self.assertIn('["Monthly sky-condition distribution","Threshold hours"]',extract("render_sky_daylight"))

    def test_daylight_ground_and_sunshine(self):
        df=sample()
        self.assertEqual(tuple(daylight_envelope(df.index,48.).layout.yaxis.range),(0,24))
        self.assertAlmostEqual(sunshine_hour_heatmap(df).data[0].z[0][0],.5)
        fig=ground_depth_heatmap(pd.DataFrame({"Jan":[4.,5.],"Feb":[6.,7.]},index=[0.,1.]))
        self.assertEqual(fig.layout.yaxis.autorange,"reversed")
    def test_meteogram_accepts_distinct_units(self):
        df=sample()
        fig,tables=build_meteogram_figure(df,[OverlaySeries("T",T,"°C","Native"),OverlaySeries("Rain",P,"mm","Daily"),OverlaySeries("Sunshine","sunshine_duration_s","s","Daily")],df.index[0],df.index[-1]+pd.Timedelta(hours=1))
        self.assertEqual(len(tables),3)
        self.assertEqual(len(fig.data),3)
        self.assertEqual(fig.layout.yaxis3.title.text,"s")
        self.assertEqual(len(tables[0]),len(df))

if __name__=="__main__":
    unittest.main()
