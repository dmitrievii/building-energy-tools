"""Pre-unblinding execution and paired arithmetic tests; synthetic targets only."""
from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from v2_m4_execution import (START, CONTROLS, RESULTS, PAIRS, PREDICTIONS, SEAL,
    contract, unstarted, allowed_names, same_score_json)
from v2_m4_score_audit import arithmetic, audit_scores
from v2_weather_run import load_predictions, score_predictions


class ExecutionTests(unittest.TestCase):
    def test_sealed_predictors_do_not_count_as_opened_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p / PREDICTIONS).write_bytes(b"sealed"); (p / SEAL).write_bytes(b"sealed")
            self.assertTrue(unstarted(p))

    def test_claim_partial_packet_or_scores_prevent_control_recapture(self):
        for n in (START, CONTROLS + ".part001", CONTROLS + ".storage.json", RESULTS, PAIRS):
            with self.subTest(n=n), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp); (p / n).write_bytes(b"retained")
                with self.assertRaisesRegex(ValueError, "ALREADY_CLAIMED"): unstarted(p)

    def test_publisher_cannot_change_sealed_inputs_old_scores_or_main(self):
        for n in (PREDICTIONS, SEAL, "v1_results_20261026.json", "../main.py", CONTROLS + ".partBAD001"):
            with self.subTest(n=n), self.assertRaises(ValueError): allowed_names([n])
        allowed_names([START, CONTROLS + ".part001", CONTROLS + ".storage.json", RESULTS, PAIRS])

    def test_actual_source_admission_and_QC_are_frozen(self):
        c, p = contract()
        self.assertEqual(sum(v["open"] for v in c["sealed_source_admission"].values()), 18)
        self.assertEqual(p["QC"]["AT"]["primary"], [10]); self.assertEqual(c["new_predictor_or_metadata_requests"], 0)

    def test_score_replay_tolerance_keeps_categories_and_counts_exact(self):
        self.assertTrue(same_score_json({"x": 1.}, {"x": 1. + 1e-10}))
        self.assertFalse(same_score_json({"x": 1.}, {"x": 1. + 1e-6}))
        self.assertFalse(same_score_json({"n": 160}, {"n": 159}))
        self.assertFalse(same_score_json({"flag": True}, {"flag": 1}))

    def test_fsum_metrics_have_known_bias_and_centred_RMSE(self):
        a = arithmetic([1., 2., 3.]); self.assertEqual(a["MAE_K"], 2.)
        self.assertAlmostEqual(a["RMSE_K"], math.sqrt(14/3)); self.assertAlmostEqual(a["centred_RMSE_K"], math.sqrt(2/3))
        self.assertEqual(arithmetic([])["n"], 0)


class PairedAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_ige_v2_weather as fixtures
        cls.fixture = fixtures.SyntheticEndToEndTests
        cls.fixture.setUpClass()
        cls.raw = pd.DataFrame(cls.fixture.pairs).to_csv(index=False, float_format="%.10f", lineterminator="\n").encode()

    def audit(self, result=None, raw=None, ledger=None):
        return audit_scores(result if result is not None else self.fixture.result,
            raw if raw is not None else self.raw, self.fixture.plan,
            ledger if ledger is not None else self.fixture.ledger)

    def test_synthetic_all72_cases_and12096_pairs(self):
        self.assertEqual(self.audit()["paired_rows"], 12096)

    def test_changed_case_metric_is_detected(self):
        d = deepcopy(self.fixture.result); d["cases"][0]["B0"]["MAE_K"] += .1
        with self.assertRaisesRegex(ValueError, "ARITHMETIC"): self.audit(result=d)

    def test_dropping_a_pair_cannot_hide_different_coverage(self):
        raw = b"\n".join(self.raw.splitlines()[:-1]) + b"\n"
        with self.assertRaisesRegex(ValueError, "COUNT"): self.audit(raw=raw)

    def test_unregistered_station_is_detected(self):
        raw = self.raw.replace(b"AT:5925", b"AT:9999", 1)
        with self.assertRaisesRegex(ValueError, "UNREGISTERED"): self.audit(raw=raw)

    def test_duplicate_hour_is_detected(self):
        raw = self.raw + self.raw.splitlines()[1] + b"\n"
        with self.assertRaisesRegex(ValueError, "DUPLICATE"): self.audit(raw=raw)

    def test_country_gain_cannot_ignore_a_station_or_change_decision(self):
        d = deepcopy(self.fixture.result); d["countries"]["DE"]["within_pilot_uniform_observed_benefit"] = False
        with self.assertRaisesRegex(ValueError, "BENEFIT"): self.audit(result=d)

    def test_six_empty_AT_summer_forecasts_keep_country_rule_blocked(self):
        fixture = self.fixture; f = load_predictions(fixture.raw, fixture.plan); ledger = deepcopy(fixture.ledger)
        mask = (f.country == "AT") & (f.season == "summer"); f.loc[mask, "R1_C"] = float("nan"); f.loc[mask, "R1_predicted"] = False
        for c in ledger["cases"]:
            if c["country"] == "AT" and c["season"] == "summer": c["finite_paired_forecast_hours"] = 0; c["R1_hours"] = 0
        raw = f.to_csv(index=False, float_format="%.10f", na_rep="", lineterminator="\n").encode()
        result, pairs = score_predictions(raw, ledger, fixture.plan, fixture.a, fixture.controls, {})
        paired = pd.DataFrame(pairs).to_csv(index=False, float_format="%.10f", lineterminator="\n").encode()
        self.assertEqual(self.audit(result=result, raw=paired, ledger=ledger)["paired_rows"], 11088)
        self.assertEqual(result["countries"]["AT"]["admitted_cases"], 18)
        self.assertFalse(result["countries"]["AT"]["within_pilot_uniform_observed_benefit"])


if __name__ == "__main__": unittest.main()
