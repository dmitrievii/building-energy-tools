#!/usr/bin/env python3
"""P9.3B2D SOURCE-ONLY original DWD P availability screen for 2020.

Objective station selection is independent of ANY 2021 original station
pressure and ERA5 prediction errors. Do not touch 2021 pressure fields.
Only source metadata 'available until' dates / original file names
containing 2021 are allowed. No future/holdout pressure is read.
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,io,json,math,re,urllib.request,zipfile
from pathlib import Path
ROOT="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"
ANCHORS=(("Berlin",52.5200,13.4050),("Hamburg",53.5511,9.9937),
("Leipzig",51.3397,12.3731),("Nuremberg",49.4521,11.0767),
("Frankfurt",50.1109,8.6821),("Munich",48.1351,11.5820),
("Cologne",50.9375,6.9603),("Hanover",52.3759,9.7320))
PERIODS=(("January","2020011000","2020011623"),("July","2020071000","2020071623"))
MIN=96
def fetch(url,limit=12_000_000):
 if not url.startswith(ROOT):raise ValueError("P93B2D_INVALID_DWD_SOURCE_URL")
 with urllib.request.urlopen(urllib.request.Request(url,headers={
     "User-Agent":"IGE-P9.3B2D-Original-DWD-StationPressure-SourceOnly/1.0"}),timeout=95) as r:
  data=r.read(limit+1)
 if len(data)>limit:raise ValueError("P93B2D_SOURCE_SIZE_OVER_LIMIT")
 return data,hashlib.sha256(data).hexdigest()
def distance_km(a,b,c,d):
 a,b,c,d=[math.radians(x) for x in (a,b,c,d)]
 q=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
 return 12742*math.asin(min(1,math.sqrt(q)))
def source_catalog():
 raw,sha=fetch(ROOT+"P0_Stundenwerte_Beschreibung_Stationen.txt",900000)
 stations={}
 for line in raw.decode("latin1").splitlines():
  fields=line.split(maxsplit=6)
  if len(fields)<7 or not re.fullmatch(r"\d{5}",fields[0]):continue
  try:
   id,start,end,z,lat,lon=fields[:6]
   item={"id":id,"start":start,"end":end,"z_m":float(z),
       "lat":float(lat),"lon":float(lon),"name":fields[6].strip().split(" "*3)[0].strip()}
  except ValueError:continue
  if item["start"]<="20200110" and item["end"]>="20210716" and -500<item["z_m"]<3500:
   stations[id]=item
 if len(stations)<100:raise ValueError("P93B2D_DWD_STATIONS_METADATA_INCOMPLETE")
 listing,ls_sha=fetch(ROOT,4_000_000)
 matches=re.findall(r"stundenwerte_P0_(\d{5})_(\d{8})_(\d{8})_hist\.zip",
     listing.decode("utf-8",errors="replace"),flags=re.I)
 assets={}
 for id,start,end in matches:
  if id in stations and start<="20200110" and end>="20210716":
   assets.setdefault(id,[]).append((start,end))
 for id,options in assets.items():
  if len(options)!=1:raise ValueError("P93B2D_DWD_SOURCE_ARCHIVE_AMBIGUOUS_"+id)
 chosen=[];seen=set()
 for city,lat,lon in ANCHORS:
  ranked=sorted((distance_km(lat,lon,s["lat"],s["lon"]),s["id"]) for id,s in stations.items() if id in assets)
  for d,id in ranked[:2]:
   if id in seen:continue
   seen.add(id)
   chosen.append({**stations[id],"anchor":city,"distance_to_anchor_km":round(d,2),
      "archive_start":assets[id][0][0],"archive_end":assets[id][0][1]})
 if not chosen or len(chosen)>16:raise ValueError("P93B2D_FIXED_ANCHOR_RANK_INVALID")
 return chosen,{"original_DWD_station_metadata_SHA256":sha,
    "original_DWD_listing_SHA256":ls_sha,"candidate_count":len(chosen),
    "selection_is_metadata_only":True,"anchor_order":[a[0] for a in ANCHORS]}
def count_native_source(id,start,end):
 source=f"stundenwerte_P0_{id}_{start}_{end}_hist.zip"
 raw,sha=fetch(ROOT+source,10_000_000)
 result={period:{"n_original_hours":0,"n_valid_P_QN10":0,"n_valid_P_QN3":0,
     "n_valid_P0_any_QN":0,"n_missing_P":0,"original_QN8_counts":collections.Counter()}
     for period,_,_ in PERIODS}
 with zipfile.ZipFile(io.BytesIO(raw)) as archive:
  if archive.testzip():raise ValueError("P93B2D_DWD_ORIGINAL_ZIP_CRC_BAD")
  members=[x for x in archive.namelist() if Path(x).name.startswith("produkt_p0_stunde_") and x.endswith(".txt")]
  if len(members)!=1:raise ValueError("P93B2D_DWD_ORIGINAL_PRODUCT_MISSING")
  with io.TextIOWrapper(archive.open(members[0]),encoding="latin1") as fh:
   r=csv.DictReader(fh,delimiter=";")
   if not {"STATIONS_ID","MESS_DATUM","P","P0","QN_8"}.issubset(
          {x.strip() for x in r.fieldnames or []}):
    raise ValueError("P93B2D_ORIGINAL_P_FIELD_MISSING")
   for row in r:
    when=(row.get("MESS_DATUM") or "").strip()
    period=next((name for name,lo,hi in PERIODS if lo<=when<=hi),None)
    if period is None:continue
    if int(row["STATIONS_ID"])!=int(id):
     raise ValueError("P93B2D_CROSS_STATION_SOURCE_RECORD")
    o=result[period];o["n_original_hours"]+=1
    q=(row.get("QN_8") or "").strip()
    o["original_QN8_counts"][q]+=1
    try:p=float(row["P"])
    except (TypeError,ValueError):p=float("nan")
    try:p0=float(row["P0"])
    except (TypeError,ValueError):p0=float("nan")
    if 450<p0<1100:o["n_valid_P0_any_QN"]+=1
    if not 450<p<1080:o["n_missing_P"]+=1
    else:
     if q=="10":o["n_valid_P_QN10"]+=1
     if q=="3":o["n_valid_P_QN3"]+=1
 for name in result:
  result[name]["original_QN8_counts"]=dict(result[name]["original_QN8_counts"])
  if result[name]["n_original_hours"]!=168:
   raise ValueError("P93B2D_CENSUS_PERIOD_NOT_168_"+name)
 return result,{"original_station_P_archive":source,"archive_SHA256":sha}
def pick(records,field):
 return next((r for r in records if all(r.get("periods",{}).get(s,{}).get(field,0)>=MIN
       for s,_,_ in PERIODS)),None)
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 chosen,meta=source_catalog()
 rows=[]
 for item in chosen:
  x={"station":item}
  try:
   x["periods"],x["source"]=count_native_source(item["id"],
     item["archive_start"],item["archive_end"])
   x["status"]="SOURCE_ONLY_COMPLETE"
  except Exception as exc:
   x["status"]="SOURCE_UNAVAILABLE"
   x["source_error"]=f"{type(exc).__name__}: {exc}"[:400]
  rows.append(x)
  print("P93B2D_CENSUS_NATIVE_P_2020",json.dumps({"id":item["id"],
    "name":item["name"],"anchor":item["anchor"],"status":x["status"],
    "jan":x.get("periods",{}).get("January"),"jul":x.get("periods",{}).get("July")}),flush=True)
 pick10=pick(rows,"n_valid_P_QN10")
 if pick10:
  selected=pick10;quality="ORIGINAL_DWD_QN8_10"
 else:
  # The automatic-only tier requires exactly original QN8=3 OR original
  # QN8=10; this is source-availability, not source weather skill.
  auto=[{**r,"periods":{name:{**d,
      "n_native_QN3_OR_QN10":d["n_valid_P_QN3"]+d["n_valid_P_QN10"]}
      for name,d in r.get("periods",{}).items()}} for r in rows]
  second=pick(auto,"n_native_QN3_OR_QN10")
  selected=(next(r for r in rows if r["station"]["id"]==second["station"]["id"])
            if second is not None else None)
  quality="ORIGINAL_DWD_QN8_3_OR_10_AUTOMATIC_QC" if selected else "NO_SOURCE_QUALIFIED"
 result={"phase":"P9_3B2D_FROZEN_DWD_2020_NATIVE_PRESSURE_SOURCE_CENSUS",
  "not_read_any_2021_original_pressure_values":True,
  "not_read_any_ERA5_skill_or_predictions":True,
  "selection_predefined_before_source_outcomes":True,
  "source_predefined_anchor_order":list(ANCHORS),
  "source_original_station_metadata":meta,
  "n_predefined_source_candidates":len(rows),
  "candidates":rows,"selection_QC_tier":quality,
  "selected_source_station":selected["station"] if selected else None,
  "selected_source_sha256":selected["source"]["archive_SHA256"] if selected else None,
  "no_fallback_after_2021_holdout":True,
  "2021_holdout_pressures_not_used_for_source_selection":True,
  "production_EPWs_qualified":False}
 outpath=out/"p9_3b2d_frozen_DWD_original_2020_pressure_source_census.json"
 outpath.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B2D_SOURCE_CENSUS_FINAL",json.dumps({"n_candidates":len(rows),
  "selected_station":result["selected_source_station"],"quality":quality,
  "no_2021_original_pressure_read":True}),flush=True)
 return result
if __name__=="__main__":
 ap=argparse.ArgumentParser();ap.add_argument("--out",default="outputs/p93b2d-census")
 run(Path(ap.parse_args().out))
