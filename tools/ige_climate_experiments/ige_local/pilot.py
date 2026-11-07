"""E1.0 engineering controls, held-out targets, and serial/process reproducibility."""
from __future__ import annotations

import collections
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gzip
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time

from .common import (InputError, digest, file_hash, log, now, peak_rss_bytes, read_json,
                     write_csv, write_json)
from .readers import UNITS, prepare, qc_allowed

STATE = None
METHODS = ["NN_NATIVE", "IDW_NATIVE", "IDW_T_FIXED_LAPSE_PROXY"]
PRED_FIELDS = ["target", "timestamp_utc", "variable", "unit", "qc_mode", "method", "control_value",
               "control_eligible", "target_qc", "target_qc_stratum", "operator", "prediction", "error",
               "status", "inputs_ready", "donor_count", "donors_json", "donor_qc_strata_json", "diagnostic_physics_flag"]


def initialize(dataset_path, expected_sha):
    global STATE
    if file_hash(dataset_path) != expected_sha:
        raise InputError("Sealed pilot dataset hash mismatch")
    with gzip.open(dataset_path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    d["lookup"] = {(s,t,v): x for s,t,v,x in d.pop("observations")}
    STATE = d


def weighted_prediction(values, distances, distance_floor, dz=None, lapse=0.0065):
    """Explicit scalar control; no moisture closure, clipping or hidden fitting."""
    if not values or len(values) != len(distances) or any(not math.isfinite(x) for x in list(values) + list(distances)):
        raise InputError("Invalid control inputs")
    if distance_floor <= 0 or any(x < 0 for x in distances):
        raise InputError("Invalid distance")
    weights = [1/max(d, distance_floor)**2 for d in distances]
    total = math.fsum(weights)
    weights = [w/total for w in weights]
    transferred = values if dz is None else [x-lapse*z for x,z in zip(values, dz)]
    if len(transferred) != len(values):
        raise InputError("Height vector length mismatch")
    return math.fsum(w*x for w,x in zip(weights, transferred)), weights


def numerical_oracles():
    # Hand-computable independent numbers, not a second copy of the implementation.
    p, w = weighted_prediction([10.0, 20.0], [1.0, 2.0], 0.25)
    lapse, _ = weighted_prediction([10.0, 20.0], [1.0, 2.0], 0.25, [100.0, 100.0])
    constant, _ = weighted_prediction([7.5, 7.5], [0.0, 12.0], 0.25)
    cases = {"inverse_square_analytic_12": abs(p-12.0) < 1e-12,
             "analytic_weights_four_fifths_one_fifth": abs(w[0]-.8) < 1e-12 and abs(w[1]-.2) < 1e-12,
             "upward_100m_temperature_decrease_0_65K": abs(lapse-11.35) < 1e-12,
             "constant_field_preserved": abs(constant-7.5) < 1e-12}
    if not all(cases.values()):
        raise InputError("Numerical control oracle failed")
    return cases


def error_metrics(errors):
    if not errors:
        return {"n": 0, "MAE": None, "RMSE": None, "bias": None, "p95_absolute_error": None}
    ordered = sorted(abs(x) for x in errors)
    return {"n": len(errors), "MAE": math.fsum(abs(x) for x in errors)/len(errors),
            "RMSE": math.sqrt(math.fsum(x*x for x in errors)/len(errors)),
            "bias": math.fsum(errors)/len(errors),
            "p95_absolute_error": ordered[max(0, math.ceil(.95*len(ordered))-1)]}


def ratio(a, b):
    return a/b if b else None


def calculate_job(job):
    start = time.monotonic()
    d = STATE
    cfg, stations, lookup = d["config"], d["stations"], d["lookup"]
    target = stations[job["target"]]
    times = d["selection"]["timestamps"]
    methods = METHODS if job["variable"] == "T" else METHODS[:2]
    rows = []
    budget_exceeded = False
    for index, t in enumerate(times):
        if index % 24 == 0:
            rss = peak_rss_bytes()
            budget_exceeded |= time.monotonic()-start > cfg["job_wall_budget_s"] or (rss is not None and rss > cfg["worker_rss_budget_bytes"])
        control = lookup.get((job["target"], t, job["variable"]))
        eligible = control is not None and control["value"] is not None and qc_allowed(target["country"], control["qc"], job["qc_mode"], cfg)
        candidates = []
        families = set()
        for candidate in d["selection"]["donors"][job["target"]]:
            key = candidate["key"]
            family = stations[key]["family"]
            if key == target["key"] or family == target["family"]:
                raise AssertionError("Target family leaked into donors")
            obs = lookup.get((key, t, job["variable"]))
            if (not control or not obs or obs["value"] is None or obs["operator"] != control["operator"] or family in families
                    or not qc_allowed(stations[key]["country"], obs["qc"], job["qc_mode"], cfg)):
                continue
            candidates.append(candidate | {"observation": obs})
            families.add(family)
            if len(candidates) == cfg["idw_max_donors"]:
                break
        for method in methods:
            chosen = candidates[:1] if method == "NN_NATIVE" else candidates
            minimum = 1 if method == "NN_NATIVE" else cfg["idw_min_donors"]
            prediction, weights = None, []
            if budget_exceeded:
                status = "UNRESOLVED_BUDGET"
            elif not control:
                status = "TARGET_OPERATOR_UNAVAILABLE"
            elif len(chosen) < minimum:
                status = "INSUFFICIENT_COMPATIBLE_DONORS"
            else:
                dz = [x["delta_height_target_minus_donor_m"] for x in chosen] if method == "IDW_T_FIXED_LAPSE_PROXY" else None
                prediction, weights = weighted_prediction([x["observation"]["value"] for x in chosen],
                    [x["distance_km"] for x in chosen], cfg["distance_floor_km"], dz, cfg["temperature_lapse_K_per_m"])
                status = "PREDICTED"
            detail = [{"station": x["key"], "distance_km": x["distance_km"],
                       "delta_height_target_minus_donor_m": x["delta_height_target_minus_donor_m"],
                       "weight": weights[i] if weights else None, "qc": x["observation"]["qc"],
                       "source": x["observation"]["source"]} for i,x in enumerate(chosen)]
            donors_qc = dict(collections.Counter(x["observation"]["qc_stratum"] for x in chosen))
            physics = ""
            if prediction is not None and job["variable"] == "RH" and not 0 <= prediction <= 100:
                physics = "RH_OUTSIDE_0_100_RETAINED_AS_RAW_SCALAR_DIAGNOSTIC"
            rows.append({"target": target["key"], "timestamp_utc": t, "variable": job["variable"], "unit": UNITS[job["variable"]],
                "qc_mode": job["qc_mode"], "method": method, "control_value": control["value"] if control else None,
                "control_eligible": eligible, "target_qc": control["qc"] if control else "absent_row",
                "target_qc_stratum": control["qc_stratum"] if control else "absent_row", "operator": control["operator"] if control else "",
                "prediction": prediction, "error": prediction-control["value"] if prediction is not None and eligible else None,
                "status": status, "inputs_ready": bool(control) and len(chosen) >= minimum,
                "donor_count": len(chosen), "donors_json": json.dumps(detail, ensure_ascii=False, sort_keys=True),
                "donor_qc_strata_json": json.dumps(donors_qc, ensure_ascii=False, sort_keys=True), "diagnostic_physics_flag": physics})
    out = Path(job["output"])
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "predictions.csv", rows, PRED_FIELDS)
    metrics, paired, qc_metrics = [], [], []
    base = {"job_id": job["job_id"], "target": job["target"], "country": target["country"],
            "variable": job["variable"], "qc_mode": job["qc_mode"], "unit": UNITS[job["variable"]]}
    for method in methods:
        subset = [r for r in rows if r["method"] == method]
        nobs = sum(r["control_eligible"] for r in subset)
        pred_all = sum(r["prediction"] is not None for r in subset)
        pred_obs = sum(r["error"] is not None for r in subset)
        metrics.append(base | {"method": method, "N_calendar": len(times), "N_obs": nobs,
                       "N_donor_ready_all": sum(r["inputs_ready"] for r in subset),
                       "N_donor_ready_obs": sum(r["inputs_ready"] and r["control_eligible"] for r in subset),
                       "N_pred_all": pred_all, "N_pred_among_obs": pred_obs,
                       "coverage_obs": ratio(nobs,len(times)), "coverage_method": ratio(pred_obs,nobs),
                       "coverage_calendar_scored_prediction": ratio(pred_obs,len(times)),
                       "failure_counts": dict(collections.Counter(r["status"] for r in subset if r["status"] != "PREDICTED")),
                       **error_metrics([r["error"] for r in subset if r["error"] is not None])})
        for stratum in sorted({r["target_qc_stratum"] for r in subset}):
            qc_rows = [r for r in subset if r["target_qc_stratum"] == stratum]
            qc_metrics.append(base | {"method": method, "target_qc_stratum": stratum,
                "N_obs": sum(r["control_eligible"] for r in qc_rows), "N_pred_among_obs": sum(r["error"] is not None for r in qc_rows),
                **error_metrics([r["error"] for r in qc_rows if r["error"] is not None])})
        if method == "NN_NATIVE":
            continue
        nn = {r["timestamp_utc"]: r for r in rows if r["method"] == "NN_NATIVE"}
        common = [r for r in subset if r["error"] is not None and nn[r["timestamp_utc"]]["error"] is not None]
        cand_metrics = error_metrics([r["error"] for r in common])
        nn_metrics = error_metrics([nn[r["timestamp_utc"]]["error"] for r in common])
        paired.append(base | {"candidate": method, "control": "NN_NATIVE", "N_common": len(common),
                      "candidate_MAE_common": cand_metrics["MAE"], "control_MAE_common": nn_metrics["MAE"],
                      "delta_MAE_common": cand_metrics["MAE"]-nn_metrics["MAE"] if common else None,
                      "uncertainty": "NOT_ASSESSED_DEVELOPMENT_ENGINEERING_PILOT"})
    report = {"job": {k:v for k,v in job.items() if k != "output"}, "metrics": metrics, "paired": paired, "qc_metrics": qc_metrics,
              "prediction_sha256": file_hash(out / "predictions.csv"), "rows": len(rows), "wall_s": time.monotonic()-start,
              "worker_pid": os.getpid(), "worker_peak_rss_bytes": peak_rss_bytes(), "budget_exceeded": budget_exceeded}
    write_json(out / "job_report.json", report)
    return report


