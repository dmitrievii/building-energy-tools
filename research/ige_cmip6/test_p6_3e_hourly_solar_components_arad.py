"""IGE P6.3E NASA POWER solar component physical-source and ARAD scientific gates."""
from __future__ import annotations
import unittest
from datetime import datetime,date,timedelta,timezone
from p6_3e_hourly_solar_components_arad import (
    solar_cos_zenith,component_contract,classify_hour,season_stats,
    COMPONENTS,SITES,ARAD_EVIDENCE,MAX_ALLOWED_GHI_KWH_H,
)

class HourlyComponentsSourceScience(unittest.TestCase):
    def test_noaa_mid_hour_sun_position_utc_and_sensible_seasons(self):
        graz=SITES["graz_station30"]
        calc=lambda y,m,d,h:solar_cos_zenith(
            datetime(y,m,d,h,tzinfo=timezone.utc),
            graz["latitude"],graz["longitude"])
        self.assertGreater(calc(2005,6,21,11),.75)
        self.assertLess(calc(2005,6,21,23),-.1)
        self.assertGreater(calc(2005,6,21,11),calc(2005,12,21,11))
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            solar_cos_zenith(datetime(2005,6,21,11),47.,15.)

    def test_physical_ghi_dni_dhi_closure_night_and_day_screens(self):
        time=datetime(2005,6,21,11,tzinfo=timezone.utc)
        stamp=time.strftime("%Y%m%d%H")
        cz=solar_cos_zenith(time,47.08,15.45)
        comp={"ALLSKY_SFC_SW_DNI":.70,
              "ALLSKY_SFC_SW_DIFF":.11,
              "TOA_SW_DWN":1.30,
              "CLRSKY_SFC_SW_DWN":.90}
        g=comp["ALLSKY_SFC_SW_DNI"]*cz+comp["ALLSKY_SFC_SW_DIFF"]
        r=classify_hour({"ghi_hour_kwh_m2":g},comp,47.08,15.45,stamp)
        self.assertTrue(r["is_daylight_NOAA"])
        self.assertFalse(r["is_deep_night_from_NOAA_and_POWER_TOA"])
        self.assertAlmostEqual(r["closure_signed_residual_kwh_m2_hour"],0)
        self.assertFalse(r["hourly_component_closure_review"])
        err=classify_hour({"ghi_hour_kwh_m2":g+.2},comp,47.08,15.45,stamp)
        self.assertTrue(err["hourly_component_closure_review"])
        night=datetime(2005,6,21,23,tzinfo=timezone.utc)
        components={**comp,"TOA_SW_DWN":0.}
        result=classify_hour({"ghi_hour_kwh_m2":.07},
                             components,47.08,15.45,night.strftime("%Y%m%d%H"))
        self.assertTrue(result["is_deep_night_from_NOAA_and_POWER_TOA"])
        self.assertTrue(result["nighttime_positive_GHI_gt_0p03"])

    def test_missing_source_hour_keeps_month_for_coverage(self):
        row=classify_hour({"ghi_hour_kwh_m2":None},
             {p:None for p in COMPONENTS},47.08,15.45,"2007071403")
        self.assertFalse(row["valid"])
        self.assertEqual((row["year"],row["month"],row["hour_utc"]),(2007,7,3))

    def test_power_companion_contract_full_native_utc_and_units(self):
        first,last=2004,2006
        beginning=date(first,12,31);end=date(last,12,31)
        times=[(beginning+timedelta(days=i)).strftime("%Y%m%d")+f"{hour:02d}"
               for i in range((end-beginning).days+1) for hour in range(24)]
        field={k:100. for k in times}
        site=SITES["graz_station30"]
        payload={"header":{"time_standard":"UTC","start":"20041231",
                   "end":"20061231","sources":["SYN1DEG"],"fill_value":-999},
                 "parameters":{p:{"units":"Wh/m^2"} for p in COMPONENTS},
                 "properties":{"parameter":{p:field.copy() for p in COMPONENTS}},
                 "geometry":{"coordinates":[site["longitude"],site["latitude"],423]}}
        data,meta=component_contract(payload,site,first,last)
        self.assertEqual(len(data),len(times))
        self.assertEqual(meta["missing_by_field"],{})
        self.assertAlmostEqual(data["2005010112"][COMPONENTS[0]],.1)
        payload["header"]["time_standard"]="LST"
        with self.assertRaisesRegex(ValueError,"UTC"):
            component_contract(payload,site,first,last)
        payload["header"]["time_standard"]="UTC"
        del payload["properties"]["parameter"][COMPONENTS[1]]["2005010100"]
        with self.assertRaisesRegex(ValueError,"calendar"):
            component_contract(payload,site,first,last)

    def test_season_summary_missing_hours_and_flags_not_silently_passed(self):
        example=[]
        for day in range(1,32):
            dt=datetime(2005,7,day,11,tzinfo=timezone.utc)
            comp={p:.2 for p in COMPONENTS}
            r=classify_hour({"ghi_hour_kwh_m2":.3},comp,47.08,15.45,
                            dt.strftime("%Y%m%d%H"))
            r["site"]="graz_station30"
            example.append(r)
        example[0]["valid"]=False
        result=next(x for x in season_stats(example,"graz_station30")
                    if x["season"]=="JJA")
        self.assertEqual(result["original_hours"],31)
        self.assertEqual(result["valid_all_component_hours"],30)
        self.assertLess(result["coverage_fraction"],1)
        self.assertGreater(result["daylight_component_closure_review_count"],0)

    def test_arad_is_confirmed_candidate_not_downloaded_source(self):
        self.assertEqual(ARAD_EVIDENCE["starting_date"],"2011-09")
        self.assertIn("NOT_ACQUIRED",ARAD_EVIDENCE["access"])
        self.assertEqual(set(ARAD_EVIDENCE["measured_components"]),
                         {"GHI","DNI","DHI","downwelling_LW"})
        self.assertIn("uni-graz.at",ARAD_EVIDENCE["contact"])

if __name__=="__main__":
    unittest.main()
