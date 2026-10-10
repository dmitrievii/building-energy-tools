#!/usr/bin/env python3
"""P6.2B GeoSphere Graz station network / solar quality reconnaissance.

Raw station measurements and q21 flags are never rewritten or imputed.
This is source AVAILABILITY + QC reconnaissance, not trained correction.
"""
from __future__ import annotations
import argparse,calendar,csv,gzip,hashlib,json,math,time
from collections import Counter,defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

HOURLY="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h"
MONTHLY="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
P3_DONORS=(30,116,200,54,8,13605)
TARGET=(46.983,15.450)
ACCEPTED_Q21={10,11,12,20,21,22}
H_FIELDS=("tl","rr","cglo")
PERIODS=((1995,1),(1995,7),(2000,1),(2000,7),
         (2005,1),(2005,7),(2010,1),(2010,7),(2014,1),(2014,7))

def download(url,limit=30000000):
    errors=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":"IGE-P6.2B-research-network-2026"}),timeout=100) as r:
                b=r.read(limit+1)
                if r.status!=200 or len(b)>limit:raise ValueError("Response truncated or not HTTP200")
                return b
        except (HTTPError,URLError,OSError,TimeoutError) as e:
            errors.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):
                break
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError("GeoSphere request unavailable "+url+": "+";".join(errors))

def sha(b):return hashlib.sha256(b).hexdigest()
def haversine(lat,lon):
    a,b=map(math.radians,(lat,lon));c,d=map(math.radians,TARGET)
    delta=math.sin((a-c)/2)**2+math.cos(a)*math.cos(c)*math.sin((b-d)/2)**2
    return 12742*math.asin(min(1,math.sqrt(delta)))

def select_stations(metadata,max_nearby=12):
    stations={}
    for item in metadata.get("stations",[]):
        try:
            sid=int(item["id"]);lat=float(item["lat"]);lon=float(item["lon"])
            if not (-90<=lat<=90 and -180<=lon<=180):continue
            dist=haversine(lat,lon)
        except (KeyError,TypeError,ValueError):continue
        stations[sid]={"id":sid,"name":item.get("name"),
                       "lat":lat,"lon":lon,"altitude":item.get("altitude"),
                       "distance_from_Graz_target_km":round(dist,3),
                       "provider_metadata":item}
    nearby=[s["id"] for s in sorted(stations.values(),key=lambda a:a["distance_from_Graz_target_km"])
            if s["distance_from_Graz_target_km"]<=75]
    selected=list(dict.fromkeys([sid for sid in P3_DONORS if sid in stations]+nearby[:max_nearby]))
    if 30 not in selected or len(selected)<3:raise ValueError("Missing Graz hourly reference candidate network")
    return selected,stations

def params_by_name(metadata):
    return {p["name"]:p for p in metadata.get("parameters",[])}

def record_flags(param_obj,code_list):
    vals=param_obj.get("data",[])
    numeric=[float(x) if x is not None else None for x in vals]
    if any(x is not None and not math.isfinite(x) for x in numeric):
        raise ValueError("Nonfinite source observation")
    return numeric

def extract_snapshot(data,station_ids,variables,flag_map,y,m):
    timestamps=data.get("timestamps",[])
    expected=calendar.monthrange(y,m)[1]*24
    if len(timestamps)!=expected:
        raise ValueError(f"Incomplete hourly sample {y}-{m}: {len(timestamps)} vs {expected}")
    if len(set(timestamps))!=len(timestamps):
        raise ValueError("Duplicate hourly provider timestamps")
    fmap={}
    for feat in data.get("features",[]):
        props=feat["properties"]
        sid=props["station"]
        sid=int(sid if not isinstance(sid,dict) else sid["id"])
        if sid not in station_ids or sid in fmap:raise ValueError("Unexpected/duplicate sampled station")
        fmap[sid]=props["parameters"]
    result=[]
    for sid in station_ids:
        block=fmap.get(sid,{})
        for var in variables:
            obj=block.get(var)
            if not isinstance(obj,dict):
                result.append({"station_id":sid,"year":y,"month":m,"variable":var,
                               "hour_count":expected,"raw_nonnull":0,
                               "qc_accepted":0,"q21_codes":"{}","source_field_missing":True})
                continue
            values=record_flags(obj,{})
            if len(values)!=expected:raise ValueError("Wrong hourly variable array length")
            fname=flag_map.get(var)
            flags=block.get(fname,{}).get("data") if fname else None
            if flags is not None and len(flags)!=expected:
                raise ValueError("Shortened quality flag array")
            codes=Counter(str(x) for x in flags) if flags is not None else Counter()
            good=sum(v is not None and flags is not None and flags[i] in ACCEPTED_Q21
                     for i,v in enumerate(values))
            result.append({
                "station_id":sid,"year":y,"month":m,"variable":var,
                "hour_count":expected,"raw_nonnull":sum(v is not None for v in values),
                "qc_accepted":good,
                "qc_fraction":round(good/expected,6),
                "q21_codes":json.dumps(dict(codes),sort_keys=True),
                "unit":obj.get("unit"),
                "quality_flag_available":flags is not None,
                "source_field_missing":False,
            })
    return result

