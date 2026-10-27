"""Scientific adversaries for V2 registration, access gates and paired scores."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import zipfile

import numpy as np
import pandas as pd

from v2_weather_registration import (R, REG, WINDOWS, INPUTS, build_registration, admission, source_specs, registered)
from v2_weather_io import (Collector, allowed_spec, control_admission, elapsed_deadline, store_packet, read_packet)
from v2_weather_run import (model_temperature, station_values, dwd_product, make_predictions,
    load_predictions, score_predictions, country_summary, metrics, delta_summary)
from v2_weather_verify import same_derived_json
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import (T, model_reference_operator, reconstruct_temperature)
from epw_climate_analyzer.engine.historical import json_bytes


class Response(io.BytesIO):
    status = 200
    def __init__(self, raw=b"original", url="https://example.invalid/exact", headers=None, status=200):
        super().__init__(raw); self.url = url; self.headers = headers or {}; self.status = status
    def geturl(self): return self.url


def small_plan():
    return {"inputs": [], "controls": [], "target_keys": [], "budget": {
        "HTTP_attempts_inputs_plus_controls_max": 240, "attempts_per_asset_max": 3,
        "body_bytes_all_attempts_inputs_plus_controls_max": 2000,
        "attempt_total_deadline_seconds": 1, "retry_delays_seconds": [0, 0]}}


def spec():
    return {"id": "donor_AT_1", "station_key": "AT:1", "kind": "station_temperature", "role": "donor",
            "url": "https://example.invalid/exact", "member": "donor.json", "max_body_bytes": 100, "source_block": None}


def ledger_for(plan, n=168):
    cases = [{"target_key": k, "country": k[:2], "season": w["season"], "requested_hours": 168,
              "finite_paired_forecast_hours": n, "source_blocks": {}, "control_values_read": False}
             for k in plan["target_keys"] for w in WINDOWS]
    ledger = {"cases": cases}; ledger["control_admission"] = control_admission(plan, ledger)
    return ledger


def at_body(key, times, values, flags):
    return json_bytes({"timestamps": [pd.Timestamp(t).isoformat() for t in times], "features": [{"properties": {
        "station": key.split(":")[1], "parameters": {"tl": {"unit": "°C", "data": values}, "tl_flag": {"data": flags}}}}]})


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = admission(); cls.plan = build_registration()

    def test_registered_bytes_replay_exactly(self):
        self.assertEqual((R / REG).read_bytes(), json_bytes(self.plan)); self.assertEqual(registered(), self.plan)

    def test_same_M1_targets_and_donors(self):
        self.assertEqual(self.plan["groups"], self.a["groups"]); self.assertEqual(len(self.plan["target_keys"]), 18)

    def test_all_72_cases_12096_hours_2019(self):
        self.assertEqual(self.plan["registered_cases"], 72); self.assertEqual(self.plan["requested_reference_hours"], 12096)
        self.assertTrue(all(w["start_UTC"].startswith("2019") for w in WINDOWS))

    def test_no_target_or_alias_observations_in_inputs(self):
        identities = {self.a["records"][k]["resolved_identity_group"] for k in self.plan["target_keys"]}
        for s in self.plan["inputs"]:
            if s["kind"] != "model_background":
                self.assertNotIn(s["station_key"], self.plan["target_keys"])
                self.assertNotIn(self.a["records"][s["station_key"]]["resolved_identity_group"], identities)

    def test_reserved_AT_2018_IV1_2022_stations_not_requested(self):
        keys = {s["station_key"] for s in self.plan["inputs"] + self.plan["controls"]}
        self.assertTrue(keys.isdisjoint({"AT:16412", "AT:5609", "AT:20123", "DE:00399", "CH:DAV"}))

    def test_DE_missing_archive_retains_original_donor(self):
        s = next(s for s in self.plan["inputs"] if s["id"] == "donor_DE_14138")
        self.assertIsNone(s["url"]); self.assertTrue(s["source_block"])
        self.assertIn("DE:14138", next(g for g in self.plan["groups"] if g["target_key"] == "DE:06170")["donors"])

    def test_exact_source_census_and_budget(self):
        x = self.plan["source_inventory"]
        self.assertEqual(x["total_registered_assets_including_blocks"], 140)
        self.assertEqual(x["requestable_assets"], 139); self.assertLessEqual(x["sum_one_complete_body_cap_bytes"], 2_000_000_000)

    def test_full_containers_are_disclosed_not_only_extracted_T(self):
        ch = next(s for s in self.plan["controls"] if s["station_key"].startswith("CH"))
        self.assertTrue(ch["raw_other_variables"]); self.assertIn("2010/2019", ch["raw_container_support"])

    def test_new_QC10_does_not_relax_old_QC22(self):
        self.assertEqual(self.plan["QC"]["AT"]["primary"], [10])
        self.assertEqual(json.loads((R / "v1_registration_20261026.json").read_text())["QC"]["AT"]["primary"], [22])

    def test_all_control_T_and_QC_are_separate(self):
        for s in self.plan["controls"]:
            with self.assertRaisesRegex(ValueError, "WRONG_PHASE"): allowed_spec(s, "inputs", self.plan)

    def test_changed_source_query_rejected_before_network(self):
        s = deepcopy(self.plan["inputs"][0]); s["url"] += "&extra=target"
        with self.assertRaisesRegex(ValueError, "UNREGISTERED"): allowed_spec(s, "inputs", self.plan)

    def test_registration_is_not_accuracy_or_operation(self):
        self.assertFalse(self.plan["production_ready"]); self.assertFalse(self.plan["merge_or_deployment_allowed"])
        self.assertFalse(self.plan["B4_P2_or_NASA_closure_qualified"])


class AcquisitionTests(unittest.TestCase):
    def run_attempt(self, opener, *, cap=100, budget=2000, attempts=0):
        p = small_plan(); p["budget"]["body_bytes_all_attempts_inputs_plus_controls_max"] = budget
        c = Collector(p, previous_attempts=attempts, opener=opener); s = spec(); s["max_body_bytes"] = cap
        with tempfile.TemporaryDirectory() as tmp:
            note = c.attempt(s, Path(tmp), 1)
            retained = (Path(tmp) / note["member"]).read_bytes() if note.get("member") else None
        return c, note, retained

    def test_success_preserves_original_bytes(self):
        c, n, raw = self.run_attempt(lambda *a, **k: Response())
        self.assertEqual(raw, b"original"); self.assertEqual(n["status"], "ORIGINAL_BODY_RECEIVED")
        self.assertEqual(c.bytes, 8); self.assertEqual(c.attempts, 1)

    def test_attempt_cap_prevents_network(self):
        c, n, raw = self.run_attempt(lambda *a, **k: self.fail("network"), attempts=240)
        self.assertFalse(n["HTTP_attempted"]); self.assertEqual(c.attempts, 240)

    def test_oversized_stream_prefix_and_probe_counted_preserved(self):
        c, n, raw = self.run_attempt(lambda *a, **k: Response(b"123456"), cap=4)
        self.assertEqual(raw, b"12345"); self.assertEqual(c.bytes, 5); self.assertEqual(n["status"], "FAILED")

    def test_global_byte_cap_not_exceeded_by_probe(self):
        c, n, raw = self.run_attempt(lambda *a, **k: Response(b"123456"), budget=4)
        self.assertEqual(c.bytes, 4); self.assertEqual(raw, b"1234"); self.assertFalse(n["retry"])

    def test_truncation_retained_but_not_an_original(self):
        c, n, raw = self.run_attempt(lambda *a, **k: Response(b"123", headers={"Content-Length": "4"}))
        self.assertEqual(raw, b"123"); self.assertEqual(n["status"], "FAILED")

    def test_content_encoding_change_is_blocked(self):
        _, n, _ = self.run_attempt(lambda *a, **k: Response(headers={"Content-Encoding": "gzip"}))
        self.assertEqual(n["status"], "FAILED")

    def test_redirect_cannot_change_source(self):
        _, n, _ = self.run_attempt(lambda *a, **k: Response(url="https://example.invalid/other"))
        self.assertEqual(n["status"], "FAILED"); self.assertFalse(n["retry"])

    def test_retryable_HTTP_error_body_is_preserved_and_counted(self):
        def opener(*a, **k):
            raise HTTPError(spec()["url"], 503, "unavailable", {}, io.BytesIO(b"errorbody"))
        c, n, raw = self.run_attempt(opener)
        self.assertEqual(raw, b"errorbody"); self.assertEqual(c.bytes, 9); self.assertTrue(n["retry"])

    def test_404_not_retried(self):
        def opener(*a, **k): raise HTTPError(spec()["url"], 404, "missing", {}, io.BytesIO(b"404"))
        _, n, raw = self.run_attempt(opener); self.assertFalse(n["retry"]); self.assertEqual(raw, b"404")

    def test_transport_error_retried_with_no_invented_original(self):
        def opener(*a, **k): raise URLError("transport")
        _, n, raw = self.run_attempt(opener); self.assertTrue(n["retry"]); self.assertEqual(n["status"], "FAILED")

    def test_deadline_inside_collector_preserves_partial_prefix(self):
        class SlowResponse(Response):
            def read(self, n):
                if self.tell(): time.sleep(.2)
                return super().read(min(n, 2))
        p = small_plan(); p["budget"]["attempt_total_deadline_seconds"] = .02
        c = Collector(p, opener=lambda *a, **k: SlowResponse(b"12345"))
        with tempfile.TemporaryDirectory() as tmp:
            n = c.attempt(spec(), Path(tmp), 1)
            self.assertEqual((Path(tmp) / n["member"]).read_bytes(), b"12")
        self.assertTrue(n["retry"]); self.assertEqual(c.bytes, 2)

    def test_all_assets_first_pass_precedes_retries(self):
        p = small_plan(); first = spec(); second = {**spec(), "id": "second", "url": spec()["url"] + "2"}
        p["inputs"] = [first, second]; calls = []
        def opener(request, **kw):
            calls.append(request.full_url)
            if len(calls) == 1: raise URLError("once")
            return Response(url=request.full_url)
        with tempfile.TemporaryDirectory() as tmp:
            c = Collector(p, opener=opener, pause=lambda s: None)
            m = c.run("inputs", Path(tmp) / "new", {"synthetic": True})
            self.assertEqual(calls, [first["url"], second["url"], first["url"]])
            self.assertEqual(m["cumulative_HTTP_attempts"], 3)

    def test_controls_without_160_forecasts_never_reach_opener(self):
        p = build_registration(); l = ledger_for(p, 159)
        with tempfile.TemporaryDirectory() as tmp, patch("v2_weather_io.Path.read_text", return_value=json.dumps(l)):
            c = Collector(p, opener=lambda *a, **k: self.fail("control network called"))
            m = c.run("controls", Path(tmp) / "new", {"synthetic": True})
        self.assertEqual(m["HTTP_attempts_phase"], 0); self.assertFalse(m["control_bodies_opened"])

    def test_input_retries_cannot_spend_reserved_control_attempts(self):
        p = small_plan(); p["budget"].update(HTTP_attempts_inputs_plus_controls_max=3, reserved_control_first_attempt_slots=2)
        p["inputs"] = [spec()]; calls = []
        def opener(*a, **k): calls.append(1); raise URLError("outage")
        with tempfile.TemporaryDirectory() as tmp:
            c = Collector(p, opener=opener, pause=lambda s: None)
            m = c.run("inputs", Path(tmp) / "new", {"synthetic": True})
        self.assertEqual(len(calls), 1); self.assertEqual(m["effective_phase_attempt_limit"], 1)

    def test_elapsed_deadline_interrupts_an_entire_stalled_open(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            with elapsed_deadline(.02): time.sleep(.5)
        self.assertLess(time.monotonic() - start, .3)

    def test_packet_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); m = {"phase": "inputs", "member_sha256": {"a.bin": sha256(b"a").hexdigest()}}
            s = store_packet(p, INPUTS, m, {"a.bin": b"a"})
            self.assertEqual(read_packet(p, INPUTS, "inputs")[0], {"a.bin": b"a"})
            part = p / s["parts"][0]["name"]; part.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "HASH"): read_packet(p, INPUTS, "inputs")


class OperatorAndEstimatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.a = admission(); cls.plan = build_registration()

    def test_AT_QC10_only_22_12_unknown_and_missing_stay_rejected(self):
        key = "AT:5925"; clock = pd.date_range(WINDOWS[0]["start_UTC"], periods=5, freq="h")
        raw = at_body(key, clock, [1.] * 5, [10., 22, 12, None, 99])
        v, q, flags = station_values(raw, key, self.a["records"][key], clock[0], clock[-1])
        self.assertEqual(q.tolist(), [True, False, False, False, False]); self.assertEqual(flags.iloc[0], "10")

    def test_AT_fractional_QC_is_not_rounded(self):
        key = "AT:5925"; clock = pd.date_range(WINDOWS[0]["start_UTC"], periods=1, freq="h")
        with self.assertRaisesRegex(ValueError, "NONINTEGER"):
            station_values(at_body(key, clock, [1.], [10.1]), key, self.a["records"][key], clock[0], clock[-1])

    def test_AT_primary_flag_does_not_override_temperature_domain(self):
        key = "AT:5925"; clock = pd.date_range(WINDOWS[0]["start_UTC"], periods=1, freq="h")
        _, q, _ = station_values(at_body(key, clock, [100.], [10]), key, self.a["records"][key], clock[0], clock[-1])
        self.assertFalse(q.iloc[0])

    def test_AT_cross_station_payload_rejected(self):
        clock = pd.date_range(WINDOWS[0]["start_UTC"], periods=1, freq="h")
        with self.assertRaisesRegex(ValueError, "CROSS_STATION"):
            station_values(at_body("AT:4030", clock, [1.], [10]), "AT:5925", self.a["records"]["AT:5925"], clock[0], clock[-1])

    def test_CH_six_sample_operator_has_correct_linear_path(self):
        clock = pd.date_range("2019-01-09T23:00Z", periods=2, freq="h")
        v = pd.Series([0., 12.], index=clock); v.attrs["unit"] = "°C"
        self.assertEqual(model_reference_operator(v, clock[1:], "mean_six_10min_nominal_nodes").iloc[0], 7.)

    def test_CH_missing_previous_node_blocks_mean(self):
        clock = pd.date_range("2019-01-10T00:00Z", periods=1, freq="h")
        v = pd.Series([12.], index=clock); v.attrs["unit"] = "°C"
        self.assertTrue(model_reference_operator(v, clock, "mean_six_10min_nominal_nodes").isna().all())

    def test_CH_original_no_row_QC_is_separate_from_QC10(self):
        key = "CH:GRO"; first = pd.Timestamp(WINDOWS[0]["start_UTC"])
        raw = b"station_abbr;reference_timestamp;tre200h0\nGRO;10.01.2019 00:00;5.2\n"
        v, q, flags = station_values(raw, key, self.a["records"][key], first, first)
        self.assertEqual(v.iloc[0], 5.2); self.assertTrue(q.iloc[0]); self.assertEqual(flags.iloc[0], "PUBLISHED_NO_ROW_QC")

    def test_DE_QN3_and_full_hour_nodes_only(self):
        key = "DE:01072"; first = pd.Timestamp(WINDOWS[0]["start_UTC"])
        product = b"STATIONS_ID;MESS_DATUM;QN;TT_10\n1072;201901100000;3;5.\n1072;201901100010;3;50.\n1072;201901100100;10;7.\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z: z.writestr("produkt_zehn_min_tu_20100101_20191231_01072.txt", product)
        v, q, flags = station_values(buf.getvalue(), key, self.a["records"][key], first, first + pd.Timedelta(hours=1))
        self.assertEqual(v.tolist(), [5., 7.]); self.assertEqual(q.tolist(), [True, False])

    def test_DE_wrong_product_ID_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z: z.writestr("produkt_zehn_min_tu_20100101_20191231_00399.txt", b"x")
        with self.assertRaisesRegex(ValueError, "IDENTITY"): dwd_product(buf.getvalue(), "01072")

    def test_R1_common_cell_degeneracy_equals_weighted_observations(self):
        g = self.plan["groups"][0]; target = admitted_reference(self.a["records"][g["target_key"]])
        refs = [admitted_reference(self.a["records"][d]) for d in g["donors"]]
        clock = pd.date_range("2019-01-10T00:00Z", periods=2, freq="h")
        baseline = pd.Series([3., 3.], index=clock); baseline.attrs.update(unit="°C", reference_operator="published_nominal_node")
        obs = {r.key: baseline + i for i, r in enumerate(refs, 1)}
        for x in obs.values(): x.attrs.update(baseline.attrs)
        bg = {r.key: baseline.copy() for r in refs}; qc = {r.key: pd.Series(True, index=clock) for r in refs}
        predicted, ledger = reconstruct_temperature(target, baseline, refs, obs, bg, qc)
        expected = sum(obs[r.key] * ledger["weight__" + r.key] for r in refs)
        np.testing.assert_allclose(predicted, expected, rtol=0, atol=1e-14)

    def test_R1_one_valid_donor_remains_nan(self):
        g = self.plan["groups"][0]; refs = [admitted_reference(self.a["records"][d]) for d in g["donors"]]
        clock = pd.date_range("2019-01-10T00:00Z", periods=1, freq="h")
        b = pd.Series([5.], index=clock); b.attrs.update(unit="°C", reference_operator="published_nominal_node")
        obs = {r.key: b.copy() for r in refs}; bg = deepcopy(obs)
        qc = {r.key: pd.Series(i == 0, index=clock) for i, r in enumerate(refs)}
        v, ledger = reconstruct_temperature(admitted_reference(self.a["records"][g["target_key"]]), b, refs, obs, bg, qc)
        self.assertTrue(v.isna().all()); self.assertFalse(ledger.candidate_admitted.any())


class FullCaseAndScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = admission(); cls.plan = build_registration()
        cls.raw, cls.ledger = make_predictions(cls.plan, cls.a, {}, {})

    def test_no_sources_retains_every_nan_and_case(self):
        f = load_predictions(self.raw, self.plan)
        self.assertEqual(len(f), 12096); self.assertEqual(len(self.ledger["cases"]), 72)
        self.assertTrue(f.R1_C.isna().all()); self.assertTrue(f.B0_C.isna().all())

    def test_no_160_hour_prediction_keeps_all_targets_closed(self):
        self.assertFalse(any(v["open"] for v in self.ledger["control_admission"].values()))

    def test_gate_threshold_is_frozen_159_vs_160(self):
        l = ledger_for(self.plan, 159)
        self.assertFalse(any(v["open"] for v in l["control_admission"].values()))
        l["cases"][0]["finite_paired_forecast_hours"] = 160
        m = control_admission(self.plan, l); self.assertEqual(sum(v["open"] for v in m.values()), 1)

    def test_dropped_case_cannot_bypass_control_gate(self):
        l = deepcopy(self.ledger); l["cases"].pop()
        with self.assertRaisesRegex(ValueError, "CENSUS"): control_admission(self.plan, l)

    def test_zero_sources_score_all72_blocks_no_false_winner(self):
        result, pairs = score_predictions(self.raw, self.ledger, self.plan, self.a, {}, {})
        self.assertEqual(len(result["cases"]), 72); self.assertEqual(result["paired_reference_hours"], 0); self.assertEqual(pairs, [])
        self.assertFalse(any(c["within_pilot_uniform_observed_benefit"] for c in result["countries"].values()))

    def test_prediction_flag_cannot_claim_nan(self):
        raw = self.raw.replace(b",False,0,", b",True,0,", 1)
        with self.assertRaises(ValueError): load_predictions(raw, self.plan)

    def synthetic_cases(self, bad_station=False, missing=False):
        targets = [k for k in self.plan["target_keys"] if k.startswith("AT")]; cases = []; errors = {}
        for i, key in enumerate(targets):
            for w in WINDOWS:
                n = 159 if missing and i == 0 and w["season"] == "winter" else 168
                cases.append({"target_key": key, "country": "AT", "season": w["season"], "paired_hours": n})
                errors[(key, w["season"])] = (np.ones(n), np.full(n, 1.1 if bad_station and i == 0 else .5))
        return cases, errors

    def test_aggregate_gain_cannot_hide_one_worsened_station(self):
        cases, errors = self.synthetic_cases(bad_station=True)
        s = country_summary("AT", cases, errors)
        self.assertLess(s["admitted_pairs"]["delta_MAE_K"], 0)
        self.assertFalse(s["within_pilot_uniform_observed_benefit"])

    def test_23_admitted_cases_cannot_pass_24_case_rule(self):
        cases, errors = self.synthetic_cases(missing=True); s = country_summary("AT", cases, errors)
        self.assertEqual(s["admitted_cases"], 23); self.assertFalse(s["within_pilot_uniform_observed_benefit"])
        self.assertIsNone(s["resampling_descriptive_only"])

    def test_full_uniform_pilot_gain_has_only_descriptive_resampling(self):
        cases, errors = self.synthetic_cases(); s = country_summary("AT", cases, errors)
        self.assertTrue(s["within_pilot_uniform_observed_benefit"])
        self.assertFalse(s["resampling_descriptive_only"]["population_CI_or_p_value"])
        self.assertFalse(s["regional_or_population_accuracy_qualified"])
        self.assertEqual(s, country_summary("AT", cases, errors))

    def test_bias_centred_RMSE_decomposition(self):
        m = metrics([1., 2., 3.]); self.assertAlmostEqual(m["RMSE_K"] ** 2, m["bias_K"] ** 2 + m["centred_RMSE_K"] ** 2)

    def test_paired_scores_do_not_mix_disjoint_hours(self):
        s = delta_summary([(np.array([1., -1.]), np.array([.5, -.5]))])
        self.assertEqual(s["delta_MAE_K"], -.5); self.assertEqual(s["B0"]["n"], s["R1"]["n"])

    def test_derived_replay_tolerance_cannot_relax_QC_census_or_categories(self):
        self.assertTrue(same_derived_json({"x": 1.}, {"x": 1. + 1e-12}))
        self.assertFalse(same_derived_json({"x": 1.}, {"x": 1. + 1e-8}))
        self.assertFalse(same_derived_json({"n": 160}, {"n": 159}))
        self.assertFalse(same_derived_json({"q": True}, {"q": 1}))


class SyntheticEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = admission(); cls.plan = build_registration(); cls.bodies = {}; cls.controls = {}
        axis = pd.date_range("2019-01-01", periods=8760, freq="h", tz="UTC")
        refs = pd.DatetimeIndex([t for w in WINDOWS for t in pd.date_range(w["start_UTC"], w["end_UTC"], freq="h")])
        for s in cls.plan["inputs"] + cls.plan["controls"]:
            key = s["station_key"]; c, sid = key.split(":")
            if s["kind"] == "model_background":
                p = s["parameters"]
                raw = json_bytes({"utc_offset_seconds": 0, "latitude": float(p["latitude"]), "longitude": float(p["longitude"]),
                    "elevation": None, "hourly_units": {"temperature_2m": "°C"},
                    "hourly": {"time": axis.strftime("%Y-%m-%dT%H:%M").tolist(), "temperature_2m": [5.] * 8760}})
            elif s["source_block"]:
                continue
            elif c == "AT":
                raw = at_body(key, refs, [10.] * len(refs), [10] * len(refs))
            elif c == "CH":
                raw = ("station_abbr;reference_timestamp;tre200h0\n" + "".join(sid + ";" + t.strftime("%d.%m.%Y %H:%M") + ";10.\n" for t in refs)).encode()
            else:
                product = ("STATIONS_ID;MESS_DATUM;QN;TT_10\n" + "".join(str(int(sid)) + ";" + t.strftime("%Y%m%d%H%M") + ";3;10.\n" for t in refs)).encode()
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z: z.writestr("produkt_zehn_min_tu_20100101_20191231_" + sid + ".txt", product)
                raw = buf.getvalue()
            (cls.controls if s["role"] == "control" else cls.bodies)[s["id"]] = raw
        cls.raw, cls.ledger = make_predictions(cls.plan, cls.a, cls.bodies, {"donor_DE_14138": "REGISTERED_BLOCK"})
        cls.result, cls.pairs = score_predictions(cls.raw, cls.ledger, cls.plan, cls.a, cls.controls, {})

    def test_same_constant_field_reconstructs_all12096_references(self):
        f = load_predictions(self.raw, self.plan)
        self.assertEqual(int(f.R1_predicted.sum()), 12096)
        np.testing.assert_allclose(f.R1_C, 10., atol=1e-10, rtol=0)
        np.testing.assert_allclose(f.B0_C, 5., atol=1e-10, rtol=0)

    def test_known_missing_third_donor_uses_only_two_fixed_others(self):
        f = load_predictions(self.raw, self.plan); p = f[f.target_key == "DE:06170"]
        self.assertTrue(p.accepted_donor_count.eq(2).all()); self.assertTrue(p.weight_2.eq(0).all())
        self.assertTrue(np.allclose(p.weight_1 + p.weight_3, 1.))

    def test_target_truth_is_read_by_score_only_and_paired_exactly(self):
        self.assertEqual(self.result["paired_reference_hours"], 12096); self.assertEqual(len(self.pairs), 12096)
        self.assertFalse(self.ledger["control_observation_input"])
        for c in self.result["countries"].values():
            self.assertAlmostEqual(c["admitted_pairs"]["B0"]["MAE_K"], 5.)
            self.assertAlmostEqual(c["admitted_pairs"]["R1"]["MAE_K"], 0.)

    def test_model_year_and_units_cannot_change(self):
        s = self.plan["inputs"][0]; obj = json.loads(self.bodies[s["id"]])
        obj["hourly_units"]["temperature_2m"] = "K"
        with self.assertRaisesRegex(ValueError, "CELSIUS"): model_temperature(json_bytes(obj), s)
        obj["hourly_units"]["temperature_2m"] = "°C"; obj["hourly"]["time"][0] = "2018-01-01T00:00"
        with self.assertRaisesRegex(ValueError, "CALENDAR"): model_temperature(json_bytes(obj), s)

    def test_synthetic_success_does_not_promote_operation(self):
        self.assertFalse(self.result["production_ready"]); self.assertFalse(self.result["automatic_R1_default_promotion"])


if __name__ == "__main__": unittest.main()
