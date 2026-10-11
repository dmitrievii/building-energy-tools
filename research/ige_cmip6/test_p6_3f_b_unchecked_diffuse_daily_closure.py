"""Scientific QA contracts for unchecked GeoSphere solar source exploration."""
from __future__ import annotations
import unittest
from datetime import datetime,date,timedelta,timezone
from p6_3f_b_unchecked_diffuse_daily_closure import (
 tier,valid_values,hourly_energy,physical_screens,daily_closure,SCIENCE_TIERS,
 TIMESTAMPS_SUPPORTED,MAX_DIFFUSE_EXCESS_WM2
)

class ProvisionalOriginalSolarScience(unittest.TestCase):
    def fixture(self,ghi_flag=20,dhi_flag=0,gh=700,di=350):
        start=datetime(2007,6,13,12,tzinfo=timezone.utc)
        return [{"timestamp":start+timedelta(minutes=10*i),
                 "cglo":float(gh),"chim":float(di),
                 "cglo_flag":ghi_flag,"chim_flag":dhi_flag}
                for i in range(6)]

    def test_q0_unchecked_is_not_automatically_rejected_as_incorrect(self):
        rows=self.fixture()
        self.assertEqual(tier(rows,"cglo"),"QC_CONFIRMED")
        self.assertEqual(tier(rows,"chim"),"COMPLETE_UNCHECKED_Q0")
        self.assertTrue(valid_values(rows,"chim"))
        self.assertAlmostEqual(hourly_energy(rows,"chim"),.35)
        self.assertAlmostEqual(hourly_energy(rows,"cglo"),.70)

    def test_missing_and_suspect_flags_not_turned_into_valid_original(self):
        rows=self.fixture()
        rows[2]["chim"]=None
        self.assertEqual(tier(rows,"chim"),"PARTIAL_OR_MISSING")
        self.assertIsNone(hourly_energy(rows,"chim"))
        rows=self.fixture()
        rows[1]["chim_flag"]=3
        self.assertEqual(tier(rows,"chim"),"UNRECOGNIZED_OR_REJECTED_FLAG")
        self.assertIsNone(hourly_energy(rows,"chim"))
        rows=self.fixture()
        rows[1]["chim_flag"]=20
        self.assertEqual(tier(rows,"chim"),"COMPLETE_MIXED_Q0_QC")
        self.assertAlmostEqual(hourly_energy(rows,"chim"),.35)
        self.assertIsNone(hourly_energy(rows[:5],"cglo"))

    def test_physical_screens_warn_but_do_not_mutate_source(self):
        m=physical_screens(.7,.35,.8)
        self.assertFalse(m["suspect"])
        self.assertFalse(m["diffuse_above_global"])
        m=physical_screens(.3,.36,.7)
        self.assertTrue(m["suspect"])
        self.assertTrue(m["diffuse_above_global"])
        n=physical_screens(0,.04,-.9)
        self.assertTrue(n["deep_night_diffuse_above_20W"])
        self.assertFalse(physical_screens(None,.1,.8)["assessable"])
        self.assertEqual(MAX_DIFFUSE_EXCESS_WM2,20.)

    def test_official_solar_day_23_to_23_and_provider_not_independent(self):
        label=date(2007,7,2)
        first=datetime(2007,7,1,23,tzinfo=timezone.utc)
        hours={}
        for i in range(24):
            dt=first+timedelta(hours=i)
            hours[dt]={"ghi_tier":"QC_CONFIRMED","ghi_kwh_m2":.1,"window":"record_start"}
        first_year=datetime(2005,1,1,tzinfo=timezone.utc)
        hours[first_year]={"window":"record_start","ghi_tier":"PARTIAL_OR_MISSING",
            "ghi_kwh_m2":None}
        out=daily_closure(hours,{label:2.4})
        self.assertEqual(len(out),1)
        self.assertTrue(out[0]["tenminute_reconstructed_qc_confirmed_day"])
        self.assertAlmostEqual(out[0]["tenminute_minus_daily_kwh_m2"],0)
        self.assertTrue(out[0]["same_provider_not_independent_ground"])
        self.assertEqual(out[0]["source_day_window"],
                         "GeoSphere cglo_j 23:00 previous UTC to 23:00 labelled UTC")

    def test_no_confirmation_from_missing_provider_qc(self):
        self.assertIn("COMPLETE_UNCHECKED_Q0",SCIENCE_TIERS)
        self.assertIn("record_end",TIMESTAMPS_SUPPORTED)
        self.assertIn("record_start",TIMESTAMPS_SUPPORTED)
        self.assertNotEqual("COMPLETE_UNCHECKED_Q0","QC_CONFIRMED")

if __name__=="__main__":
    unittest.main()
