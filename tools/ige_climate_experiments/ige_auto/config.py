from __future__ import annotations

import calendar
import datetime as dt
import math
from pathlib import Path

from ige_local.common import HOUR, UTC, InputError, digest, iso, read_json

BASES = {"height", "seasonal_height", "monthly_height", "harmonic_height", "height_geo", "seasonal_geo"}
VARIABLES = {"T", "RH", "p", "log_e_water"}


def load(path):
    path = Path(path).resolve()
    c = read_json(path)
    allowed = {"schema", "database", "results", "countries", "variables", "years", "sample_days_per_month",
               "sample_start_day", "sites_per_country", "split_seed", "split_fractions", "inner_folds", "qc_mode",
               "rejected_native_qc", "water_vapour_assumption", "co_location_km", "cases_per_partition", "models",
               "optimizer", "workers", "memory_budget_bytes", "selection_metric", "final_refit", "evaluate_holdout"}
    if c.get("schema") != "IGE_AUTO_REGRESSION_CONFIG_v1" or set(c) != allowed:
        raise InputError("Unknown automatic regression schema/key")
    for k in ("database", "results"):
        c[k] = str((path.parent/c[k]).resolve())
    database, results = Path(c["database"]), Path(c["results"])
    if not database.is_dir():
        raise InputError("Database not found: " + str(database))
    if results.is_relative_to(database) or database.is_relative_to(results):
        raise InputError("Database and regression results must be disjoint")
    for name, permitted in (("countries", {"AT","DE","CH"}), ("variables", VARIABLES)):
        if not c.get(name) or len(c[name]) != len(set(c[name])) or not set(c[name]) <= permitted:
            raise InputError("Invalid/duplicate " + name)
    if set(c["years"]) != {"D", "V", "C"}:
        raise InputError("Declare D, V and C years")
    years = []
    for role, ys in c["years"].items():
        if not ys or any(type(y) is not int or not 1900 <= y <= 2200 for y in ys):
            raise InputError("Invalid years for " + role)
        years.extend(ys)
    if len(years) != len(set(years)):
        raise InputError("D/V/C years must be distinct")
    if not 1 <= c["sample_days_per_month"] <= 28 or not 1 <= c["sample_start_day"] <= 28:
        raise InputError("Invalid monthly sample")
    if c["sample_start_day"]+c["sample_days_per_month"] > 29:
        raise InputError("Monthly sample must fit February without wrapping")
    f = c["split_fractions"]
    if set(f) != {"D","V","C"} or any(not 0 < x < 1 for x in f.values()) or abs(sum(f.values())-1) > 1e-10:
        raise InputError("Positive D/V/C family fractions must sum to one")
    if type(c["sites_per_country"]) is not int or c["sites_per_country"] < 0:
        raise InputError("sites_per_country: 0 means all; otherwise nonnegative integer")
    integers = ["inner_folds", "workers", "sample_days_per_month", "sample_start_day", "cases_per_partition", "memory_budget_bytes", "split_seed"]
    if any(type(c[k]) is not int for k in integers):
        raise InputError("Integer sampling/resource settings required")
    if not 2 <= c["inner_folds"] <= 10 or not 1 <= c["workers"] <= 8:
        raise InputError("Invalid fold/worker count")
    if c["qc_mode"] not in {"primary","sensitivity_all_published"}:
        raise InputError("Invalid QC mode")
    if "log_e_water" in c["variables"] and c["water_vapour_assumption"] != "BUCK_LIQUID_WATER_EXPLICIT":
        raise InputError("Derived log(e) requires explicit water-phase assumption")
    if not math.isfinite(c["co_location_km"]) or c["co_location_km"] < 0 or c["memory_budget_bytes"] < 1024*1024:
        raise InputError("Invalid geometry/memory limits")
    if set(c["rejected_native_qc"]) != {"AT", "DE", "CH"} or any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in c["rejected_native_qc"].values()):
        raise InputError("Declare exact native rejection strings for AT, DE and CH")
    if not 50 <= c["cases_per_partition"] <= 1000000:
        raise InputError("cases_per_partition must be 50..1000000")
    if c["selection_metric"] != "equal_country_station_macro_MAE":
        raise InputError("This version selects by equal-country station-macro MAE")
    if c["final_refit"] not in {"D_ONLY","D_PLUS_V"} or type(c["evaluate_holdout"]) is not bool:
        raise InputError("Invalid final refit/holdout option")
    ids = []
    for m in c["models"]:
        if set(m) != {"id","basis","kernel","regression"} or not m["id"].replace("_","").isalnum():
            raise InputError("Invalid model specification")
        if m["basis"] not in BASES or m["kernel"] not in {"idw","gaussian"} or m["regression"] not in {"ols","ridge","huber"}:
            raise InputError("Unsupported basis/kernel/regression")
        ids.append(m["id"])
    if not ids or len(ids) != len(set(ids)) or len(ids)>20:
        raise InputError("Declare 1..20 unique structural candidates")
    opt = c["optimizer"]
    if set(opt) != {"max_evaluations","max_iterations","wall_seconds_per_model","starts","min_fit_cases","rank_rcond","max_condition"}:
        raise InputError("Unknown optimizer option")
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in opt.values()):
        raise InputError("Optimizer settings must be finite numbers")
    if any(type(opt[k]) is not int for k in ("max_evaluations", "max_iterations", "starts", "min_fit_cases")):
        raise InputError("Integer optimizer counts required")
    if opt["max_evaluations"] < 10 or opt["max_iterations"] < 1 or opt["wall_seconds_per_model"] <= 0 or not 1 <= opt["starts"] <= 3:
        raise InputError("Invalid optimizer budget")
    if opt["min_fit_cases"] < 10 or not 0 < opt["rank_rcond"] < 1 or opt["max_condition"] <= 1:
        raise InputError("Invalid regression support/rank threshold")
    c["config_source_path"] = str(path)
    return c


def windows(c):
    result = []
    for year in sorted(y for ys in c["years"].values() for y in ys):
        for month in range(1,13):
            lo = dt.datetime(year,month,c["sample_start_day"],tzinfo=UTC)
            result.append({"start":iso(lo),"end_exclusive":iso(lo+dt.timedelta(days=c["sample_days_per_month"]))})
    return result


def native_config(c):
    return {"database":c["database"],"results":c["results"],"countries":c["countries"],"windows":windows(c)}


def data_signature(c):
    keys = ["database","countries","years","sample_days_per_month","sample_start_day","sites_per_country",
            "split_seed","split_fractions","inner_folds","qc_mode","rejected_native_qc","water_vapour_assumption","co_location_km"]
    return digest({k:c[k] for k in keys})
