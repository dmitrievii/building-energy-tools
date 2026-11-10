from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
from ige_local.common import InputError, UTC, digest, read_config_json, read_json

SCHEMA = "IGE_FULL_CPU_CONFIG_v1"
BASES = {"height", "monthly", "harmonic", "urban_static", "urban_harmonic"}
COORDINATES = {"T", "p", "RH", "log_e", "q", "Td", "D"}

def load(path, require_database=True):
    path = Path(path).resolve()
    c = read_config_json(path)
    required = {"schema","database","results","countries","years","cohort_anchor","anchor_cube_id",
                "seed","inner_folds","split_fractions","workers","memory_budget_bytes","batch_hours",
                "donors","tuning","models","urban","qc_mode","rejected_native_qc"}
    if set(c) != required or c.get("schema") != SCHEMA:
        raise InputError("Unknown/missing full-CPU configuration key or schema")
    for name in ("database","results"):
        c[name] = str((path.parent/c[name]).resolve())
    db, out = Path(c["database"]), Path(c["results"])
    if db == out or db.is_relative_to(out) or out.is_relative_to(db):
        raise InputError("Database and results must be disjoint")
    if require_database and not db.is_dir(): raise InputError("Database not found: "+str(db))
    if not c["countries"] or len(c["countries"]) != len(set(c["countries"])) or not set(c["countries"]) <= {"AT","DE","CH"}:
        raise InputError("Invalid countries")
    if set(c["years"]) != {"D","V","C"}: raise InputError("Declare D/V/C years")
    ys=[]
    for role, years in c["years"].items():
        if not years or any(type(y) is not int or not 1900 <= y <= 2200 for y in years): raise InputError("Invalid years")
        ys += years
    if len(ys) != len(set(ys)): raise InputError("D/V/C years must be disjoint and unique")
    for name,lo,hi in (("workers",1,16),("inner_folds",2,5),("batch_hours",24,8784),("seed",0,2**31)):
        if type(c[name]) is not int or not lo <= c[name] <= hi: raise InputError("Invalid "+name)
    if c["memory_budget_bytes"] < 256*1024**2: raise InputError("Memory budget below 256 MiB")
    if len(c["years"]["D"]) < c["inner_folds"]: raise InputError("Need at least inner_folds independent D years")
    if set(c["split_fractions"]) != {"D","V","C"} or any(not 0 < v < 1 for v in c["split_fractions"].values()) or abs(sum(c["split_fractions"].values())-1) > 1e-10:
        raise InputError("Invalid family fractions")
    d=c["donors"]
    if set(d)!={"candidate_count","max_donors","min_donors","radius_km","max_height_difference_m","co_location_km","cross_border"}: raise InputError("Invalid donor keys")
    if not 2 <= d["min_donors"] <= d["max_donors"] <= d["candidate_count"] <= 256 or not 0 < d["radius_km"] <= 1500 or d["max_height_difference_m"] <= 0 or d["co_location_km"] < 0 or type(d["cross_border"]) is not bool:
        raise InputError("Invalid donor settings")
    if d["cross_border"]: raise InputError("Cross-border operators are not harmonized in v0.4; use false")
    t=c["tuning"]
    if set(t)!={"hours_per_month","targets_per_country","max_evaluations","max_iterations","starts","min_fit_cases","ridge_lambda"}: raise InputError("Invalid tuning keys")
    if not 24 <= t["hours_per_month"] <= 744 or not 10 <= t["max_evaluations"] <= 1000 or not 1 <= t["max_iterations"] <= 200 or t["starts"] not in (1,2) or t["min_fit_cases"] < 20 or t["ridge_lambda"] < 0:
        raise InputError("Invalid tuning budgets")
    if not 4 <= t["targets_per_country"] <= 1000:raise InputError("Invalid metadata-only tuning target count")
    if c["qc_mode"] != "all_published_finite": raise InputError("v0.4 retains all finite published QC states; exact rejections are explicit")
    if set(c["rejected_native_qc"]) != {"AT","DE","CH"}: raise InputError("Declare AT/DE/CH QC rejection lists")
    ids=[]
    for m in c["models"]:
        if set(m)!={"id","coordinate","basis","aux_temperature_basis"} or m["coordinate"] not in COORDINATES or m["basis"] not in BASES or m["aux_temperature_basis"] not in BASES or not m["id"].replace('_','').isalnum(): raise InputError("Invalid model")
        ids.append(m["id"])
    if not ids or len(ids)!=len(set(ids)): raise InputError("Duplicate/empty models")
    u=c["urban"]
    if set(u)!={"radii_m","reference_year","minimum_valid_fraction","seconds_between_requests","timeout_seconds"}: raise InputError("Invalid urban settings")
    if u["reference_year"]!=2018 or len(u["radii_m"])!=2 or sorted(u["radii_m"])!=u["radii_m"] or any(not 100<=r<=5000 for r in u["radii_m"]) or not .5<=u["minimum_valid_fraction"]<=1 or u["seconds_between_requests"]<.5 or not 5<=u["timeout_seconds"]<=180: raise InputError("Invalid urban source/scale settings")
    if c["cohort_anchor"]!="auto": c["cohort_anchor"]=str((path.parent/c["cohort_anchor"]).resolve())
    c["_config_path"]=str(path)
    return c

