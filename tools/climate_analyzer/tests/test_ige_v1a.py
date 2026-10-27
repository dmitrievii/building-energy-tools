"""Provenance and counterexamples to unsupported R1 accuracy claims."""
import json
import socket
import unittest
from unittest.mock import patch

import numpy as np

from v1a_qc10_r1_audit import (
    R, audit, idw_weights, native_qc, qc_meaning, squared_risk_identity)


class QCProvenanceTests(unittest.TestCase):
    def test_QC10_unknown_originality_is_not_unchecked(self):
        q = qc_meaning(10)
        self.assertEqual(q["verification"], "automatic")
        self.assertEqual(q["originality"], "unknown")
        self.assertFalse(q["unchanged_instrument_measurement_certified"])

    def test_QC10_does_not_identify_particular_gapfill(self):
        self.assertFalse(qc_meaning(10)["specific_gap_fill_or_edit_identified"])

    def test_original_flags_remain_distinct(self):
        self.assertEqual(qc_meaning(12)["originality"], "original")
        self.assertEqual(qc_meaning(22)["verification"], "manual")
        self.assertEqual(qc_meaning(11)["originality"], "changed")
        self.assertEqual(qc_meaning(21)["originality"], "changed")

    def test_integral_JSON_representations_only(self):
        self.assertEqual([native_qc(q) for q in (10, 10.0, "10")], [10, 10, 10])
        for q in (True, False, 10.1, "10.1", float("nan"), float("inf")):
            with self.subTest(q=q), self.assertRaises(ValueError):
                native_qc(q)

    def test_undocumented_code_fails_closed(self):
        with self.assertRaises(ValueError):
            native_qc(13)

    def test_null_is_not_accepted_original(self):
        self.assertEqual(qc_meaning(None)["verification"], "undefined")
        self.assertFalse(qc_meaning(None)["unchanged_instrument_measurement_certified"])


class R1ScientificCounterexamples(unittest.TestCase):
    def test_exact_paired_squared_risk_identity(self):
        e = np.array([2., -1., 0., 3.]); c = np.array([-1., .2, .7, -2.])
        row = squared_risk_identity(e, c)
        self.assertAlmostEqual(row["delta_MSE_K2"], row["direct_delta_MSE_K2"], places=13)
        self.assertTrue(row["target_errors_required"])

    def test_uninformative_uncorrelated_change_can_harm(self):
        row = squared_risk_identity([1, -1, 1, -1], [1, 1, -1, -1])
        self.assertEqual(row["twice_error_correction_cross_moment_K2"], 0)
        self.assertGreater(row["delta_MSE_K2"], 0)

    def test_donor_agreement_and_perfect_LOO_do_not_certify_target(self):
        weights = idw_weights([10., 20., 30.])
        correction = weights @ np.array([1., 1., 1.])
        # Every donor has error -1: other donors correct it perfectly.
        self.assertAlmostEqual(-1 + correction, 0.)
        # A different local target has baseline error +1: it gets worse.
        self.assertGreater(abs(1 + correction), abs(1))

    def test_RMSE_benefit_does_not_imply_MAE_benefit(self):
        e = np.array([0., 0., 10.]); c = np.array([3., 3., -4.])
        self.assertLess(squared_risk_identity(e, c)["delta_MSE_K2"], 0)
        self.assertGreater(np.abs(e + c).mean(), np.abs(e).mean())

    def test_zero_correction_does_not_invent_benefit(self):
        self.assertEqual(squared_risk_identity([1, 2], [0, 0])["delta_MSE_K2"], 0)

    def test_missing_errors_cannot_be_used_in_risk_claim(self):
        for e, c in (([], []), ([1], [1, 2]), ([float("nan")], [1])):
            with self.subTest(e=e), self.assertRaises(ValueError):
                squared_risk_identity(e, c)

    def test_IDW_is_frozen_inverse_square(self):
        np.testing.assert_allclose(idw_weights([5., 10.]), [.8, .2], rtol=0, atol=1e-15)

    def test_shared_donors_are_not_independent_sample_count(self):
        w = idw_weights([5., 150., 150.]); neff = 1 / (w @ w)
        self.assertLess(neff, 1.01)
        self.assertNotEqual(neff, 3)

    def test_no_one_donor_or_unregistered_geometry_rule(self):
        for d in ([10], [4, 10], [10, 151], [10, 20, 30, 40]):
            with self.subTest(d=d), self.assertRaises(ValueError):
                idw_weights(d)


class OriginalPacketAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # An offline replay must work with network access made impossible.
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network in offline audit")):
            cls.result = audit()

    def test_all_six_original_AT_donors_have_native_QC10(self):
        rows = self.result["AT_donor_originals"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["native_QC_counts"] == {"10": 6792} for r in rows))
        self.assertEqual(sum(r["rows"] for r in rows), 40752)

    def test_decoder_preserves_flags_values_and_body_hash(self):
        self.assertTrue(all(r["native_QC_preserved_after_decoder"] and r["T_values_and_original_SHA_preserved"] for r in self.result["AT_donor_originals"]))

    def test_original_V1_primary_still_accepts_zero_AT_hours(self):
        self.assertTrue(all(r["V1_primary_QC22_accepted_hours"] == 0 for r in self.result["AT_donor_originals"]))
        registration = json.loads((R / "v1_registration_20261026.json").read_text())
        self.assertEqual(registration["QC"]["AT"]["primary"], [22])

    def test_old_and_current_metadata_code_list_agree(self):
        self.assertTrue(self.result["old_and_new_official_q21_equal"])
        self.assertEqual(self.result["tl_flag_code_list_ref"], "q21")

    def test_control_temperature_and_new_weather_stay_closed(self):
        self.assertFalse(self.result["AT_control_T_opened"])
        self.assertEqual(self.result["new_station_measurement_or_model_HTTP_requests"], 0)
        self.assertTrue(all(g["target_T_read"] is False for g in self.result["groups"]))

    def test_two_donors_do_not_silently_become_one_donor_LOO(self):
        groups = [g for g in self.result["groups"] if len(g["donors"]) == 2]
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(r["status"] == "NOT_ESTIMABLE_WITH_TWO_DONORS_WITHOUT_CHANGING_R1" for g in groups for r in g["donor_LOO_diagnostics"]))

    def test_shared_grid_cells_do_not_count_as_independent_support(self):
        stg = next(g for g in self.result["groups"] if g["target_key"] == "CH:STG")
        self.assertEqual(stg["geometry"]["unique_returned_cells_target_and_donors"], 1)
        self.assertEqual(stg["geometry"]["unique_temperature_arrays_target_and_donors"], 1)
        self.assertFalse(stg["geometry"]["effective_weight_count_is_independent_sample_size"])

    def test_reported_heights_never_prove_terrain_causality(self):
        self.assertTrue(all(g["geometry"]["height_proxy_status"].startswith("REPORTED_ONLY") and not g["geometry"]["terrain_cause_proved"] for g in self.result["groups"]))

    def test_revealed_donor_diagnostics_cannot_promote_R1(self):
        self.assertEqual(self.result["2018_status"], "REVEALED_DIAGNOSTICS_NOT_NEW_HOLDOUT")
        self.assertFalse(self.result["R1_default_promotion_allowed"])
        self.assertFalse(self.result["production_ready"])


class NextDesignTests(unittest.TestCase):
    def test_design_is_not_mislabelled_as_concrete_preregistration(self):
        p = json.loads((R / "v1a_next_validation_design_20261027.json").read_text())
        self.assertIn("COHORT_NOT_YET_REGISTERED", p["status"])
        self.assertEqual(p["cohort"], [])
        self.assertIsNone(p["actual_prediction_seal_sha256"])
        self.assertEqual(p["new_station_measurement_requests_authorized_by_this_design_file"], 0)

    def test_new_AT_product_estimand_is_distinct_from_old_original_QC(self):
        p = json.loads((R / "v1a_next_validation_design_20261027.json").read_text())
        q = p["QC_strata"]["AT_new_primary_product_reconstruction"]
        self.assertEqual(q["reference_codes"], [10])
        self.assertFalse(q["original_sensor_accuracy_claim_allowed"])
        self.assertTrue(p["original_V1_QC22_registration_unchanged"])

    def test_requested_case_census_and_independent_status_axes(self):
        p = json.loads((R / "v1a_next_validation_design_20261027.json").read_text())
        self.assertEqual(p["planned_targets_per_country"] * len(p["countries"]) * len(p["windows_UTC"]), p["planned_cases"])
        self.assertEqual(p["planned_cases"] * 168, p["planned_reference_hours"])
        self.assertFalse(p["scoring"]["pooled_country_winner"])
        self.assertTrue({"code_correctness", "physical_admissibility", "independent_accuracy", "operation"} <= set(p["qualification"]))


if __name__ == "__main__":
    unittest.main()
