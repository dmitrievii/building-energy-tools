#!/usr/bin/env python3
"""P6.2B GeoSphere hourly 1995–2014 station 30 annual raw/QC extraction.

Keep every original hourly value, provenance, UTC timestamp and q21 flags.
Generate conservative QC-screened hourly and month-year descriptive statistics.
NO gap filling, NO model calibration, NO conversion of cglo to GHI or rr to
certified precipitation accumulation until the recorded hour semantics are
verified independently.
"""
from __future__ import annotations
import argparse
import calendar
from collections import Counter,defaultdict
import csv
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h"
STATION=30
FIELDS=("tl","rf","rr","cglo","ff","p")
UNITS={
    "tl":("°C","degC"),
    "rf":("%",),
    "rr":("mm",),
    "cglo":("W/m²","W/m2","J/cm²","J/cm2"),
    "ff":("m/s",),
    "p":("hPa",),
}
# Raw values are always retained. Extremely broad plausible ranges screen
# spurious sensor readings from diagnostics; they are not gap-filled.
RANGES={"tl":(-75,65),"rf":(0,105),"rr":(0,250),
        "cglo":(-20,2000),"ff":(0,110),"p":(500,1200)}
GOOD_Q21={10,11,12,20,21,22}

def fetch(url,max_bytes=45000000):
    failures=[]
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={
                "Accept":"application/json",
                "User-Agent":"IGE-independent-climate-engine-P6.2B-2026",
            }),timeout=150) as resp:
                raw=resp.read(max_bytes+1)
                if resp.status!=200 or len(raw)>max_bytes:
                    raise RuntimeError("Unexpected GeoSphere response length/status")
                return raw
        except (HTTPError,URLError,TimeoutError,OSError) as e:
            failures.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):
                break
            if attempt<3:time.sleep(min(3*2**attempt,15))
    raise RuntimeError(f"GeoSphere hourly fetch failed: {url}: {failures}")

def metadata_contract(metadata):
    stations={int(x["id"]):x for x in metadata.get("stations",[]) if "id" in x}
    if STATION not in stations:raise ValueError("Graz station 30 absent from provider metadata")
    specs={x["name"]:x for x in metadata.get("parameters",[])}
    for name in FIELDS:
        if name not in specs or specs[name].get("unit") not in UNITS[name]:
            raise ValueError(f"Missing or unknown provider parameter/unit: {name}")
    flags={name:name+"_flag" for name in FIELDS if name+"_flag" in specs}
    q21=metadata.get("code_lists",{}).get("q21",[])
    known={int(x["key"]) for x in q21 if x.get("key") is not None}
    if flags and not GOOD_Q21<=known:
        raise ValueError("GeoSphere q21 code-list missing required quality statuses")
    for k,v in flags.items():
        if specs[v].get("code_list_ref") not in ("q21",None):
            raise ValueError(f"Unexpected quality flag code-list for {v}")
    return specs,stations[STATION],flags,known

def parse_utc(value):
    text=str(value)
    dt=datetime.fromisoformat(text.replace("Z","+00:00"))
    if dt.tzinfo is None or dt.utcoffset()!=timedelta(0):
        raise ValueError("Station clock not explicitly UTC")
    return dt.astimezone(timezone.utc)

