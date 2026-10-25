"""A1.3 phase isolation and paired-error oracles using synthetic weather only."""
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"research/ige_cmip6"))
from a13_prepare import registered, parent_inputs, REGISTRATION, R, code_hashes
from a13_acquire import allowed_spec, collect, assert_seal_code
from a13_run import selected_temperature_csv, model_temperature, make_predictions, load_predictions, compare, metrics, block_comparison, checked_sources


def observation_body(sid, *, gap=False):
    protocol, _ = parent_inputs()
    rows = ["station_abbr;reference_timestamp;tre200h0"]
    # The invalid numeric strings are outside admitted windows; a parser that
    # converts weather before selection fails this independent fixture.
    rows += [f"{sid};01.01.2024 00:00;not-a-number", f"{sid};01.01.2025 00:00;not-a-number"]
    for w in protocol["windows"]:
        for i,t in enumerate(pd.date_range(w["start_UTC"], periods=168, freq="h", tz="UTC")):
            value = "" if gap and w["season"] == "winter" and i == 0 else "2"
            rows.append(f"{sid};{t.strftime('%d.%m.%Y %H:%M')};{value}")
    return ("\n".join(rows)+"\n").encode()


def model_body(spec):
    return json.dumps({"latitude": float(spec["parameters"]["latitude"]), "longitude": float(spec["parameters"]["longitude"]),
        "utc_offset_seconds": 0, "elevation": 0, "hourly_units": {"temperature_2m": "°C"},
        "hourly": {"time": pd.date_range("2025-01-01", periods=8760, freq="h").strftime("%Y-%m-%dT%H:%M").tolist(), "temperature_2m": [0.]*8760}}).encode()


def fixture_packet(path, phase, *, gaps=(), extra_control=False, control_override=None):
    plan = registered(); bodies = {}; receipts = []
    for spec in plan[phase]:
        key = spec["station_key"]
        raw = model_body(spec) if spec["kind"] == "model_background" else observation_body(key.split(":")[1], gap=key in gaps)
        if control_override and key in control_override: raw = control_override[key]
        bodies[spec["member"]] = raw
        receipts.append({**{k:spec[k] for k in ("id", "station_key", "kind", "role", "url", "member")},
            "status": "ORIGINAL_BODY_RECEIVED", "bytes": len(raw), "sha256": sha256(raw).hexdigest()})
    if extra_control: bodies["control_CH_BAS.csv"] = b"synthetic control leak"
    manifest = {"phase": phase, "registration_sha256": sha256((R/REGISTRATION).read_bytes()).hexdigest(),
        "sources": receipts, "original_body_sha256": {n:sha256(b).hexdigest() for n,b in bodies.items()}, "control_bodies_opened_this_phase": phase == "controls"}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in bodies.items(): archive.writestr(name, body)
        archive.writestr("manifest.json", json.dumps(manifest))
    return path


class RegistrationAndPhaseTests(unittest.TestCase):
    def test_fixed_subsets_and_200MB_budget_preserve_24_case_experiment(self):
        p = registered()
        self.assertEqual((p["all_frozen_cases"], p["ready_cases"]), (24, 8))
        self.assertEqual(len(p["inputs"]), 12); self.assertEqual(len(p["controls"]), 2)
        self.assertEqual(p["source_budget"]["max_decoded_body_bytes_all_attempts_inputs_plus_controls"], 200000000)
        self.assertFalse(p["strict_blindness_certified"])

    def test_controls_cannot_be_requested_in_predictor_phase(self):
        p = registered()
        for spec in p["controls"]:
            with self.assertRaisesRegex(ValueError, "WRONG_PHASE"): allowed_spec(spec, "inputs", p)
        for spec in p["inputs"]: allowed_spec(spec, "inputs", p)

    def test_model_target_coordinates_are_permitted_but_not_target_observations(self):
        p = registered(); targets = {s["station_key"] for s in p["controls"]}
        self.assertEqual({s["station_key"] for s in p["inputs"] if s["kind"] == "model_background"} & targets, targets)
        self.assertTrue(all(s["station_key"] not in targets for s in p["inputs"] if s["kind"] == "station_observation"))

    def test_missing_published_seal_blocks_control_io_before_directory_or_network(self):
        opener = Mock()
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/"not_created"
            with self.assertRaisesRegex(ValueError, "SEAL_COMMIT_REQUIRED"): collect("controls", out, opener=opener)
            opener.assert_not_called(); self.assertFalse(out.exists())

    def test_a_change_of_code_or_protocol_invalidates_seal(self):
        good = {"code_sha256": code_hashes(), "control_observation_bodies_opened": False}
        assert_seal_code(good)
        bad = deepcopy(good); bad["code_sha256"]["research/ige_cmip6/a13_run.py"] = "0"*64
        with self.assertRaisesRegex(ValueError, "CHANGED_AFTER"): assert_seal_code(bad)


