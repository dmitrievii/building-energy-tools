#!/usr/bin/env python3
"""P9.1H1 read original SmartSMEAR public 2018 development-only temperature payload.

Downloaded original bytes are SHA-pinned and NOT uploaded. No quality claims
until original metadata and native source QC can be inspected separately.
"""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

HOST="https://smear-backend.2.rahtiapp.fi"
BASE=HOST+"/search/timeseries"
FROZEN_VAR=("HYY_META.T42","HYY_META.T672")
BEGIN="2018-01-10T00:00:00"
END="2018-01-11T00:00:00"
LIMIT=5_000_000

def fetch(tablevar):
    if tablevar not in FROZEN_VAR:
        raise ValueError("P9H1_NOT_FROZEN_SMARTSMEAR_PROFILE_VARIABLE")
    request_params={"tablevariable":tablevar,"from":BEGIN,"to":END}
    url=BASE+"?"+urllib.parse.urlencode(request_params)
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.1H1-original-2018-unscored-source","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=85) as response:
        if response.geturl()!=url:
            raise ValueError("P9H1_UNREGISTERED_SOURCE_REDIRECT")
        raw=response.read(LIMIT+1)
        content_type=response.headers.get("Content-Type","")
    if len(raw)>LIMIT:
        raise ValueError("P9H1_EXTERNAL_ORIGINAL_OBS_RESPONSE_TOO_LARGE")
    obj=json.loads(raw)
    structural={"root_type":type(obj).__name__,
                "top_level_keys":list(obj)[:20] if isinstance(obj,dict) else [],
                "list_length":len(obj) if isinstance(obj,list) else None}
    if isinstance(obj,dict):
        structural["nested_content_shape"]={
            k:{"type":type(v).__name__,
               "count":len(v) if isinstance(v,(dict,list)) else None,
               "child_keys":list(v[0])[:15] if isinstance(v,list) and v and isinstance(v[0],dict) else
                            (list(v)[:15] if isinstance(v,dict) else [])}
            for k,v in obj.items()}
    elif isinstance(obj,list):
        structural["first_row_keys"]=list(obj[0])[:20] if obj and isinstance(obj[0],dict) else []
    return {
        "official_source_query_parameters":request_params,
        "original_source_payload_sha256":hashlib.sha256(raw).hexdigest(),
        "original_payload_length_bytes":len(raw),
        "content_type":content_type,
        "structural_metadata":structural,
        "real_provider_2018_sensor_temperatures_have_NOT_been_QC_qualified":True,
        "original_payload_not_uploaded":True
    }

def main():
    out=Path("outputs/p9h1/smartsmear_original_2018_profile_SOURCE_READBACK.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for variable in FROZEN_VAR:
        try:
            res=fetch(variable)
            res["source_access_status"]="ACTUAL_PROVIDER_2018_TEMPERATURE_RESPONSE_RECEIVED_UNQUALIFIED"
        except Exception as exc:
            res={"source_access_status":"SOURCE_READ_BLOCKED",
                 "error_class":type(exc).__name__, "error":str(exc)[:350]}
        res["tablevariable"]=variable
        rows.append(res)
    summary={
        "phase":"P9.1H1_REAL_2018_SMARTSMEAR_DEV_SOURCE_PROBE",
        "provider":"University_of_Helsinki_SmartSMEAR",
        "site":"HYYTIALA",
        "native_local_standard_time_UTC_plus_two_not_DST":True,
        "development_window_only":True,
        "2021_holdout_unread":True,
        "original_temperature_QC_verified":False,
        "ERA5_vs_original_tower_skill_scored":False,
        "near_surface_inversion_model_qualified":False,
        "production_epw_ready":False,
        "results":rows}
    out.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(summary,ensure_ascii=False))
    if any(x["source_access_status"]=="SOURCE_READ_BLOCKED" for x in rows):
        raise RuntimeError("P9H1_ORIGINAL_SMARTSMEAR_2018_TEMPERATURE_ACCESS_UNQUALIFIED")

if __name__=="__main__":
    main()