def process_year(year,meta,data):
    if year<1995 or year>2014:raise ValueError("Outside accepted P6.2B calibration horizon")
    specs,station,flags,known=metadata_contract(meta)
    timestamps=data.get("timestamps",[])
    expected_hours=(366 if calendar.isleap(year) else 365)*24
    if len(timestamps)!=expected_hours:
        raise ValueError(f"Incomplete UTC hourly index {year}: {len(timestamps)}/{expected_hours}")
    actual_times=[parse_utc(s) for s in timestamps]
    expected_start=datetime(year,1,1,tzinfo=timezone.utc)
    if any(when!=expected_start+timedelta(hours=i) for i,when in enumerate(actual_times)):
        raise ValueError(f"Missing, duplicated or shifted hourly UTC time index in {year}")
    items=data.get("features",[])
    if len(items)!=1:raise ValueError("GeoSphere returned unexpected feature count")
    props=items[0].get("properties",{})
    ident=props.get("station")
    ident=int(ident if not isinstance(ident,dict) else ident["id"])
    if ident!=STATION:raise ValueError("Wrong station in API response")
    params=props.get("parameters",{})
    raw_series={};qc_series={};missingflags=[]
    for name in FIELDS:
        item=params.get(name)
        if not isinstance(item,dict) or item.get("unit") not in UNITS[name]:
            raise ValueError(f"Missing station hourly parameter or wrong unit: {name}")
        samples=item.get("data")
        if not isinstance(samples,list) or len(samples)!=expected_hours:
            raise ValueError(f"Provider {name} expected {expected_hours} UTC hours")
        raw_series[name]=samples
        flag_name=flags.get(name)
        if flag_name is None:
            missingflags.append(name)
            qc_series[name]=[None]*expected_hours
            continue
        f=params.get(flag_name)
        if not isinstance(f,dict) or len(f.get("data",[]))!=expected_hours:
            # Do not silently use unverified observations where q21 was advertised.
            missingflags.append(name)
            qc_series[name]=[None]*expected_hours
        else:
            qc_series[name]=f["data"]
    # Preserve full hourly provenance even when QC is unavailable.
    entries=[];monthly=defaultdict(lambda:defaultdict(list))
    counts={name:Counter() for name in FIELDS}
    codecounts={name:Counter() for name in FIELDS}
    for i,when in enumerate(actual_times):
        rec={"timestamp_utc":when.isoformat().replace("+00:00","Z"),
             "year":when.year,"month":when.month,"day":when.day,"hour":when.hour}
        for name in FIELDS:
            value=raw_series[name][i]
            num=None if value is None else float(value)
            if num is not None and not math.isfinite(num):
                raise ValueError(f"Non-finite source value: {name} {when}")
            q=qc_series[name][i]
            if q is not None:
                try:flag=int(q)
                except (ValueError,TypeError):raise ValueError(f"Non-integer q21 flag {name} {q}")
                if flag not in known:
                    raise ValueError(f"Unknown quality flag {name}/{flag}")
            else:flag=None
            good=(num is not None and flag in GOOD_Q21 and
                  RANGES[name][0]<=num<=RANGES[name][1])
            rec[name+"_raw"]=num
            rec[name+"_q21"]=flag
            rec[name+"_accepted"]=num if good else None
            codecounts[name][str(flag)]+=1
            counts[name]["accepted" if good else "rejected"]+=1
            if num is None:counts[name]["raw_null"]+=1
            elif not RANGES[name][0]<=num<=RANGES[name][1]:
                counts[name]["out_of_range"]+=1
            monthly[(when.year,when.month)][name].append(num if good else None)
        entries.append(rec)
    monthly_rows=[]
    for (y,m) in sorted(monthly):
        row={"year":y,"month":m,"expected_UTC_hours":calendar.monthrange(y,m)[1]*24}
        for name in FIELDS:
            values=monthly[(y,m)][name]
            available=[v for v in values if v is not None]
            row[name+"_qc_hours"]=len(available)
            row[name+"_coverage"]=len(available)/row["expected_UTC_hours"]
            row[name+"_mean_if_90pct"]=sum(available)/len(available) if len(available)/len(values)>=.9 else None
            # Raw hourly rr units / measurement semantics are not yet certified:
            # this is a diagnostic sum ONLY when all hours passed QC.
            if name=="rr":
                row["rr_hourly_sum_unverified_mm"]=sum(available) if len(available)==len(values) else None
        monthly_rows.append(row)
    audit={
        "status":"PASS",
        "stage":"P6.2B_SOURCE_HOURLY",
        "station_id":STATION,"station_metadata":station,
        "year":year,"expected_hours":expected_hours,"hour_count":len(entries),
        "parameter_units":{n:specs[n].get("unit") for n in FIELDS},
        "parameter_metadata":{n:specs[n] for n in FIELDS},
        "quality_flag_definitions":meta.get("code_lists",{}).get("q21",[]),
        "quality_policy":"accept only q21 codes 10/11/12/20/21/22 with broad physical screening; retain raw separately",
        "unavailable_quality_flags":missingflags,
        "counts_by_parameter":{n:dict(counts[n]) for n in FIELDS},
        "q21_distribution":{n:dict(codecounts[n]) for n in FIELDS},
        "method_caveat":"Hourly tl and cglo/rr timestamps need parameter-specific interpretation; precipitation sums unverified and not used in calibration",
    }
    return entries,monthly_rows,audit

def write_csv_gz(path,rows):
    if not rows:raise ValueError("Cannot emit empty series")
    with gzip.open(path,"wt",encoding="utf8",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def save(year,out):
    metadata_raw=fetch(BASE+"/metadata",8000000)
    meta=json.loads(metadata_raw)
    specs,station,flags,known=metadata_contract(meta)
    requested=list(FIELDS)+[flags[v] for v in FIELDS if v in flags]
    if len(requested)*8784>1000000:
        raise ValueError("GeoSphere API datapoint request cap exceeded")
    query=urlencode({
        "station_ids":str(STATION),"parameters":",".join(requested),
        "start":f"{year}-01-01T00:00","end":f"{year}-12-31T23:00",
        "output_format":"geojson"
    })
    url=BASE+"?"+query
    raw=fetch(url)
    entries,months,qa=process_year(year,meta,json.loads(raw))
    out.mkdir(parents=True,exist_ok=True)
    with gzip.open(out/"original_hourly_provider.geojson.gz","wb") as f:f.write(raw)
    write_csv_gz(out/"hourly_raw_qc.csv.gz",entries)
    with (out/"monthly_coverage.csv").open("w",encoding="utf8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(months[0]))
        writer.writeheader();writer.writerows(months)
    qa["source_url"]=url
    qa["source_uncompressed_sha256"]=hashlib.sha256(raw).hexdigest()
    qa["provider_metadata_sha256"]=hashlib.sha256(metadata_raw).hexdigest()
    qa["requested_parameters"]=requested
    qa["hourly_csv_gzip_sha256"]=hashlib.sha256((out/"hourly_raw_qc.csv.gz").read_bytes()).hexdigest()
    qa["monthly_csv_sha256"]=hashlib.sha256((out/"monthly_coverage.csv").read_bytes()).hexdigest()
    (out/"quality_provenance.json").write_text(json.dumps(qa,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2B HOURLY OBS",year,"PASS",len(entries),"hours",
          "hourly QC",[qa["counts_by_parameter"][n].get("accepted",0) for n in FIELDS],flush=True)

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--year",type=int,required=True,choices=tuple(range(1995,2015)))
    a.add_argument("--output-root",type=Path,default=Path("outputs/p6_2b_hourly"))
    opts=a.parse_args()
    save(opts.year,opts.output_root/str(opts.year))

if __name__=="__main__":main()
