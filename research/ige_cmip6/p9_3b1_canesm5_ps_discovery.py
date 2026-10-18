#!/usr/bin/env python3
"""P9.3B1 immutable original-model data identification: CanESM5 daily ps.

Single public Pangeo/ESGF original-data mirror catalog access. A catalog hit
does NOT qualify pressure; next step must read original asset and CMIP attrs.
Never confuse unadjusted model pressure with NEX GDDP fine-grid pressure.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,urllib.request,urllib.error
from pathlib import Path

CATALOG="https://storage.googleapis.com/cmip6/pangeo-cmip6.csv"
MATCH={"activity_id":"CMIP","institution_id":"CCCma","source_id":"CanESM5",
       "experiment_id":"historical","member_id":"r1i1p1f1",
       "table_id":"day","variable_id":"ps","grid_label":"gn"}
ALLOWED_ALTERNATE_TABLES=("Amon","6hrPlev","6hrLev","day")

def fetch_catalog(url=CATALOG):
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-Scientific-Source-Audit-P9.3B1/1.0"})
    with urllib.request.urlopen(req,timeout=65) as reply:
        b=reply.read(35_000_000)
        if reply.read(1):raise ValueError("P93B1_SOURCE_CATALOG_OVERSIZE")
    return b

def qualify_rows(rows):
    exact=[r for r in rows if all(str(r.get(k,""))==v for k,v in MATCH.items())]
    for r in exact:
        url=r.get("zstore","")
        if not url.startswith("gs://cmip6/") or "CanESM5/" not in url:
            raise ValueError("P93B1_GCM_ORIGINAL_ZSTORE_PATH_UNTRUSTED")
    alt=[{"variable_id":r.get("variable_id"),"table_id":r.get("table_id"),
          "grid_label":r.get("grid_label"),"member_id":r.get("member_id"),
          "source_id":r.get("source_id"),"zstore":r.get("zstore")} for r in rows
         if all(str(r.get(k,""))==v for k,v in MATCH.items()
                if k not in ("table_id","grid_label"))
           and r.get("table_id") in ALLOWED_ALTERNATE_TABLES]
    return exact,alt

def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    result={"phase":"P9_3B1_ORIGINAL_CANESM5_PS_SOURCE_DISCOVERY",
       "identity":MATCH,"catalog_url":CATALOG,
       "catalog_is_mirror_not_native_GCM_field_measurement":True,
       "NEX_GDDP_native_grid_ps_missing":True,
       "native_CanESM5_grid_ps_not_equal_fine_grid_surface_pressure":True,
       "production_epw_ready":False}
    try:
        payload=fetch_catalog()
        result["original_catalog_http_sha256"]=hashlib.sha256(payload).hexdigest()
        reader=csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        if not set(MATCH)|{"zstore"} <= set(reader.fieldnames or []):
            raise ValueError("P93B1_CATALOG_MISSING_ID_FIELDS")
        rows=list(reader)
        exact,alt=qualify_rows(rows)
        result["catalog_total_zarr_entries"]=len(rows)
        result["exact_original_day_ps_assets"]=len(exact)
        result["source_assets"]=[{"zstore":r["zstore"],"version":r.get("version"),
            "grid":r["grid_label"],"table":r["table_id"],"member":r["member_id"]} for r in exact]
        result["other_original_ps_table_candidates"]=alt[:20]
        result["identification_status"]="EXACT_ORIGINAL_DAILY_PS_CATALOG_HIT_UNREAD" if exact else "EXACT_ORIGINAL_DAILY_PS_NOT_IN_PANGEO_CATALOG"
        print("P93B1_ORIGINAL_CATALOG",json.dumps({
          "n_catalog_assets":len(rows),"exact_ps_day":len(exact),
          "ps_other_tables":len(alt),"identity_status":result["identification_status"],
          "assets":result["source_assets"]}),flush=True)
    except Exception as e:
        result["identification_status"]="SOURCE_CATALOG_UNAVAILABLE_NOT_PROOF_ABSENT"
        result["source_error"]=f"{type(e).__name__}: {e}"[:600]
        print("P93B1_CATALOG_SOURCE_BLOCKED",result["source_error"],flush=True)
    (out/"p9_3b1_original_ps_identification.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    return result
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--out",default="outputs/p93b1-source-identification")
    run(a.parse_args().out)
