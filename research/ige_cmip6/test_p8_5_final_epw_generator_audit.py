"""IGE P8.5 fail-closed whole-generator evidence-chain and red-release QC tests."""
import copy
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

import p8_5_final_epw_generator_audit as f
import p7c3_ensemble as e


class TestFinalGeneratorAudit(unittest.TestCase):
    def test_eight_model_four_period_384_climate_signal_audit(self):
        src=f.source_matrix()
        self.assertEqual(src["n_models"],8)
        self.assertEqual(src["n_periods"],4)
        self.assertEqual(src["n_original_GCM_monthly_signals"],384)
        self.assertFalse(src["source_zip_bytes_reverified_in_this_audit"])

    def test_registered_member_identity_32_unique(self):
        self.assertEqual(len(f.registered_member_identity()),32)
        self.assertIn(("IPSL-CM6A-LR",e.WINDOWS[0]),f.registered_member_identity())

    def test_original_28_full_4_blocked_research_status_source_hash(self):
        audit=f.validate_manifests()
        self.assertTrue(audit["manifest_consistency_pass"])
        self.assertEqual(audit["registered_GCM_full_research_members"],28)
        self.assertEqual(audit["registered_GCM_blocked_members"],4)
        self.assertFalse(audit["original_28_licensed_EPW_bytes_currently_rehashed"])
        self.assertEqual(audit["published_original_license_baseline_sha256"],f.BASELINE_SHA)

    def test_original_28_report_shas_have_unique_source_files(self):
        audit=f.validate_manifests()
        self.assertEqual(len(set(audit["P7C4_28_sha_sources"])),28)
        self.assertEqual(len(set(audit["P7C5B_28_sha_outputs"])),28)
        self.assertNotEqual(
            set(audit["P7C4_28_sha_sources"]),
            set(audit["P7C5B_28_sha_outputs"]))

    def test_no_humidity_convergence_claim_from_600_iterations(self):
        audit=f.validate_manifests()
        self.assertEqual(audit["optimizer_not_strictly_converged_members"],28)
        self.assertEqual(audit["optimizer_max_iterations_each"],600)
        self.assertFalse(audit["strict_optimizer_convergence_accepted_for_production"])

    def test_original_28_humidity_saturation_total_remains_visible(self):
        audit=f.validate_manifests()
        self.assertEqual(audit["P7C4_RH_near_100_hours_28_members_np_isclose"],14520)
        self.assertEqual(audit["P7C5_RH_ge99p995_hours_28_members"],14536)
        self.assertEqual(audit["P7C4_vs_P7C5_RH_saturation_count_difference"],16)
        self.assertTrue(audit["P7C4_vs_P7C5_RH_count_definitions_differ"])
        self.assertEqual(audit["RH_source_original_8760_saturation_hours_from_previous_audit"],229)

    def test_stale_illuminance_in_original_28_is_explicit(self):
        audit=f.validate_manifests()
        self.assertGreater(audit["p7c5_prephotometric_global_lux_stale_source_hours"],100000)
        self.assertGreater(audit["p7c5_prephotometric_direct_lux_stale_source_hours"],90000)
        self.assertGreater(audit["p7c5_prephotometric_diffuse_lux_stale_source_hours"],100000)
        self.assertLessEqual(audit["p7c5b_after_correction_max_lux_closure_residual"],.5)
        self.assertFalse(audit["p7c5b_photometry_independently_measured_qualified"])

    def test_preregistered_production_gates_are_red_even_if_manifest_is_green(self):
        out=f.release_gates(f.source_matrix(),f.validate_manifests(),{
            "all_public_EPWs_structurally_verified":True})
        self.assertTrue(out["research_aggregate_technical_audit_pass"])
        self.assertFalse(out["operational_release_ready"])
        self.assertFalse(out["production_epw_ready"])
        self.assertTrue(out["ready_for_research_sensitivity_with_explicit_limitations"])

    def test_public_fixture_absence_fails_actual_EPWs_readback_gate(self):
        out=f.release_gates(f.source_matrix(),f.validate_manifests(),None)
        self.assertFalse(out["research_aggregate_technical_audit_pass"])
        self.assertFalse(out["release_gate_results"]["public_8760_35_EPW_readback_pass"])

    def test_undocumented_boolean_not_permitted(self):
        self.assertTrue(f.truth("True"))
        self.assertFalse(f.truth("False"))
        with self.assertRaisesRegex(ValueError,"INVALID_EXPLICIT_BOOLEAN"):
            f.truth("yes")

    def test_tampered_p7c5b_immutable_source_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=f.read_csv(f.P7C5B_MEMBERS)
            source[0]["source_p7c4_sha256"]="0"*64
            file=Path(tmp)/"photometric.csv"
            with file.open("w",newline="") as fp:
                writer=csv.DictWriter(fp,fieldnames=source[0].keys())
                writer.writeheader();writer.writerows(source)
            with self.assertRaisesRegex(ValueError,"SOURCE_HASH"):
                f.validate_manifests({"p7c5b_members":file})

    def test_tampered_IPSL_block_state_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=f.read_csv(f.P7C4_BLOCK)
            rows[0]["complete_EPW_generated"]="True"
            file=Path(tmp)/"block.csv"
            with file.open("w",newline="") as fp:
                writer=csv.DictWriter(fp,fieldnames=rows[0].keys())
                writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(ValueError,"HUMIDITY_BLOCK"):
                f.validate_manifests({"p7c4_block":file})

    def test_tampered_optim_convergence_does_not_obtain_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=f.read_csv(f.P7C4_MEMBERS)
            source[0]["optimizer_converged_by_delta"]="True"
            file=Path(tmp)/"members.csv"
            with file.open("w",newline="") as fp:
                writer=csv.DictWriter(fp,fieldnames=source[0].keys())
                writer.writeheader();writer.writerows(source)
            with self.assertRaisesRegex(ValueError,"NONCONVERGENCE"):
                f.validate_manifests({"p7c4_members":file})

    def test_baseline_hash_difference_not_silently_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj=f.read_json(f.P7C4);obj["baseline_sha256"]="fake"
            file=Path(tmp)/"public.json";file.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"BASELINE_AUTHENTICATED"):
                f.validate_manifests({"p7c4":file})

    def test_audit_never_allows_bad_production_epw_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj=f.read_json(f.P7C4);obj["production_epw_ready"]=True
            file=Path(tmp)/"public.json";file.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"MISREPRESENTED_AS_PRODUCTION"):
                f.validate_manifests({"p7c4":file})

    def test_nonexistent_public_EPW_paths_must_not_pass(self):
        with self.assertRaises((FileNotFoundError,OSError)):
            f.real_public_epw_probe(["/not/a/real/epw.epw"])

    def test_empty_EPWs_are_not_substituted_with_summary_metrics(self):
        with self.assertRaisesRegex(ValueError,"NO_ORIGINAL_PUBLIC_EPW"):
            f.real_public_epw_probe([])

    def test_authentic_meteonorm_28_byte_report_must_remain_unverified(self):
        audit=f.validate_manifests()
        self.assertFalse(audit["original_28_licensed_EPW_bytes_available_to_current_audit"])
        self.assertFalse(audit["current_EnergyPlus_28_licensed_member_simulations_executed"])


if __name__=="__main__":
    unittest.main()
