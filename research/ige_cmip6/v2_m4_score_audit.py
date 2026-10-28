"""Paired arithmetic audit, separate from the frozen estimator/scorer.

Uses the published paired rows, fsum and explicit group membership. This is
code verification, not an independent weather dataset or an estimator change.
Unpaired all-reference B0 values are outside this paired-row arithmetic audit.
"""
from __future__ import annotations
import io
import math

import numpy as np
import pandas as pd

FIELDS = ["target_key", "country", "season", "time_UTC", "observed_C", "B0_C", "R1_C"]
TOL = 1.1e-8


def arithmetic(values):
    x = [float(v) for v in values]
    if any(not math.isfinite(v) for v in x): raise ValueError("M4_NONFINITE_PAIRED_ERROR")
    n = len(x)
    if not n: return {"n": 0, "MAE_K": None, "RMSE_K": None, "bias_K": None, "centred_RMSE_K": None}
    mean = math.fsum(x) / n
    return {"n": n, "MAE_K": math.fsum(abs(v) for v in x) / n,
        "RMSE_K": math.sqrt(math.fsum(v * v for v in x) / n), "bias_K": mean,
        "centred_RMSE_K": math.sqrt(math.fsum((v - mean) ** 2 for v in x) / n)}


def close(actual, expected):
    if actual is None or expected is None: return actual is None and expected is None
    return math.isfinite(float(actual)) and math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=TOL)


def check_summary(declared, frame):
    expected = {"B0": arithmetic(frame.B0_C - frame.observed_C), "R1": arithmetic(frame.R1_C - frame.observed_C)}
    for method, metrics in expected.items():
        if declared[method]["n"] != metrics["n"]: raise ValueError("M4_PAIRED_METRIC_COUNT_MISMATCH")
        for name in ("MAE_K", "RMSE_K", "bias_K", "centred_RMSE_K"):
            if not close(declared[method][name], metrics[name]): raise ValueError("M4_PAIRED_ARITHMETIC_MISMATCH:" + method + ":" + name)
    delta = expected["R1"]["MAE_K"] - expected["B0"]["MAE_K"] if len(frame) else None
    if not close(declared["delta_MAE_K"], delta): raise ValueError("M4_PAIRED_DELTA_MISMATCH")


def paired_frame(raw):
    if not raw.strip(): return pd.DataFrame(columns=FIELDS)
    frame = pd.read_csv(io.BytesIO(raw))
    if list(frame.columns) != FIELDS: raise ValueError("M4_PAIRED_COLUMNS_CHANGED")
    frame["time_UTC"] = pd.to_datetime(frame.time_UTC, utc=True)
    if frame.duplicated(["target_key", "time_UTC"]).any(): raise ValueError("M4_DUPLICATE_PAIRED_HOUR")
    if not np.isfinite(frame[["observed_C", "B0_C", "R1_C"]].to_numpy(dtype=float)).all(): raise ValueError("M4_NONFINITE_PAIRED_VALUE")
    return frame


