#!/usr/bin/env python3
"""Discover available independent NASA NEX-GDDP-CMIP6 GCM runs for rsds.
No guesswork over member IDs: inspect THREDDS catalogRef hierarchy.
"""
import urllib.request,urllib.error,xml.etree.ElementTree as ET
import json,time,pathlib,datetime
OUT=pathlib.Path("outputs/gcm_discovery"); OUT.mkdir(parents=True,exist_ok=True)
base="https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6"
models=("MRI-ESM2-0","MPI-ESM1-2-HR","CanESM5","GFDL-ESM4","IPSL-CM6A-LR","ACCESS-CM2","NorESM2-MM","EC-Earth3")
def read(url):
 request=urllib.request.Request(url,headers={"User-Agent":"IGE-CMIP6-GCM-Ensemble-Discovery/0.4"})
 with urllib.request.urlopen(request,timeout=35) as r:
  if r.status!=200:raise RuntimeError("HTTP "+str(r.status))
  return ET.fromstring(r.read(600000))
def refs(doc):
 return [{"name":x.attrib.get("name",""),"href":x.attrib.get("{http://www.w3.org/1999/xlink}href","")} for x in doc.iter() if x.tag.rsplit("}",1)[-1]=="catalogRef"]
def datasets(doc):
 return [{"name":x.attrib.get("name",""),"urlPath":x.attrib.get("urlPath","")} for x in doc.iter() if x.tag.rsplit("}",1)[-1]=="dataset" and x.attrib.get("urlPath")]
output=[]
for model in models:
 result={"model":model,"scenarios":{},"errors":[]}
 for scenario in ("historical","ssp245","ssp585"):
  try:
   doc=read(f"{base}/{model}/{scenario}/catalog.xml")
   candidates=refs(doc)
   result["scenarios"][scenario]={"members":candidates[:30]}
   print("MEMBER_CATALOG",model,scenario,len(candidates),[r["name"] for r in candidates[:15]],flush=True)
   for member in ("r1i1p1f1","r1i1p2f1","r1i1p1f2","r1i1p1f3"):
    if not any(r["name"]==member for r in candidates):continue
    try:
     run=read(f"{base}/{model}/{scenario}/{member}/rsds/catalog.xml")
     item=datasets(run)
     years=sorted({int(x["name"].split("_")[-2]) for x in item if x["name"].endswith(".nc") and x["name"].split("_")[-2].isdigit()})
     result["scenarios"][scenario]["rsds"]={"member":member,"n_years":len(years),"first_year":min(years) if years else None,"last_year":max(years) if years else None,"example":item[:1]}
     print("RSDS_VALID",model,scenario,member,len(years),min(years) if years else None,max(years) if years else None,flush=True)
     break
    except Exception as exc:
     result["errors"].append(f"{scenario}/{member} rsds: {type(exc).__name__}:{exc}")
  except Exception as exc:
   result["errors"].append(f"{scenario} member list: {type(exc).__name__}:{exc}")
   print("ERROR",model,scenario,str(exc),flush=True)
 output.append(result)
(OUT/"nasa_rsds_gcm_discovery.json").write_text(json.dumps({"generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"results":output},ensure_ascii=False,indent=2),encoding="utf8")
valid=[r for r in output if all(k in r["scenarios"] and r["scenarios"][k].get("rsds") for k in ("historical","ssp245","ssp585"))]
print("VALID_MODELS",[(x["model"],{s:x["scenarios"][s]["rsds"]["member"] for s in ("historical","ssp245","ssp585")}) for x in valid],flush=True)
if len(valid)<4:raise RuntimeError(f"Insufficient independent models: {len(valid)}")
