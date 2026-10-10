#!/usr/bin/env python3
"""P6.2B Solar Reference Closure: immutable 1995–2014 GeoSphere daily GHI source.

GeoSphere cglo_j is a *calibrated 24-hour irradiation SUM* in J/cm²,
covering 00–24 MOZ = 23:00 UTC previous day through 23:00 UTC nominal day.
NASA NEX-GDDP-CMIP6 rsds is a climate-model daily GHI series with its OWN
calendar/day boundaries. Do not align source days for per-date error metrics.
Conversion: 1 J/cm² = 1/360 kWh/m². NEVER reclassify q21=0 as verified.
"""
from __future__ import annotations
import argparse,calendar,csv,gzip,hashlib,json,math,time
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

URL="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d"
STATION=30
NAME="cglo_j"
FLAG="cglo_j_flag"
UNIT="J/cm²"
QC_GOOD={10,11,12,20,21,22}
KWH_PER_J_CM2=1./360.
PERIODS=((1995,1999),(2000,2004),(2005,2009),(2010,2014))

def sha(data):return hashlib.sha256(data).hexdigest()

def read_json(url,limit=18000000):
    errors=[]
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={"Accept":"application/json",
                         "User-Agent":"IGE-independent-climate-engine-P6.2B-solar-2026"}),timeout=120) as resp:
                data=resp.read(limit+1)
                if resp.status!=200 or len(data)>limit:
                    raise RuntimeError("GeoSphere source response invalid/truncated")
                return data,json.loads(data)
        except (HTTPError,URLError,OSError,TimeoutError) as e:
            errors.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):break
            if attempt<3:time.sleep(2**attempt)
    raise RuntimeError("GeoSphere endpoint failed: "+url+"; "+str(errors))

def meta_contract(meta):
    byname={p['name']:p for p in meta.get('parameters',[])}
    for key in (NAME,FLAG):
        if key not in byname:raise ValueError("Required calibrated daily solar/quality parameter not available: "+key)
    if byname[NAME].get("unit")!=UNIT:
        raise ValueError("GeoSphere daily radiation unit changed; refusing implicit conversion")
    description=str(byname[NAME].get("description",""))
    if "24-Stundensumme" not in description or "MOZ" not in description:
        raise ValueError("Daily solar interval definition changed: "+description)
    station={int(s['id']):s for s in meta.get('stations',[]) if s.get('id') is not None}
    if STATION not in station:raise ValueError("Graz station 30 missing from daily metadata")
    codes={int(x['key']) for x in meta.get('code_lists',{}).get('q21',[])
           if x.get('key') is not None}
    if not QC_GOOD<=codes or 0 not in codes:
        raise ValueError("Official q21 meanings incomplete; cannot apply trusted QC")
    return byname,station[STATION],codes

def dates_between(start,end):
    d=start
    while d<=end:
        yield d
        d+=timedelta(days=1)

