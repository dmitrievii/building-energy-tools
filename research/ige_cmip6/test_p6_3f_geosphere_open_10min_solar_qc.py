"""IGE P6.3F open 10-min radiation: no fabricated flags or time convention."""
from __future__ import annotations
import unittest
from datetime import datetime,date,timedelta,timezone
from p6_3f_geosphere_open_10min_solar_qc import (
    metadata_contract,decode_year,hourly_aggregate,parse_utc,metric,
    QC_ACCEPTED,WINDOWS,SEASONS,station_source_identity
)

class OpenStationSolarQC(unittest.TestCase):
    def make_metadata(self):
        return {"parameters":[
             {"name":"cglo","unit":"W/m²"},
             {"name":"chim","unit":"W/m²"},
             {"name":"cglo_flag","unit":"code","code_list_ref":"q21"},
             {"name":"chim_flag","unit":"code","code_list_ref":"q21"}],
           "code_lists":{"q21":[
              {"key":0,"value":"ungeprüfte Daten"},
              *({"key":v,"value":"automatisch oder manuell geprüft"} for v
                in sorted(QC_ACCEPTED))]},
           "stations":[{"id":30,"name":"Graz Universität"},
                       {"id":16412,"name":"Graz reference site"}]}

    def test_metadata_requires_separate_diffuse_original_and_qc(self):
        _,legend,stations=metadata_contract(self.make_metadata())
        self.assertIn(16412,stations)
        self.assertIn(0,legend)
        m=self.make_metadata()
        m["parameters"]=[p for p in m["parameters"] if p["name"]!="chim_flag"]
        with self.assertRaisesRegex(ValueError,"per-parameter QC"):
            metadata_contract(m)
        m=self.make_metadata();m["parameters"][1]["unit"]="J/cm²"
        with self.assertRaisesRegex(ValueError,"variable/unit"):
            metadata_contract(m)

    def test_timestamp_explicit_utc_and_ten_min_grid(self):
        expected=datetime(2005,1,1,tzinfo=timezone.utc)
        self.assertEqual(parse_utc("2005-01-01T00:00:00Z"),expected)
        for invalid in ("2005-01-01T00:00:00","2005-01-01T02:00:00+02:00",
                        "2005-01-01T00:05:00Z"):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                parse_utc(invalid)

    def test_six_of_six_per_parameter_and_unchecked_zero_is_never_accepted(self):
        t=datetime(2012,7,1,12,tzinfo=timezone.utc)
        rows=[]
        for i in range(6):
            rows.append({"timestamp":t+timedelta(minutes=10*i),"station_id":30,
               "cglo":600.,"chim":300.,"cglo_flag":20,
               "chim_flag":0 if i==2 else 20,
               "cglo_accepted":True,
               "chim_accepted":i!=2})
        result=hourly_aggregate(rows,"record_start",2012)[t]
        self.assertTrue(result["cglo_qualified"])
        self.assertAlmostEqual(result["cglo_kwh_m2"],.6)
        self.assertFalse(result["chim_qualified"])
        self.assertIsNone(result["chim_kwh_m2"])
        self.assertFalse(result["joint_qualified"])
        end_label=hourly_aggregate(rows,"record_end",2012)
        self.assertIsNone(end_label[t]["cglo_kwh_m2"])
        self.assertEqual(end_label[t]["minute_slots"],5)
        self.assertNotEqual(result["minute_slots"],end_label[t]["minute_slots"])

    def test_original_full_year_calendar_and_quality_flags(self):
        year=2005
        beginning=datetime(year,1,1,tzinfo=timezone.utc)
        n=365*144
        stamps=[(beginning+timedelta(minutes=i*10)).isoformat() for i in range(n)]
        def p(values,unit=None):
            return {"data":values,"unit":unit}
        payload={"timestamps":stamps,"features":[{"properties":{
             "station":30,"parameters":{
                 "cglo":p([100.]*n,"W/m²"),
                 "chim":p([50.]*n,"W/m²"),
                 "cglo_flag":p([0]*n),
                 "chim_flag":p([20]*n)}}}]}
        rows,qc=decode_year(payload,30,year)
        self.assertEqual(len(rows),n)
        self.assertEqual(qc["cglo"]["approved_slots"],0)
        self.assertEqual(qc["chim"]["approved_slots"],n)
        self.assertEqual(qc["cglo"]["q_0"],n)
        self.assertEqual(len(hourly_aggregate(rows,"record_start",year)),8760)
        # Do not repair a missing UTC timestamp by shifting.
        payload["timestamps"][6]=payload["timestamps"][5]
        with self.assertRaisesRegex(ValueError,"shifted"):
            decode_year(payload,30,year)

    def test_combined_parent_and_individual_child_not_independent_when_original_data_identical(self):
        origin=datetime(2012,6,12,12,tzinfo=timezone.utc)
        raw=[{"timestamp":origin+timedelta(minutes=10*i),"cglo":400.,
              "chim":None,"cglo_flag":12,"chim_flag":0} for i in range(6)]
        duplicate=[dict(r) for r in raw]
        self.assertTrue(station_source_identity(raw,duplicate))
        duplicate[2]["cglo"]=403.
        self.assertFalse(station_source_identity(raw,duplicate))
        duplicate[2]["cglo"]=400.
        duplicate[4]["chim_flag"]=12
        self.assertFalse(station_source_identity(raw,duplicate))
        self.assertFalse(station_source_identity(raw,duplicate[:5]))

    def test_satellite_comparison_has_null_scores_with_no_verified_observations(self):
        self.assertEqual(metric([])["n"],0)
        self.assertIsNone(metric([])["mae"])
        m=metric([(.2,.3)]*40)
        self.assertEqual(m["n"],40)
        self.assertAlmostEqual(m["bias"],.1)
        self.assertIsNone(m["pearson_r"])
        m=metric([(float(k),float(k)+1.) for k in range(40)])
        self.assertAlmostEqual(m["pearson_r"],1.)
        self.assertAlmostEqual(m["rmse"],1.)

if __name__=="__main__":
    unittest.main()
