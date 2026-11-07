"""Reproducible synthetic engineering evidence. Writes only to the supplied folder."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys
import time

from support_auto import ROOT, config, synthetic_cube
from ige_auto.experiment import environment, evaluate, train
from ige_auto.cases import inner_cases
from ige_auto.fit import optimize
from ige_local.common import read_json, write_json
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    c = config(args.out)
    c["variables"] = ["T", "RH", "p", "log_e_water"]
    c["models"] = read_json(ROOT/"config_auto_regression.json")["models"]
    c["optimizer"]["max_evaluations"] = 200
    cube = synthetic_cube(args.out, c)
    begin = time.monotonic()
    serial = train(cube.path, c, args.out/"serial")
    c2 = copy.deepcopy(c); c2["workers"] = 2
    parallel = train(cube.path, c2, args.out/"parallel")
    a = read_json(args.out/"serial"/"selected_models.sealed.json")["models"]
    b = read_json(args.out/"parallel"/"selected_models.sealed.json")["models"]
    holdout = evaluate(args.out/"serial")
    c3 = copy.deepcopy(c); c3["optimizer"].update(max_evaluations=600, max_iterations=100, starts=2)
    folds = inner_cases(cube, c3, "T"); rng = np.random.default_rng(41); truth = [2.7, .5]
    for pair in folds:
        for cases in pair:
            cases.dist = cases.dist/100
            cases.dv = rng.normal(0, 10, size=cases.dv.shape)*cases.mask
            base, x, _ = cases.design("height", "idw", truth)
            cases.y = base-4.2*x[:, 0]
    nonlinear = optimize(folds, c3["models"][0], c3)
    nonlinear.pop("trace", None)
    evidence = {"schema": "IGE_AUTO_ENGINEERING_VALIDATION_v1", "scope": "SYNTHETIC_NOT_WEATHER_ACCURACY",
                "environment": environment(), "serial": serial, "parallel": parallel,
                "selected_models_identical_serial_spawn": a == b, "C_evaluation_exit_code": holdout["exit_code"],
                "known_height_coefficient_T": -7.3, "fitted_T_coefficients": a["T"]["regression"]["coefficients"],
                "nonlinear_IDW_truth_eta": truth, "nonlinear_IDW_fitted": nonlinear,
                "scientific_accuracy_qualified": False, "user_full_database_fit": False,
                "wall_seconds_including_all_operations": time.monotonic()-begin}
    write_json(args.out/"engineering_evidence.json", evidence)
    assert a == b and serial["exit_code"] == 0 and parallel["exit_code"] == 0 and holdout["exit_code"] == 0
    np.testing.assert_allclose(nonlinear["eta"], truth, atol=.002)


if __name__ == "__main__":
    main()
