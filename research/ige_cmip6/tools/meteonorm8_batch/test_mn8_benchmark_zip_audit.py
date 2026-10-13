"""Synthetic QA for P8 private Meteonorm EPW ZIP, no licensed weather."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from mn8_benchmark_zip_audit import audit_epw, audit_zip, match_site, scenario_from_name, seed_from_name

def fake_epw(n=8760,temperature=12,lat=46.983,lon=15.45):
    lines=[
        "LOCATION,Graz,-,AUT,SYNTHETIC,00000,"+str(lat)+","+str(lon)+",1,332"
    ] + ["DESIGN CONDITIONS,0"]*7
    for day in range(365):
        import datetime
        d=datetime.date(2005,1,1)+datetime.timedelta(days=day)
        for hour in range(1,25):
            row=["2005",str(d.month),str(d.day),str(hour),"60","SYNTHETIC",
                 str(temperature),"5","63","97000","0","0","300","0","0","0",
                 "0","0","0","9999","180","2","5","4","9999","99999",
                 "9","999999999","10","0.15","0","0","0.2","0","99"]
            lines.append(",".join(row))
            if len(lines)==8+n:
                break
        if len(lines)==8+n:
            break
    return ("\n".join(lines)+"\n").encode()

class Tests(unittest.TestCase):
    def test_scenario_recognition(self):
        self.assertEqual(scenario_from_name("Graz-hour_RCP4.5_2050_seed1.epw"),"rcp45_2050")
        self.assertEqual(scenario_from_name("IGESonnblick_rcp85_2100_seed03.epw"),"rcp85_2100")
        self.assertEqual(scenario_from_name("Graz_contemporary_seed01.epw"),"contemporary")
    def test_seed_recognition(self):
        self.assertEqual(seed_from_name("Tripoli_RCP8.5_2100_seed03.epw"),3)
    def test_site_match(self):
        self.assertEqual(match_site(46.983,15.45),"graz")
        self.assertEqual(match_site(37.527,22.412),"tripoli_greece")
        self.assertIsNone(match_site(0,0))
    def test_valid_weather_structure(self):
        x=audit_epw(fake_epw(),"Graz_contemporary_seed01.epw")
        self.assertEqual(x["hour_rows"],8760)
        self.assertEqual(x["unique_hours"],8760)
        self.assertEqual(x["status"],"WARN" if x["warnings"] else "PASS")
        self.assertEqual(x["site"],"graz")
    def test_invalid_hour_count(self):
        x=audit_epw(fake_epw(n=10),"Graz_contemporary_seed01.epw")
        self.assertEqual(x["status"],"FAIL")
    def test_zip_no_epw_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"input.zip"
            with zipfile.ZipFile(p,"w") as z:
                z.writestr("README.txt","hello")
            with self.assertRaisesRegex(ValueError,"No .epw"):
                audit_zip(p)
    def test_zip_single_pass_missing_19(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"input.zip"
            with zipfile.ZipFile(p,"w") as z:
                z.writestr("Graz_contemporary_seed01.epw",fake_epw())
            r=audit_zip(p)
            self.assertEqual(r["epw_count"],1)
            self.assertEqual(len(r["missing_seed1"]),19)
            self.assertEqual(r["unassigned_filename_scenarios_or_seeds"],[])
            self.assertTrue(r["no_network_calls"])

if __name__=="__main__":
    unittest.main()
