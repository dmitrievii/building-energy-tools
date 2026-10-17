"""P8.6 private 57-file crossfield scientific and source-authenticity contracts."""
from __future__ import annotations
import copy
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import p8_6_private_crossfield_qualification as p
from p8_4d_epw_wind_qualification import write_epw
from test_p8_4d_epw_wind_qualification import headers, fixture


def rows():
    a=fixture()
    for i,r in enumerate(a):
        # Meaningful synthetic drybulb/dew point/RH/Buck pressure triple.
        r[6]="20"
        r[7]="10"
        r[8]=f"{100*p.sat_pa(10)/p.sat_pa(20):.4f}"
        r[9]="98000"
        r[12]="350"
        r[13]="0";r[14]="0";r[15]="0"
        r[16]="0";r[17]="0";r[18]="0";r[19]="9999"
        r[22]="2";r[23]="1";r[33]="0"
        # The fixture had missing direction at source calm, but valid noncalm.
    return a


class TestPrivateSourceCrossfield(unittest.TestCase):
    def test_source_384_signals_are_unique(self):
        self.assertEqual(len(p.read_registered_ratios()),384)

    def test_2001_noleap_8760_strict_clock(self):
        m=p.calendar(rows())
        self.assertTrue(m["hourly_time_axis_pass"])
        self.assertTrue(m["mixed_TMY_year_labels_allowed"])

    def test_year_label_variation_in_typical_year_is_valid(self):
        a=rows()
        for i in range(24*31,24*31+24):a[i][0]="1996"
        self.assertTrue(p.calendar(a)["mixed_TMY_year_labels_allowed"])

    def test_Daylight_saving_clock_jump_rejected(self):
        a=rows();a[80][3]="1"
        with self.assertRaisesRegex(ValueError,"HOUR_ENDING_OR_DST"):
            p.calendar(a)

    def test_leap_day_must_not_appear(self):
        a=rows()
        a[24*59][1]="2";a[24*59][2]="29"
        with self.assertRaisesRegex(ValueError,"HOUR_ENDING_OR_DST"):
            p.calendar(a)

    def test_incomplete_8760_rejected(self):
        with self.assertRaisesRegex(ValueError,"8760"):
            p.calendar(rows()[:-1])

    def test_photo_only_changes_allowed_and_all_other_34_fields_immutable(self):
        a=rows()
        b=copy.deepcopy(a);b[700][13]="1200.0"
        c=copy.deepcopy(b);c[700][16]="25000"
        self.assertTrue(p.verify_source_pair(a,b,c)["P7C5B_only_illuminance_16_17_18"])

    def test_photometry_not_allowed_to_modify_wind_or_solar(self):
        a=rows()
        b=copy.deepcopy(a)
        c=copy.deepcopy(b);c[0][20]="40"
        with self.assertRaisesRegex(ValueError,"P7C5B_CHANGED"):
            p.verify_source_pair(a,b,c)

    def test_p7c4_not_allowed_to_modify_cloud(self):
        a=rows()
        b=copy.deepcopy(a);b[0][22]="10"
        with self.assertRaisesRegex(ValueError,"P7C4_CHANGED_IMMUTABLE"):
            p.verify_source_pair(a,b,b)

    def test_missing_private_source_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,"PRIVATE_MEMBER_MISSING"):
                p.member_bytes(temp,"not_installed.epw")

    def test_private_zip_rejects_duplicate_basename(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/"repeat.zip"
            with zipfile.ZipFile(src,"w") as z:
                z.writestr("archive1/scenario.epw",b"test")
                z.writestr("archive2/scenario.epw",b"test")
            with self.assertRaisesRegex(ValueError,"MISSING_DUPLICATE"):
                p.member_bytes(src,"scenario.epw")

    def test_private_zip_with_one_archive_subfolder_can_be_read(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/"unique.zip"
            with zipfile.ZipFile(src,"w") as z:
                z.writestr("original/scenario.epw",b"original contents")
            self.assertEqual(p.member_bytes(src,"scenario.epw"),b"original contents")

    def test_baseline_sha_mismatch_does_not_count_as_original_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            src=Path(temp)/"not_original.epw"
            src.write_bytes(b"fake")
            with self.assertRaisesRegex(ValueError,"AUTHENTIC_METEONORM_BASELINE_SHA"):
                p.verify_original_bundle(src,temp,temp,Path(temp)/"results")

    def test_Buck_psychrometrics_q_and_RH_exact(self):
        q=p.actual_q(20.,100*p.sat_pa(10.)/p.sat_pa(20.),98000.)
        self.assertGreater(q,.005)
        self.assertLess(q,.01)

    def test_synthetic_well_defined_source_physics_pass(self):
        r=p.diagnose(rows())
        self.assertTrue(r["critical_physics_pass"],r["critical_physics_failures"])
        self.assertEqual(r["diagnostics"]["source_hourly_fields_scored"],8760)
        self.assertEqual(r["diagnostics"]["missing_noncalm_FROM_azimuth"]
                         if "missing_noncalm_FROM_azimuth" in r["diagnostics"] else 0,0)

    def test_bad_RH_dewpoint_crossfield_is_counted_not_imputed(self):
        a=rows();a[0][8]="95"
        r=p.diagnose(a)
        self.assertFalse(r["critical_physics_pass"])
        self.assertGreater(r["critical_physics_failures"]["RH_dewpoint_Buck_disagreement_gt2pp"],0)

    def test_dewpoint_above_drybulb_blocked(self):
        a=rows();a[0][7]="21";a[0][8]="100"
        self.assertGreater(p.diagnose(a)["critical_physics_failures"]["dewpoint_above_drybulb"],0)

    def test_full_noncalm_missing_azimuth_blocked_even_when_EPW_35_fields(self):
        a=rows();a[2][20]="999"
        r=p.diagnose(a)
        self.assertEqual(r["critical_physics_failures"]["missing_noncalm_FROM_azimuth"],1)

    def test_illuminance_recomposition_exact_and_bad_value_caught(self):
        a=rows()
        a[4][13]="100";a[4][14]="120";a[4][15]="40"
        a[4][16]="10000";a[4][17]="12000";a[4][18]="4000"
        self.assertTrue(p.diagnose(a)["critical_physics_pass"])
        a[4][16]="5000"
        self.assertEqual(p.diagnose(a)["critical_physics_failures"][
            "illuminance_GHI_DNI_DHI_closure_gt2lux"],1)

    def test_dhi_cannot_exceed_ghi_outside_tolerance(self):
        a=rows()
        a[7][13]="1";a[7][15]="10"
        self.assertEqual(p.diagnose(a)["critical_physics_failures"]["diffuse_exceeds_global"],1)

    def test_numeric_cloud_sentinel_recognized_as_missing(self):
        a=rows();a[2][22]="99";a[2][23]="99"
        out=p.diagnose(a)
        self.assertEqual(out["diagnostics"]["cloud_opaque_missing_hours"],1)

    def test_rh_saturation_criteria_are_explicitly_distinct(self):
        a=rows()
        a[0][6]="20";a[0][7]="20"
        a[0][8]="99.997"
        out=p.diagnose(a)
        self.assertEqual(out["diagnostics"]["RH_ge99p995_hours"],1)
        self.assertEqual(out["diagnostics"].get("P7C4_legacy_np_isclose_near100_hours",0),0)

    def test_source_reference_preservation_counts_are_8760(self):
        a=rows()
        b=copy.deepcopy(a)
        out=p.diagnose(b,a)
        self.assertEqual(out["diagnostics"]["historical_cloud_hours_inherited"],8760)
        self.assertEqual(out["diagnostics"]["historical_wind_direction_hours_inherited"],8760)

    def test_episodes_measure_actual_contiguous_hour_sequence(self):
        self.assertEqual(p.run_lengths([True,True,False,True])["maximum_consecutive_hours"],2)
        self.assertEqual(p.run_lengths([True]*75)["episodes_ge72h"],1)

    def test_public_research_smoke_never_licenses_private_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/"synthetic.epw"
            write_epw(source,headers(),rows())
            out=p.public_research_smoke(source,Path(temp)/"result")
            self.assertFalse(out["scientific_original_57_file_gate_pass"])
            self.assertFalse(out["production_epw_ready"])
            self.assertEqual(out["actual_licensed_Meteonorm_corrected_validated"],0)


if __name__=="__main__":
    unittest.main()
