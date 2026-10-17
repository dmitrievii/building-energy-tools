#!/usr/bin/env python3
"""P9.1H1B *single-site* official KNMI Cabauw LB1 2018 source and NetCDF QA.

One authenticated request to public dataset listing, then at most two original
monthly files (Jan/Jul 2018); no 2021. Provider's published anonymous key is
discovered from its official page on each deliberate run. No secret committed.
Archive only provenance and structural metadata; not raw meteorology.
"""
from __future__ import annotations
import hashlib,io,json,re,urllib.parse,urllib.request
from pathlib import Path
import numpy as np
import xarray as xr

LANDING="https://developer.dataplatform.knmi.nl/open-data-api"
HOST="https://api.dataplatform.knmi.nl"
DATASET="cesar_tower_meteo_lb1_t10"
VERSION="v1.3"
BASE=f"{HOST}/open-data/v1/datasets/{DATASET}/versions/{VERSION}/files"
MONTHS=("201801","201807")
MAXLEN=35_000_000

def get(url,maxlen=MAXLEN,token=None):
    hdr={"User-Agent":"IGE-P9.1H1B-registered-2018-Cabauw-LB1-source-audit"}
    if token:hdr["Authorization"]=token
    req=urllib.request.Request(url,headers=hdr)
    with urllib.request.urlopen(req,timeout=90) as response:
        raw=response.read(maxlen+1)
        actual=response.geturl()
    if len(raw)>maxlen:
        raise ValueError("P9H1B_EXTERNAL_SOURCE_SIZE_LIMIT")
    return raw,actual

def public_token():
    raw,actual=get(LANDING,400_000)
    if actual!=LANDING:raise ValueError("P9H1B_PROVIDER_API_DOCS_REDIRECT")
    doc=raw.decode("utf-8",errors="ignore")
    keys=re.findall(r"eyJ[A-Za-z0-9_\-]{60,240}",doc)
    if not keys:
        raise RuntimeError("P9H1B_KNMI_PUBLIC_ANON_KEY_NOT_FOUND_IN_ORIGINAL_DOCUMENTATION")
    # Official page publishes a single anonymous JWT-like key; never print it.
    key=max(keys,key=len)
    return key,hashlib.sha256(raw).hexdigest()

def verified_catalog(token):
    raw,url=get(BASE+"?maxKeys=1000&sorting=asc",2_000_000,token)
    if url.split("?")[0]!=BASE:raise ValueError("P9H1B_CATALOG_REDIRECT")
    data=json.loads(raw)
    names=[r["filename"] for r in data.get("files",[]) if isinstance(r,dict) and isinstance(r.get("filename"),str)]
    chosen={}
    for month in MONTHS:
        possible=[s for s in names if month in s and s.endswith(".nc")]
        if len(possible)!=1:
            chosen[month]={"status":"BLOCKED_NOT_EXACTLY_ONE_2018_MONTHLY_FILE","matches":possible[:5]}
        else:chosen[month]={"status":"FOUND_ONE","filename":possible[0]}
    return chosen,{"source_catalog_SHA256":hashlib.sha256(raw).hexdigest(),
                   "file_count_first_page":len(names),
                   "catalog_totalCount":data.get("totalCount"),
                   "has_next_page":bool(data.get("nextPageToken")),
                   "filename_first_three":names[:3],
                   "filename_last_three":names[-3:]}

def one_month(filename,token):
    if not filename.endswith(".nc") or not any(m in filename for m in MONTHS):
        raise ValueError("P9H1B_UNREGISTERED_OR_NON_NETCDF_MONTH")
    raw,actual=get(f"{BASE}/{urllib.parse.quote(filename,safe='')}/url",250_000,token)
    if actual.split("?")[0]!=f"{BASE}/{urllib.parse.quote(filename,safe='')}/url":
        raise ValueError("P9H1B_ORIGINAL_FILE_DOWNLOAD_URL_REDIRECT")
    payload=json.loads(raw)
    temporary=payload.get("temporaryDownloadUrl")
    if not isinstance(temporary,str) or not temporary.startswith("https://"):
        raise ValueError("P9H1B_PROVIDER_NO_SIGNED_DOWNLOAD_URL")
    source,redirect=get(temporary)
    with xr.open_dataset(io.BytesIO(source),engine="h5netcdf",decode_times=False) as ds:
        vars={}
        for name,da in ds.variables.items():
            info={"dimensions":list(da.dims),"shape":list(da.shape),
                  "units":str(da.attrs.get("units","")),
                  "long_name":str(da.attrs.get("long_name",""))[:140],
                  "standard_name":str(da.attrs.get("standard_name",""))[:140],
                  "dtype":str(da.dtype)}
            if name.lower() in ("ta","t","temperature","air_temperature"):
                arr=np.asarray(da.values,dtype=float)
                info["finite_count"]=int(np.isfinite(arr).sum())
                info["finite_fraction"]=float(np.isfinite(arr).mean())
                info["min"]=float(np.nanmin(arr))
                info["max"]=float(np.nanmax(arr))
            vars[name]=info
        attributes={k:str(v)[:250] for k,v in list(ds.attrs.items())[:30]}
    return {"file_name":filename,"original_file_SHA256":hashlib.sha256(source).hexdigest(),
            "original_file_bytes":len(source),"netcdf_dimensions":{k:int(v["shape"][0]) if False else str(d) for k,d in []},
            "netcdf_variables":vars,"global_attributes":attributes,
            "original_temperature_bytes_NOT_uploaded":True}

def main():
    root=Path("outputs/p9h1b");root.mkdir(parents=True,exist_ok=True)
    report={"phase":"P9.1H1B_KNMI_REAL_2018_CABAUW_FIRST_SOURCE_AUDIT",
            "provider_dataset":f"{DATASET}/{VERSION}",
            "2018_only_windows":list(MONTHS),
            "2021_holdout_not_accessed":True,
            "production_epw_ready":False,
            "source_native_data_QC_qualification":False}
    try:
        key,docs_sha=public_token()
        report["public_provider_auth_document_SHA256"]=docs_sha
        selected,catalog=verified_catalog(key)
        report["source_listing"]=catalog
        report["month_choices"]=selected
        report["files"]={}
        for month in MONTHS:
            spec=selected[month]
            if spec["status"]!="FOUND_ONE":
                continue
            try:
                report["files"][month]=one_month(spec["filename"],key)
                report["files"][month]["status"]="GENUINE_KNMI_LB1_FILE_DECODED_SOURCE_QC_NOT_YET_GATED"
            except Exception as exc:
                report["files"][month]={"status":"SOURCE_OR_NETCDF_DECODE_BLOCKED",
                    "error_class":type(exc).__name__,"error":str(exc)[:350]}
    except Exception as exc:
        report["source_access_status"]="BLOCKED"
        report["blocked_reason_type"]=type(exc).__name__
        report["blocked_reason"]=str(exc)[:350]
    (root/"p9_1h1b_cabauw_2018_original_source_discovery.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("P9H1B_CABAUW_GENUINE_SOURCE_READBACK",json.dumps(report,ensure_ascii=False))
    # Source access failure is explicitly reported in artifact, not passed as proof.
    if len(report.get("files",{}))!=2 or any(
        v["status"]!="GENUINE_KNMI_LB1_FILE_DECODED_SOURCE_QC_NOT_YET_GATED"
        for v in report.get("files",{}).values()
    ):raise RuntimeError("P9H1B_SOURCE_GATE_BLOCKED; DO NOT_GENERALIZE")

if __name__=="__main__":
    main()
