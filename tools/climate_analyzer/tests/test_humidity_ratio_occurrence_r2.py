"""Humidity-ratio occurrence: physical reference bins and report parity."""
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.extended_visualization import (
    occurrence_default_edges,occurrence_table,occurrence_figure,W_OCCURRENCE_EDGES,W_OCCURRENCE_COLORS)
from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer.profile_interpretation import generic_figure_interpretation

W="humidity_ratio_g_kg"

class HumidityRatioOccurrenceTests(unittest.TestCase):
    def test_reference_classes_conserve_valid_observations(self):
        values=[0.,2.9,3.,6.,10.,15.,20.,25.,35.,-1.,np.nan]
        df=pd.DataFrame({W:values},index=pd.date_range("2026-01-01",periods=len(values),freq="h"))
        df.attrs["canonical_native_interval_minutes"]=60
        for series in (df[W],pd.Series([1.,2.]),pd.Series([25.,30.])):
            self.assertEqual(tuple(occurrence_default_edges(series,W)),W_OCCURRENCE_EDGES)
        table=occurrence_table(df,W,W_OCCURRENCE_EDGES)
        np.testing.assert_array_equal(table.iloc[0].to_numpy(),[2,1,1,1,1,1,2])
        pct=occurrence_table(df,W,W_OCCURRENCE_EDGES,basis="Percentage")
        self.assertAlmostEqual(float(pct.iloc[0].sum()),100.)
        self.assertEqual(tuple(t.marker.color for t in occurrence_figure(table,"g/kg","Hours").data),W_OCCURRENCE_COLORS)
        with self.assertRaises(ValueError):occurrence_table(df,W,[-1.,3.])
        # Custom positive edges remain supported.
        custom=occurrence_table(df,W,[5.,12.])
        self.assertEqual(float(custom.to_numpy().sum()),9.)

    def test_daily_classes_month_axis_and_shared_narrative(self):
        idx=pd.date_range("2026-01-01","2026-12-31 23:00",freq="h")
        df=pd.DataFrame({W:np.resize([3.,6.,10.,15.,20.,25.],len(idx))},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        for stat,phrase in (("Mean","typical humidity ratio"),("Minimum","persistent outdoor moisture exposure"),("Maximum","peak outdoor water-vapour content")):
            with self.subTest(stat=stat):
                edges=occurrence_default_edges(df[W],W,basis="Days",daily_stat=stat)
                table=occurrence_table(df,W,edges,basis="Days",daily_stat=stat)
                np.testing.assert_array_equal(table.sum(axis=1),pd.date_range("2026-01-01",periods=12,freq="MS").days_in_month)
                fig=occurrence_figure(table,"g/kg","Days")
                fig.update_layout(title=f"Humidity ratio · occurrence · Days · daily {stat}")
                printed=report_figure(fig,width_pt=500,height_pt=230)
                expected=list(pd.date_range("2026-01-01",periods=12,freq="MS").strftime("%b"))
                for plot in (fig,printed):
                    apply_monthly_axes(plot)
                    self.assertEqual(list(plot.layout.xaxis.ticktext),expected)
                    self.assertEqual(tuple(t.marker.color for t in plot.data),W_OCCURRENCE_COLORS)
                note=generic_figure_interpretation(df,fig,"occurrence",domain="",column=W,args=("Days",stat))
                self.assertIn("Fixed outdoor humidity-ratio reference boundaries",note)
                self.assertIn(phrase,note)
                df_bad=df.copy();df_bad.iloc[0,0]=-1.
                self.assertEqual(float(occurrence_table(df_bad,W,edges,basis="Days",daily_stat=stat).to_numpy().sum()),364.)