def sealed(path, field):
    a=read_json(path)
    if a.get(field)!=digest({k:v for k,v in a.items() if k!=field}): raise InputError("Seal differs: "+str(path))
    return a

def anchor(c):
    if c["cohort_anchor"]!="auto": candidates=[Path(c["cohort_anchor"])]
    else:
        root=Path(c["_config_path"]).parent.parent
        candidates=[]
        for parent, dirs, files in os.walk(root):
            p=Path(parent)
            dirs[:]=[d for d in dirs if d not in {"Database",".git","raw","parts","csv","downloaded","__pycache__"} and not d.startswith('.venv') and not (p/d).resolve().is_relative_to(Path(c["results"]))]
            if "split.sealed.json" in files and p.name=="cube": candidates.append(p/"split.sealed.json")
    found=[]
    for p in candidates:
        try:
            s=sealed(p,"split_id"); meta=read_json(p.parent/"metadata.json")
            if c["anchor_cube_id"] and meta.get("cube_id")!=c["anchor_cube_id"]: continue
            if any((r/"C_OPENED.json").exists() for r in (p.parent.parent,p.parent.parent.parent)):
                raise InputError("Original C exposure marker exists: "+str(p))
            if s.get("schema")!="IGE_AUTO_SPLIT_v1": continue
            found.append((p,s))
        except (OSError,KeyError,json.JSONDecodeError): continue
    if not found: raise InputError("Original cohort anchor not found. Set cohort_anchor to the previous run's cube/split.sealed.json; retain that run beside this program")
    def signature(s): return digest({k:s[k] for k in ("stations","family_roles","times","time_roles")})
    if len({signature(s) for _,s in found})!=1: raise InputError("Ambiguous original cohorts; specify cohort_anchor explicitly")
    p,s=sorted(found,key=lambda x:str(x[0]))[0]
    legacy_years={r:{dt.datetime.fromisoformat(t.replace('Z','+00:00')).year for t,rr in zip(s["times"],s["time_roles"]) if rr==r} for r in ("D","V","C")}
    for role in ("V","C"):
        if legacy_years[role] & set(c["years"]["D"]): raise InputError("Original V/C years cannot enter D")
    if not legacy_years["C"] <= set(c["years"]["C"]): raise InputError("Original C years must remain C")
    return p,s

def native_configuration(c):
    ys=sorted(y for years in c["years"].values() for y in years)
    return {"database":c["database"],"results":c["results"],"countries":c["countries"],"windows":[{"start":f"{y}-01-01T00:00:00Z","end_exclusive":f"{y+1}-01-01T00:00:00Z"} for y in ys]}

def data_config(c):
    return {k:c[k] for k in ("countries","years","seed","inner_folds","split_fractions","qc_mode","rejected_native_qc")} | {"co_location_km":c["donors"]["co_location_km"]}