def six_donor_monthly(metadata,out):
    p=params_by_name(metadata)
    for key in ("tl_mittel","rr"):
        if key not in p:raise ValueError("Missing official monthly climate field "+key)
    official=[sid for sid in P3_DONORS if sid in
              {int(s["id"]) for s in metadata.get("stations",[]) if s.get("id") is not None}]
    if 30 not in official:raise ValueError("Official monthly Graz missing")
    fields=["tl_mittel","rr"]
    for key in ("tl_mittel_flag","rr_flag"):
        if key in p:fields.append(key)
    url=MONTHLY+"?"+urlencode({
        "station_ids":",".join(map(str,official)),
        "parameters":",".join(fields),
        "start":"1995-01-01","end":"2014-12-31","output_format":"geojson"})
    raw=download(url,12000000)
    obj=json.loads(raw)
    times=obj.get("timestamps",[])
    if len(times)!=240 or str(times[0])[:7]!="1995-01" or str(times[-1])[:7]!="2014-12":
        raise ValueError("Unexpected official monthly timeline")
    diag=[]
    byid={}
    for f in obj.get("features",[]):
        props=f["properties"]
        station=props["station"]
        sid=int(station if not isinstance(station,dict) else station["id"])
        if sid in byid:raise ValueError("Duplicate donor")
        byid[sid]=props["parameters"]
    for sid in official:
        fieldsdata=byid.get(sid,{})
        for var in ("tl_mittel","rr"):
            data=fieldsdata.get(var,{}).get("data")
            if data is not None and len(data)!=240:raise ValueError("Official donor partial series")
            valid=[] if data is None else [float(x) for x in data if x is not None]
            if any(not math.isfinite(v) for v in valid):raise ValueError("Monthly NaN")
            flag_name=var+"_flag"
            flags=fieldsdata.get(flag_name,{}).get("data")
            if flags is not None and len(flags)!=240:raise ValueError("Official monthly flag length")
            diag.append({"station_id":sid,"variable":var,"months_total":240,
                         "raw_nonnull":len(valid),"missing":240-len(valid),
                         "quality_flag_available":flags is not None,
                         "quality_code_histogram":json.dumps(dict(Counter(str(z) for z in flags))) if flags is not None else "{}"})
    with gzip.open(out/"official_six_donor_monthly_1995_2014.geojson.gz","wb") as f:f.write(raw)
    return diag,{"url":url,"raw_sha256":sha(raw),"stations_requested":official,
                 "station_features_present":sorted(byid),"fields":fields}

