"""R2.18 targeted palette contract; full catalogue evidence uses the audit runner."""
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.climate_model import CANONICAL_VARIABLES
from epw_climate_analyzer.chart_theme import (METRIC_COLORS,metric_colorscale,PRECIPITATION_COLORSCALE,
    SKY_CONDITION_COLORS,RAIN_DAY_COLORS,EXPOSURE_COLORS,wind_speed_colorscale)
from epw_climate_analyzer.directional_climate import directional_table,directional_figure
from epw_climate_analyzer.extended_visualization import sky_distribution,occurrence_figure
from epw_climate_analyzer.precipitation_findings import rain_day_classes_figure
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer.palette_audit import inspect_palette
from epw_climate_analyzer.utci_findings import paired_monthly_figure,mrt_monthly_figure
from epw_climate_analyzer.utci_presentation import duration_figure

class UniversalPaletteTests(unittest.TestCase):
    def test_canonical_registry(self):
        self.assertFalse(set(CANONICAL_VARIABLES)-set(METRIC_COLORS))
    def test_rain_exposure_and_wind_colour_independent(self):
        idx=pd.date_range("2026-01-01",periods=4,freq="h")
        df=pd.DataFrame({"wind_speed_m_s":[2.,3.,4.,5.],"wind_direction_deg":[0.,0.,90.,90.],
                         "liquid_precipitation_depth_mm":[0.,2.,1.,0.]},index=idx)
        radial="Wind-driven rain exposure"
        exposure=directional_table(df,radial=radial,colour=radial)
        wind=directional_table(df,radial=radial,colour="Wind speed")
        np.testing.assert_allclose(exposure.radius,wind.radius,equal_nan=True)
        np.testing.assert_allclose(exposure.radius,exposure.colour,equal_nan=True)
        f=directional_figure(exposure,radial,radial,"Rain")
        g=directional_figure(wind,radial,"Wind speed","Wind")
        self.assertEqual(f.data[0].marker.colorscale,tuple(map(tuple,PRECIPITATION_COLORSCALE)))
        self.assertEqual(g.data[0].marker.colorscale,tuple(map(tuple,wind_speed_colorscale())))
        self.assertEqual(g.data[0].marker.cmin,0.)
        self.assertEqual(g.data[0].marker.cmax,12.)
        self.assertEqual(inspect_palette(f)["signature"],inspect_palette(report_figure(f,width_pt=500,height_pt=310))["signature"])
    def test_sky_classes_and_rain_severity(self):
        idx=pd.date_range("2026-01-01",periods=8,freq="h")
        column="total_sky_cover_tenths"
        df=pd.DataFrame({column:[0.,1.,2.,3.,7.,8.,10.,np.nan]},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        table=sky_distribution(df,column)
        self.assertEqual(list(table.columns),["Clear","Intermediate","Overcast"])
        np.testing.assert_allclose(table.sum().to_numpy(),[3.,2.,2.])
        f=occurrence_figure(table,"","Hours")
        self.assertEqual(tuple(tr.marker.color for tr in f.data),tuple(SKY_CONDITION_COLORS.values()))
        f=rain_day_classes_figure(pd.DataFrame({c:[i] for i,c in enumerate(RAIN_DAY_COLORS)},index=["Jan"]))
        self.assertEqual(tuple(tr.marker.color for tr in f.data),tuple(RAIN_DAY_COLORS.values()))
    def test_utci_exposure_identity(self):
        idx=pd.date_range("2026-01-01",periods=24,freq="h")
        values=pd.DataFrame({"Open sun":30.,"Direct-beam shade":25.},index=idx)
        for f in (paired_monthly_figure(values,values),mrt_monthly_figure(values),duration_figure(values,1.,"UTCI")):
            for tr in f.data:
                self.assertEqual(tr.line.color,EXPOSURE_COLORS[tr.name])
    def test_audit_detects_unbound_colours(self):
        f=go.Figure(go.Bar(x=[1,2],y=[3,4]))
        self.assertTrue(inspect_palette(f)["implicit_channels"])
        f.update_traces(marker_color=METRIC_COLORS["liquid_precipitation_depth_mm"])
        self.assertFalse(inspect_palette(f)["implicit_channels"])

    def test_shading_ledger_explicit_semantics(self):
        from epw_climate_analyzer.solar_shading import monthly_shading_figure
        from epw_climate_analyzer.chart_theme import SHADING_IRRADIATION_COLORS
        table=pd.DataFrame({"Shaded total (direct-only)":[50.],"Intercepted direct":[20.],"Unshaded total":[70.]})
        f=monthly_shading_figure(table,["Jan"])
        self.assertFalse(inspect_palette(f)["implicit_channels"])
        for tr in f.data:
            actual=tr.line.color if tr.type=="scatter" else tr.marker.color
            self.assertEqual(actual,SHADING_IRRADIATION_COLORS[tr.name])

    def test_contour_and_invisible_helper_are_explicitly_classified(self):
        f=go.Figure(go.Contour(z=[[1.,2.],[3.,4.]],contours={"coloring":"none"},line={"color":"#2563EB"}))
        f.add_scatter(x=[None],y=[None],opacity=0.)
        self.assertFalse(inspect_palette(f)["implicit_channels"])
        f.data[0].contours.coloring="fill"
        self.assertTrue(inspect_palette(f)["implicit_channels"])
