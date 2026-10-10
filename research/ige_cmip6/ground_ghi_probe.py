#!/usr/bin/env python3
"""Independent radiation ground-observation census (no missing-value fills)."""
from __future__ import annotations
import urllib.request,urllib.parse,json,hashlib,datetime,pathlib
BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
OUT=pathlib.Path("outputs/ground_ghi");OUT.mkdir(parents=True,exist_ok=True)
station_ids=(30,116,200,54,8,13605)
p={"parameters":"cglo_j,cglo_j_flag",
"station_ids":",".join(map(str,station_ids)),
"start":"1991-01-01","end":"2020-12-31","output_format":"geojson"}
url=BASE+"?"+urllib.parse.urlencode(p)
req=urllib.request.Request(url,headers={"User-Agent":"IGE-Ground-Radiation-Validation-2026","Accept":"application/json"})
with urllib.request.urlopen(req,timeout=100) as r:
 body=r.read(5_000_000)
 print("HTTP",r.status,"BYTES",len(body),flush=True)
raw=json.loads(body)
(OUT/"geosphere_graz_ground_global_irradiation.geojson").write_bytes(body)
rows=[]
for feature in raw["features"]:
 props=feature["properties"]
 vals=props["parameters"]["cglo_j"]["data"]
 flags=props["parameters"]["cglo_j_flag"]["data"]
 sid=props["station"]
 usable=sum(x is not None and flag in (10,11,12,20,21,22) for x,flag in zip(vals,flags))
 recorded=sum(x is not None for x in vals)
 byyear={y:sum(x is not None for x,t in zip(vals,raw["timestamps"]) if int(t[:4])==y)
         for y in range(1991,2021)}
 d={"station":sid,"recorded_months":recorded,"q_flag_valid_months":usable,
    "yearly_month_coverage":byyear,"global_radiation_unit":"J/cm²",
    "conversion_to_kwh_m2":"divide by 360"}
 print("GROUND",sid,"recorded",recorded,"usable",usable,"first",next(((y,n) for y,n in byyear.items() if n>0),None),flush=True)
 rows.append(d)
(OUT/"ground_ghi_station_coverage.json").write_text(json.dumps({"source":url,"sha256":hashlib.sha256(body).hexdigest(),
  "year_range":[1991,2020],"station_inventory":rows},indent=2,ensure_ascii=False),encoding="utf8")
