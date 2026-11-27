"""R2.21 E: event severity and physical cumulative resource conservation."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.p4_extremes import events
from epw_climate_analyzer.event_severity import bubble_figure,bubble_note,severity_unit
from epw_climate_analyzer.cumulative_resources import monthly_accumulation,extensive_profile,degree_profile,ventilation_profile
from epw_climate_analyzer.degree_metrics import degree_metric_table
from epw_climate_analyzer.decisions import natural_ventilation_condition

T="dry_bulb_temperature_c"
G="global_horizontal_radiation_wh_m2"
W="humidity_ratio_g_kg"

class EventCumulativeTests(unittest.TestCase):
    def test_bubble_area_exact_severity_and_threshold_equality(self):
        idx=pd.date_range("2026-07-01",periods=9,freq="D")
        s=pd.Series([31.,32.,20.,34.,35.,20.,30.,20.,np.nan],index=idx)
        table=events(s,threshold=30.,daily=True)
        self.assertEqual(list(table.excess),[3.,9.,0.])
        f=bubble_figure(table,unit="days",threshold=30.,above=True,quantity="Daily maximum temperature [°C]")
        self.assertEqual(f.data[0].marker.sizemode,"area")
        np.testing.assert_array_equal(f.data[0].marker.size,[3.,9.])
        self.assertEqual(f.data[1].marker.symbol,"circle-open")
        self.assertEqual(f.layout.meta["severity_unit"],"K·d")
        self.assertIn("9.00 K·d",bubble_note(table,unit="days",above=True,quantity="Daily maximum temperature [°C]"))
        self.assertEqual(severity_unit("Daily precipitation [mm]","days"),"mm")
        self.assertEqual(severity_unit("Relative humidity [%]","hours"),"percentage points·h")

    def test_cold_and_subhourly_events_preserve_peak_and_excess(self):
        idx=pd.date_range("2026-01-01",periods=5,freq="30min")
        table=events(pd.Series([-2.,-4.,1.,-1.,-1.],index=idx),threshold=0.,above=False,step=pd.Timedelta(minutes=30))
        f=bubble_figure(table,unit="hours",threshold=0.,above=False,quantity="Temperature [°C]")
        np.testing.assert_array_equal(f.data[0].x,[1.,1.])
        np.testing.assert_array_equal(f.data[0].y,[-4.,-1.])
        np.testing.assert_array_equal(f.data[0].marker.size,[3.,1.])

    def hourly(self):
        idx=pd.to_datetime(["2025-12-31 23:00","2026-01-01 00:00","2026-01-01 01:00","2026-03-01 00:00","2026-03-01 01:00"])
        df=pd.DataFrame({T:[10.,19.,25.,20.,np.nan],W:[7.,7.,8.,12.,7.],G:[100.,200.,300.,400.,np.nan],"hour_of_day":idx.hour},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_year_reset_and_missing_months_are_not_zero_filled(self):
        df=self.hourly()
        table=monthly_accumulation(df,df[G]/1000.)
        self.assertAlmostEqual(table.loc[(2025,12),"cumulative"],.1)
        self.assertAlmostEqual(table.loc[(2026,1),"cumulative"],.5)
        self.assertTrue(np.isnan(table.loc[(2026,2),"cumulative"]))
        self.assertAlmostEqual(table.loc[(2026,3),"cumulative"],.9)
        self.assertAlmostEqual(table.loc[(2026,3),"coverage"],1/744)
        f,note=extensive_profile(df,G)
        self.assertEqual(len(f.data),2)
        self.assertFalse(f.data[1].connectgaps)
        self.assertEqual(f.data[1].marker.symbol[0],"circle-open")
        self.assertIn("0.90 kWh/m²",note)

    def test_native_monthly_totals_and_complete_marker(self):
        idx=pd.date_range("2026-01-01",periods=3,freq="MS")
        df=pd.DataFrame({"sunshine_duration_s":[360000.,720000.,1080000.]},index=idx)
        df.attrs["canonical_native_resolution"]="monthly"
        f,_=extensive_profile(df,"sunshine_duration_s")
        np.testing.assert_array_equal(np.asarray(f.data[0].y)[:3],[100.,300.,600.])
        self.assertEqual(tuple(f.data[0].marker.symbol[:3]),("circle","circle","circle"))

    def test_degree_profile_matches_annual_indicator_and_signed_kgt(self):
        df=self.hourly()
        args=dict(heating_indoor_c=20.,heating_limit_c=12.,cooling_indoor_c=20.,cooling_limit_c=18.3)
        f,_=degree_profile(df,**args)
        expected=degree_metric_table(df,metric="Degree-hours",aggregation="Annual",**args)
        self.assertEqual(expected.iloc[0,0],10.)
        self.assertEqual(expected.iloc[1,1],4.)
        series=[t for t in f.data if t.name=="Cooling degree-hours (KGT) · 2026"][0]
        self.assertAlmostEqual(series.y[0],4.)
        self.assertAlmostEqual(series.y[2],4.)
        jan=df.loc["2026-01-01"].iloc[:1]
        f,_=degree_profile(jan,**args)
        self.assertEqual(f.data[1].y[0],-1.)

    def test_nv_profile_matches_strict_mask_and_native_duration(self):
        df=self.hourly()
        args=dict(t_min_c=16.,t_max_c=26.,d_max_g_kg=9.)
        f,_=ventilation_profile(df,fixed=args)
        mask=natural_ventilation_condition(df,**args)
        self.assertEqual(f.data[1].y[0],float(mask.loc["2026-01"].sum()))
        self.assertEqual(f.data[1].y[2],float(mask.loc["2026"].sum()))

    def test_atlas_uses_same_profile_and_bubble(self):
        from epw_climate_analyzer.p66_catalogue import Diagram,SOL
        from epw_climate_analyzer.p66_render import make_figure,_event_figure
        from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation
        df=self.hourly()
        d=Diagram("test",SOL,"Global horizontal irradiation · cumulative annual profile","cumulative_resource",G,"kWh/m²")
        f,note=make_figure(d,df,{})
        expected,expected_note=extensive_profile(df,G)
        self.assertEqual(note,expected_note)
        np.testing.assert_array_equal(f.data[1].y,expected.data[1].y)
        self.assertTrue(validate_figure_interpretation(f,note))
        s=pd.Series([31.,33.],index=pd.date_range("2026-07-01",periods=2,freq="D"))
        table=events(s,threshold=30.,daily=True)
        bubble=_event_figure(table,s,"intensity",30.,True,"days","Daily maximum temperature [°C]")
        self.assertEqual(bubble.data[0].marker.sizemode,"area")
        self.assertEqual(bubble.data[0].marker.size[0],4.)

if __name__=="__main__":
    unittest.main()
