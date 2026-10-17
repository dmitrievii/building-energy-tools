#!/usr/bin/env python3
"""Check genuine upstream SmartSMEAR API *schema* and hash it, not sensor measurements.

An API schema is not the same as an authenticated source meteorological archive.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ENDPOINT="https://smear-backend.2.rahtiapp.fi/q/openapi"

def run(out: str):
    import yaml
    req=urllib.request.Request(ENDPOINT,headers={
        "User-Agent":"IGE-P9.1H1-external-provenance-schema-only",
        "Accept":"application/yaml, application/json"
    })
    with urllib.request.urlopen(req,timeout=45) as resp:
        if resp.geturl()!=ENDPOINT:
            raise ValueError("P9H1_UNREGISTERED_SCHEMA_URL_REDIRECT")
        blob=resp.read(5_000_001)
    if len(blob)>5_000_000:
        raise ValueError("P9H1_TOO_LARGE_API_SCHEMA")
    spec=yaml.safe_load(blob)
    if not isinstance(spec,dict) or "openapi" not in spec or "paths" not in spec:
        raise ValueError("P9H1_NOT_A_REAL_OPENAPI_DOCUMENT")
    ops={}
    for path in ("/search/timeseries","/search/timeseries/csv",
                 "/search/variable","/station"):
        if path not in spec["paths"] or "get" not in spec["paths"][path]:
            raise ValueError("P9H1_EXPECTED_UPSTREAM_SOURCE_API_ENDPOINT_MISSING:"+path)
        metadata=spec["paths"][path]["get"]
        ops[path]={"parameters": [
            {"name":p.get("name"),"in":p.get("in"),"required":p.get("required",False)}
            for p in metadata.get("parameters",[]) if isinstance(p,dict)],
            "operation_id":metadata.get("operationId")
        }
    result={"phase":"P9.1H1_SMARTSMEAR_ORIGINAL_API_SCHEMA_AUDIT",
            "source_url":ENDPOINT,
            "original_OpenAPI_schema_sha256":hashlib.sha256(blob).hexdigest(),
            "API_version":spec.get("info",{}).get("version"),
            "methods_verified":ops,
            "original_station_temperature_values_downloaded":False,
            "provider_QC_validated":False,
            "near_surface_inversion_model_qualified":False,
            "production_epw_ready":False}
    dest=Path(out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="outputs/p9h1/smartsmear_schema_audit.json")
    args=p.parse_args()
    run(args.out)
