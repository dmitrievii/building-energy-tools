import copy
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest

from p9_3b3_compare_pressure import hydrostatic_pressure, to_legacy_reference
from p9_3b3_compare_run import (_day_census, compare_repair_record, control_integrity,
                               load_protocol, metadata_audit, run)
from p9_3b3_generator import ThermoDonor
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import DailyTarget, SourceSemantics
from test_p9_3b3_compare_foundation import coordinate, pressure


class ComparisonPipeline(unittest.TestCase):
    def test_metadata_does_not_promote_ground_height_or_reveal_observations(self):
        p = load_protocol()
        audit = metadata_audit(p)
        self.assertEqual([s["country"] for s in audit["stations"]], ["AT", "DE", "CH"])
        self.assertTrue(all(s["P1_sensor_reference_status"] == "SOURCE_BLOCKED" for s in audit["stations"]))
        self.assertTrue(all(len(s["blockers"]) == 2 for s in audit["stations"]))
        self.assertFalse(audit["new_station_validation_performed"])
        self.assertTrue(all(not op["interval_verified"] for op in audit["operators"]))

    def test_real_runner_preserves_controls_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"new"
            r = run(path)
            disk = json.loads((path/"p1_c1_comparison.json").read_text())
            self.assertEqual(r["protocol_sha256"], disk["protocol_sha256"])
            self.assertGreaterEqual(len(r["controls"]), 20)
            self.assertFalse(r["independent_holdout_opened"])
            self.assertFalse(r["source_values_modified"])
            self.assertEqual(r["source_census_status"], "NOT_RUN_METADATA_AUDIT_ONLY")
            with self.assertRaises(FileExistsError):
                run(path)

    def test_missing_one_input_is_not_silently_metadata_only(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "BOTH"):
                run(Path(td)/"new", original_zip="not-read.zip")
            self.assertFalse((Path(td)/"new").exists())

    def test_control_hash_failure_is_detected_before_comparison(self):
        p = copy.deepcopy(load_protocol())
        key = next(iter(p["protected_control_sha256"]))
        p["protected_control_sha256"][key] = "0"*64
        with self.assertRaisesRegex(ValueError, "CONTROL_CHANGED"):
            control_integrity(p)

    def test_all_twelve_donors_enter_nominal_and_interval_union(self):
        t = DailyTarget("2013-01-08", 270., 280., 275., .0015, 80.,
                        SourceSemantics("DERIVED_TAS_MIDRANGE", "WATER_ICE"))
        donors = []
        for i in range(1, 13):
            date = f"2019-01-{i:02}"
            p = PressureReference((97000.,)*24, "SYNTHETIC", "DECLARED_GRID", reference_date=date)
            donors.append(ThermoDonor(date, (275.,)*24, (.0015,)*24, p, False))
        row = _day_census(t, donors, False, load_protocol()["pressure_scenarios"])
        self.assertEqual(row["eligible_donors"], 12)
        for scenario in row["scenarios"]:
            self.assertEqual(scenario["status"], "ALL_DONORS_CERTIFIED_INFEASIBLE")
            self.assertEqual(len(scenario["certificates"]), 12)
            self.assertFalse(scenario["source_feasibility_established"])
            self.assertFalse(scenario["external_pressure_uncertainty_established"])
        self.assertEqual(compare_repair_record(row, {"status":"CERTIFIED_INFEASIBLE"}),
                         "PRIOR_CONDITIONAL_CERTIFICATE_REPRODUCED")
        with self.assertRaisesRegex(AssertionError, "FALSE_REJECTION"):
            compare_repair_record(row, {"status":"EXACT_DEFINED_OPERATORS"})

    def test_no_donors_is_source_blocked_not_infeasible(self):
        t = DailyTarget("2013-01-08", 270., 280., 275., .0015, 80.,
                        SourceSemantics("DERIVED_TAS_MIDRANGE", "WATER_ICE"))
        row = _day_census(t, [], False, load_protocol()["pressure_scenarios"])
        self.assertTrue(all(s["status"] == "SOURCE_BLOCKED_NO_ELIGIBLE_DONOR" for s in row["scenarios"]))

    def test_adapter_cannot_launder_observed_pressure_by_manual_candidate(self):
        r = hydrostatic_pressure(pressure(), coordinate(368, "THERMO_SENSOR", verified=True),
            [280.], [.005], proxy_source="SYNTHETIC", proxy_date="2021-02-01")
        forged = dataclasses.replace(r, pressure=dataclasses.replace(r.pressure,
                                     usage="OBSERVED_VALIDATION_ONLY"))
        with self.assertRaisesRegex(ValueError, "OBSERVED"):
            to_legacy_reference(forged)


if __name__ == "__main__":
    unittest.main()
