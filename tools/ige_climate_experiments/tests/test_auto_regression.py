from __future__ import annotations

import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

for _n in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_n] = "1"
import numpy as np

from support_auto import ROOT, config, save_cube, synthetic_cube
from support import files_unchanged_state, make_at
from ige_auto.cases import Cases, feature_names, inner_cases, macro_weights, role_cases, sample_grid
from ige_auto.config import data_signature, load, native_config, windows
from ige_auto.data import Cube, buck_water, build, choose_and_split
from ige_auto.experiment import evaluate, sealed_read, train
from ige_auto.fit import Unidentifiable, fit_cases, linear_solve, optimize, predict
from ige_auto.metrics import metrics, nearest
from ige_auto.oracles import self_check
from ige_local.audit import audit
from ige_local.common import InputError, digest, file_hash, read_json, write_json


class LinearTests(unittest.TestCase):
    def test_analytical_oracles(self):
        self.assertEqual(self_check()["OLS_known_gradient"], "PASS")

    def test_weighted_multifeature_solution(self):
        rng = np.random.default_rng(3); x = rng.normal(size=(80, 3)); theta = np.array([.2, -6.2, 3.])
        r = linear_solve(x, x@theta, np.linspace(.1, 1, 80))
        np.testing.assert_allclose(r["coefficients"], theta, atol=1e-12)

    def test_rank_deficiency_not_rescued_by_ridge(self):
        x = np.ones((30, 2))
        with self.assertRaises(Unidentifiable):
            linear_solve(x, np.arange(30.), np.ones(30), loss="ridge", ridge=100.)

    def test_no_height_variation_rejected(self):
        with self.assertRaises(Unidentifiable):
            linear_solve(np.zeros((30, 1)), np.ones(30), np.ones(30))

    def test_huber_reduces_single_outlier_influence(self):
        x = np.ones((50, 1)); y = np.full(50, 2.); y[-1] = 100.
        h = linear_solve(x, y, np.ones(50), loss="huber", delta=.5)
        o = linear_solve(x, y, np.ones(50))
        self.assertLess(abs(h["coefficients"][0]-2), abs(o["coefficients"][0]-2))

    def test_buck_reference_and_derived_assumption(self):
        self.assertAlmostEqual(float(buck_water(0)), 6.1121, places=8)


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.c = config(self.base); self.cube = synthetic_cube(self.base, self.c)

    def tearDown(self):
        del self.cube
        self.tmp.cleanup()

    def test_physical_family_excluded_all_hours(self):
        a = role_cases(self.cube, self.c, "T", "D", "D", {"D"})
        for j, d in enumerate(a.d):
            same = np.array([self.cube.stations[s]["family"] == self.cube.stations[d]["family"] for s in a.s])
            self.assertFalse(np.any(a.mask[same, j]))

    def test_inner_fold_never_uses_validation_family_in_fit_or_donors(self):
        for a, b in inner_cases(self.cube, self.c, "T"):
            held = set(b.ledger["target_families"])
            self.assertFalse(held & set(a.ledger["target_families"]))
            self.assertFalse(held & set(a.ledger["donor_families"]))
            self.assertFalse(held & set(b.ledger["donor_families"]))

    def test_outer_V_donors_D_only(self):
        b = role_cases(self.cube, self.c, "T", "V", "V", {"D"})
        self.assertFalse(set(b.ledger["target_families"]) & set(b.ledger["donor_families"]))
        self.assertEqual(b.ledger["target_years"], [2023])

    def test_constant_gradient_recovered_with_partial_hours(self):
        a = role_cases(self.cube, self.c, "T", "D", "D", {"D"})
        f = fit_cases(a, self.c["models"][0], [1., 0.], self.c["optimizer"])
        self.assertAlmostEqual(f["coefficients"][0], -7.3, places=10)
        self.assertLess(a.obs.sum(), len(a.y))
        self.assertGreater(a.fit_mask.sum(), 20)

    def test_monthly_coefficients_recovered(self):
        cube = synthetic_cube(self.base/"seasonal", self.c, seasonal=True)
        a = role_cases(cube, self.c, "T", "D", "D", {"D"})
        f = fit_cases(a, self.c["models"][1], [1., 0.], self.c["optimizer"])
        np.testing.assert_allclose(f["coefficients"], [-4.-.3*m for m in range(1, 13)], atol=1e-10)

    def test_time_and_availability_not_used_to_sample(self):
        a = role_cases(self.cube, self.c, "T", "D", "D", {"D"})
        p = role_cases(self.cube, self.c, "p", "D", "D", {"D"})
        self.assertEqual(a.row_id, p.row_id)

    def test_weights_normalized_and_neff_not_independent_N(self):
        a = role_cases(self.cube, self.c, "T", "V", "V", {"D"})
        for kernel, eta in (("idw", [1.3, 1.]), ("gaussian", [4., 1.])):
            w = a.weights(kernel, eta)
            np.testing.assert_allclose(w[a.ready].sum(axis=1), 1., atol=1e-12)
            self.assertTrue(np.all(w[~a.mask] == 0))
            n = 1/np.sum(w[a.ready]**2, axis=1)
            self.assertTrue(np.all(n <= a.n_donors[a.ready]+1e-12))

    def test_target_truth_cannot_change_donors_or_prediction(self):
        a = role_cases(self.cube, self.c, "T", "V", "V", {"D"})
        model = self.c["models"][0]; f = {"coefficients": [-7.3]}
        p = predict(a, model, [1., 0.], f)[0]
        a.y[:] = 123456
        np.testing.assert_array_equal(predict(a, model, [1., 0.], f)[0], p)

    def test_equal_station_and_country_training_weights(self):
        a = role_cases(self.cube, self.c, "T", "D", "D", {"D"})
        w = macro_weights(a, a.fit_mask)
        totals = [w[a.station == s].sum() for s in set(a.station[a.fit_mask])]
        np.testing.assert_allclose(totals, np.full(len(totals), 1/len(totals)), atol=1e-12)

    def test_zero_observations_have_defined_coverage(self):
        a = role_cases(self.cube, self.c, "T", "V", "V", {"D"}); a.obs[:] = False
        m = metrics(a, nearest(a))
        self.assertEqual(m["N_scored"], 0); self.assertIsNone(m["MAE"]); self.assertIsNone(m["coverage_observed"])

    def test_optimizer_flat_weights_are_flagged(self):
        r = optimize(inner_cases(self.cube, self.c, "T"), self.c["models"][0], self.c)
        self.assertEqual(r["status"], "CONVERGED")
        self.assertTrue(r["nearly_flat_sampled_objective"])
        self.assertIn("not established", r["weight_identifiability"])

    def test_continuous_IDW_parameter_recovery_on_informative_transfer(self):
        c = copy.deepcopy(self.c); c["optimizer"].update(max_evaluations=600, max_iterations=100, starts=2)
        folds = inner_cases(self.cube, c, "T"); rng = np.random.default_rng(41)
        model = c["models"][0]; truth = [2.7, .5]
        for pair in folds:
            for a in pair:
                a.dist = a.dist/100
                a.dv = rng.normal(0, 10, size=a.dv.shape)*a.mask
                base, x, _ = a.design("height", "idw", truth)
                a.y = base-4.2*x[:, 0]
        r = optimize(folds, model, c)
        self.assertEqual(r["status"], "CONVERGED")
        np.testing.assert_allclose(r["eta"], truth, atol=2e-3)
        self.assertLess(r["objective"], 1e-6)

    def test_hard_evaluation_budget_and_no_fake_convergence(self):
        c = copy.deepcopy(self.c); c["optimizer"]["max_evaluations"] = 1
        r = optimize(inner_cases(self.cube, c, "T"), c["models"][0], c)
        self.assertEqual(r["status"], "UNRESOLVED_OPTIMIZATION")
        self.assertLessEqual(len(r["trace"]), 1)

    def test_cube_tampering_detected(self):
        shutil.copytree(self.cube.path, self.base/"tampered")
        path = self.base/"tampered"/"values.npy"
        body = path.read_bytes(); path.write_bytes(body[:-1]+bytes([body[-1] ^ 1]))
        with self.assertRaises(InputError):
            Cube(path.parent)

    def test_memory_budget_rejects_before_case_matrix(self):
        c = copy.deepcopy(self.c); c["memory_budget_bytes"] = 100
        with self.assertRaises(InputError):
            role_cases(self.cube, c, "T", "D", "D", {"D"})

    def test_duplicate_family_has_one_donor_per_hour(self):
        arrays = {n: np.asarray(getattr(self.cube, n)).copy() for n in ("values", "operators", "qc", "sources", "eligible")}
        meta = copy.deepcopy(self.cube.meta)
        ds = np.flatnonzero(self.cube.roles == "D"); a, b = map(int, ds[:2])
        meta["stations"][b]["family"] = meta["stations"][a]["family"]
        cube = save_cube(self.base/"duplicate_cube", meta, arrays)
        cases = role_cases(cube, self.c, "T", "V", "V", {"D"})
        cols = [i for i, d in enumerate(cases.d) if d in (a, b)]
        self.assertTrue(np.all(cases.mask[:, cols].sum(axis=1) <= 1))

    def test_missing_T_does_not_remove_pressure(self):
        t = role_cases(self.cube, self.c, "T", "D", "D", {"D"})
        p = role_cases(self.cube, self.c, "p", "D", "D", {"D"})
        self.assertTrue(np.any(~t.obs & p.obs))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.c = config(self.base); self.cube = synthetic_cube(self.base, self.c)

    def tearDown(self):
        del self.cube
        self.tmp.cleanup()

    def test_training_and_separate_holdout_opening(self):
        out = self.base/"fit"
        r = train(self.cube.path, self.c, out)
        self.assertEqual(r["exit_code"], 0); self.assertFalse((out/"C_OPENED.json").exists())
        models = sealed_read(out/"selected_models.sealed.json", "selected_id")
        self.assertAlmostEqual(models["models"]["T"]["regression"]["coefficients"][0], -7.3, places=9)
        score = evaluate(out); self.assertEqual(score["exit_code"], 0)
        with self.assertRaisesRegex(InputError, "already opened"):
            evaluate(out)
        self.assertTrue(evaluate(out, repeat=True)["repeated_exposure"])

    def test_C_value_mutation_cannot_change_fit_or_selection(self):
        one = self.base/"one"; two = self.base/"two"
        train(self.cube.path, self.c, one)
        arrays = {n: np.asarray(getattr(self.cube, n)).copy() for n in ("values", "operators", "qc", "sources", "eligible")}
        # Mutate C-station values in every year AND every station in C years.
        arrays["values"][self.cube.roles == "C"] = 9999
        arrays["values"][:, self.cube.time_roles == "C"] = -9999
        altered = save_cube(self.base/"altered", self.cube.meta, arrays)
        train(altered.path, self.c, two)
        a = read_json(one/"selected_models.sealed.json"); b = read_json(two/"selected_models.sealed.json")
        self.assertEqual(a["models"], b["models"])
        self.assertEqual(a["selection_scores_V"], b["selection_scores_V"])

    def test_serial_and_spawned_models_match(self):
        one, two = self.base/"serial", self.base/"spawn"
        train(self.cube.path, self.c, one)
        c = copy.deepcopy(self.c); c["workers"] = 2
        train(self.cube.path, c, two)
        self.assertEqual(read_json(one/"selected_models.sealed.json")["models"], read_json(two/"selected_models.sealed.json")["models"])

    def test_all_failed_candidates_not_reported_as_best(self):
        c = copy.deepcopy(self.c); c["optimizer"]["min_fit_cases"] = 999999
        out = self.base/"failed"; r = train(self.cube.path, c, out)
        self.assertEqual(r["exit_code"], 2); self.assertFalse(r["selected"])
        with self.assertRaisesRegex(InputError, "No fitted model"):
            evaluate(out)

    def test_selected_model_tamper_blocks_evaluation(self):
        out = self.base/"fit"; train(self.cube.path, self.c, out)
        p = out/"selected_models.sealed.json"; d = read_json(p); d["models"]["T"]["eta"][0] += 1; write_json(p, d)
        with self.assertRaises(InputError):
            evaluate(out)

    def test_fit_cli_reuses_cube_and_keeps_C_closed(self):
        cmd = [sys.executable, str(ROOT/"ige_regression.py"), "fit", "--config", self.c["config_source_path"], "--cube", str(self.cube.path)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        self.assertFalse(list(Path(self.c["results"]).rglob("C_OPENED.json")))

    def test_all_six_structures_and_four_variables_execute(self):
        c = copy.deepcopy(self.c)
        c["models"] = read_json(ROOT/"config_auto_regression.json")["models"]
        c["variables"] = ["T", "RH", "p", "log_e_water"]
        c["optimizer"]["max_evaluations"] = 200
        r = train(self.cube.path, c, self.base/"matrix")
        self.assertEqual(r["models_requested"], 24)
        self.assertGreaterEqual(r["models_eligible"], 12)
        self.assertEqual(set(r["selected"]), set(c["variables"]))
        self.assertEqual(r["selected"]["T"], "height_idw_ols")

    def test_model_code_change_blocks_C(self):
        out = self.base/"fit"; train(self.cube.path, self.c, out)
        p = out/"run_spec.sealed.json"; d = read_json(p); d.pop("run_spec_id")
        d["implementation"]["ige_regression.py"] = "0"*64
        d["run_spec_id"] = digest(d); write_json(p, d)
        with self.assertRaises(InputError): evaluate(out)
        self.assertFalse((out/"C_OPENED.json").exists())


class NativeAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name); self.c = config(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_paths_with_spaces_and_cyrillic(self):
        c = config(self.base/"Данные с пробелом")
        self.assertTrue(Path(c["database"]).is_dir())

    def test_overlapping_years_rejected(self):
        p = Path(self.c["config_source_path"]); d = read_json(p); d["years"]["V"] = d["years"]["D"]; write_json(p, d)
        with self.assertRaises(InputError): load(p)

    def test_nonfinite_optimizer_rejected(self):
        p = Path(self.c["config_source_path"]); text = p.read_text(); text = text.replace('"max_condition": 100000000.0', '"max_condition": 1e999'); p.write_text(text)
        with self.assertRaises(InputError): load(p)

    def test_native_build_preserves_QC_partial_hours_and_sources(self):
        def observations(records):
            for sid, rows in records.items():
                rows[0]["tl_flag"] = 12; rows[1]["tl_flag"] = 22; rows[2]["tl_flag"] = 0
                rows[3]["tl"] = None
        make_at(self.base/"Database", nsites=15, hours=4, start="2020-01-15T00:00:00Z", transform=observations)
        before = files_unchanged_state(self.base/"Database")
        with contextlib.redirect_stdout(io.StringIO()):
            snap, _ = audit(native_config(self.c), self.base/"E0")
            build(snap, self.c, self.base/"native_cube")
        cube = Cube(self.base/"native_cube")
        t = {s: i for i, s in enumerate(cube.times)}
        self.assertTrue(np.all(cube.eligible[:, t["2020-01-15T00:00:00Z"], 0]))
        self.assertTrue(np.all(cube.eligible[:, t["2020-01-15T01:00:00Z"], 0]))
        self.assertFalse(np.any(cube.eligible[:, t["2020-01-15T02:00:00Z"], 0]))
        self.assertFalse(np.any(cube.eligible[:, t["2020-01-15T03:00:00Z"], 0]))
        self.assertTrue(np.all(cube.eligible[:, t["2020-01-15T03:00:00Z"], 2]))
        self.assertEqual(before, files_unchanged_state(self.base/"Database"))
        self.assertFalse(cube.meta["source_errors"])

    def test_QC_sensitivity_retains_unchecked_without_calling_it_bad(self):
        def observations(records):
            for rows in records.values(): rows[0]["tl_flag"] = 0
        make_at(self.base/"Database", nsites=15, hours=1, start="2020-01-15T00:00:00Z", transform=observations)
        c = copy.deepcopy(self.c); c["qc_mode"] = "sensitivity_all_published"
        with contextlib.redirect_stdout(io.StringIO()):
            snap, _ = audit(native_config(c), self.base/"E0"); build(snap, c, self.base/"cube")
        cube = Cube(self.base/"cube")
        self.assertTrue(np.all(cube.eligible[:, 0, 0]))
        self.assertIn("unchecked", [q["stratum"] for q in cube.meta["qc_codebook"]])

    def test_derived_vapour_requires_explicit_assumption(self):
        p = Path(self.c["config_source_path"]); d = read_json(p); d["variables"] = ["log_e_water"]; d["water_vapour_assumption"] = "auto"; write_json(p, d)
        with self.assertRaises(InputError): load(p)

    def test_native_end_to_end_run_command(self):
        for year in (2020, 2023, 2025):
            make_at(self.base/"Database", nsites=15, hours=24, start=str(year)+"-01-15T00:00:00Z")
        p = Path(self.c["config_source_path"]); c = read_json(p)
        c.update(cases_per_partition=5000, models=[c["models"][0]])
        write_json(p, c)
        before = files_unchanged_state(self.base/"Database")
        r = subprocess.run([sys.executable, str(ROOT/"ige_regression.py"), "run", "--config", str(p)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        self.assertEqual(before, files_unchanged_state(self.base/"Database"))
        results = [p for p in Path(self.c["results"]).glob("*/summary.json")]
        self.assertEqual(len(results), 1)
        summary = read_json(results[0]); self.assertEqual(summary["selected"]["T"], "height_idw_ols")
        fitted = read_json(results[0].parent/"selected_models.sealed.json")["models"]["T"]
        self.assertAlmostEqual(fitted["regression"]["coefficients"][0], 40., places=8)

    def test_too_few_completed_families_gets_readiness_failure(self):
        make_at(self.base/"Database", nsites=4, hours=4, start="2020-01-15T00:00:00Z")
        with contextlib.redirect_stdout(io.StringIO()):
            snap, _ = audit(native_config(self.c), self.base/"E0")
        with self.assertRaisesRegex(InputError, "enough independent"):
            build(snap, self.c, self.base/"cube")


if __name__ == "__main__":
    unittest.main()
