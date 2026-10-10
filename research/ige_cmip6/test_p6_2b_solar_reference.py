"""P6.2B solar 20-year official source and no-synthetic-GHI science contracts."""
from __future__ import annotations
import calendar,math
from datetime import date,timedelta
import unittest
from collections import defaultdict

from p6_2b_solar_daily_reference import (
    meta_contract,parse_source,PERIODS,KWH_PER_J_CM2,
)
from p6_2b_solar_reference_audit import monthly_closure

def meta():
    return {
        "stations":[{"id":30,"name":"Graz Universität/Heinrichstraße","lat":47.08,"lon":15.448056}],
        "parameters":[
            {"name":"cglo_j","unit":"J/cm²",
             "description":"Globalstrahlung, kalibrierte 24-Stundensumme aus den Stundenwerten 0-24 Uhr MOZ (23 Vortag - 23 Tag UTC)"},
            {"name":"cglo_j_flag","unit":"code"},
        ],
        "code_lists":{"q21":[{"key":k,"value":str(k)} for k in (0,10,11,12,20,21,22)]}
    }

def source(first=1995,last=1999):
    start=date(first,1,1);end=date(last,12,31);days=(end-start).days+1
    stamp=[(start+timedelta(days=i)).isoformat()+"T00:00+00:00" for i in range(days)]
    return {"timestamps":stamp,"features":[{"properties":{
        "station":30,"parameters":{
            "cglo_j":{"unit":"J/cm²","data":[360.]*days},
            "cglo_j_flag":{"unit":"code","data":[20]*days},
        },
    }}]}

def synthetic_twenty_years():
    daily=[]
    for year in range(1995,2015):
        for month in range(1,13):
            for day in range(1,calendar.monthrange(year,month)[1]+1):
                daily.append({"year":year,"month":month,"day":day,"trusted_daily_kwh_m2":2.5})
    official=[]
    for year in range(1995,2015):
        for month in range(1,13):
            official.append({"year":year,"month":month,"official_q21":20,
                             "official_monthly_kwh_m2_if_checked":2.5*calendar.monthrange(year,month)[1]})
    return daily,official

class SourceSolarTests(unittest.TestCase):
    def test_own_source_unit_conversion(self):
        self.assertAlmostEqual(2738*KWH_PER_J_CM2,2738/360)
        self.assertAlmostEqual(360*KWH_PER_J_CM2,1.)

    def test_original_five_years_all_quality_approved(self):
        m=meta();raw=source()
        rows,qa=parse_source(raw,m,1995,1999)
        self.assertEqual(len(rows),1826)
        self.assertEqual(qa["quality_counts"]["accepted"],1826)
        self.assertEqual(qa["quality_counts"]["rejected"],0)
        self.assertEqual(qa["daily_time_boundaries"],m["parameters"][0]["description"])
        self.assertAlmostEqual(rows[0]["cglo_j_accepted_kwh_m2"],1.)

    def test_source_unchanged_and_qc_zero_never_accepted(self):
        m=meta();raw=source()
        raw["features"][0]["properties"]["parameters"]["cglo_j_flag"]["data"][0]=0
        raw["features"][0]["properties"]["parameters"]["cglo_j"]["data"][1]=None
        rows,q=parse_source(raw,m,1995,1999)
        self.assertEqual(q["quality_counts"]["rejected"],2)
        self.assertEqual(rows[0]["cglo_j_raw_J_cm2"],360.)
        self.assertIsNone(rows[0]["cglo_j_accepted_kwh_m2"])
        self.assertIsNone(rows[1]["cglo_j_accepted_kwh_m2"])

    def test_unknown_source_units_fail_closed(self):
        m=meta();m["parameters"][0]["unit"]="W/m²"
        with self.assertRaisesRegex(ValueError,"unit changed"):
            meta_contract(m)

    def test_moz_hour_definition_change_rejected(self):
        m=meta();m["parameters"][0]["description"]="Global irradiance at local noon"
        with self.assertRaisesRegex(ValueError,"interval definition changed"):
            meta_contract(m)

    def test_incomplete_daily_calendar_rejected(self):
        m=meta();raw=source()
        raw["timestamps"].pop()
        with self.assertRaisesRegex(ValueError,"date count"):
            parse_source(raw,m,1995,1999)

    def test_one_bad_utc_daily_label_rejected(self):
        m=meta();raw=source()
        raw["timestamps"][1]="1995-01-03T00:00+00:00"
        with self.assertRaisesRegex(ValueError,"missing/shifted"):
            parse_source(raw,m,1995,1999)

    def test_daily_to_monthly_closure(self):
        daily,official=synthetic_twenty_years()
        rows,stats=monthly_closure(daily,official)
        self.assertEqual(len(rows),240)
        self.assertEqual(stats["days_observed"],7305)
        self.assertEqual(stats["months_with_all_daily_checked"],240)
        self.assertEqual(stats["years_with_12_checked_daily_months"],list(range(1995,2015)))
        self.assertAlmostEqual(stats["monthly_max_abs_difference_kwh_m2"],0.)

    def test_incomplete_station_month_never_scaled_to_complete_sum(self):
        daily,official=synthetic_twenty_years()
        daily[0]["trusted_daily_kwh_m2"]=None
        rows,stats=monthly_closure(daily,official)
        self.assertEqual(stats["months_with_all_daily_checked"],239)
        self.assertIsNone(rows[0]["observed_daily_sum_kwh_m2_if_complete"])
        self.assertIsNone(rows[0]["daily_sum_minus_monthly_kwh_m2"])
        self.assertNotIn(1995,stats["years_with_12_checked_daily_months"])

    def test_daily_vs_official_month_discrepancy_not_forced_to_zero(self):
        daily,official=synthetic_twenty_years()
        official[0]["official_monthly_kwh_m2_if_checked"]*=1.1
        rows,stats=monthly_closure(daily,official)
        self.assertLess(rows[0]["daily_sum_minus_monthly_kwh_m2"],0)
        self.assertGreater(stats["monthly_max_abs_difference_kwh_m2"],0)

if __name__=="__main__":unittest.main()
