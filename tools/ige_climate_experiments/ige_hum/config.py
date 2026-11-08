"""Stdlib preflight and explicit anchoring to the existing cohort."""
import json
from pathlib import Path
from ige_auto.config import load as load_base,data_signature
from ige_local.common import InputError,digest,read_json


def sealed(path,key):
    value=read_json(path)
    if value.get(key)!=digest({k:v for k,v in value.items() if k!=key}):raise InputError("Sealed document mismatch: "+str(path))
    return value


def load(path):
    path=Path(path).resolve()
    try:h=read_json(path)
    except json.JSONDecodeError as exc:raise InputError("Invalid humidity JSON config; use / in Windows paths: "+str(exc)) from exc
    if not isinstance(h,dict):raise InputError("Humidity configuration must be a JSON object")
    expected={"schema","base_config","cohort_anchor","results","coordinates","primary_metric","workers","auxiliary_optimizer"}
    if set(h)!=expected or h["schema"]!="IGE_HUMIDITY_COMPARISON_v1":raise InputError("Unknown humidity configuration schema/key")
    if h["coordinates"]!=["RH","log_e","q"] or h["primary_metric"]!="equal_country_station_macro_MAE_RH":
        raise InputError("This registered comparison requires RH/log_e/q and common RH macro-MAE")
    if type(h["workers"]) is not int or h["workers"]!=1:raise InputError("This sequential comparison supports workers=1")
    for key in ("base_config","cohort_anchor","results"):
        if not isinstance(h[key],str) or not h[key].strip() or any(ord(ch)<32 for ch in h[key]):raise InputError("Invalid path: "+key)
        h[key]=str((path.parent/h[key]).resolve())
    c=load_base(h["base_config"])
    if c["evaluate_holdout"]:raise InputError("Set evaluate_holdout=false; run never opens C")
    if not {"T","RH","p"}.issubset(c["variables"]):raise InputError("Base config must include T/RH/p")
    if c["water_vapour_assumption"]!="BUCK_LIQUID_WATER_EXPLICIT":raise InputError("Explicit liquid-water convention required")
    if c["final_refit"]!="D_PLUS_V":raise InputError("This version registers final_refit=D_PLUS_V")
    result,db=Path(h["results"]),Path(c["database"])
    if result.is_relative_to(db) or db.is_relative_to(result):raise InputError("Results must be disjoint from Database")
    anchor=Path(h["cohort_anchor"])
    if not anchor.is_file():raise InputError("Cohort anchor not found; retain the original cube/split.sealed.json: "+str(anchor))
    split=sealed(anchor,"split_id")
    if split.get("schema")!="IGE_AUTO_SPLIT_v1" or split["data_signature"]!=data_signature(c):
        raise InputError("Base data selection differs from frozen cohort; do not silently reassign C")
    anchor_root=anchor.parent.parent
    if (anchor_root/"C_OPENED.json").exists():raise InputError("Anchor C was already exposed; a new confirmatory protocol is required")
    if result==anchor_root or result.is_relative_to(anchor_root) or anchor_root.is_relative_to(result):
        raise InputError("Humidity results must be separate from original run")
    opt=h["auxiliary_optimizer"]
    if not isinstance(opt,dict) or set(opt)!=set(c["optimizer"]):raise InputError("Auxiliary optimizer keys differ from registered optimizer contract")
    import math
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in opt.values()):raise InputError("Auxiliary optimizer values must be finite")
    if any(type(opt[k]) is not int for k in ("max_evaluations","max_iterations","starts","min_fit_cases")):raise InputError("Auxiliary optimizer counts must be integers")
    if (opt["max_evaluations"]<10 or opt["max_iterations"]<1 or opt["wall_seconds_per_model"]<=0 or not 1<=opt["starts"]<=3
            or opt["min_fit_cases"]<10 or not 0<opt["rank_rcond"]<1 or opt["max_condition"]<=1):raise InputError("Invalid auxiliary optimizer budget/rank limits")
    c["workers"]=1
    h["config_source_path"]=str(path)
    return h,c,split


def check_cohort(cube,anchor):
    for key in ("data_signature","family_roles","inner_folds","times","time_roles"):
        if cube.meta[key]!=anchor[key]:raise InputError("Frozen cohort changed: "+key)
    fields=("key","family","country","lat","lon","height_m","station_type")
    clean=lambda rows:[{k:s.get(k) for k in fields} for s in rows]
    if clean(cube.meta["stations"])!=clean(anchor["stations"]):raise InputError("Frozen station cohort/geometry changed; C must not be reassigned")