def parse_source(d,metadata,first,last):
    params,station,codes=meta_contract(metadata)
    if (first,last) not in PERIODS:raise ValueError("Only declared nonoverlapping 5-year scientific periods")
    start=date(first,1,1);end=date(last,12,31)
    wanted=list(dates_between(start,end))
    timestamps=d.get('timestamps',[])
    if len(timestamps)!=len(wanted):
        raise ValueError(f"Daily source date count {len(timestamps)} expected {len(wanted)}")
    if any(str(ts)[:10]!=w.isoformat() or
           not str(ts).endswith(("+00:00","Z"))
           for ts,w in zip(timestamps,wanted)):
        raise ValueError("Daily GeoSphere UTC-labelled dates are missing/shifted/duplicated")
    features=d.get("features",[])
    if len(features)!=1:raise ValueError("GeoSphere returned nonunique/missing station features")
    prop=features[0]["properties"]
    actual=prop.get("station")
    actual=int(actual if not isinstance(actual,dict) else actual["id"])
    if actual!=STATION:raise ValueError("Wrong GeoSphere station in source")
    info=prop.get("parameters",{})
    solar=info.get(NAME,{});qc=info.get(FLAG,{})
    if solar.get("unit")!=UNIT or len(solar.get('data',[]))!=len(wanted) \
       or len(qc.get('data',[]))!=len(wanted):
        raise ValueError("Daily solar/quality vector incomplete or mismatched units")
    rows=[];qcodes=Counter();stats=Counter()
    for idx,day in enumerate(wanted):
        val=solar['data'][idx]
        raw=None if val is None else float(val)
        if raw is not None and not math.isfinite(raw):raise ValueError("Nonfinite daily source")
        flag=qc['data'][idx]
        if flag is not None:
            try:flag=int(flag)
            except (ValueError,TypeError):raise ValueError(f"Invalid q21 code {flag!r}")
            if flag not in codes:raise ValueError(f"Unknown source q21 code {flag}")
        ok=(raw is not None and flag in QC_GOOD and 0<=raw<=4500)
        qcodes[str(flag)]+=1
        stats['accepted' if ok else 'rejected']+=1
        if raw is None:stats['null']+=1
        elif not 0<=raw<=4500:stats['out_of_range']+=1
        rows.append({
            "date_geo_moz_utc_label":day.isoformat(),
            "year":day.year,"month":day.month,"day":day.day,
            "cglo_j_raw_J_cm2":raw,"cglo_j_q21":flag,
            "cglo_j_accepted_kwh_m2":round(raw*KWH_PER_J_CM2,10) if ok else None,
        })
    report={
        "status":"PASS_SOURCE_QC","stage":"P6.2B_SOLAR_REFERENCE",
        "year_start":first,"year_end":last,"station_id":STATION,
        "station_metadata":station,"expected_days":len(wanted),
        "calendar":"Gregorian","source_parameters":[NAME,FLAG],
        "source_radiation_unit":UNIT,"conversion_kwh_m2_per_J_cm2":KWH_PER_J_CM2,
        "daily_time_boundaries":description_from_param(params[NAME]),
        "q21_distribution":dict(qcodes),
        "quality_counts":{k:stats.get(k,0) for k in ("accepted","rejected","null","out_of_range")},
        "rejected_raw_values_preserved":True,
    }
    return rows,report

def description_from_param(p):
    return str(p.get("description",""))

def save(first,last,out):
    metadata_bytes,metadata=read_json(URL+"/metadata",8000000)
    _,_,_=meta_contract(metadata)
    query=urlencode({
        "station_ids":str(STATION),
        "parameters":f"{NAME},{FLAG}",
        "start":f"{first}-01-01","end":f"{last}-12-31",
        "output_format":"geojson"})
    source_url=URL+"?"+query
    response_bytes,response=read_json(source_url)
    records,qa=parse_source(response,metadata,first,last)
    out.mkdir(parents=True,exist_ok=True)
    with gzip.open(out/"original_geosphere_daily_5y.geojson.gz","wb") as f:
        f.write(response_bytes)
    with (out/"daily_station30_cglo_j_qc.csv").open("w",encoding="utf8",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=list(records[0]))
        wr.writeheader();wr.writerows(records)
    qa.update({
        "provider_request":source_url,
        "provider_raw_uncompressed_sha256":sha(response_bytes),
        "metadata_uncompressed_sha256":sha(metadata_bytes),
        "csv_sha256":sha((out/"daily_station30_cglo_j_qc.csv").read_bytes()),
    })
    (out/"source_quality_report.json").write_text(json.dumps(
        qa,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("SOLAR REFERENCE",first,last,"PASS",qa["expected_days"],
          "verified",qa["quality_counts"]["accepted"],
          "unverified",qa["quality_counts"]["rejected"],flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--first",type=int,required=True)
    p.add_argument("--last",type=int,required=True)
    p.add_argument("--out-root",type=Path,default=Path("outputs/p6_2b_solar_chunks"))
    args=p.parse_args()
    save(args.first,args.last,args.out_root/f"{args.first}-{args.last}")

if __name__=="__main__":main()
