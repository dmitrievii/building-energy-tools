"""R2.17 semantic natural ventilation colour consistency across chart routes."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.chart_theme import (
    NV_COLOR, NIGHT_FLUSHING_COLOR, NV_REJECTED_COLOR, NV_SUITABILITY_COLORSCALE,
    NIGHT_FLUSHING_COLORSCALE, semantic_color_from_text, NV_REJECTION_REASON_COLORS,
)
from epw_climate_analyzer.residual_findings import eligibility_figure, nv_special_figure
from epw_climate_analyzer.p3_persistence_chart import persistence_figure
from epw_climate_analyzer.p3_ui import nv_sensitivity_figure
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer.directional_climate import directional_table, directional_figure, directional_class_table, directional_class_figure
from epw_climate_analyzer.charts import threshold_bar_chart
from epw_climate_analyzer.aggregations import threshold_count_by_period

class NaturalVentilationPaletteTests(unittest.TestCase):
    def test_periods_and_heatmaps(self):
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({"dry_bulb_temperature_c":20.,"humidity_ratio_g_kg":6.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        mask=pd.Series(idx.hour<12,index=idx)
        ledger=pd.DataFrame({"Natural ventilation":mask.astype(float),"Night flushing":mask.astype(float)},index=idx)
        for name,colour,scale in (("nv",NV_COLOR,NV_SUITABILITY_COLORSCALE),("night",NIGHT_FLUSHING_COLOR,NIGHT_FLUSHING_COLORSCALE)):
            for period in ("Daily","Weekly","Monthly","Seasonal","Annual"):
                fig,_=eligibility_figure(df,name,period,ledger=ledger)
                for view in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                    self.assertEqual(view.data[0].marker.color,colour)
            for period in ("day","week","month"):
                fig,_=eligibility_figure(df,name,period,view="map",ledger=ledger)
                self.assertEqual(fig.layout.coloraxis.colorscale,tuple(map(tuple,scale)))
                self.assertEqual((fig.layout.coloraxis.cmin,fig.layout.coloraxis.cmax),(0.,1.))
        self.assertEqual(semantic_color_from_text("Natural-ventilation suitable hours"),NV_COLOR)
        self.assertEqual(semantic_color_from_text("Night-flushing suitable hours"),NIGHT_FLUSHING_COLOR)
        fig=threshold_bar_chart(threshold_count_by_period(df,mask,"Daily",label="suitable_hours"),"Natural-ventilation suitable hours","hours")
        self.assertEqual(fig.data[0].marker.color,NV_COLOR)
    def test_duration_persistence_and_directional(self):
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({"dry_bulb_temperature_c":20.,"humidity_ratio_g_kg":6.,"wind_speed_m_s":2.,"wind_direction_deg":270.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        mask=pd.Series(idx.hour<12,index=idx)
        for style,colour,attr in (("Daily duration",NV_COLOR,"line"),("Persistence",NV_COLOR,"marker")):
            fig,_=nv_special_figure(df,style,mask=mask)
            self.assertEqual(getattr(fig.data[0],attr).color,colour)
        fig,_=nv_sensitivity_figure(df,mask.astype(float))
        self.assertEqual(fig.data[0].colorscale,tuple(map(tuple,NV_SUITABILITY_COLORSCALE)))
        table=directional_table(df,radial="Hours",colour="Natural ventilation suitability",nv_mask=mask)
        fig=directional_figure(table,"Hours","Natural ventilation suitability","NV")
        self.assertEqual(fig.data[0].marker.colorscale,tuple(map(tuple,NV_SUITABILITY_COLORSCALE)))
        table=directional_class_table(df,quantity="Natural ventilation suitability",radial="Hours",nv_mask=mask)
        fig=directional_class_figure(table,"NV")
        self.assertEqual(tuple(t.marker.color for t in fig.data),(NV_REJECTED_COLOR,NV_COLOR))

    def test_rejection_reason_colours_follow_labels_not_rank(self):
        idx=pd.date_range("2026-01-01",periods=6,freq="h")
        df=pd.DataFrame({"dry_bulb_temperature_c":[10.,30.,30.,20.,20.,20.],
                         "humidity_ratio_g_kg":[6.,6.,6.,12.,12.,12.],
                         "wind_speed_m_s":[.2,2.,8.,8.,2.,2.]},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        for limits in ({},{"wind_min":.5,"wind_max":6.}):
            fig,_=nv_special_figure(df,"Rejected reasons",**limits)
            for view in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                trace=view.data[0]
                self.assertEqual(tuple(trace.marker.color),
                                 tuple(NV_REJECTION_REASON_COLORS[x] for x in trace.x))
                self.assertEqual(len(set(trace.marker.color)),len(trace.x))
                expected={"Too cold":1.,"Too hot":2.,"Too humid":3.,
                          "Wind too weak":1.,"Wind too strong":2.}
                self.assertEqual(dict(zip(trace.x,trace.y)),{x:expected[x] for x in trace.x})
