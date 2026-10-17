"""IGE P8.4D EPW clock/direction/QC/license and native EnergyPlus contracts."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
import p8_4d_epw_wind_qualification as d
import p8_4d_native_energyplus_wind as e
import p8_4c_future_wind_baseline as c


def headers():
    return [
        ["LOCATION","Graz","Styria","AUT","P8D_RESEARCH_ONLY","999999",46.875,15.375,1,366],
        ["DESIGN CONDITIONS","0"],
        ["TYPICAL/EXTREME PERIODS","0"],
        ["GROUND TEMPERATURES","0"],
        ["HOLIDAYS/DAYLIGHT SAVINGS","No","0","0","0"],
        ["COMMENTS 1","Test fixture not measured EPW"],
        ["COMMENTS 2","Synthetic weather, unit tests only"],
        ["DATA PERIODS","1","1","Data","Sunday","1/1","12/31"],
    ]


def fixture():
    rows=[]
    begin=dt.date(2013,1,1)
    for i in range(d.N):
        date=begin+dt.timedelta(days=i//24)
        speed=.4 if i%5==0 else 2.0
        direction=999 if i%5==0 else (i*23.5)%360.
        x=["2013",str(date.month),str(date.day),
            str(i%24+1),"60","?9"*11,
            "12","5","63","98000","0","0","310",
            "0","0","0","0","0","0","9999",f"{direction:.3f}",
            f"{speed:.3f}","99","99","9999","99999","9",
            "999999999","10","0.15","0","0","0.2","0","99"]
        assert len(x)==35
        rows.append(x)
    return rows


class P8DWindContracts(unittest.TestCase):
    def test_EPWC_8760_by_35_strict_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"synthetic.epw"
            d.write_epw(path,headers(),fixture())
            _,rows,meta=d.read_epw(path)
            self.assertEqual(len(rows),8760)
            self.assertEqual(meta["year"],2013)
            self.assertEqual(meta["original_noncalm_missing_direction_hours"],0)

    def test_explicit_missing_direction_is_preserved(self):
        a=fixture()
        a[1][20]="999"
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.epw"
            d.write_epw(p,headers(),a)
            _,r,m=d.read_epw(p)
        self.assertEqual(m["original_noncalm_missing_direction_hours"],1)
        self.assertEqual(r[1][20],"999")

    def test_negative_source_wind_rejected(self):
        rows=fixture()
        rows[2][21]="-1"
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.epw";d.write_epw(p,headers(),rows)
            with self.assertRaisesRegex(ValueError,"NEGATIVE"):
                d.read_epw(p)

    def test_missing_source_wind_sentinel_rejected(self):
        rows=fixture()
        rows[2][21]="999"
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.epw";d.write_epw(p,headers(),rows)
            with self.assertRaisesRegex(ValueError,"MISSING"):
                d.read_epw(p)

    def test_missing_or_jumping_EPW_hour_rejected(self):
        rows=fixture()
        rows[123][3]="1"
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.epw";d.write_epw(p,headers(),rows)
            with self.assertRaisesRegex(ValueError,"CLOCK"):
                d.read_epw(p)

    def test_wrong_row_count_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x.epw"
            d.write_epw(p,headers(),fixture()[:-1])
            with self.assertRaisesRegex(ValueError,"8760"):
                d.read_epw(p)

    def test_nonfinite_or_invalid_azimuth_rejected(self):
        for direction in ("361","nan","-1"):
            rows=fixture()
            rows[2][20]=direction
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/"x.epw";d.write_epw(p,headers(),rows)
                with self.assertRaisesRegex(ValueError,"FROM_AZIMUTH"):
                    d.read_epw(p)

    def test_cannot_claim_public_analogue_as_proprietary(self):
        with self.assertRaisesRegex(ValueError,"LICENSED_REQUIRES"):
            d.authenticate("any.epw",{"sha256":"x"},None,"licensed_local")

    def test_license_provenance_and_sha_both_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"source.json"
            p.write_text(json.dumps({"provider":"Meteonorm",
                "sha256":"fake","user_authorized_research_use":True}))
            with self.assertRaisesRegex(ValueError,"LICENSE_OR_SHA"):
                d.authenticate("private.epw",{"sha256":"other"},p,"licensed_local")

    def test_public_original_derived_hash_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/"synthetic.epw"
            d.write_epw(base,headers(),fixture())
            report=Path(tmp)/"p7b5_science_audit.json"
            report.write_text(json.dumps({"production_epw_ready":False,
                "derived_sha256":{base.name:d.sha(base)}}))
            k=d.authenticate(base,{"sha256":d.sha(base)},report,"p7b5_public")
            self.assertFalse(k["authenticated_licensed_meteonorm"])
            report.write_text(json.dumps({"production_epw_ready":False,
                "derived_sha256":{base.name:"tampered"}}))
            with self.assertRaisesRegex(ValueError,"IMMUTABLE_SHA"):
                d.authenticate(base,{"sha256":d.sha(base)},report,"p7b5_public")

    def test_no_other_EPW_field_mutated_under_future_ratios(self):
        ratio,_=c.read_registered_wind_ratios(c.SIGNALS)
        a=fixture()
        _,r=d.monthly_scalar_wind_morph(headers(),a,"CanESM5","ssp245-2040-2059",ratio)
        self.assertEqual(len(r["monthly"]),12)
        self.assertLess(r["maximum_monthly_speed_balance_mps"],.001)
        # This test uses original real previously registered ratio values.
        b,_=d.monthly_scalar_wind_morph(headers(),a,"CanESM5","ssp245-2040-2059",ratio)
        self.assertEqual(a[0][20],"999")
        self.assertTrue(r["wind_direction_preserved_exactly"])
        self.assertTrue(r["nonwind_34_epw_fields_preserved_exactly"])
        self.assertEqual(r["model"],"CanESM5")

    def test_source_calm_azimuth_promoted_is_unqualified(self):
        a=fixture()
        ratios={(model,window,month):1.5 for model in
                ("CanESM5",) for window in ("ssp245-2040-2059",)
                for month in range(1,13)}
        _,r=d.monthly_scalar_wind_morph(headers(),a,"CanESM5","ssp245-2040-2059",ratios)
        self.assertGreater(r["newly_promoted_unqualified_source_calm_direction_hours"],0)
        self.assertFalse(r["EPW_wind_physical_direction_quality_pass"])

    def test_numeric_original_calm_direction_still_unqualified_when_promoted(self):
        a=fixture()
        for x in a:
            if float(x[21])<.5:x[20]="75"
        ratios={("CanESM5","ssp245-2040-2059",m):1.5 for m in range(1,13)}
        _,r=d.monthly_scalar_wind_morph(headers(),a,"CanESM5","ssp245-2040-2059",ratios)
        self.assertEqual(r["morphed_noncalm_missing_direction_hours"],0)
        self.assertFalse(r["EPW_wind_physical_direction_quality_pass"])

    def test_strong_wind_persistence_and_16_sector_rose(self):
        a=fixture()
        assert len(d.stats(a)["rose16"])==16
        self.assertEqual(d.stats(a)["high_wind_3h_rolling_windows"],0)

    def test_three_wind_only_counterfactuals_preserve_header_and_nonwind_fields(self):
        a=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            m=d.counterfactuals(headers(),a,Path(tmp))
            self.assertEqual(len(m),3)
            for x in (.5,1.,1.5):
                _,b,_=d.read_epw(Path(tmp)/f"research_wind_only_x{x:.1f}.epw")
                self.assertTrue(all(r[k]==s[k] for r,s in zip(a,b)
                    for k in range(35) if k!=21))

    def test_generated_EnergyPlus_fixture_contains_wind_coefficients(self):
        f=("! 1ZoneUncontrolled.idf\nVersion,26.2;\n"
           "SimulationControl,No,No,No,Yes,No;\n"
           "Site:Location,Denver,39,-105,-7,1800;\n"
           "RunPeriod,Annual,1,1,,12,31;\n"
           "Zone,ZONE ONE;\n")
        win=e.build_model(f,True);fixed=e.build_model(f,False)
        self.assertIn("0.10, 0.0, 0.20, 0.0;",win)
        self.assertIn("1.0, 0.0, 0.0, 0.0;",fixed)
        self.assertNotIn("0.10, 0.0, 0.20, 0.0;",fixed)
        self.assertIn("Zone Infiltration Standard Density Volume Flow Rate",win)

    def test_native_EnergyPlus_release_hash_from_official_workflow(self):
        self.assertEqual(e.OFFICIAL_RELEASE,"v26.2.0")
        self.assertEqual(len(e.OFFICIAL_TARBALL_SHA256),64)
        self.assertEqual(len(e.CASES),5)

    def test_never_claim_natural_ventilation_from_infiltration_IDF(self):
        f=("! 1ZoneUncontrolled.idf\nVersion,26.2;\n"
           "SimulationControl,No,No,No,Yes,No;\n"
           "Site:Location,Denver,39,-105,-7,1800;\n"
           "RunPeriod,Annual,1,1,,12,31;\n"
           "Zone,ZONE ONE;\n")
        test=e.build_model(f,True)
        self.assertNotIn("ZoneVentilation:WindandStackOpenArea",test)
        self.assertNotIn("ZoneVentilation:DesignFlowRate",test)


if __name__=="__main__":
    unittest.main()
