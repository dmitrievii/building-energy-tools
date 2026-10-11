"""P6.3D scientific contracts: official q21=0, NASA POWER UTC starts, source units and daily solar boundaries."""
from __future__ import annotations
import unittest,json
from unittest.mock import patch
from datetime import date,datetime,timedelta,timezone
from p6_3d_hourly_satellite_reference_validation import (
    source_contract,http_json,energy_hourly_kwh,validate_power_response,
    hourly_sum,metrics,SITES,WINDOWS,RAW_POWER_KIND
)

class HourlyIndependentSolarContracts(unittest.TestCase):
    def test_nasa_power_messages_array_supported_and_provider_errors_fail(self):
        # Actual POWER API 'messages' field is an array, not a dictionary.
        class Response:
            status=200
            def __init__(self,data):self.data=json.dumps(data).encode("utf8")
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return self.data
        for messages in ([], ["Data provided from NASA POWER"], {"info":"ok"}):
            with self.subTest(messages=messages):
                with patch("p6_3d_hourly_satellite_reference_validation.urlopen",
                           return_value=Response({"messages":messages,"header":{}})):
                    raw,data=http_json("https://example.invalid/original")
                    self.assertEqual(data["messages"],messages)
                    self.assertGreater(len(raw),10)
        for errors in ([{"level":"error","message":"INVALID"}],
                       ["ERROR: provider data unavailable"],
                       {"error":"POWER rejected request"}):
            with self.subTest(errors=errors):
                with patch("p6_3d_hourly_satellite_reference_validation.urlopen",
                           return_value=Response({"messages":errors})):
                    with self.assertRaisesRegex(RuntimeError,
                                               "NO silent fallback"):
                        http_json("https://example.invalid/original")

    def test_approved_geo_daily_does_not_certify_unchecked_hourly(self):
        meta={"code_lists":{"q21":[
           {"key":0,"value":"ungeprüfte Daten"},
           *[{"key":k,"value":"quality verified"} for k in (10,11,12,20,21,22)]]}}
        archived={"hourly_solar_flag_approved":0,"hourly_solar_unverified":87648,
                  "hourly_counts_total":87648}
        verdict=source_contract(meta,archived)
        self.assertEqual(verdict["original_hourly_solar_approved_count"],0)
        self.assertIn("NEVER",verdict["scientific_prohibition"])
        altered=dict(archived,hourly_solar_flag_approved=8)
        with self.assertRaisesRegex(ValueError,"findings changed"):
            source_contract(meta,altered)
        meta["code_lists"]["q21"][0]["value"]="automatisch geprüft"
        with self.assertRaisesRegex(ValueError,"not confirmed"):
            source_contract(meta,archived)

    def test_provider_hourly_radiation_unit_conversion_is_not_daily_kwh(self):
        self.assertAlmostEqual(energy_hourly_kwh(850.,"W/m^2"),.85)
        self.assertAlmostEqual(energy_hourly_kwh(850.,"Wh/m^2"),.85)
        self.assertAlmostEqual(energy_hourly_kwh(.85,"kW-hr/m^2"),.85)
        for unit in ("kW-hr/m^2/day","MJ/m^2/day","unknown"):
            with self.assertRaisesRegex(ValueError,"Unknown NASA POWER"):
                energy_hourly_kwh(1.,unit)
        with self.assertRaisesRegex(ValueError,"non-negative"):
            energy_hourly_kwh(-1.,"Wh/m^2")
        with self.assertRaisesRegex(ValueError,"implausible"):
            energy_hourly_kwh(1600.,"Wh/m^2")

    def test_synchronized_provider_hourly_utc_and_physical_metadata(self):
        first=date(2004,12,31);last=date(2006,12,31)
        days=(last-first).days+1
        period=[(first+timedelta(days=i)).strftime("%Y%m%d")
                for i in range(days)]
        data={stamp+f"{hour:02d}":200. for stamp in period for hour in range(24)}
        temperatures={key:10. for key in data}
        site=SITES["graz_station30"]
        payload={"header":{"time_standard":"UTC","start":"20041231",
             "end":"20061231","fill_value":-999.},
            "parameters":{"ALLSKY_SFC_SW_DWN":{"units":"Wh/m^2"},
                          "T2M":{"units":"C"}},
            "properties":{"parameter":{"ALLSKY_SFC_SW_DWN":data,"T2M":temperatures}},
            "geometry":{"coordinates":[site["longitude"],site["latitude"],430]}}
        parsed,provenance=validate_power_response(payload,site,2004,2006)
        self.assertEqual(len(parsed),days*24)
        self.assertEqual(provenance["hourly_missing"],0)
        self.assertAlmostEqual(parsed["2005010105"]["ghi_hour_kwh_m2"],.2)
        payload["header"]["time_standard"]="LST"
        with self.assertRaisesRegex(ValueError,"non-UTC"):
            validate_power_response(payload,site,2004,2006)
        payload["header"]["time_standard"]="UTC"
        del data["2006010100"]
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            validate_power_response(payload,site,2004,2006)

    def test_start_stamped_power_geosphere_23utc_boundary_correct(self):
        time0=datetime(2005,1,1,0,tzinfo=timezone.utc)
        data={}
        for i in range(-1,49):
            hour=time0+timedelta(hours=i)
            data[hour.strftime("%Y%m%d%H")]={
               "ghi_hour_kwh_m2":(1.0 if i==-1 else 0.2 if i==23 else .1),
               "air_temperature_c":20.,"valid":True}
        solar,t,verified=hourly_sum(data,date(2005,1,1),"geosphere_23_23UTC")
        self.assertTrue(verified)
        self.assertAlmostEqual(solar,1+23*.1)
        solar_mid,_,_=hourly_sum(data,date(2005,1,1),"utc_midnight_00_24UTC")
        self.assertAlmostEqual(solar_mid,23*.1+.2)
        self.assertNotAlmostEqual(solar,solar_mid)

    def test_provider_missing_hour_cannot_be_replaced(self):
        time0=datetime(2005,1,1,tzinfo=timezone.utc)
        data={}
        for i in range(-1,24):
            when=time0+timedelta(hours=i)
            data[when.strftime("%Y%m%d%H")]={
                "ghi_hour_kwh_m2":1.,"air_temperature_c":5.,"valid":True}
        data["2005010107"]["valid"]=False
        total,temperature,valid=hourly_sum(data,date(2005,1,1),
                    "geosphere_23_23UTC")
        self.assertFalse(valid)
        self.assertIsNone(total)
        self.assertIsNone(temperature)

    def test_metrics_are_gridded_not_ground_observed(self):
        rows=[{"site":"graz_station30","season":"JJA",
               "window":"geosphere_23_23UTC","valid_day":True,
               "official_ghi_kwh_m2_day":2.+i*.01,
               "power_ghi_kwh_m2_day":3.+i*.01} for i in range(90)]
        report=metrics(rows,"JJA","geosphere_23_23UTC","graz_station30")
        self.assertEqual(report["source_type"],RAW_POWER_KIND)
        self.assertAlmostEqual(report["mean_bias_kwh_m2_day"],1.)
        self.assertAlmostEqual(report["daily_pearson_r"],1.)
        self.assertFalse(report["qualified_as_accepted_hourly_station_measurement"])
        self.assertEqual(report["coverage_status"],"COMPLETE_OR_NEAR_COMPLETE_REFERENCE")

if __name__=="__main__":
    unittest.main()
