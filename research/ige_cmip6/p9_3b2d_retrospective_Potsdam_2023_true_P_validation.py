#!/usr/bin/env python3
"""P9.3B2D correction of the ORIGINAL frozen Potsdam 2023 station P benchmark.

2023 Potsdam original absolute pressure was falsely classified missing in
P9.3B2C because padded CSV field '   P' was accessed as 'P'. The source
does contain native P: recreate B0/B3/B4 on same original frozen Jan/Jul
2023 with original ERA5 and physical ARCO geopotential. RETROSPECTIVE,
not new independent validation or a station selection.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,io,json,math,statistics,zipfile
from pathlib import Path
import p9_1a_global_historical_backbone as era
from p9_3b2_hypsometric_pressure_model import correct_pressure
from p9_3b2c_arco_original_surface_geopotential_probe import read_arco
from p9_3b2d_dwd_2020_source_pressure_census import fetch,ROOT
STATION={"id":"03987","name":"Potsdam","lat":52.3812,"lon":13.0622,"z":81.}
ARCHIVE="stundenwerte_P0_03987_19750701_20251231_hist.zip"
PERIODS=(("January","2023-01-10","2023-01-16"),("July","2023-07-10","2023-07-16"))
def dates(start):
 d=dt.datetime.fromisoformat(start+"T00:00")
 return [(d+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(168)]
def original_P():
 raw,sha=fetch(ROOT+ARCHIVE,12_000_000)
 slots={name:set(dates(start)) for name,start,end in PERIODS}
 measurements={name:{} for name,_,_ in PERIODS}
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  if z.testzip():raise ValueError("P93B2D_POTSDAM_OLD_ZIP_CORRUPT")
  names=[m for m in z.namelist() if Path(m).name.startswith("produkt_p0_stunde_") and m.endswith(".txt")]
  if len(names)!=1:raise ValueError("P93B2D_POTSDAM_ORIGINAL_MEMBER")
  with io.TextIOWrapper(z.open(names[0]),encoding="latin1") as fp:
   reader=csv.DictReader(fp,delimiter=";")
   raw_header=list(reader.fieldnames or [])
   reader.fieldnames=[f.lstrip("\ufeff").strip() for f in raw_header]
   if not {"P","P0","QN_8","STATIONS_ID","MESS_DATUM"}.issubset(reader.fieldnames):
    raise ValueError("P93B2D_POTSDAM_NORMALIZED_P_FIELDS_MISSING")
   for r in reader:
    rawdt=(r.get("MESS_DATUM") or "").strip()
    try:t=dt.datetime.strptime(rawdt,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
    except ValueError:continue
    n=next((n for n in slots if t in slots[n]),None)
    if n is None:continue
    if int(r["STATIONS_ID"])!=3987:raise ValueError("P93B2D_WRONG_STATION")
    if r["QN_8"].strip() not in ("3","10"):continue
    try:p=float(r["P"])
    except (TypeError,ValueError):continue
    if 450<p<1080:measurements[n][t]=p
 return measurements,{"original_archive_SHA256":sha,
                       "native_header_with_spaces_before_correction":raw_header,
                       "P_is_true_station_pressure":True,
                       "P0_is_sealevel_not_used":True}
def era_provider(start,end,expected=None):
 url=era.request_url(STATION["lat"],STATION["lon"],start,end)
 raw=era.get_original_source(url,timeout=90)
 response,arr,meta=era.parse_source(raw,STATION["lat"],STATION["lon"],start,end)
 c=(float(meta["selected_cell_latitude"]),float(meta["selected_cell_longitude"]))
 if expected and any(abs(a-b)>1e-7 for a,b in zip(c,expected)):
  raise ValueError("P93B2D_ORIGINAL_ERA5_SELECTED_GRID_CHANGED")
 out={}
 for i,t in enumerate(response["hourly"]["time"]):
  x=(arr["surface_pressure"][i],arr["temperature_2m"][i],arr["dew_point_2m"][i])
  if all(v is not None and math.isfinite(float(v)) for v in x):
   out[t]=tuple(float(v) for v in x)
 return out,meta,c
def metric(obs,pred,keys):
 d=[pred[k]-obs[k] for k in keys]
 return {"n":len(d),"MAE_hPa":statistics.fmean(abs(v) for v in d),
         "RMSE_hPa":math.sqrt(statistics.fmean(v*v for v in d)),
         "bias_hPa":statistics.fmean(d)}
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 target,prov=original_P()
 first,meta,coord=era_provider(PERIODS[0][1],PERIODS[0][2])
 ARCO=read_arco({"DE_POTSDAM_ORIGINAL_2023":coord})
 z=float(ARCO["points"]["DE_POTSDAM_ORIGINAL_2023"]["ERA5_ARCO_surface_geopotential_height_m"])
 r={"phase":"P9_3B2D_RETROSPECTIVE_CORRECTED_POTSDAM_ORIGINAL_2023_STATION_PRESSURE",
    "prior_P93B2C_missing_P_claim_SUPERSEDED_by_corrected_parser":True,
    "original_observation_period_PREVIOUSLY_FROZEN_IN_P93B2C":True,
    "not_new_independent_2021_holdout":True,
    "no_model_parameter_fit_to_measured_P":True,
    "native_DWD_original_P_field_source":prov,
    "original_ERA5_ARCO_geopotential":ARCO,
    "production_epw_ready":False,"cases":[]}
 for season,start,end in PERIODS:
  source,metadata,grid=(first,meta,coord) if season=="January" else era_provider(start,end,coord)
  keys=[t for t in dates(start) if t in target[season] and t in source]
  item={"season":season,"original_DWD_measured_station_P_hours":len(target[season]),
        "exact_source_hour_pairs":len(keys),
        "QC_tier":"Original DWD QN_8=3/10, automatic tier includes QN3",
        "ERA5_canonical_weather_sha256":metadata["canonical_hourly_weather_and_selected_cell_sha256"],
        "native_CDS_GRIB_not_byte_verified":True}
  if len(keys)<96:
   item["status"]="SOURCE_FAIL_CLOSED_INSUFFICIENT_HOURLY_PAIR"
  else:
   pred={}
   for k in keys:
    p,T,dp=source[k]
    pred[k]={"B0":p,
       "B3":correct_pressure(p,T,dp,STATION["z"],float(metadata["response_elevation_m_unverified"]),"ISOTHERMAL_VIRTUAL_T"),
       "B4":correct_pressure(p,T,dp,STATION["z"],z,"ISOTHERMAL_VIRTUAL_T")}
   item["metrics"]={m:metric(target[season],{k:pred[k][m] for k in keys},keys)
      for m in ("B0","B3","B4")}
   item["status"]="RETROSPECTIVE_POTS_RECORRECTED_ORIGINAL_STATION_P"
  r["cases"].append(item)
  print("P93B2D_ORIGINAL_2023_POTSDAM_RECORRECTED",json.dumps({
      "season":season,"status":item["status"],"n":len(keys),
      "MAE":{k:round(v["MAE_hPa"],4) for k,v in item.get("metrics",{}).items()}}),flush=True)
 (out/"p9_3b2d_Potsdam_2023_DWD_original_P_retrospective_correction.json").write_text(
     json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 return r
if __name__=="__main__":
 a=argparse.ArgumentParser();a.add_argument("--out",default="outputs/p93b2d-Potsdam-corrected")
 run(Path(a.parse_args().out))
