#!/usr/bin/env python3
"""Probe GeoSphere Austria klima-v2-1m raw monthly mean temperature records.
Retains source response unchanged for accountable downstream parsing.
"""
import datetime,json,pathlib,urllib.request,urllib.parse,hashlib
out=pathlib.Path("geosphere_bridge_probe");out.mkdir(exist_ok=True)
api="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1m"
for name,url in [
 ("metadata",api+"/metadata"),
 ("station30",api+"?"+urllib.parse.urlencode({"parameters":"tl_mittel","station_ids":"30","start":"1991-01-01","end":"2020-12-31","output_format":"json"}))
]:
 try:
  request=urllib.request.Request(url,headers={"User-Agent":"IGE-Independent-Climate-Engine-Research/0.2.3","Accept":"application/json"})
  with urllib.request.urlopen(request,timeout=80) as response:
   b=response.read(12000000)
   code=response.status;ctype=response.headers.get("Content-Type")
  (out/(name+".json")).write_bytes(b)
  data=json.loads(b)
  print("PROBE",name,"HTTP",code,"BYTES",len(b),"SHA256",hashlib.sha256(b).hexdigest(),"CONTENT_TYPE",ctype,flush=True)
  print("SHAPE",name,"TOP_KEYS",list(data)[:25] if isinstance(data,dict) else type(data).__name__,flush=True)
  if name=="station30":
   if isinstance(data,dict):
    print("TIMESTAMPS",len(data.get("timestamps",[])), "FEATURES",len(data.get("features",[])),flush=True)
    if data.get("features"):
     item=data["features"][0]
     print("FIRST_FEATURE_SHAPE",str(item)[:1800],flush=True)
   print("PREFIX",str(data)[:1800],flush=True)
  else:
   s=str(data)
   for term in ["tl_mittel","Graz","'id': 30",'"id": 30']:
    print("METADATA_FIND",term,s.find(term),flush=True)
 except Exception as exc:
  print("PROBE_ERROR",name,type(exc).__name__,str(exc),flush=True)
  raise
