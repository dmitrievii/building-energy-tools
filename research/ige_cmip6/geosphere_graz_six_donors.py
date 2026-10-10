#!/usr/bin/env python3
"""Download observed 1991–2020 GeoSphere records for six P3 Graz donors.

Independent open research evidence. No modification of the Climate Analyzer.
Read-only GeoSphere Austria Dataset API, parameter semantics from live metadata.
"""
import datetime as dt
import hashlib,json,pathlib,urllib.parse,urllib.request,sys

BASE="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
IDS=(30,116,200,54,8,13605)
QUERY={
  "parameters":"tl_mittel,rr",
  "station_ids":",".join(map(str,IDS)),
  "start":"1991-01-01",
  "end":"2020-12-31",
  "output_format":"geojson"
}
OUT=pathlib.Path("geosphere_graz_donors");OUT.mkdir(exist_ok=True)
def get(url):
 req=urllib.request.Request(url,headers={"User-Agent":"IGE-independent-climate-research-2026","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=100) as r:
  buf=r.read(12_000_000)
  if r.status!=200:raise RuntimeError(f"HTTP {r.status}")
 return buf
meta_raw=get(BASE+"/metadata")
meta=json.loads(meta_raw)
info={int(item["id"]):item for item in meta["stations"] if item.get("id") in IDS}
if set(info)!=set(IDS):raise RuntimeError(f"Missing station metadata: {sorted(set(IDS)-set(info))}")
params={x["name"]:x for x in meta["parameters"]}
if params["tl_mittel"]["unit"]!="°C" or params["rr"]["unit"]!="mm":
 raise RuntimeError("Unexpected GeoSphere native parameter units")
url=BASE+"?"+urllib.parse.urlencode(QUERY)
raw=get(url);d=json.loads(raw)
stamp=d.get("timestamps",[])
if len(stamp)!=360 or stamp[0][:7]!="1991-01" or stamp[-1][:7]!="2020-12":
 raise RuntimeError(f"Unexpected time coverage: {len(stamp)} {stamp[:1]} {stamp[-1:]}")
features=d.get("features",[])
feature_map={}
for feature in features:
 props=feature.get("properties",{})
 station=props.get("station")
 if station is None:raise RuntimeError("GeoSphere feature without station identifier")
 ident=int(station) if not isinstance(station,dict) else int(station["id"])
 if ident not in IDS or ident in feature_map:raise RuntimeError("Wrong or duplicate station "+str(ident))
 feature_map[ident]=feature
if set(feature_map)!=set(IDS):raise RuntimeError(f"Missing features {sorted(set(IDS)-set(feature_map))}")
catalog=[]
for ident in IDS:
 f=feature_map[ident]
 vals=f["properties"]["parameters"]
 report={"station_id":ident,"name":info[ident]["name"],
         "lat":info[ident]["lat"],"lon":info[ident]["lon"],"altitude":info[ident]["altitude"]}
 for param in ("tl_mittel","rr"):
  data=vals[param]["data"]
  report[param+"_count"]=len(data)
  report[param+"_missing"]=sum(x is None for x in data)
  report[param+"_range"]=[min(x for x in data if x is not None),max(x for x in data if x is not None)]
  print("DONOR",ident,report["name"],param,"size",len(data),"missing",report[param+"_missing"],"range",report[param+"_range"],flush=True)
 catalog.append(report)
(OUT/"raw_geosphere_six_graz_donors_1991_2020.geojson").write_bytes(raw)
(OUT/"dataset_metadata_relevant.json").write_text(json.dumps({
 "endpoint":BASE,
 "title":meta.get("title"),"parameters":[params[n] for n in ("tl_mittel","rr")],
 "stations":[info[n] for n in IDS],
 "quality_flags":meta.get("code_lists",{}).get("q21"),
 "source_request":url,
 "source_response_sha256":hashlib.sha256(raw).hexdigest(),
 "metadata_response_sha256":hashlib.sha256(meta_raw).hexdigest(),
 "created_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 },ensure_ascii=False,indent=2),encoding="utf8")
(OUT/"donor_inventory.json").write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding="utf8")
print("DONE source_sha256",hashlib.sha256(raw).hexdigest(),"stations",len(catalog),flush=True)
