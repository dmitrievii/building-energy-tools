#!/usr/bin/env python3
"""P9.1H1 genuine SmartSMEAR ORIGINAL variable metadata discovery; no observations scored."""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT="https://smear-backend.2.rahtiapp.fi"
QUERY=(("variable","T42"),("variable","T672"),("tablevariable","T42"))
def fetch_metadata(param,value):
    path="/search/variable"
    if param not in ("variable","tablevariable") or value not in ("T42","T672"):
        raise ValueError("P9H1_UNREGISTERED_SMARTSMEAR_METADATA_QUERY")
    query=urllib.parse.urlencode({param:value})
    url=ROOT+path+"?"+query
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.1H1-original-SMEAR-metadata-only","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=65) as response:
        if response.geturl()!=url:
            raise ValueError("P9H1_METADATA_URL_REDIRECT_NOT_REGISTERED")
        raw=response.read(6_000_001)
    if len(raw)>6_000_000:
        raise ValueError("P9H1_METADATA_TOO_LARGE")
    payload=json.loads(raw)
    return {"request":url,"original_response_SHA256":hashlib.sha256(raw).hexdigest(),
            "root_type":type(payload).__name__,"result_count":len(payload) if isinstance(payload,(list,dict)) else None,
            "metadata_first_records":payload[:4] if isinstance(payload,list) else
                {k:(v[:4] if isinstance(v,list) else v) for k,v in list(payload.items())[:6]},
            "not_real_temperature_timeseries":True}

def main():
    out=Path("outputs/p9h1/smartsmear_variable_metadata.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    items=[]
    for parameter,value in QUERY:
        try:
            item=fetch_metadata(parameter,value)
            item["status"]="METADATA_REAL_RESPONSE"
        except Exception as error:
            item={"parameter":parameter,"value":value,"status":"SOURCE_QUERY_BLOCKED",
                  "exception_type":type(error).__name__,
                  "error":str(error)[:300]}
        items.append(item)
    report={"phase":"P9.1H1_AUTHENTIC_SMARTSMEAR_VARIABLE_METADATA_DISCOVERY",
            "items":items,"original_multiheight_temperature_values_scored":False,
            "original_native_observation_QC_qualified":False,
            "production_epw_ready":False}
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(report,ensure_ascii=False))
    # FAIL only if all genuine calls failed, to distinguish real connectivity.
    if not any(x["status"]=="METADATA_REAL_RESPONSE" for x in items):
        raise RuntimeError("P9H1_ALL_OFFICIAL_SMARTSMEAR_METADATA_REQUESTS_BLOCKED")

if __name__=="__main__":
    main()