def job_failure(job, error):
    methods = METHODS if job["variable"] == "T" else METHODS[:2]
    metrics = [{"job_id": job["job_id"], "target": job["target"], "country": job["target"][:2],
                "variable": job["variable"], "unit": UNITS[job["variable"]], "qc_mode": job["qc_mode"], "method": m,
                "N_calendar": job["expected_N_calendar"], "N_obs": job["expected_N_obs"],
                "N_pred_all": 0, "N_pred_among_obs": 0, "N_donor_ready_all": None, "N_donor_ready_obs": None,
                "coverage_obs": ratio(job["expected_N_obs"],job["expected_N_calendar"]),
                "coverage_method": ratio(0,job["expected_N_obs"]), "coverage_calendar_scored_prediction": ratio(0,job["expected_N_calendar"]),
                "failure_counts": {"EXECUTION_FAILURE": job["expected_N_calendar"]}, **error_metrics([])} for m in methods]
    return {"job": {k:v for k,v in job.items() if k != "output"}, "execution_failure": str(error),
            "metrics": metrics, "paired": [], "qc_metrics": [], "prediction_sha256": None,
            "rows": 0, "wall_s": None, "worker_pid": None, "worker_peak_rss_bytes": None}


def aggregate_profile(reports):
    metrics = [m for r in reports for m in r["metrics"]]
    output = []
    groups = collections.defaultdict(list)
    for m in metrics:
        groups[(m["country"], m["variable"], m["qc_mode"], m["method"])].append(m)
    for (country, variable, qc_mode, method), group in sorted(groups.items()):
        n = sum(m["n"] for m in group)
        output.append({"country": country, "variable": variable, "qc_mode": qc_mode, "method": method,
            "N_calendar": sum(m["N_calendar"] for m in group), "N_obs": sum(m["N_obs"] for m in group),
            "N_pred_among_obs": n, "N_pred_all": sum(m["N_pred_all"] for m in group),
            "MAE_hour_pooled": math.fsum(m["MAE"]*m["n"] for m in group if m["n"])/n if n else None,
            "RMSE_hour_pooled": math.sqrt(math.fsum(m["RMSE"]**2*m["n"] for m in group if m["n"])/n) if n else None,
            "bias_hour_pooled": math.fsum(m["bias"]*m["n"] for m in group if m["n"])/n if n else None,
            "MAE_target_macro": math.fsum(m["MAE"] for m in group if m["n"])/sum(bool(m["n"]) for m in group) if n else None,
            "targets_with_control": sum(bool(m["N_obs"]) for m in group), "targets_with_scoring": sum(bool(m["n"]) for m in group)})
    return output


