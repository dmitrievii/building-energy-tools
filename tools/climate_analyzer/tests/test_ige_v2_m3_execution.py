"""M3 executor tests; no weather or control request is made."""
from pathlib import Path
import tempfile
import unittest

from v2_m3_execution import (START, INPUTS, CONTROLS, PREDICTIONS, LEDGER, SEAL,
    state, new_names_allowed, artifact_manifest, contract)


class ExecutionTests(unittest.TestCase):
    def test_empty_state_can_claim_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); self.assertEqual(state(p), "UNSTARTED")
            (p / START).write_bytes(b"claimed")
            with self.assertRaisesRegex(ValueError, "ALREADY_CLAIMED"): state(p)

    def test_any_original_or_prediction_prevents_recapture(self):
        for n in (INPUTS + ".storage.json", INPUTS + ".part001", PREDICTIONS, LEDGER, SEAL):
            with self.subTest(n=n), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / n).write_bytes(b"retained")
                with self.assertRaisesRegex(ValueError, "ALREADY_CLAIMED"): state(p)

    def test_control_bytes_are_not_an_input_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p / (CONTROLS + ".part001")).write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "CONTROL"): state(p)

    def test_published_members_cannot_target_old_results_or_controls(self):
        for n in ("v1_results_20261026.json", CONTROLS + ".part001", INPUTS + ".partBAD001", "../main.py", "sub/path", "x\\y"):
            with self.subTest(n=n), self.assertRaises(ValueError): new_names_allowed([n])

    def test_new_original_parts_and_actual_seal_are_permitted(self):
        new_names_allowed([START, INPUTS + ".storage.json", INPUTS + ".part001", PREDICTIONS, LEDGER, SEAL])

    def test_artifact_census_is_exclusive_and_detects_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p / "one").write_bytes(b"original")
            self.assertEqual(len(artifact_manifest(p)), 1)
            with self.assertRaises(FileExistsError): artifact_manifest(p)

    def test_execution_contract_cannot_change_scientific_inventory(self):
        c, plan = contract()
        self.assertEqual(c["controls_requested_by_this_stage"], 0)
        self.assertEqual(plan["registered_cases"], 72)
        self.assertEqual(plan["QC"]["AT"]["primary"], [10])


if __name__ == "__main__": unittest.main()
