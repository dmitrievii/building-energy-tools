"""R2.21 D historical anomaly qualification with independent known aggregates."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.climate_anomalies import (
    QUANTITIES,VIEWS,available,monthly_values,annual_values,analyze,figure,
)

T="dry_bulb_temperature_c"
P="liquid_precipitation_depth_mm"
G="global_horizontal_radiation_wh_m2"

class ClimateAnomalyTests(unittest.TestCase):
    def monthly(self):
        idx=pd.date_range("2015-01-01","2021-12-01",freq="MS")
        df=pd.DataFrame({T:idx.month+(idx.year-2015)*2.,P:idx.month*10.+(idx.year-2015),G:1000.*idx.month},index=idx)
        df.attrs.update(canonical_calendar_mode="historical",canonical_native_resolution="monthly")
        return df

    def test_reference_uses_equal_weighted_year_month_values(self):
        full=self.monthly()
        target=full.loc["2021"].copy()
        a=analyze(target,full,T,2015,2019)
        np.testing.assert_allclose(a["reference"]["mean"],np.arange(1,13)+4.)
        np.testing.assert_allclose(a["anomalies"].loc[2021],8.)
        self.assertEqual(a["annual_n"],5)
        self.assertAlmostEqual(a["annual_anomalies"].loc[2021],8.)
        self.assertEqual(a["reference"]["n"].tolist(),[5]*12)
        np.testing.assert_allclose(a["reference"].p05,np.arange(1,13)+.4)
        np.testing.assert_allclose(a["reference"].p95,np.arange(1,13)+7.6)

    def test_missing_month_never_annualized_or_zero_filled(self):
        full=self.monthly();full.loc["2016-02-01",T]=np.nan
        target=full.loc["2021"].drop(pd.Timestamp("2021-03-01"))
        a=analyze(target,full,T,2015,2019)
        self.assertEqual(a["reference"].loc[2,"n"],4)
        self.assertTrue(np.isnan(a["reference"].loc[2,"p05"]))
        self.assertTrue(np.isnan(a["anomalies"].loc[2021,3]))
        self.assertTrue(np.isnan(a["annual"].loc[2021]))
        self.assertEqual(a["annual_n"],4)

    def test_hourly_complete_leap_months_and_missing_record(self):
        idx=pd.date_range("2020-02-01","2020-03-01",freq="h",inclusive="left")
        full=pd.DataFrame({T:10.,P:.5,G:100.},index=idx)
        full.attrs.update(canonical_calendar_mode="historical",canonical_native_interval_minutes=60)
        m=monthly_values(full,P)
        self.assertEqual(m.loc[(2020,2),"value"],348.)
        self.assertAlmostEqual(monthly_values(full,G).loc[(2020,2),"value"],69.6)
        self.assertEqual(monthly_values(full,T).loc[(2020,2),"value"],10.)
        self.assertTrue(np.isnan(monthly_values(full.iloc[1:],T).loc[(2020,2),"value"]))
        self.assertAlmostEqual(monthly_values(full.iloc[1:],P).loc[(2020,2),"coverage"],695/696)
        self.assertTrue(np.isnan(annual_values(m,P).loc[2020]))

    def test_native_monthly_extensive_totals_and_relative_units(self):
        full=self.monthly()
        a=analyze(full.loc["2021"],full,P,2015,2019)
        np.testing.assert_allclose(a["anomalies"].loc[2021],4.)
        self.assertEqual(a["annual_anomalies"].loc[2021],48.)
        f,note,_=figure(full.loc["2021"],full,P,2015,2019,VIEWS[0],relative=True)
        self.assertAlmostEqual(f.data[0].y[0],100*4/12)
        self.assertIn("positive reference totals",note)
        full.loc[full.index.year<=2019,P]=0.
        with self.assertRaises(ValueError):
            figure(full.loc["2021"],full,P,2015,2019,VIEWS[0],relative=True)

    def test_four_views_same_reference_and_target(self):
        full=self.monthly()
        for view in VIEWS:
            f,note,_=figure(full,full,T,2015,2019,view,year=2021)
            self.assertEqual(f.layout.meta["reference_start"],2015)
            self.assertEqual(f.layout.meta["reference_end"],2019)
            self.assertIn("2015–2019",note)
        f,_,_=figure(full,full,T,2015,2019,VIEWS[2])
        self.assertEqual(f.data[0].zmin,-f.data[0].zmax)
        self.assertEqual(f.data[0].zmid,0)

    def test_typical_year_and_generated_are_not_admitted(self):
        df=self.monthly()
        df.attrs["canonical_calendar_mode"]="typical_year"
        self.assertEqual(available(df),[])
        with self.assertRaises(ValueError):monthly_values(df,T)
        df.attrs["canonical_calendar_mode"]="historical"
        df.attrs["anomaly_generated_source"]=True
        self.assertEqual(available(df),[])

    def test_atlas_uses_explicit_reference_and_identical_interpretation(self):
        from epw_climate_analyzer.p66_catalogue import catalogue,REP
        from epw_climate_analyzer.p66_render import make_figure
        from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation
        full=self.monthly();target=full.loc["2021"]
        self.assertFalse(any(d.kind=="climate_anomaly" for d in catalogue(target,{},REP)))
        context={"anomaly reference years":[2015,2019],"anomaly quantities":[T]}
        d=next(d for d in catalogue(target,context,REP) if d.kind=="climate_anomaly" and d.args[2]==VIEWS[2])
        f,note=make_figure(d,target,context,reference_df=full)
        expected,expected_note,_=figure(target,full,T,2015,2019,VIEWS[2])
        self.assertEqual(note,expected_note)
        np.testing.assert_array_equal(f.data[0].z,expected.data[0].z)
        self.assertTrue(validate_figure_interpretation(f,note))

if __name__=="__main__":
    unittest.main()
