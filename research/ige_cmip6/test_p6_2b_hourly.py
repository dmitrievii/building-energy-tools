"""P6.2B source safety and historical hourly station 30 QA contracts."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import json
import unittest

from p6_2b_hourly_observations import (
    STATION,FIELDS,GOOD_Q21,metadata_contract,parse_utc,process_year,
)

def fixture(year=1995):
    leap=year%4==0 and (year%100!=0 or year%400==0)
    hours=(366 if leap else 365)*24
    timestamps=[(datetime(year,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat()
                for i in range(hours)]
    units={"tl":"°C","rf":"%","rr":"mm","cglo":"W/m²","ff":"m/s","p":"hPa"}
    metadata={
        "stations":[{"id":STATION,"name":"Graz","altitude":366}],
        "parameters":[{"name":k,"unit":u} for k,u in units.items()]+
                     [{"name":k+"_flag","unit":"code","code_list_ref":"q21"} for k in units],
        "code_lists":{"q21":[{"key":q,"value":str(q)} for q in
                             (0,10,11,12,20,21,22)]}
    }
    vals={"tl":12,"rf":55,"rr":0.3,"cglo":340,"ff":2.4,"p":980}
    data={
        "timestamps":timestamps,
        "features":[{"properties":{"station":STATION,"parameters":{
            **{k:{"unit":units[k],"data":[v]*hours} for k,v in vals.items()},
            **{k+"_flag":{"unit":"code","data":[10]*hours} for k in FIELDS}
        }}}]
    }
    return metadata,data

class HourlyStationContracts(unittest.TestCase):
    def test_1995_8760_utc_hours(self):
        m,d=fixture(1995)
        hourly,monthly,quality=process_year(1995,m,d)
        self.assertEqual(len(hourly),8760)
        self.assertEqual(len(monthly),12)
        self.assertEqual(quality["hour_count"],8760)
        self.assertEqual(quality["counts_by_parameter"]["tl"]["accepted"],8760)
        self.assertEqual(hourly[0]["tl_raw"],12)
        self.assertEqual(hourly[0]["tl_accepted"],12)
        self.assertEqual(monthly[0]["rr_hourly_sum_unverified_mm"],223.2)

    def test_leap_year_8784(self):
        m,d=fixture(2000)
        _,month,q=process_year(2000,m,d)
        self.assertEqual(q["hour_count"],8784)
        self.assertEqual(month[1]["expected_UTC_hours"],696)

    def test_q21_unchecked_is_rejected_and_raw_kept(self):
        m,d=fixture(1995)
        d["features"][0]["properties"]["parameters"]["tl_flag"]["data"][0]=0
        h,month,q=process_year(1995,m,d)
        self.assertEqual(h[0]["tl_raw"],12)
        self.assertIsNone(h[0]["tl_accepted"])
        self.assertEqual(h[0]["tl_q21"],0)
        self.assertEqual(q["counts_by_parameter"]["tl"]["rejected"],1)

    def test_no_flag_means_source_unverified(self):
        m,d=fixture(1995)
        m["parameters"]=[x for x in m["parameters"] if x["name"]!="p_flag"]
        d["features"][0]["properties"]["parameters"].pop("p_flag")
        h,_,q=process_year(1995,m,d)
        self.assertIn("p",q["unavailable_quality_flags"])
        self.assertEqual(q["counts_by_parameter"]["p"]["accepted"],0)
        self.assertIsNone(h[4]["p_accepted"])

    def test_missing_measurement_not_zero(self):
        m,d=fixture(1995)
        d["features"][0]["properties"]["parameters"]["rr"]["data"][0]=None
        h,month,q=process_year(1995,m,d)
        self.assertIsNone(h[0]["rr_raw"])
        self.assertIsNone(h[0]["rr_accepted"])
        self.assertIsNone(month[0]["rr_hourly_sum_unverified_mm"])
        self.assertEqual(q["counts_by_parameter"]["rr"]["raw_null"],1)

    def test_shifted_utc_hour_blocks(self):
        m,d=fixture(1995)
        d["timestamps"][2]=d["timestamps"][1]
        with self.assertRaisesRegex(ValueError,"hourly UTC time index"):
            process_year(1995,m,d)

    def test_wrong_units_not_coerced(self):
        m,d=fixture(1995)
        m["parameters"][0]["unit"]="K"
        with self.assertRaisesRegex(ValueError,"unknown provider parameter/unit"):
            metadata_contract(m)

    def test_no_unapproved_q21_status(self):
        m,d=fixture(1995)
        d["features"][0]["properties"]["parameters"]["cglo_flag"]["data"][0]=33
        with self.assertRaisesRegex(ValueError,"Unknown quality flag"):
            process_year(1995,m,d)

    def test_physically_implausible_value_preserved_but_screened(self):
        m,d=fixture(1995)
        d["features"][0]["properties"]["parameters"]["rf"]["data"][0]=112
        h,_,q=process_year(1995,m,d)
        self.assertEqual(h[0]["rf_raw"],112)
        self.assertIsNone(h[0]["rf_accepted"])
        self.assertEqual(q["counts_by_parameter"]["rf"]["out_of_range"],1)

    def test_non_utc_rejected(self):
        with self.assertRaisesRegex(ValueError,"not explicitly UTC"):
            parse_utc("1995-01-01T01:00:00+01:00")

if __name__=="__main__":
    unittest.main()
