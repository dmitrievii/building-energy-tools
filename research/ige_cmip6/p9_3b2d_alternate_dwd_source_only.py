#!/usr/bin/env python3
"""DWD official alternate-family 10-minute and subdaily pressure schema+availability.
Amendment A is committed BEFORE this code is run. Never reveal measured P values.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,re,urllib.parse,urllib.request,zipfile
from pathlib import Path
from collections import Counter

SOURCES = (
 {"family":"URBAN_10MIN", "root":"https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate_urban/10_minutes/pressure/historical/",
  "id":"00399", "pattern":r"10minutenwerte_P0_STADT_00399_(\d{8})_(\d{8})_hist\.zip",
  "meta":"zehn_st_min_p0_Beschreibung_Stationen.txt", "min_n":144},
 {"family":"SUBDAILY_PP", "root":"https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/subdaily/pressure/historical/",
  "id":"01420", "pattern":r"terminwerte_PP_01420_(\d{8})_(\d{8})_hist\.zip",
  "meta":"PP_Terminwerte_Beschreibung_Stationen.txt", "min_n":35},
 {"family":"SUBDAILY_PP", "root":"https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/subdaily/pressure/historical/",
  "id":"02559", "pattern":r"terminwerte_PP_02559_(\d{8})_(\d{8})_hist\.zip",
  "meta":"PP_Terminwerte_Beschreibung_Stationen.txt", "min_n":35},
 {"family":"SUBDAILY_PP", "root":"https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/subdaily/pressure/historical/",
  "id":"01550", "pattern":r"terminwerte_PP_01550_(\d{8})_(\d{8})_hist\.zip",
  "meta":"PP_Terminwerte_Beschreibung_Stationen.txt", "min_n":35},
)
WINDOWS = {"JAN_2023":("2023011000","2023011623"),
           "JUL_2023":("2023071000","2023071623")}
CERTIFIED_BY_FAMILY = {"URBAN_10MIN":"P0_ST_10", "SUBDAILY_PP":"PP_TER"}
FORBIDDEN_SEALEVEL = {"P0","PP0","QFF","QNH","LUFTDRUCK_MEERESHOEHE",
                      "LUFTDRUCK_MEERESNIVEAU"}
QUALITY_FIELDS = ("QN_8","QN_4","QUALITAETS_NIVEAU","QN_9","QN")
MAX_RAW = 9_000_000


def fetch(url, max_raw=MAX_RAW):
    u=urllib.parse.urlsplit(url)
    if u.scheme!="https" or u.hostname!="opendata.dwd.de" or not (
        u.path.startswith("/climate_environment/CDC/observations_germany/climate_urban/10_minutes/pressure/historical/")
        or u.path.startswith("/climate_environment/CDC/observations_germany/climate/subdaily/pressure/historical/")):
        raise ValueError("P93B2D_ALTERNATE_SOURCE_NOT_ALLOWLISTED")
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.3B2D-Amendment-A-source-only/1.0"})
    with urllib.request.urlopen(req,timeout=100) as response:
        raw=response.read(max_raw+1)
    if len(raw)>max_raw:
        raise ValueError("P93B2D_ALTERNATE_SOURCE_TOO_LARGE")
    return raw,hashlib.sha256(raw).hexdigest()


def original_archive_name(listing, src):
    values=set(re.findall(src["pattern"],listing.decode("utf8","replace"),re.I))
    qualified=sorted((s,e) for s,e in values if s<="20230110" and e>="20230716")
    if len(qualified)!=1:
        raise ValueError("P93B2D_ALTERNATIVE_SOURCE_NO_UNAMBIGUOUS_2023_ARCHIVE")
    s,e=qualified[0]
    if src["family"]=="URBAN_10MIN":
        return f"10minutenwerte_P0_STADT_{src['id']}_{s}_{e}_hist.zip"
    return f"terminwerte_PP_{src['id']}_{s}_{e}_hist.zip"


def parse_time(original, family):
    x=re.sub(r"\D","",(original or "").strip())
    if len(x) not in (10,12):
        return None
    if family=="URBAN_10MIN" and not (len(x)==12 and x[-2:]=="00"):
        return None
    if family=="SUBDAILY_PP" and len(x)==12 and x[-2:]!="00":
        return None
    return x[:10]


def original_source_count(raw,src):
    metrics={k:{"native_exact_hour_rows":0,"valid_original_pressure":0,
       "missing_original_pressure":0,"QC_counts":Counter(),
       "valid_by_QC":Counter()} for k in WINDOWS}
    seen={n:set() for n in WINDOWS}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:
            raise ValueError("P93B2D_ALTERNATIVE_SOURCE_ZIP_CRC")
        candidates=[n for n in z.namelist() if Path(n).name.lower().startswith("produkt")
                    and n.lower().endswith((".txt",".csv"))]
        if len(candidates)!=1:
            raise ValueError("P93B2D_ALTERNATIVE_SOURCE_PRODUCT_NOT_UNIQUE_"+repr(candidates[:8]))
        with io.TextIOWrapper(z.open(candidates[0]),encoding="latin1") as fh:
            reader=csv.DictReader(fh,delimiter=";")
            cols=[str(x or "").strip() for x in (reader.fieldnames or [])]
            keys={c.upper():c for c in cols}
            field_name=CERTIFIED_BY_FAMILY[src["family"]]
            valid_field=keys.get(field_name)
            if valid_field is None:
                return {"status":"PRESSURE_COLUMN_NOT_CERTIFIED",
                  "original_csv_fields":cols,"windows":metrics}
            if valid_field.upper() in FORBIDDEN_SEALEVEL:
                raise ValueError("P93B2D_SEALEVEL_FIELD_USED_AS_STATION_PRESSURE")
            qcfield=next((keys[x] for x in QUALITY_FIELDS if x in keys),None)
            timefield=next((keys[x] for x in ("MESS_DATUM","MESS_DATUM_TERMIN","REFERENCE_TIMESTAMP")
                      if x in keys),None)
            if not timefield:
                return {"status":"TIMESTAMP_COLUMN_NOT_CERTIFIED",
                   "original_csv_fields":cols,"windows":metrics}
            stationfield=keys.get("STATIONS_ID")
            for row in reader:
                if stationfield:
                    try:
                        if int(row[stationfield])!=int(src["id"]):
                            raise ValueError("P93B2D_ALTERNATIVE_SOURCE_STATION_ID_MISMATCH")
                    except (TypeError,ValueError) as e:
                        raise ValueError("P93B2D_ALTERNATIVE_STATION_ID_NOT_CERTIFIED") from e
                tt=parse_time(row.get(timefield),src["family"])
                name=next((k for k,(a,b) in WINDOWS.items() if tt and a<=tt<=b),None)
                if name is None:
                    continue
                if tt in seen[name]:
                    raise ValueError("P93B2D_ALTERNATIVE_DUPLICATE_EXACT_HOUR")
                seen[name].add(tt)
                m=metrics[name]
                m["native_exact_hour_rows"]+=1
                qc=(row.get(qcfield) or "").strip() if qcfield else "NO_NATIVE_QC_COLUMN"
                m["QC_counts"][qc]+=1
                try:
                    p=float((row.get(valid_field) or "").strip())
                except (ValueError,TypeError):
                    p=float("nan")
                if math.isfinite(p) and 450<p<1100:
                    m["valid_original_pressure"]+=1
                    m["valid_by_QC"][qc]+=1
                else:
                    m["missing_original_pressure"]+=1
    for m in metrics.values():
        m["QC_counts"]=dict(m["QC_counts"])
        m["valid_by_QC"]=dict(m["valid_by_QC"])
    return {"status":"ORIGINAL_PRESSURE_COLUMN_READ","field_name":valid_field,
      "quality_field":qcfield,
      "time_field":timefield,"original_csv_fields":cols,
      "time_support":("10minute minute=00 sample, NOT hourly mean" if
                      src["family"]=="URBAN_10MIN" else "subdaily exact-hour observation, NOT hourly coverage"),
      "windows":metrics}


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    report={"phase":"P9_3B2D_ALTERNATIVE_DWD_SOURCE_ONLY_AMENDMENT_A",
      "prereg":"docs/IGE_P9_3B2D_SOURCE_RECOVERY_AMENDMENT_A_20261020_RU.md",
      "observed_source_values_written":False,"ERA5_model_called":False,
      "pressure_prediction_errors_accessed":False,"windows":WINDOWS,
      "original_DWD_hourly_2023_prior_six_stations_blocked":True,"sources":[]}
    cache={}
    for src in SOURCES:
        rec={"family":src["family"],"station_id":src["id"],
             "source_only":True,"min_per_window":src["min_n"]}
        report["sources"].append(rec)
        try:
            root=src["root"]
            if root not in cache:
                lst,ls_sha=fetch(root,3_000_000)
                meta,meta_sha=fetch(root+src["meta"],1_000_000)
                cache[root]=(lst,ls_sha,meta,meta_sha)
            listing,ls_sha,meta,meta_sha=cache[root]
            rec["listing_SHA256"]=ls_sha
            rec["metadata_SHA256"]=meta_sha
            lines=[x.strip() for x in meta.decode("latin1").splitlines()
                   if re.match(r"^\s*"+src["id"]+r"\s",x)]
            rec["station_original_metadata_lines"]=lines[:3]
            archive=original_archive_name(listing,src)
            raw,sha=fetch(root+archive)
            rec["original_archive"]=archive
            rec["original_archive_SHA256"]=sha
            rec.update(original_source_count(raw,src))
            if rec["status"]=="ORIGINAL_PRESSURE_COLUMN_READ":
                rec["meets_source_coverage_threshold"]=all(
                   rec["windows"][k]["valid_original_pressure"]>=src["min_n"]
                   for k in WINDOWS)
            else:
                rec["meets_source_coverage_threshold"]=False
        except Exception as ex:
            rec["status"]="SOURCE_BLOCKED"
            rec["reason"]=f"{type(ex).__name__}: {ex}"[:360]
            rec["meets_source_coverage_threshold"]=False
        print("P93B2D_AMENDMENT_A_SOURCE_ONLY",json.dumps({
            "source":rec["family"],"id":rec["station_id"],"status":rec["status"],
            "eligible":rec["meets_source_coverage_threshold"],"field":rec.get("field_name"),
            "original_csv_fields":rec.get("original_csv_fields"),
            "windows":rec.get("windows")},default=lambda x:dict(x)),flush=True)
    report["n_sources_eligible"]=sum(x["meets_source_coverage_threshold"] for x in report["sources"])
    report["status"]=("SOURCE_RECOVERY_IDENTIFIED_CANDIDATE" if report["n_sources_eligible"]
                      else "ALTERNATIVE_ORIGINAL_SOURCES_BLOCKED")
    (out/"p9_3b2d_source_recovery_amendment_a.json").write_text(
      json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False,default=lambda x:dict(x))+"\n")
    print("P93B2D_AMENDMENT_A_FINAL",json.dumps({
        "status":report["status"],"eligible":report["n_sources_eligible"],
        "no_pressure_model_run":True}),flush=True)
    return report


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--out",default="outputs/p93b2d-recovery")
    args=a.parse_args()
    assert CERTIFIED_BY_FAMILY["URBAN_10MIN"]=="P0_ST_10"
    assert CERTIFIED_BY_FAMILY["SUBDAILY_PP"]=="PP_TER"
    assert "P" not in CERTIFIED_BY_FAMILY.values()
    assert "PP_ST_10" not in CERTIFIED_BY_FAMILY.values()
    assert parse_time("202301100000","URBAN_10MIN")=="2023011000"
    assert parse_time("202301100010","URBAN_10MIN") is None
    assert parse_time("2023011000","SUBDAILY_PP")=="2023011000"
    assert parse_time("202301100000","SUBDAILY_PP")=="2023011000"
    assert parse_time("202301100010","SUBDAILY_PP") is None
    run(args.out)