def audit_scores(result, raw, plan, ledger):
    f = paired_frame(raw); expected = {(k, w["season"]) for k in plan["target_keys"] for w in plan["windows"]}
    cases = result["cases"]
    if len(cases) != 72 or {(c["target_key"], c["season"]) for c in cases} != expected:
        raise ValueError("M4_ALL72_REGISTERED_CASES_REQUIRED")
    if result["paired_reference_hours"] != len(f): raise ValueError("M4_TOTAL_PAIRED_COUNT_MISMATCH")
    forecasts = {(c["target_key"], c["season"]): c["finite_paired_forecast_hours"] for c in ledger["cases"]}
    if len(f) and (not set(f.target_key) <= set(plan["target_keys"]) or not f.country.eq(f.target_key.str[:2]).all()):
        raise ValueError("M4_UNREGISTERED_PAIRED_STATION")
    if any((k, s) not in expected for k, s in zip(f.target_key, f.season)):
        raise ValueError("M4_UNREGISTERED_PAIRED_SEASON")
    for case in cases:
        key, season = case["target_key"], case["season"]
        if case["country"] != key[:2]: raise ValueError("M4_CASE_COUNTRY_MISMATCH")
        p = f[(f.target_key == key) & (f.season == season)]
        n = len(p); w = next(w for w in plan["windows"] if w["season"] == season)
        if n and not pd.DatetimeIndex(p.time_UTC).isin(pd.date_range(w["start_UTC"], w["end_UTC"], freq="h")).all():
            raise ValueError("M4_PAIRED_HOUR_OUTSIDE_REGISTERED_WINDOW")
        if n != case["paired_hours"] or case["forecast_hours"] != forecasts[(key, season)] or n > forecasts[(key, season)]:
            raise ValueError("M4_CASE_PAIRED_OR_FORECAST_COUNT_MISMATCH")
        if (n >= 160) != (case["status"] == "ADMITTED_PILOT_CASE"): raise ValueError("M4_CASE160_ADMISSION_MISMATCH")
        if not n <= case["B0_all_reference"]["n"] <= 168: raise ValueError("M4_ALL_REFERENCE_COUNT_DOMAIN")
        check_summary(case, p)
    for country in ("AT", "DE", "CH"):
        d = result["countries"][country]; cc = [c for c in cases if c["country"] == country]
        good = [c for c in cc if c["paired_hours"] >= 160]
        if len(cc) != 24: raise ValueError("M4_COUNTRY24_CASES_REQUIRED")
        if d["admitted_cases"] != len(good) or d["registered_cases"] != 24: raise ValueError("M4_COUNTRY_CASE_CENSUS")
        p = f[f.country == country]
        good_keys = {(c["target_key"], c["season"]) for c in good}
        mask = [(k, s) in good_keys for k, s in zip(p.target_key, p.season)]
        admitted = p.loc[mask] if len(p) else p
        check_summary(d["admitted_pairs"], admitted); check_summary(d["all_available_pairs_descriptive"], p)
        targets = {k for k in plan["target_keys"] if k.startswith(country)}
        if set(d["stations_admitted_pairs"]) != targets: raise ValueError("M4_SIX_COUNTRY_STATIONS_REQUIRED")
        for key, summary in d["stations_admitted_pairs"].items(): check_summary(summary, admitted[admitted.target_key == key])
        changes = [s["delta_MAE_K"] for s in d["stations_admitted_pairs"].values() if s["delta_MAE_K"] is not None]
        expected_flag = (len(good) == 24 and d["admitted_pairs"]["delta_MAE_K"] is not None
                         and d["admitted_pairs"]["delta_MAE_K"] < 0 and len(changes) == 6 and max(changes) <= 0)
        if d["within_pilot_uniform_observed_benefit"] != expected_flag: raise ValueError("M4_FROZEN_UNIFORM_BENEFIT_RULE_MISMATCH")
        if len(good) < 24:
            if d["resampling_descriptive_only"] is not None: raise ValueError("M4_INCOMPLETE_COUNTRY_RESAMPLING")
        else:
            samples = d["resampling_descriptive_only"]
            if (samples["draws"] != 10000 or samples["PCG64_seed"] != 20261027 or samples["population_CI_or_p_value"] is not False
                    or samples["blocks"] != 4 or samples["all6_stations_synchronous"] is not True):
                raise ValueError("M4_REGISTERED_DESCRIPTIVE_RESAMPLING_CHANGED")
            sizes, changes_sums = [], []
            for w in plan["windows"]:
                block = admitted[admitted.season == w["season"]]
                sizes.append(len(block))
                changes_sums.append(math.fsum(abs(float(r)) - abs(float(b)) for r, b in zip(block.R1_C - block.observed_C, block.B0_C - block.observed_C)))
            draw = np.random.Generator(np.random.PCG64(20261027)).integers(0, 4, size=(10000, 4))
            delta = np.asarray(changes_sums)[draw].sum(axis=1) / np.asarray(sizes)[draw].sum(axis=1)
            if not close(samples["lower_K"], np.quantile(delta, .025)) or not close(samples["upper_K"], np.quantile(delta, .975)):
                raise ValueError("M4_SYNCHRONOUS_WEEK_RESAMPLING_MISMATCH")
    return {"schema": "IGE_V2_M4_PAIRED_ARITHMETIC_AUDIT_v1", "status": "PASS", "paired_rows": len(f),
        "all72_cases_and18_sites_checked": True, "country_case_and_station_metrics_checked": True,
        "frozen_uniform_benefit_and_descriptive_resampling_checked": True,
        "source_or_estimator_independence_implied": False, "all_reference_B0_not_recomputed_from_paired_only_CSV": True}