def write_csv(path,rows):
    if not rows:raise ValueError("No rows")
    with path.open("w",encoding="utf8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)

def execute(out):
    out.mkdir(parents=True,exist_ok=True)
    hraw=download(HOURLY+"/metadata",8000000)
    mraw=download(MONTHLY+"/metadata",8000000)
    hmeta=json.loads(hraw);mmeta=json.loads(mraw)
    selected,station_catalog=select_stations(hmeta)
    hp=params_by_name(hmeta)
    fields=[x for x in H_FIELDS if x in hp]
    if "cglo" not in fields:raise ValueError("Hourly radiation field cglo missing")
    flags={v:v+"_flag" for v in fields if v+"_flag" in hp}
    quality=hmeta.get("code_lists",{}).get("q21",[])
    quality_codes={int(x["key"]) for x in quality if x.get("key") is not None}
    if flags and not ACCEPTED_Q21<=quality_codes:
        raise ValueError("GeoSphere q21 meanings changed; do not classify data")
    monthly_inventory,monthly_prov=six_donor_monthly(mmeta,out)
    write_csv(out/"official_donor_monthly_inventory.csv",monthly_inventory)
    with (out/"candidate_station_metadata.json").open("w",encoding="utf8") as f:
        json.dump({"selected":[station_catalog[sid] for sid in selected],
                   "hourly_parameter_metadata":[hp[k] for k in fields+list(flags.values())],
                   "hourly_q21":quality,
                   "solar_related_monthly_metadata":[p for p in mmeta.get("parameters",[])
                      if any(word in (str(p.get("name",""))+" "+str(p.get("long_name",""))).lower()
                             for word in ("strahl","global","cglo","glo","sonne"))]},
                  f,ensure_ascii=False,indent=2)
    rawfiles={}
    allrows=[]
    for y,m in PERIODS:
        use_fields=fields+list(flags.values())
        url=HOURLY+"?"+urlencode({
            "station_ids":",".join(map(str,selected)),
            "parameters":",".join(use_fields),
            "start":f"{y}-{m:02d}-01T00:00",
            "end":f"{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}T23:00",
            "output_format":"geojson"})
        buf=download(url,45000000)
        result=extract_snapshot(json.loads(buf),selected,fields,flags,y,m)
        allrows.extend(result)
        fn=f"station_network_{y}_{m:02d}.geojson.gz"
        with gzip.open(out/fn,"wb") as f:f.write(buf)
        rawfiles[fn]={"url":url,"sha256_of_uncompressed_provider_response":sha(buf),
                      "stations":len(selected),"raw_response_bytes":len(buf)}
        print("GRAZ STATION NETWORK",y,m,"stations",len(selected),
              "qc solar",sum(r["qc_accepted"] for r in result if r["variable"]=="cglo"),flush=True)
    write_csv(out/"multi_station_hourly_q21_inventory.csv",allrows)
    summary={}
    for sid in selected:
        samples=[r for r in allrows if r["station_id"]==sid and r["variable"]=="cglo"]
        summary[str(sid)]={
            "station_name":station_catalog[sid]["name"],
            "distance_km":station_catalog[sid]["distance_from_Graz_target_km"],
            "sampled_months":len(samples),
            "cglo_raw_nonnull_hours":sum(r["raw_nonnull"] for r in samples),
            "cglo_q21_accepted_hours":sum(r["qc_accepted"] for r in samples),
            "cglo_months_ge90pct_quality":sum(r["qc_accepted"]>=.9*r["hour_count"] for r in samples),
        }
    report={"status":"PASS_SOURCE_RECONNAISSANCE_ONLY","stage":"P6.2B",
            "purpose":"Graz nearby station donor quality and radiation availability",
            "hourly_probe_months":[f"{y}-{m:02d}" for y,m in PERIODS],
            "selected_station_count":len(selected),
            "selected_station_ids":selected,
            "variable_count":len(fields),
            "solar_quality_coverage":summary,
            "month_source_provenance":rawfiles,
            "official_monthly_donors":monthly_prov,
            "source_metadata_sha256":{"hourly":sha(hraw),"monthly":sha(mraw)},
            "outputs_sha256":{
                "multi_station_hourly_q21_inventory.csv":sha((out/"multi_station_hourly_q21_inventory.csv").read_bytes()),
                "official_donor_monthly_inventory.csv":sha((out/"official_donor_monthly_inventory.csv").read_bytes()),
            },
            "limits":[
                "10 sampled winter/summer months across five years; NOT a 20-year coverage proof.",
                "Geographical proximity is not sufficient evidence of radiation climatology representativeness.",
                "Original q21=0 observations are retained but not certified as quality-checked.",
                "Official monthly data may lack provider quality flags, and have different parameter semantics.",
                "No model correction, gap-filling, interpolation or EPW generation performed.",
            ]}
    (out/"p6_2b_graz_station_network_report.json").write_text(json.dumps(
        report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2B NETWORK",report["status"],"stations",len(selected),
          "sample_months",len(PERIODS),flush=True)
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("outputs/p6_2b_graz_network"))
    args=ap.parse_args()
    execute(args.out)
