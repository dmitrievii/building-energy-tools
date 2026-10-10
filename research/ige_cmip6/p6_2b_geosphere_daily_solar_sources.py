#!/usr/bin/env python3
"""P6.2B GeoSphere official station DAILY solar parameter provenance reconnaissance.

Only discover parameter descriptions/codes and sample short observed periods.
Do not assume daily solar amount unit, no daily-hourly synchronization, no
imputation or reclassification of q21=0 and no automatic use of APOLIS v2 CRS.
"""
from __future__ import annotations
import argparse,calendar,gzip,hashlib,json,math,time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d"
MONTHLY="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
STATION=30
DATES=((1995,7),(2005,7),(2014,7))
QGOOD={10,11,12,20,21,22}
def get(url,limit=10000000):
    errors=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={"User-Agent":"IGE-P6.2B-daily-solar-source-2026","Accept":"application/json"}),timeout=100) as resp:
                raw=resp.read(limit+1)
                if resp.status!=200 or len(raw)>limit:raise RuntimeError("Response rejected or too long")
                return raw
        except (HTTPError,URLError,TimeoutError,OSError) as e:
            errors.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):
                break
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError("Source request failed "+url+" "+str(errors))
def sha(b):return hashlib.sha256(b).hexdigest()

def candidates(meta):
    solar=[]
    for p in meta.get("parameters",[]):
        name=str(p.get("name",""))
        low=(name+" "+str(p.get("long_name",""))).lower()
        # 'sunshine duration' is not a direct irradiance observation; never
        # substitute it for measured global horizontal radiation.
        if name.endswith("_flag"):continue
        if name=="cglo" or "globalstrahl" in low or "global irradi" in low:
            solar.append(p)
    return solar

def availability(meta):
    ids={int(x["id"]):x for x in meta.get("stations",[]) if "id" in x}
    return ids.get(STATION)

def extract(data,station_id,name,flagname,year,month):
    stamps=data.get("timestamps",[])
    days=calendar.monthrange(year,month)[1]
    if len(stamps)!=days:raise ValueError("Unexpected daily sample timeline length")
    fmap={}
    for f in data.get("features",[]):
        props=f["properties"];sid=props["station"]
        sid=int(sid if not isinstance(sid,dict) else sid["id"])
        if sid==station_id:fmap=props.get("parameters",{})
    item=fmap.get(name)
    if not isinstance(item,dict):
        return {"variable":name,"year":year,"month":month,"present":False,
                "non_null":0,"quality_checked":0}
    vals=item.get("data",[])
    if len(vals)!=days:raise ValueError("Incomplete sampled daily variable")
    nums=[float(x) if x is not None else None for x in vals]
    if any(x is not None and not math.isfinite(x) for x in nums):
        raise ValueError("Nonfinite sampled solar source")
    flags=fmap.get(flagname,{}).get("data") if flagname else None
    if flags is not None and len(flags)!=days:raise ValueError("Incomplete daily quality flags")
    return {"variable":name,"year":year,"month":month,"present":True,
            "unit":item.get("unit"),"non_null":sum(x is not None for x in nums),
            "quality_checked":sum(v is not None and flags is not None and
                                  flags[i] in QGOOD for i,v in enumerate(nums)),
            "flag_available":flags is not None,
            "flag_codes":dict(Counter(str(x) for x in flags)) if flags is not None else {}}

def execute(out):
    out.mkdir(parents=True,exist_ok=True)
    output={"stage":"P6.2B_DAILY_SOLAR_SOURCE_RECON","status":"PASS_METADATA",
            "snapshots":[],"resources":{},"limitations":[
                "Daily irradiation differs from hourly power and requires explicit unit/time-interval semantics.",
                "No daily solar field is not evidence of absence of all solar observations at other GeoSphere products.",
                "Station metadata and quality flags do not establish 20-year data completeness.",
                "Official APOLIS-v2 daily radiation product has known wrong CRS and is not used here."
            ]}
    for resource in (BASE,MONTHLY):
        raw=get(resource+"/metadata")
        meta=json.loads(raw)
        solar=candidates(meta)
        params={x["name"]:x for x in meta.get("parameters",[])}
        station=availability(meta)
        name="daily" if resource==BASE else "monthly"
        output["resources"][name]={
            "metadata_sha256":sha(raw),"station30_available":bool(station),
            "station30_metadata":station,
            "global_radiation_candidates":solar,
            "q21_code_list":meta.get("code_lists",{}).get("q21",[])
        }
        (out/f"{name}_metadata_solar_candidates.json").write_text(json.dumps(
            output["resources"][name],indent=2,ensure_ascii=False)+"\n",encoding="utf8")
        if name!="daily" or not station:continue
        for par in solar[:3]:
            var=par["name"]
            flag=var+"_flag" if var+"_flag" in params else None
            for year,month in DATES:
                last=calendar.monthrange(year,month)[1]
                url=BASE+"?"+urlencode({
                    "station_ids":str(STATION),
                    "parameters":",".join([var]+([flag] if flag else [])),
                    "start":f"{year}-{month:02d}-01",
                    "end":f"{year}-{month:02d}-{last}",
                    "output_format":"geojson"})
                try:
                    buf=get(url,8000000)
                    result=extract(json.loads(buf),STATION,var,flag,year,month)
                    filename=f"daily_{var}_{year}_{month:02d}_station30.geojson.gz"
                    with gzip.open(out/filename,"wb") as f:f.write(buf)
                    result.update({"source_sha256":sha(buf),"source_url":url,"filename":filename})
                except Exception as ex:
                    result={"variable":var,"year":year,"month":month,
                            "status":"REQUEST_NOT_VERIFIED","error":str(ex),"source_url":url}
                output["snapshots"].append(result)
                print("DAILY GLOBAL SOLAR",var,year,month,
                      "presence",result.get("present"),
                      "checked",result.get("quality_checked"),flush=True)
    (out/"p6_2b_daily_monthly_solar_metadata_report.json").write_text(
        json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("DAILY/MONTHLY SOLAR CATALOG",output["status"],
          "daily candidate count",len(output["resources"]["daily"]["global_radiation_candidates"]),
          "monthly",len(output["resources"]["monthly"]["global_radiation_candidates"]),flush=True)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("outputs/p6_2b_daily_solar"))
    args=ap.parse_args()
    execute(args.out)
