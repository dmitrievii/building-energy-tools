"""P4 analytic fixtures: complete coverage, gaps, empirical statistics."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer import p4_extremes as p

class P4Tests(unittest.TestCase):
    def fixture(self,n=96):
        df=pd.DataFrame({p.T:30.,p.P:1.,p.RH:80.,p.V:2.,p.W:7.,p.SNOW:0.},index=pd.date_range("2025-06-01",periods=n,freq="h"))
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_complete_days_and_gaps(self):
        df=self.fixture()
        self.assertEqual(len(p.temperature_events(df,threshold=30,above=True,minimum=3,stat="max")[1]),1)
        a=df.drop(df.index[30])
        daily,events=p.temperature_events(a,threshold=30,above=True,minimum=2,stat="max")
        self.assertTrue(np.isnan(daily.iloc[1]["max"]))
        self.assertEqual(events.duration.tolist(),[2.])
        roll=p.rolling_windows(a,p.P,3,total=True)
        self.assertTrue(np.isnan(roll.loc[df.index[31]]))
        self.assertEqual(roll.loc[df.index[33]],3.)
        self.assertEqual(p.cumulative_precipitation(a).loc[df.index[31]],1.)

    def test_hourly_events_missing_and_inclusive(self):
        df=self.fixture(6);s=pd.Series([1.,1.,np.nan,1.,0.,1.],index=df.index)
        a=p.events(s,threshold=1,above=True,minimum=1,step=p.cadence(df))
        self.assertEqual(a.duration.tolist(),[2.,1.,1.])
        self.assertEqual(a.excess.sum(),0.)
        a=p.events(s,threshold=1,above=False,minimum=1,step=p.cadence(df),inclusive=False)
        self.assertEqual(a.duration.tolist(),[1.])

    def test_wet_dry_and_freeze(self):
        df=self.fixture()
        df[p.P]=0.;df.loc[df.index[:24],p.P]=1.
        _,wet,dry=p.wet_dry_events(df,1.)
        self.assertEqual(wet.duration.tolist(),[1.])
        self.assertEqual(dry.duration.tolist(),[3.])
        df.loc[df.index[0],p.T]=-1.
        self.assertEqual(p.day_indicators(df).iloc[0,0],1.)
        self.assertEqual(p.freeze_thaw_days(df).iloc[0,1],1.)

    def test_freeze_thaw_cycles_observed_wet_and_gap(self):
        df=self.fixture(30)
        df[p.T]=2.
        df.loc[df.index[24:27],p.T]=[-1.,0.,-2.]
        a=p.freeze_thaw_cycles(df,wet_threshold=1.)
        self.assertEqual(len(a),1)
        self.assertEqual(a.iloc[0]["Freeze-to-thaw duration [h]"],3.)
        self.assertEqual(a.iloc[0]["Minimum air temperature [°C]"],-2.)
        self.assertEqual(a.iloc[0]["Antecedent wet at freeze"],1.)
        self.assertTrue(p.freeze_thaw_cycles(df.drop(df.index[25])).empty)

    def test_design_coincident_and_probability(self):
        df=self.fixture(4);df[p.T]=[10.,20.,30.,40.];df[p.W]=[1.,2.,3.,4.]
        a=p.design_conditions(df,p.T,[25.],upper=True,coincident=[p.W])
        self.assertAlmostEqual(a.iloc[0]["Quantile"],32.5)
        self.assertEqual(a.iloc[0][p.W+" · coincident"],3.)
        self.assertEqual(a.iloc[0][p.W+" · tail mean"],4.)
        r,n=p.correlation(df,[p.T,p.W]);self.assertAlmostEqual(r.iloc[0,1],1.);self.assertEqual(n.iloc[0,1],4)
        _,_,z,h=p.joint_density(df,p.T,p.W,bins=3)
        self.assertAlmostEqual(z.sum(),100.);self.assertAlmostEqual(h.sum(),4.)

    def test_idf_source_gate_and_complete_years(self):
        df=self.fixture()
        with self.assertRaises(ValueError):p.empirical_idf(df)
        with self.assertRaises(ValueError):p.empirical_idf(df,historical_native=True)
        idx=pd.date_range("2010-01-01","2020-01-01",freq="h",inclusive="left")
        df=pd.DataFrame({p.P:2.},index=idx);df.attrs["canonical_native_interval_minutes"]=60.
        a=p.empirical_idf(df,historical_native=True,durations=(.5,1,24))
        self.assertEqual(set(a.duration_h),{1,24});self.assertEqual(len(a),20)
        np.testing.assert_allclose(a.intensity_mm_h,2.)
        self.assertAlmostEqual(a.return_period_y.max(),11.)
        with self.assertRaises(ValueError):p.empirical_idf(df.drop(idx[45]),historical_native=True)

    def test_timeline_without_qualifying_events(self):
        from epw_climate_analyzer.p4_ui import event_timeline_figure
        df=self.fixture()
        for stat in ("max","mean","min"):
            daily,table=p.temperature_events(df,threshold=35.,above=True,minimum=3,stat=stat)
            self.assertTrue(table.empty)
            fig=event_timeline_figure(table,daily[stat],unit="days",threshold=35.,quantity=stat)
            self.assertEqual(len(fig.data),2)
            np.testing.assert_allclose(fig.data[0].y,[30.]*4)
            self.assertEqual(list(fig.data[1].y),[35.,35.])
            self.assertEqual(len(fig.layout.shapes),0)
        # A zero-event hourly timeline keeps a source gap unconnected.
        df=df.iloc[[0,1,3]].copy()
        s=df[p.V]
        table=p.events(s,threshold=5.,above=True,minimum=3,step=p.cadence(df))
        fig=event_timeline_figure(table,s,unit="hours",threshold=5.,step=p.cadence(df))
        self.assertTrue(np.isnan(fig.data[0].y[2]))
        self.assertFalse(fig.data[0].connectgaps)

    def test_p4_route_contract(self):
        import ast
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        funcs={n.name:ast.get_source_segment(source,n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
        for name,token in (("render_temperature","temperature_panel"),("render_humidity","persistence_panel"),
                           ("render_humidity","multivariate_panel"),("render_wind","persistence_panel"),
                           ("render_precipitation","precipitation_panel"),("render_hvac_passive","hvac_panel"),
                           ("render_time_series_overlay","multivariate_panel"),("render_time_series_overlay","event_viewer")):
            self.assertIn(token,funcs[name])
        self.assertIn("precipitation_panel(df,native_df,chart_group,render_plot)",funcs["render_precipitation"])
        self.assertIn("native_df is not None and native_liquid_available",funcs["render_precipitation"])
        self.assertIn('["Extreme events and day indicators","Daily extremes and ranking"]',funcs["render_temperature"])

if __name__=="__main__":unittest.main()
