"""Fixed RH classes and quantity-independent monthly occurrence axes."""
import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from epw_climate_analyzer.extended_visualization import (
    occurrence_default_edges, occurrence_table, occurrence_figure,
    RH_OCCURRENCE_EDGES, RH_OCCURRENCE_COLORS,
)
from epw_climate_analyzer.calendar_heatmap_axes import apply_monthly_axes
from epw_climate_analyzer.p6_report_structure import report_figure
from epw_climate_analyzer.profile_interpretation import generic_figure_interpretation

RH="relative_humidity_pct"

class RelativeHumidityOccurrenceTests(unittest.TestCase):
    def test_fixed_classes_valid_range_and_exact_boundaries(self):
        values=[0.,29.,30.,40.,60.,80.,90.,95.,100.,-1.,101.,np.nan]
        df=pd.DataFrame({RH:values},index=pd.date_range("2026-01-01",periods=len(values),freq="h"))
        df.attrs["canonical_native_interval_minutes"]=60
        for v in (df[RH],pd.Series([80.,85.]),pd.Series([10.,20.])):
            self.assertEqual(tuple(occurrence_default_edges(v,RH)),RH_OCCURRENCE_EDGES)
        table=occurrence_table(df,RH,RH_OCCURRENCE_EDGES)
        np.testing.assert_array_equal(table.iloc[0].to_numpy(),[2,1,1,1,1,1,2])
        pct=occurrence_table(df,RH,RH_OCCURRENCE_EDGES,basis="Percentage")
        self.assertAlmostEqual(float(pct.iloc[0].sum()),100.)
        fig=occurrence_figure(table,"%", "Hours")
        self.assertEqual(tuple(t.marker.color for t in fig.data),RH_OCCURRENCE_COLORS)
        with self.assertRaises(ValueError):
            occurrence_table(df,RH,[0.,100.])

    def test_all_daily_statistics_and_legacy_month_axes(self):
        idx=pd.date_range("2026-01-01","2026-12-31 23:00",freq="h")
        df=pd.DataFrame({RH:np.resize([30.,60.,80.,95.],len(idx)),
                         "dry_bulb_temperature_c":15.+np.sin(np.arange(len(idx))/24),
                         "dew_point_temperature_c":5.+np.sin(np.arange(len(idx))/24)},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        expected=list(pd.date_range("2026-01-01",periods=12,freq="MS").strftime("%b"))
        for col,unit in ((RH,"%"),("dry_bulb_temperature_c","°C"),("dew_point_temperature_c","°C")):
            for stat in ("Mean","Minimum","Maximum"):
                with self.subTest(column=col,stat=stat):
                    edges=occurrence_default_edges(df[col],col,basis="Days",daily_stat=stat)
                    table=occurrence_table(df,col,edges,basis="Days",daily_stat=stat)
                    np.testing.assert_array_equal(table.sum(axis=1),pd.date_range("2026-01-01",periods=12,freq="MS").days_in_month)
                    fig=occurrence_figure(table,unit,"Days")
                    fig.update_layout(title=f"{col} · occurrence · Days · daily {stat}")
                    for plot in (fig,report_figure(fig,width_pt=500,height_pt=230)):
                        apply_monthly_axes(plot)
                        self.assertEqual(list(plot.layout.xaxis.ticktext),expected)
                        np.testing.assert_array_equal(plot.data[0].y,table.iloc[:,0].to_numpy())
                    legacy=go.Figure(fig)
                    legacy.update_layout(meta=None,xaxis=dict(title="Period",tickvals=None,ticktext=None,tickmode="auto"))
                    self.assertEqual(list(report_figure(legacy,width_pt=500,height_pt=230).layout.xaxis.ticktext),expected)
                    if col==RH:
                        note=generic_figure_interpretation(df,fig,"occurrence",domain="",column=RH,args=("Days",stat))
                        self.assertIn("Fixed outdoor relative-humidity classes",note)
                        self.assertIn({"Mean":"typical relative humidity","Minimum":"persistent high humidity","Maximum":"peak relative humidity"}[stat],note)

    def test_invalid_interval_excludes_incomplete_daily_statistic(self):
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({RH:np.full(48,80.)},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60
        df.iloc[0,0]=101.
        for stat in ("Mean","Minimum","Maximum"):
            table=occurrence_table(df,RH,RH_OCCURRENCE_EDGES,basis="Days",daily_stat=stat)
            self.assertEqual(float(table.to_numpy().sum()),1.)
