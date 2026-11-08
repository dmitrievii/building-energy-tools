"""Sealed D/V selection and separately opened C evaluation."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib.metadata
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time

import numpy as np

from ige_local.common import InputError, digest, file_hash, log, now, peak_rss_bytes, read_json, write_csv, write_json, source_audit_failed
from . import VERSION
from .cases import Cases, inner_cases, role_cases
from .config import data_signature
from .data import Cube
from .fit import Unidentifiable, fit_cases, kernel_parameters, optimize, predict
from .metrics import PREDICTION_FIELDS, metrics, nearest, prediction_rows


def implementation_manifest():
    root = Path(__file__).resolve().parents[1]
    paths = [root/"ige_regression.py"]
    for folder in ("ige_auto", "ige_local"):
        paths.extend(sorted((root/folder).glob("*.py")))
    return {str(p.relative_to(root)).replace(os.sep, "/"): file_hash(p) for p in paths}


def environment():
    return {"python": sys.version, "platform": platform.platform(), "version": VERSION,
            "dependencies": {n: importlib.metadata.version(n) for n in ("numpy", "scipy")},
            "threads": {n: os.environ.get(n) for n in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}}


def sealed_write(path, data, key):
    data = dict(data); data[key] = digest(data); write_json(path, data)
    return data


def sealed_read(path, key):
    data = read_json(path)
    if data.get(key) != digest({k: v for k, v in data.items() if k != key}):
        raise InputError("Sealed document mismatch: " + str(path))
    return data


def _model_worker(cube_path, c, variable, model, output):
    started = time.monotonic()
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    cube = Cube(cube_path, verify=False)
    result = {"variable": variable, "model": model, "status": "STARTED"}
    try:
        folds = inner_cases(cube, c, variable)
        write_json(output/"case_ledger.json", [x.ledger for pair in folds for x in pair])
        search = optimize(folds, model, c)
        trace = search.pop("trace", [])
        write_json(output/"optimization_trace.json", trace)
        result["optimization"] = search
        del folds
        if search["status"] != "CONVERGED":
            result["status"] = search["status"]
        else:
            eta = search["eta"]
            a = role_cases(cube, c, variable, "D", "D", {"D"}, "outer_D_fit")
            fitted = fit_cases(a, model, eta, c["optimizer"])
            result.update(fit_D=fitted, kernel_parameters=kernel_parameters(model, eta), D_cases=a.ledger)
            del a
            b = role_cases(cube, c, variable, "V", "V", {"D"}, "outer_V_selection")
            pred, neff, w = predict(b, model, eta, fitted)
            result["validation"] = metrics(b, pred, b.fit_mask)
            result["V_cases"] = b.ledger
            result["n_eff_V_median"] = float(np.median(neff[b.ready])) if np.any(b.ready) else None
            nn = nearest(b)
            result["paired_NN"] = metrics(b, nn, b.fit_mask & np.isfinite(pred))
            good = b.fit_mask
            result["status"] = "ELIGIBLE" if good.sum() >= c["optimizer"]["min_fit_cases"] and np.all(np.isfinite(pred[good])) else "INSUFFICIENT_V"
            write_csv(output/"V_predictions.csv", prediction_rows(b, pred, neff, w), PREDICTION_FIELDS)
            # Historical controls are not candidates, priors, or fit targets.
            controls = {"NN_NATIVE": metrics(b, nn)}
            base, _, _ = b.design("height", "idw", [2., -100.])
            base[~b.ready] = np.nan
            controls["IDW_HORIZONTAL_BETA2_COMPARATOR"] = metrics(b, base)
            if variable == "T":
                native, xx, _ = b.design("height", "idw", [2., -100.])
                historical = native-6.5*xx[:, 0]; historical[~b.ready] = np.nan
                controls["T_LAPSE_MINUS6_5_K_KM_HISTORICAL_COMPARATOR"] = metrics(b, historical)
            result["controls"] = controls
    except (Unidentifiable, InputError, ValueError, np.linalg.LinAlgError) as exc:
        result["status"] = "UNIDENTIFIABLE_OR_UNSUPPORTED"; result["reason"] = str(exc)
    result["worker_wall_seconds"] = time.monotonic()-started
    result["process_lifetime_peak_rss_bytes"] = peak_rss_bytes()
    write_json(output/"result.json", result)
    return result


def final_fit(cube, c, selected):
    result = {}
    for variable, r in selected.items():
        model = r["model"]; eta = r["optimization"]["eta"]
        if c["final_refit"] == "D_ONLY":
            fitted = r["fit_D"]; ledger = r["D_cases"]; donors = ["D"]
        else:
            panels = [(np.flatnonzero(cube.roles == role), np.flatnonzero(cube.time_roles == role)) for role in ("D", "V")]
            a = Cases(cube, panels, np.flatnonzero(np.isin(cube.roles, ["D", "V"])), variable, c, "final_D_plus_V_fit")
            fitted = fit_cases(a, model, eta, c["optimizer"]); ledger = a.ledger; donors = ["D", "V"]
        result[variable] = {"model": model, "eta": eta, "kernel_parameters": kernel_parameters(model, eta),
                            "regression": fitted, "donor_roles": donors, "fit_cases": ledger,
                            "units": {"T": "degC", "RH": "%", "p": "hPa", "log_e_water": "ln(e / 1 hPa), derived liquid-water assumption"}[variable],
                            "coefficient_units": "output units per km of contrast; harmonic/season factors dimensionless",
                            "height_semantics": "published station geometry proxy; p fit is empirical, not calibrated barometer hypsometry"}
    return result


def train(cube_path, c, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    cube = Cube(cube_path)
    if cube.meta["data_signature"] != data_signature(c):
        raise InputError("Cube selection/split differs from configuration; prepare a new cube")
    spec = sealed_write(output/"run_spec.sealed.json", {
        "schema": "IGE_AUTO_RUN_v1", "created_utc": now(), "configuration": c, "cube_path": str(cube.path),
        "cube_id": cube.meta["cube_id"], "implementation": implementation_manifest(), "environment": environment(),
        "selection": "D grouped inner CV; V macro MAE chooses structure; numerical ties <=1e-10*max(1,best_MAE) prefer fewer coefficients; C unused",
        "exposure": "Native source containers parsed automatically; C is computationally withheld, not claimed blind raw data",
        "no_full_year_gate": True, "scientific_qualification": False}, "run_spec_id")
    tasks = [(v, m) for v in c["variables"] for m in c["models"]]
    results = []
    begin = time.monotonic()
    if c["workers"] == 1:
        for v, m in tasks:
            log("Training " + v + " / " + m["id"])
            r = _model_worker(str(cube.path), c, v, m, str(output/"models"/v/m["id"]))
            results.append(r); log("  " + r["status"])
    else:
        with ProcessPoolExecutor(max_workers=c["workers"], mp_context=multiprocessing.get_context("spawn")) as pool:
            futures = {pool.submit(_model_worker, str(cube.path), c, v, m, str(output/"models"/v/m["id"])): (v, m) for v, m in tasks}
            for f in as_completed(futures):
                v, m = futures[f]
                try:
                    r = f.result()
                except Exception as exc:
                    r = {"variable": v, "model": m, "status": "WORKER_FAILED", "reason": str(exc)}
                results.append(r); log(v + " / " + m["id"] + ": " + r["status"])
    results.sort(key=lambda r: (r["variable"], r["model"]["id"]))
    # All eligible models must use the same pre-observation V rows and donor mask.
    selected = {}; selection_failures = {}
    for v in c["variables"]:
        rs = [r for r in results if r["variable"] == v and r["status"] == "ELIGIBLE"]
        if len({r["V_cases"]["case_id"] for r in rs}) > 1:
            raise InputError("Candidates have different V case sets")
        if rs:
            best_score = min(r["validation"][c["selection_metric"]] for r in rs)
            tol = 1e-10*max(1., abs(best_score))
            tied = [r for r in rs if r["validation"][c["selection_metric"]] <= best_score+tol]
            selected[v] = min(tied, key=lambda r: (len(r["fit_D"]["coefficients"]),
                             {"ols": 0, "ridge": 1, "huber": 2}[r["model"]["regression"]], r["model"]["id"]))
        else:
            selection_failures[v] = "NO_ELIGIBLE_CONVERGED_MODEL"
    final = {}
    for v, r in selected.items():
        try:
            final.update(final_fit(cube, c, {v: r}))
        except (Unidentifiable, InputError, np.linalg.LinAlgError) as exc:
            selection_failures[v] = "FINAL_REFIT_FAILED: " + str(exc)
    # Recheck immutable inputs after spawned calculations, before sealing models.
    Cube(cube.path)
    if implementation_manifest() != spec["implementation"]:
        raise InputError("Implementation changed during fitting")
    selected_file = sealed_write(output/"selected_models.sealed.json", {
        "schema": "IGE_AUTO_SELECTED_v1", "run_spec_id": spec["run_spec_id"], "cube_id": cube.meta["cube_id"],
        "models": final, "selection_failures": selection_failures,
        "selection_scores_V": {v: r["validation"] for v, r in selected.items()},
        "weights_frozen_before_final_refit": True, "final_refit": c["final_refit"],
        "implementation_id": digest(spec["implementation"])}, "selected_id")
    comparison = []; coefficients = []
    for r in results:
        row = {"variable": r["variable"], "model": r["model"]["id"], "status": r["status"],
               "selected_structure": r["variable"] in selected and selected[r["variable"]]["model"]["id"] == r["model"]["id"]}
        row.update({k: r.get("validation", {}).get(k) for k in ("MAE", "RMSE", "bias", "N_scored", c["selection_metric"])})
        row["reason"] = r.get("reason", ""); comparison.append(row)
        if "fit_D" in r:
            coefficients.extend({"stage": "D", "variable": r["variable"], "model": r["model"]["id"], "feature": name, "coefficient_per_km": value}
                                for name, value in zip(r["fit_D"]["feature_names"], r["fit_D"]["coefficients"]))
    for v, r in final.items():
        coefficients.extend({"stage": c["final_refit"], "variable": v, "model": r["model"]["id"], "feature": n, "coefficient_per_km": x}
                            for n, x in zip(r["regression"]["feature_names"], r["regression"]["coefficients"]))
    write_csv(output/"model_comparison.csv", comparison, ["variable", "model", "status", "selected_structure", "MAE", "RMSE", "bias", "N_scored", c["selection_metric"], "reason"])
    write_csv(output/"coefficients.csv", coefficients, ["stage", "variable", "model", "feature", "coefficient_per_km"])
    e0 = cube.meta.get("source_audit") or {}
    e0_failed = source_audit_failed(e0)
    country_gaps = {v: [country for country in c["countries"] if not r["validation"]["by_country"].get(country, {}).get("N_scored")]
                    for v, r in selected.items()}
    country_gaps = {v: x for v, x in country_gaps.items() if x}
    unavailable = bool(cube.meta.get("notes") or cube.meta.get("source_errors") or e0_failed or country_gaps)
    summary = {"version": VERSION, "finished_utc": now(), "run_spec_id": spec["run_spec_id"], "selected_id": selected_file["selected_id"],
               "models_requested": len(tasks), "models_eligible": sum(r["status"] == "ELIGIBLE" for r in results),
               "selected": {v: r["model"]["id"] for v, r in final.items()}, "selection_failures": selection_failures,
               "source_read_failures": cube.meta.get("source_errors", []), "source_readiness_notes": cube.meta.get("notes", []),
               "E0_errors_or_quarantine": e0_failed, "variables_missing_V_countries": country_gaps,
               "holdout_opened": False, "scientific_accuracy_qualified": False, "wall_seconds": time.monotonic()-begin,
               "parent_process_lifetime_peak_rss_bytes": peak_rss_bytes(),
               "exit_code": 2 if selection_failures or unavailable else 0}
    write_json(output/"summary.json", summary)
    lines = ["# IGE — автоматический подбор пространственных регрессий", "", "Версия " + VERSION + ".", "",
             "Обучение завершено. Код завершения: **%s**." % summary["exit_code"], "",
             "D: обучение и внутренняя проверка по семействам станций. V: выбор структуры. На момент окончания обучения C не открыт.",
             "Доноры каждой внутренней проверки полностью исключают проверяемые семейства из обучения.",
             "Использованы отдельные доступные часы; полные годы не требуются. Метрики относятся к сохранённой выборке, а не ко всей базе.", "",
             "Выбранные модели: " + str(summary["selected"]) + ".", "",
             "- `model_comparison.csv`: сравнение по общим доступным часам V.",
             "- `coefficients.csv`: коэффициенты до и после заявленного дообучения.",
             "- `selected_models.sealed.json`: формулы, единицы, параметры весов, SVD и происхождение.",
             "- `models/<величина>/<модель>/`: трасса оптимизации, внутренние проверки, прогнозы V с QC и отказами.", "",
             "Оптимизация локальная; сходимость не доказывает единственность параметров или их физическую причинность.",
             "Старый градиент −6.5 K/km и IDW β=2 — только исторические контроли; в подбор не входят.",
             "Давление использует высоту площадки как прокси. log(e) вычислен из T/RH по Buck над жидкой водой; это не независимое измерение e.",
             "Значения RH не обрезаются. QC не превращается в выдуманные веса доверия; неопубликованная ручная проверка не означает ошибку.", "",
             "Проверка C: `python ige_regression.py evaluate --run \"" + str(output) + "\"`.",
             "Открытие C регистрируется. Повторная проверка требует явного `--repeat` и теряет статус первого открытия.",
             "Входные сырые контейнеры уже были автоматически прочитаны; здесь не заявляется слепой доступ к исходникам.",
             "Численные тесты программы и инженерный запуск не заменяют научную квалификацию точности."]
    (output/"REPORT_RU.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return summary


def evaluate(run, repeat=False):
    run = Path(run).resolve(); spec = sealed_read(run/"run_spec.sealed.json", "run_spec_id")
    selected = sealed_read(run/"selected_models.sealed.json", "selected_id")
    if selected["run_spec_id"] != spec["run_spec_id"] or selected["cube_id"] != spec["cube_id"]:
        raise InputError("Model/run identity mismatch")
    if implementation_manifest() != spec["implementation"] or digest(spec["implementation"]) != selected["implementation_id"]:
        raise InputError("Implementation differs from sealed fitting code")
    if not selected["models"]:
        raise InputError("No fitted model to evaluate")
    cube = Cube(spec["cube_path"]); c = spec["configuration"]
    if cube.meta["cube_id"] != spec["cube_id"]:
        raise InputError("Cube differs from sealed model inputs")
    marker = run/"C_OPENED.json"
    if marker.exists() and not repeat:
        raise InputError("C already opened. Use --repeat to record another exposure, not a new confirmation")
    # Exclusive marker creation prevents two concurrent first-opening evaluations.
    if not marker.exists():
        try:
            with marker.open("x", encoding="utf-8") as f:
                import json
                json.dump({"first_opened_utc": now(), "selected_id": selected["selected_id"]}, f)
        except FileExistsError as exc:
            raise InputError("Another process opened C") from exc
    from ige_local.common import new_run
    output = new_run(run/"holdout_evaluations")
    report = {"selected_id": selected["selected_id"], "opened_utc": now(), "repeated_exposure": repeat,
              "scientific_accuracy_qualified": False, "panels": {}}
    for variable, r in selected["models"].items():
        panels = {}
        for name, target, time_role in (("joint_C_sites_C_years", "C", "C"), ("spatial_C_sites_D_years", "C", "D"), ("temporal_D_sites_C_years", "D", "C")):
            b = role_cases(cube, c, variable, target, time_role, set(r["donor_roles"]), name)
            p, neff, w = predict(b, r["model"], r["eta"], r["regression"])
            common = b.fit_mask & np.isfinite(p)
            panels[name] = {"model": metrics(b, p), "NN_own": metrics(b, nearest(b)),
                            "model_paired": metrics(b, p, common), "NN_paired": metrics(b, nearest(b), common), "cases": b.ledger}
            write_csv(output/(variable+"_"+name+".csv"), prediction_rows(b, p, neff, w), PREDICTION_FIELDS)
        report["panels"][variable] = panels
    Cube(cube.path)
    if implementation_manifest() != spec["implementation"]:
        raise InputError("Implementation changed during C evaluation")
    report["exit_code"] = 0 if all(x["model"]["N_scored"] for panels in report["panels"].values() for x in panels.values()) else 2
    report["evaluation_directory"] = str(output)
    write_json(output/"summary.json", report)
    summary = read_json(run/"summary.json")
    summary.update(holdout_opened=True, latest_holdout_evaluation=str(output), latest_holdout_exit_code=report["exit_code"])
    write_json(run/"summary.json", summary)
    log("C evaluation: " + str(output))
    return report