class SourceContractTests(unittest.TestCase):
    def test_selection_precedes_temperature_number_parsing(self):
        protocol,_ = parent_inputs(); subsets = selected_temperature_csv(observation_body("DEM"), "DEM", protocol)
        self.assertEqual({s:len(b.splitlines())-1 for s,b in subsets.items()}, {s:168 for s in ("winter", "spring", "summer", "autumn")})
        self.assertNotIn(b"not-a-number", b"".join(subsets.values()))

    def test_source_station_alias_duplicate_timestamp_and_qc_change_fail(self):
        protocol,_ = parent_inputs()
        cases = [b"station_abbr;reference_timestamp;tre200h0\nBAS;10.01.2025 00:00;1\n",
            b"station_abbr;reference_timestamp;tre200h0\nDEM;10.01.2025 00:00;1\nDEM;10.01.2025 00:00;2\n",
            b"station_abbr;reference_timestamp;tre200h0\nDEM;2025-01-10T00:00;1\n",
            b"station_abbr;reference_timestamp;tre200h0;tre200h0_qc\nDEM;10.01.2025 00:00;1;0\n"]
        for raw in cases:
            with self.assertRaises(ValueError): selected_temperature_csv(raw, "DEM", protocol)

    def test_model_UTC_units_and_annual_clock_are_explicit_not_guessed(self):
        spec = registered()["inputs"][0]; obj = json.loads(model_body(spec))
        for mutate in (lambda o:o.update(utc_offset_seconds=3600), lambda o:o["hourly_units"].update(temperature_2m="K"), lambda o:o["hourly"]["time"].pop()):
            altered = deepcopy(obj); mutate(altered)
            with self.assertRaises(ValueError): model_temperature(json.dumps(altered).encode(), spec)

    def test_null_model_temperature_is_not_interpolated_or_relabelled(self):
        spec = registered()["inputs"][0]; obj = json.loads(model_body(spec)); obj["hourly"]["temperature_2m"][0] = None
        values, proof = model_temperature(json.dumps(obj).encode(), spec)
        self.assertTrue(pd.isna(values.iloc[0])); self.assertEqual(proof["missing_or_outside_A1_domain_hours"], 1)
        self.assertFalse(proof["native_ERA5_orography_verified"])

    def test_foreign_grid_and_numeric_strings_cannot_masquerade_as_requested_model(self):
        spec = registered()["inputs"][0]; obj = json.loads(model_body(spec))
        altered = deepcopy(obj); altered["longitude"] += 10
        with self.assertRaisesRegex(ValueError, "50KM"): model_temperature(json.dumps(altered).encode(), spec)
        obj["hourly"]["temperature_2m"][0] = "0"
        with self.assertRaisesRegex(ValueError, "VALUE_AXIS_OR_TYPE"): model_temperature(json.dumps(obj).encode(), spec)


class PredictionPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.temp.name)
        cls.path = fixture_packet(cls.folder/"inputs.zip", "inputs")
        cls.raw, cls.ledger, _ = make_predictions(cls.path); cls.p = load_predictions(cls.raw)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_hand_constant_residual_gives_1344_predictions_and_all_24_cases(self):
        p = self.p
        self.assertEqual(len(p), 4032); self.assertEqual(len(self.ledger["cases"]), 24)
        self.assertEqual(p.prediction_admitted.sum(), 1344)
        np.testing.assert_allclose(p.loc[p.prediction_admitted, "B0_C"], 0.)
        np.testing.assert_allclose(p.loc[p.prediction_admitted, "R1_C"], 2., atol=1e-10)
        self.assertTrue(p.loc[~p.prediction_admitted, "R1_C"].isna().all())
        self.assertFalse(self.ledger["target_observation_input"])

    def test_third_ALT_slot_stays_TIT_with_zero_weight_not_replaced(self):
        p = self.p[self.p.target_key == "CH:ALT"]
        self.assertTrue((p.donor_3 == "CH:TIT").all()); self.assertTrue((p.weight_3 == 0).all())
        np.testing.assert_allclose(p.weight_1+p.weight_2, 1., atol=1e-10)

    def test_one_ALT_donor_gap_blocks_R1_without_replacing_it_with_B0(self):
        path = fixture_packet(self.folder/"gap.zip", "inputs", gaps=("CH:ENG",))
        raw, ledger,_ = make_predictions(path); p = load_predictions(raw)
        row = p[(p.target_key == "CH:ALT") & (p.season == "winter")].iloc[0]
        self.assertEqual(row.B0_C, 0.); self.assertTrue(pd.isna(row.R1_C)); self.assertFalse(row.prediction_admitted)
        self.assertEqual(row.accepted_donor_count, 1); self.assertEqual(ledger["actual_R1_predicted_hours"], 1343)

    def test_three_donor_case_renormalizes_when_one_donor_is_missing(self):
        path = fixture_packet(self.folder/"two_left.zip", "inputs", gaps=("CH:DEM",))
        raw,_,_ = make_predictions(path); p = load_predictions(raw)
        row = p[(p.target_key == "CH:BAS") & (p.season == "winter")].iloc[0]
        self.assertEqual(row.accepted_donor_count, 2); self.assertEqual(row.R1_C, 2.); self.assertTrue(row.prediction_admitted)

    def test_extra_control_asset_cannot_hide_in_predictor_packet(self):
        path = fixture_packet(self.folder/"leaked.zip", "inputs", extra_control=True)
        with self.assertRaisesRegex(ValueError, "UNREGISTERED_BODY"): checked_sources(path, "inputs")

    def test_common_hours_and_all_reference_baseline_are_separate(self):
        p = self.p.copy(); index = p.index[(p.target_key == "CH:BAS") & (p.season == "winter")][:2]
        p.loc[index, "B0_C"] = [3., 7.]; p.loc[index, "R1_C"] = [2., np.nan]; p.loc[index[1], "prediction_admitted"] = False
        raw = p.to_csv(index=False, float_format="%.10f", lineterminator="\n").encode()
        control = b"station_abbr;reference_timestamp;tre200h0\nBAS;10.01.2025 00:00;0\nBAS;10.01.2025 01:00;1\n"
        path = fixture_packet(self.folder/"controls.zip", "controls", control_override={"CH:BAS": control})
        result,_ = compare(raw, self.ledger, path)
        winter = next(r for r in result["cases"] if r["target_key"] == "CH:BAS" and r["season"] == "winter")
        self.assertEqual(winter["B0_all_reference"], {"n":2, "MAE_K":4.5, "RMSE_K":np.sqrt(22.5), "bias_K":4.5})
        self.assertEqual(winter["B0_paired"]["n"], 1); self.assertEqual(winter["B0_paired"]["MAE_K"], 3.)
        self.assertEqual(winter["R1_paired"]["MAE_K"], 2.); self.assertEqual(winter["delta_MAE_K"], -1.)
        self.assertEqual(len(result["cases"]), 24); self.assertFalse(result["independent_accuracy_qualified"])


class StatisticalOracles(unittest.TestCase):
    def test_MAE_RMSE_and_bias_have_independent_hand_values(self):
        m = metrics(np.array([-1., 2., -3.]))
        self.assertEqual(m["MAE_K"], 2.); self.assertAlmostEqual(m["RMSE_K"], np.sqrt(14/3)); self.assertAlmostEqual(m["bias_K"], -2/3)

    def test_block_bootstrap_preserves_hour_weights_and_seed(self):
        blocks = [(np.array([4.]), np.array([0.])), (np.array([1.,1.]), np.array([2.,2.]))]
        r = block_comparison(blocks)
        self.assertAlmostEqual(r["delta_MAE_K"], -2/3)
        self.assertEqual(r, block_comparison(blocks)); self.assertEqual(r["bootstrap_95pct"]["lower_K"], -4.)
        self.assertEqual(r["bootstrap_95pct"]["upper_K"], 1.)

    def test_zero_or_single_blocks_do_not_manufacture_uncertainty(self):
        self.assertIsNone(block_comparison([])["delta_MAE_K"])
        self.assertIsNone(block_comparison([(np.array([1.]), np.array([0.]))])["bootstrap_95pct"])


if __name__ == "__main__": unittest.main()