def pilot(snapshot, cfg, output):
    start = time.monotonic()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    oracles = numerical_oracles()
    path, preparation = prepare(snapshot, cfg, output)
    selection = read_json(output / "selection.sealed.json")
    initialize(str(path), preparation["dataset_sha256"])
    package = Path(__file__).resolve().parents[1]
    source_code = {p.relative_to(package).as_posix(): file_hash(p)
                   for p in sorted([package / "ige_experiments.py", *package.joinpath("ige_local").glob("*.py")])}
    jobs = []
    for target in selection["targets"]:
        for variable in cfg["variables"]:
            for qc_mode in cfg["qc_modes"]:
                j = {"target": target, "variable": variable, "qc_mode": qc_mode,
                     "expected_N_calendar": len(selection["timestamps"]),
                     "expected_N_obs": sum(bool((x := STATE["lookup"].get((target,t,variable))) is not None and x["value"] is not None
                             and qc_allowed(STATE["stations"][target]["country"], x["qc"], qc_mode, cfg)) for t in selection["timestamps"])}
                j["job_id"] = digest(j)[:20]
                jobs.append(j)
    manifest = {"schema": "IGE_E10_RUN_SPEC_v1", "role": "D_DEVELOPMENT", "registered_at_utc": now(),
                "snapshot_id": snapshot["snapshot_id"], "selection_id": selection["selection_id"],
                "dataset_sha256": preparation["dataset_sha256"], "effective_config": cfg,
                "code_sha256_by_path": source_code, "jobs": jobs, "expected_jobs_per_profile": len(jobs),
                "method_contract": {"NN_NATIVE": "nearest available compatible native scalar, one independent donor",
                    "IDW_NATIVE": "geographic inverse-square scalar, declared floor and available donor limits",
                    "IDW_T_FIXED_LAPSE_PROXY": "same weights plus T_d - lapse*(z_target-z_donor); published station-height proxy"},
                "claim": "engineering control pilot, not confirmatory method selection or legacy annual replay"}
    manifest["specification_sha256"] = digest(manifest)
    write_json(output / "run_specification.sealed.json", manifest)
    profiles = []
    for workers in cfg["benchmark_workers"]:
        prefix = output / ("workers_" + str(workers))
        prefix.mkdir(exist_ok=False)
        work = [j | {"output": str(prefix / j["job_id"])} for j in jobs]
        profile_start = time.monotonic()
        reports = []
        log(f"E1.0: workers={workers}, jobs={len(work)}")
        if workers == 1:
            initialize(str(path), preparation["dataset_sha256"])
            for i, j in enumerate(work, 1):
                try:
                    reports.append(calculate_job(j))
                except Exception as exc:
                    reports.append(job_failure(j, type(exc).__name__ + ": " + str(exc)))
                log(f"  {i}/{len(work)} {j['target']} {j['variable']} {j['qc_mode']}")
        elif work:
            # Explicit spawn also tests Windows' process model on Linux.
            with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                    initializer=initialize, initargs=(str(path), preparation["dataset_sha256"])) as pool:
                futures = {pool.submit(calculate_job, j): j for j in work}
                for i, future in enumerate(as_completed(futures), 1):
                    j = futures[future]
                    try:
                        reports.append(future.result())
                    except Exception as exc:
                        reports.append(job_failure(j, type(exc).__name__ + ": " + str(exc)))
                    log(f"  {i}/{len(work)} {j['target']} {j['variable']} {j['qc_mode']}")
        reports.sort(key=lambda r: r["job"]["job_id"])
        report = {"workers": workers, "wall_s": time.monotonic()-profile_start, "expected_jobs": len(jobs),
                  "completed_jobs": sum("execution_failure" not in r for r in reports),
                  "failed_jobs": sum("execution_failure" in r for r in reports),
                  "budget_exceeded_jobs": sum(bool(r.get("budget_exceeded")) for r in reports),
                  "worker_peak_rss_bytes": max((r["worker_peak_rss_bytes"] or 0 for r in reports), default=0) or None,
                  "job_reports": reports, "country_aggregates": aggregate_profile(reports)}
        write_json(prefix / "profile.json", report)
        flat = [m for r in reports for m in r["metrics"]]
        write_csv(prefix / "metrics.csv", flat, ["job_id", "country", "target", "variable", "unit", "qc_mode", "method", "N_calendar", "N_obs", "N_pred_all", "N_pred_among_obs", "coverage_method", "coverage_calendar_scored_prediction", "MAE", "RMSE", "bias", "p95_absolute_error", "failure_counts"])
        write_csv(prefix / "paired.csv", [m for r in reports for m in r["paired"]], ["job_id", "target", "variable", "qc_mode", "candidate", "control", "N_common", "candidate_MAE_common", "control_MAE_common", "delta_MAE_common", "uncertainty"])
        write_csv(prefix / "qc_metrics.csv", [m for r in reports for m in r["qc_metrics"]], ["target", "variable", "qc_mode", "method", "target_qc_stratum", "N_obs", "N_pred_among_obs", "MAE", "RMSE", "bias"])
        profiles.append(report)
    expected = {j["job_id"] for j in jobs}
    hashes = [{r["job"]["job_id"]: r["prediction_sha256"] for r in p["job_reports"]} for p in profiles]
    reproducible = bool(jobs) and bool(hashes) and all(set(h)==expected and all(h.values()) for h in hashes) and all(h == hashes[0] for h in hashes[1:])
    compared_serial_and_parallel = 1 in cfg["benchmark_workers"] and any(w > 1 for w in cfg["benchmark_workers"])
    legacy = [
        {"method": "P8.2F_ACCEPTED_ANNUAL", "status": "SOURCE_BLOCKED", "reason": "Exact accepted annual T/P/e/RH, 12 monthly e inputs and cohort lineage not reconstructed by this small hourly pilot; no substitution under the old method name"},
        {"method": "S1_FROZEN_ADAPTER", "status": "CAPABILITY_BLOCKED", "reason": "Exact frozen annual/monthly adapter and gradient/input contract not executed by these scalar controls"},
        {"method": "R1_FROZEN_RESEARCH", "status": "CAPABILITY_BLOCKED", "reason": "Registered full R1 input/implementation replay not bundled in this scalar engineering pilot"}]
    total_scored = sum(m["n"] for r in profiles[0]["job_reports"] for m in r["metrics"]) if profiles else 0
    complete = reproducible and total_scored and not preparation["read_failures"] and not any(p["failed_jobs"] or p["budget_exceeded_jobs"] for p in profiles)
    summary = {"schema": "IGE_E10_REPORT_v1", "created_at_utc": now(), "role": "D_DEVELOPMENT",
        "status": "ENGINEERING_PILOT_COMPLETE_LEGACY_REPLAY_PENDING" if complete else "ENGINEERING_PILOT_INCOMPLETE_OR_NO_SCORED_CASES",
        "numerical_oracles": oracles, "serial_parallel_prediction_hashes_match": reproducible if compared_serial_and_parallel else None,
        "profiles_prediction_hashes_consistent": reproducible,
        "profile_sizes": [{k:p[k] for k in ("workers", "wall_s", "expected_jobs", "completed_jobs", "failed_jobs", "budget_exceeded_jobs", "worker_peak_rss_bytes")} for p in profiles],
        "scored_method_case_pairs_first_profile": total_scored,
        "legacy_replays": legacy, "prepare": preparation, "wall_s_including_prepare": time.monotonic()-start,
        "environment": {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(), "cpu_count": os.cpu_count(), "coordinator_peak_rss_bytes": peak_rss_bytes()},
        "quality_axes": {"code_numerics": "ANALYTIC_CONTROLS_PASSED", "physics_semantics": "NATIVE_OPERATOR_MATCHING_WITH_PUBLISHED_GEOMETRY_PROXIES; NO_JOINT_STATE_CLOSURE",
            "independent_accuracy": "NOT_ASSESSED; DEVELOPMENT_DESCRIPTIVE_ERRORS_ONLY", "operation": "LOCAL_E0_E10_ENGINEERING_TOOL"},
        "limitations": ["No new holdout opened", "No superiority inference or confidence intervals", "All-negative/no-donor outcomes retained", "E1.0 full legacy replay remains pending", "Peak per-worker RSS is not total machine RAM", "Native operators are conservatively matched, not redefined as equivalent", "No downloads or source changes"]}
    write_json(output / "summary.json", summary)
    lines = ["# E1.0 — малый локальный пилот", "", "Статус: `" + summary["status"] + "`.", "",
             "Это development-пилот простых контролей NN/IDW/фиксированного температурного градиента.",
             "Описательные ошибки не являются независимой квалификацией и не выбирают победителя.", "",
             "| Workers | Jobs | Ошибки выполнения | Время, s | Peak RSS одного worker, bytes |", "|---:|---:|---:|---:|---:|"]
    lines += [f"| {p['workers']} | {p['completed_jobs']}/{p['expected_jobs']} | {p['failed_jobs']} | {p['wall_s']:.3f} | {p['worker_peak_rss_bytes']} |" for p in profiles]
    lines += ["", "Совпадение хешей прогнозов профилей: **" + str(reproducible) + "**.", "",
              "`availability.csv` — точные почасовые маски выбранных окон в сводном виде;",
              "`dataset.sealed.json.gz` сохраняет значения, QC, операторы и ссылки на источники.",
              "В `workers_N/metrics.csv` ошибки и собственное покрытие; `paired.csv` — сравнения",
              "с NN на общих часах; `qc_metrics.csv` — категории QC контроля. QC доноров —",
              "отдельное поле каждого прогноза в `workers_N/<job_id>/predictions.csv`.", "",
              "## Незавершённая часть E1.0", ""]
    lines += ["- `" + x["method"] + "`: `" + x["status"] + "` — " + x["reason"] for x in legacy]
    lines += ["", "Не запущены E1.T/E2 как поиск улучшений, IV1, F1 или расчёт здания. Неполные годы разрешены;"]
    lines += ["автоматический и ручной QC участвуют в primary, неопределённый AT QC — в отдельной sensitivity."]
    (output / "REPORT_RU.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
