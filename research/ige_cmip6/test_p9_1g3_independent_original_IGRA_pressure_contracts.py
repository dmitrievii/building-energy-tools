"""IGE P9.1G3 independent original IGRA fixed-width radiosonde physical contracts."""
import io
import math
import unittest
import zipfile
import p9_1g3_independent_IGRA_era5_925_850 as g


def igra_level(p_pa,z_m,temp_tenth_C,quality="B"):
    line=list(" "*51)
    line[0]="1";line[1]="0"
    line[9:15]=list(f"{p_pa:6d}")
    line[16:21]=list(f"{z_m:5d}")
    line[22:27]=list(f"{temp_tenth_C:5d}")
    line[27]=quality
    return "".join(line)+"\n"


def sample_archive(t925=60,t850=-5,z925=800,z850=1500):
    header=f"#{g.STATION} 2019 01 10 00 0000 {2:4d} ncdc-test\n"
    assert header[13:17]=="2019",(repr(header),header[13:17])
    assert header[32:36].strip()=="2",(repr(header),header[32:36])
    raw=header+igra_level(92500,z925,t925)+igra_level(85000,z850,t850)
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as zip:
        zip.writestr(g.STATION+"-data.txt",raw)
    return output.getvalue()


class IGRARealArchiveContracts(unittest.TestCase):
    def test_01_fixed_original_soundings_site_hours_pressure_levels(self):
        self.assertEqual(g.STATION,"GMM00010393")
        self.assertEqual(g.LEVELS,(925,850))
        self.assertEqual(len(g.fixed_slots()),28)

    def test_02_source_only_original_NCEI_HTTPS(self):
        self.assertTrue(g.ZIP_URL.startswith("https://www.ncei.noaa.gov/pub/data/igra/data/data-por/"))
        with self.assertRaisesRegex(ValueError,"ONLY_ORIGINAL_IGRA"):
            g.archive_source("https://example.com/fake.zip",10)

    def test_03_correct_fixed_original_station_geometry(self):
        meta=b"GMM00010393 52.2167 14.1167 112.0 LINDENBERG 1905 2026 101418"
        o=g.parse_metadata(meta)
        self.assertAlmostEqual(o["lat"],52.2167)
        self.assertAlmostEqual(o["station_original_elevation_m"],112.)

    def test_04_missing_station_metadata_fails_not_invented(self):
        with self.assertRaisesRegex(ValueError,"STATION_MISSING"):
            g.parse_metadata(b"other")

    def test_05_fixed_original_IGRA2_925_850_T_1decimal_and_GPH(self):
        rows,origin=g.extract_original_igra_925_850(sample_archive(),112.)
        self.assertEqual(len(rows),1)
        row=rows["2019-01-10T00:00"]
        self.assertEqual(row[925]["temperature_c"],6.)
        self.assertEqual(row[850]["temperature_c"],-.5)
        self.assertEqual(row[850]["geopotential_height_m"],1500.)
        self.assertEqual(origin["original_IGRA_T925_T850_QA_flags"],{"B":2})

    def test_06_IGRA_QC_deleted_is_not_promoted_to_measured_sounding(self):
        rows,o=g.extract_original_igra_925_850(sample_archive(t850=-8888),112.)
        self.assertEqual(len(rows),0)
        self.assertEqual(o["n_true_source_headers_at_registered_nominal_hours"],1)

    def test_07_below_station_pressure_level_is_excluded(self):
        rows,o=g.extract_original_igra_925_850(sample_archive(z925=115),112.)
        self.assertEqual(len(rows),0)

    def test_08_exact_925_850_potential_temperature_gradient_uses_K_and_heights(self):
        levels={925:{"temperature_c":5.,"geopotential_height_m":850.},
                850:{"temperature_c":1.,"geopotential_height_m":1500.}}
        p=g.profile_gradient(levels)
        self.assertAlmostEqual(p["temperature_gradient_K_km"],-4/650*1000)
        self.assertTrue(math.isfinite(p["theta_gradient_K_km"]))

    def test_09_negative_temperature_lapse_cannot_be_called_positive_T_inversion(self):
        levels={925:{"temperature_c":5.,"geopotential_height_m":850.},
                850:{"temperature_c":1.,"geopotential_height_m":1500.}}
        self.assertFalse(g.profile_gradient(levels)["model_resolved_positive_temp_gradient"])

    def test_10_no_interpolation_if_reported_level_missing(self):
        rows,_=g.extract_original_igra_925_850(sample_archive(z850=-9999),112.)
        self.assertEqual(len(rows),0)

if __name__=="__main__":
    unittest.main()
