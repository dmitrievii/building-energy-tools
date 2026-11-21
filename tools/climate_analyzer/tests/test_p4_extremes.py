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

if __name__=="__main__":unittest.main()
