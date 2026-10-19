#!/usr/bin/env python3
"""P9.3B2 genuine original station pressure, preregistered AT DE CH 2024.

Independent station level absolute pressure measured by official GeoSphere
'p', DWD 'P' (not P0), and MeteoSwiss 'prestah0' (not pp0qffh0).
ERA5 grid pressure and ERA5 physical density are independent predictions.
SRTM90 at ERA5 nominal grid point is *not* native ERA5 geopotential height.
No observed station p used in model, parameter selection, altitude offset
fitting, or source pressure calibration. All failures fail closed per cell.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,io,json,math,re,statistics,urllib.request,zipfile
from collections import Counter
from pathlib import Path
import p9_1b_geosphere_original_station_holdouts as at
import p8_1e_swiss_external as ch
import p9_1a_global_historical_backbone as era
from p9_3b2_hypsometric_pressure_model import evaluate_methods,correct_pressure
PERIODS=(("January","2024-01-10","2024-01-16"),
         ("July","2024-07-10","2024-07-16"))
SCHEMAS={
 "AT":{"station":"Graz Universität","station_id":30,"z_station_m":366.0,
       "requested_coords":(47.0800,15.448056),"selected_grid":(47.0,15.5),
       "SRTM90_grid_z_m":332.0,"SRTM90_ref_sha":"814dbcdafa7f9f9ea4f62a6219406e7fd821bb7f6a001bb174da5085bf20f1ad",
       "expected_provider_grid_z_m":467.0},
 "DE":{"station":"Oberstdorf","station_id":3730,"z_station_m":806.0,
       "requested_coords":(47.3984,10.2759),"selected_grid":(47.5,10.25),
       "SRTM90_grid_z_m":862.0,"SRTM90_ref_sha":"814dbcdafa7f9f9ea4f62a6219406e7fd821bb7f6a001bb174da5085bf20f1ad",
       "expected_provider_grid_z_m":1182.0},
 "CH":{"station":"Davos","station_id":"DAV","z_station_m":1594.0,
       "requested_coords":(46.812969,9.843558),"selected_grid":(46.75,9.75),
       "SRTM90_grid_z_m":1995.0,"SRTM90_ref_sha":"814dbcdafa7f9f9ea4f62a6219406e7fd821bb7f6a001bb174da5085bf20f1ad",
       "expected_provider_grid_z_m":1999.0}
}
DWD_PRESS_ROOT="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"
MIN=96
def times(start):
 start=dt.datetime.fromisoformat(start+"T00:00")
 return [(start+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(168)]
def obs_AT():
 meta,sha=at.source_json(at.BASE+"/metadata")
 s=next(s for s in meta["stations"] if int(s["id"])==30)
 params={x["name"]:x for x in meta["parameters"]}
 if {k:params[k]["unit"] for k in ("p","p_flag") }!={"p":"hPa","p_flag":"code"}:
  raise ValueError("P93B2_AT_NATIVE_STATION_ABSOLUTE_PRESSURE_ID_OR_UNITS_MISSING")
 if abs(float(s["altitude"])-366)>0.6:
  raise ValueError("P93B2_AT_STATION_ELEVATION_METADATA_DRIFT")
 result={}
 for name,st,en in PERIODS:
  import urllib.parse
  url=at.BASE+"?"+urllib.parse.urlencode({"parameters":"p,p_flag","station_ids":"30",
       "start":st+"T00:00Z","end":en+"T23:00Z","output_format":"geojson"})
  response,digest=at.source_json(url)
  timestamp=[dt.datetime.fromisoformat(str(x).replace("Z","+00:00")).astimezone(
      dt.timezone.utc).strftime("%Y-%m-%dT%H:%M") for x in response["timestamps"]]
  if timestamp!=times(st):raise ValueError("P93B2_AT_ORIGINAL_UTC_HOUR_AXIS_MISMATCH")
  valid={};qc=Counter()
  for feature in response["features"]:
   station=feature["properties"].get("station")
   sid=int(station["id"] if isinstance(station,dict) else station)
   if sid!=30:raise ValueError("P93B2_AT_OTHER_OR_DUPLICATE_STATION")
   p=feature["properties"]["parameters"]
   if p["p"].get("unit")!="hPa":raise ValueError("P93B2_AT_STATION_P_UNIT_DRIFT")
   z=p["p"]["data"];q=p["p_flag"]["data"]
   if len(z)!=168 or len(q)!=168:raise ValueError("P93B2_AT_ORIGINAL_ARRAY_SHORT")
   for t,v,f in zip(timestamp,z,q):
    qc[str(f)]+=1
    if v is not None and f in at.GOOD_FLAGS:
     v=float(v)
     if 450<v<1080 and math.isfinite(v):valid[t]=v
  result[name]={"values":valid,"original_sha256":digest,
       "native_QC":dict(qc),"QC_tier":"GeoSphere original p_flag accepted 10,11,12,20,21,22",
       "source_variable":"p station-level hPa not pred"}
 return {"station_metadata_SHA":sha,"station_height_m":float(s["altitude"])},result
def _download_DWD_pressure(url,max_bytes=9_000_000):
 from urllib.parse import urlsplit
 u=urlsplit(url)
 if u.hostname!="opendata.dwd.de" or not u.path.startswith(
       "/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"):
  raise ValueError("P93B2_DWD_UNTRUSTED_SOURCE")
 with urllib.request.urlopen(urllib.request.Request(url,
     headers={"User-Agent":"IGE-P93B2-original-DWD-station-QFE"}),timeout=85) as fh:
  raw=fh.read(max_bytes+1)
 if len(raw)>max_bytes:raise ValueError("P93B2_DWD_SOURCE_OVER_LIMIT")
 return raw,hashlib.sha256(raw).hexdigest()
def obs_DE():
 md,md_sha=_download_DWD_pressure(DWD_PRESS_ROOT+"P0_Stundenwerte_Beschreibung_Stationen.txt",900000)
 stations=[s for s in md.decode("latin1").splitlines() if re.match(r"^\s*03730\s",s)]
 if len(stations)!=1:raise ValueError("P93B2_DWD_ORIGINAL_PRESSURE_STATION_METADATA")
 station=stations[0].split(maxsplit=6)
 if abs(float(station[3])-806)>1:raise ValueError("P93B2_DWD_PRESS_STATION_HEIGHT_CHANGED")
 listing,ls_sha=_download_DWD_pressure(DWD_PRESS_ROOT,2_000_000)
 assets=sorted(set(re.findall(r"stundenwerte_P0_03730_(\d{8})_(\d{8})_hist\.zip",
                             listing.decode("utf-8",errors="replace"),re.I)))
 selected=[(a,b) for a,b in assets if a<="20240110" and b>="20240716"]
 if len(selected)!=1:raise ValueError("P93B2_DWD_ORIGINAL_2024_PRESSURE_ZIP_AMBIGUOUS")
 start,end=selected[0]
 raw,source_sha=_download_DWD_pressure(DWD_PRESS_ROOT+f"stundenwerte_P0_03730_{start}_{end}_hist.zip",8_000_000)
 result={name:{"values":{},"original_sha256":source_sha,"native_QC":Counter(),
      "QC_tier":"DWD QN_8=10 fully QC, QN_8=3 automatic QC qualified separately",
      "source_variable":"P original pressure station hPa NOT P0 sea-level"} for name,_,_ in PERIODS}
 date_sets={name:set(times(st)) for name,st,en in PERIODS}
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  if z.testzip():raise ValueError("P93B2_DWD_PRESSURE_ZIP_CRC_INVALID")
  member=[s for s in z.namelist() if Path(s).name.startswith("produkt_p0_stunde_") and s.endswith(".txt")]
  if len(member)!=1:raise ValueError("P93B2_DWD_PRODUCT_P0_MEMBER_MISSING")
  with io.TextIOWrapper(z.open(member[0]),encoding="latin1") as fp:
   reader=csv.DictReader(fp,delimiter=";")
   columns=set(k.strip() for k in (reader.fieldnames or ()))
   if not {"MESS_DATUM","STATIONS_ID","QN_8","P","P0"}.issubset(columns):
    raise ValueError("P93B2_DWD_EXPECTED_TRUE_STATION_P_AND_P0_SEALEVEL_COLUMNS_MISSING_"+str(columns))
   for row in reader:
    stamp=(row.get("MESS_DATUM") or "").strip()
    try:t=dt.datetime.strptime(stamp,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
    except ValueError:continue
    n=next((name for name in date_sets if t in date_sets[name]),None)
    if n is None:continue
    if int(row["STATIONS_ID"])!=3730:raise ValueError("P93B2_DWD_INCORRECT_STATION")
    qc=int(row["QN_8"]);result[n]["native_QC"][str(qc)]+=1
    if qc not in (3,10):continue
    value=(row.get("P") or "").strip()
    try:v=float(value)
    except ValueError:continue
    if 450<v<1080:
     if t in result[n]["values"]:raise ValueError("P93B2_DWD_DUPLICATE_P_HOUR")
     result[n]["values"][t]=v
 for x in result.values():x["native_QC"]=dict(x["native_QC"])
 return {"station_metadata_SHA":md_sha,"listing_SHA":ls_sha,
         "station_height_m":float(station[3])},result
def obs_CH():
 stations_raw,sha_meta=ch.fetch("https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv",
                    max_bytes=12_000_000)
 stations,_=ch.parse_meta(stations_raw)
 s=stations["DAV"]
 if abs(s["hoehe_m"]-1594)>1:raise ValueError("P93B2_CH_STATION_HEIGHT_METADATA_DRIFT")
 url="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/dav/ogd-smn_dav_h_historical_2020-2029.csv"
 data,sha=ch.fetch(url,max_bytes=160_000_000)
 rows,columns=ch.decode_csv(data)
 key=ch.pick_col(columns,"prestah0")
 sea=ch.pick_col(columns,"pp0qffh0","pp0qnhh0")
 stamp=ch.pick_col(columns,"reference_timestamp")
 if not key or not sea or not stamp:
  raise ValueError("P93B2_CH_ORIGINAL_STATION_QFE_OR_QFF_SOURCE_COLUMNS_MISSING")
 date_sets={name:set(times(st)) for name,st,en in PERIODS}
 result={name:{"values":{},"original_sha256":sha,"native_QC":{},
       "QC_tier":"Swiss published original 1h OGD; equivalent per-sample QN not available",
       "source_variable":"prestah0 QFE hourly hPa NOT pp0qffh0 sea-level",
       "timestamp_semantics":"UTC END of preceding hour; nominal and preregistered -1h diagnostics"} for name,_,_ in PERIODS}
 for row in rows:
  if (row.get("station_abbr") or "").strip().upper()!="DAV":
   raise ValueError("P93B2_CH_SOURCE_OTHER_STATION")
  ts=(row.get(stamp) or "").strip()
  try: t=dt.datetime.strptime(ts,"%d.%m.%Y %H:%M").strftime("%Y-%m-%dT%H:%M")
  except ValueError:continue
  n=next((name for name in date_sets if t in date_sets[name]),None)
  if n is None:continue
  rawval=(row.get(key) or "").strip()
  if rawval in ("","-","NaN","-999","-9999"):continue
  try:p=float(rawval)
  except ValueError:continue
  if 450<p<1080:
   if t in result[n]["values"]:raise ValueError("P93B2_CH_DUPLICATE_UTC_STATION_HOUR")
   result[n]["values"][t]=p
 return {"station_metadata_SHA":sha_meta,"station_height_m":s["hoehe_m"]},result
def source_ERA5(country,season,start,end):
 cfg=SCHEMAS[country]
 lat,lon=cfg["requested_coords"]
 url=era.request_url(lat,lon,start,end)
 raw=era.get_original_source(url,timeout=90)
 obj,arr,meta=era.parse_source(raw,lat,lon,start,end)
 returned=(meta["selected_cell_latitude"],meta["selected_cell_longitude"])
 if any(abs(a-b)>1e-5 for a,b in zip(returned,cfg["selected_grid"])):
  raise ValueError("P93B2_ERA5_GRID_LATLON_DIFFERENT_FROM_PREREGISTERED_SOURCE")
 altitude=float(meta["response_elevation_m_unverified"])
 if abs(altitude-cfg["expected_provider_grid_z_m"])>1:
  raise ValueError("P93B2_OPENMETEO_GRID_ELEVATION_METADATA_DRIFT")
 times_=obj["hourly"]["time"]
 forecast={}
 for i,t in enumerate(times_):
  p=arr["surface_pressure"][i];T=arr["temperature_2m"][i];dp=arr["dew_point_2m"][i]
  if any(v is None or not math.isfinite(v) for v in (p,T,dp)):continue
  methods=evaluate_methods(p,T,dp,cfg["z_station_m"],cfg["SRTM90_grid_z_m"])
  # A *separately labelled* source-service height sensitivity, NOT ERA5
  # native geopotential validation or scientifically selected winner.
  methods["B3_OPENMETEO_PROVIDER_ELEVATION_SENSITIVITY_hPa"]=correct_pressure(
    p,T,dp,cfg["z_station_m"],altitude,"ISOTHERMAL_VIRTUAL_T")
  forecast[t]=methods
 return forecast,{"canonical_ERA5_grid_weather_SHA":meta["canonical_hourly_weather_and_selected_cell_sha256"],
     "raw_provider_SHA":meta["raw_original_response_sha256"],
     "provider_grid_z_m_UNVERIFIED_NATIVE_OROGRAPHY":altitude,
     "selected_ERA5_grid":list(returned),
     "SRTM90_grid_center_z_m":cfg["SRTM90_grid_z_m"],
     "original_provider_grid_height_different_from_SRTM_proxy":altitude!=cfg["SRTM90_grid_z_m"]}
def metric(obs,pred,keys):
 errs=[pred[t]-obs[t] for t in keys]
 if len(errs)<MIN:return None
 return {"n":len(errs),"MAE_hPa":statistics.fmean(abs(e) for e in errs),
  "RMSE_hPa":math.sqrt(statistics.fmean(e*e for e in errs)),
  "bias_hPa":statistics.fmean(errs)}
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 data={"phase":"P9_3B2_2024_INDEPENDENT_STATION_ABSOLUTE_PRESSURE_AT_DE_CH",
  "preregistered_observation_windows":PERIODS,"units":"hPa",
  "fixed_original_station_QFE_source":True,"sea_level_reduced_pressure_NOT_USED":True,
  "source_ERA5_grid_elevation_NOT_proved_native_orography":True,
  "SRTM90_natural_terrain_vs_ERA5_model_effective_surface_height_NOT_proved_same":True,
  "B3_provider_elevation_only_an_extra_source_semantics_sensitivity_preobservations":True,
  "station_pressure_NOT_USED_in_model_prediction_or_parameter_calibration":True,
  "n_nominal_original_station_pressure_site_hours":1008,
  "min_native_pressure_QC_hours_per_cell":MIN,
  "no_climate_future_pressure_projection_inferred":True,
  "production_epw_ready":False,
  "source":{},"cells":[]}
 for country,func in (("AT",obs_AT),("DE",obs_DE),("CH",obs_CH)):
  try:
   station_meta,periods=func()
   data["source"][country]={"status":"ORIGINAL_STATION_QFE_OBTAINED",
       **station_meta,"site":SCHEMAS[country]}
  except Exception as exc:
   reason=f"{type(exc).__name__}: {exc}"[:650]
   print("P93B2_SOURCE_STATION_BLOCKED",country,reason,flush=True)
   data["source"][country]={"status":"SOURCE_BLOCKED","reason":reason}
   for season,st,en in PERIODS:
    data["cells"].append({"country":country,"season":season,"status":"SOURCE_BLOCKED",
       "n_QC_source_pressure_hours":0,"reason":reason})
   continue
  for season,st,en in PERIODS:
   observed=periods[season]
   row={"country":country,"station":SCHEMAS[country]["station"],
        "season":season,"n_expected_hours":168,
        "n_QC_source_pressure_hours":len(observed["values"]),
        "station_pressure_original_SHA":observed["original_sha256"],
        "station_level_pressure_field":observed["source_variable"],
        "station_pressure_native_QC_histogram":observed["native_QC"],
        "station_pressure_QC_tier":observed["QC_tier"]}
   try:
    pred,source=source_ERA5(country,season,st,en)
    row["source_ERA5_provenance"]=source
    keys=[t for t in times(st) if t in observed["values"] and t in pred]
    row["n_identical_QC_source_hours"]=len(keys)
    row["height_station_minus_SRTM90_source_grid_m"]=(SCHEMAS[country]["z_station_m"]-
                                              SCHEMAS[country]["SRTM90_grid_z_m"])
    row["height_station_minus_provider_grid_z_m"]=(SCHEMAS[country]["z_station_m"]-
                                              SCHEMAS[country]["expected_provider_grid_z_m"])
    methods=next(iter(pred.values())).keys()
    row["metrics"]={m:metric(observed["values"],{t:pred[t][m] for t in keys},keys)
        for m in methods}
    row["status"]="INDEPENDENT_ORIGINAL_STATION_ABSOLUTE_PRESSURE_SCORED" if len(keys)>=MIN else "INSUFFICIENT_STATION_QC_ORIGINAL_PRESSURE"
    if row["status"].startswith("INDEPENDENT"):
     b0=row["metrics"]["B0_UNCHANGED_ERA5_GRID_hPa"]["MAE_hPa"]
     row["delta_MAE_B1_minus_B0_hPa"]=row["metrics"]["B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa"]["MAE_hPa"]-b0
     row["delta_MAE_B2_minus_B0_hPa"]=row["metrics"]["B2_FIXED_LAPSE_SENSITIVITY_hPa"]["MAE_hPa"]-b0
     row["delta_MAE_B3_minus_B0_hPa"]=row["metrics"]["B3_OPENMETEO_PROVIDER_ELEVATION_SENSITIVITY_hPa"]["MAE_hPa"]-b0
    # Swiss OGD hour-end semantics: original registered 1-hour diagnostic
    # only. Never choose the better timestamp after observing skill.
    if country=="CH" and row["status"].startswith("INDEPENDENT"):
     shifted={t:observed["values"].get(
         (dt.datetime.fromisoformat(t)+dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
          for t in times(st)}
     shifted={t:v for t,v in shifted.items() if v is not None}
     shift_keys=[t for t in times(st) if t in shifted and t in pred]
     row["Swiss_end_hour_shift_minus_1h_sensitivity"]={m:metric(
        shifted,{t:pred[t][m] for t in shift_keys},shift_keys) for m in methods}
   except Exception as e:
    row["status"]="ERA5_SOURCE_OR_MODEL_BLOCKED";row["reason"]=f"{type(e).__name__}: {e}"[:650]
   data["cells"].append(row)
   print("P93B2_INDEPENDENT_PRESSURE_RESULT",json.dumps({
       "country":country,"season":season,"status":row["status"],
       "n_QC":row["n_QC_source_pressure_hours"],
       "n_identical_hours":row.get("n_identical_QC_source_hours",0),
       "B0_MAE":row.get("metrics",{}).get("B0_UNCHANGED_ERA5_GRID_hPa",{}).get("MAE_hPa") if row.get("metrics",{}).get("B0_UNCHANGED_ERA5_GRID_hPa") else None,
       "B1_MAE":row.get("metrics",{}).get("B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa",{}).get("MAE_hPa") if row.get("metrics",{}).get("B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa") else None,
       "B2_MAE":row.get("metrics",{}).get("B2_FIXED_LAPSE_SENSITIVITY_hPa",{}).get("MAE_hPa") if row.get("metrics",{}).get("B2_FIXED_LAPSE_SENSITIVITY_hPa") else None,
       "B3_MAE":row.get("metrics",{}).get("B3_OPENMETEO_PROVIDER_ELEVATION_SENSITIVITY_hPa",{}).get("MAE_hPa") if row.get("metrics",{}).get("B3_OPENMETEO_PROVIDER_ELEVATION_SENSITIVITY_hPa") else None
   }),flush=True)
 scored=[x for x in data["cells"] if x["status"]=="INDEPENDENT_ORIGINAL_STATION_ABSOLUTE_PRESSURE_SCORED"]
 data["n_registered_original_cells"]=6
 data["n_scored_original_cells"]=len(scored)
 data["n_source_original_pressure_hours_on_common_support"]=sum(x["n_identical_QC_source_hours"] for x in scored)
 data["n_B1_better_than_B0"]=sum(x["delta_MAE_B1_minus_B0_hPa"]<0 for x in scored)
 data["n_B1_worse_than_B0"]=sum(x["delta_MAE_B1_minus_B0_hPa"]>0 for x in scored)
 data["n_B3_better_than_B0"]=sum(x["delta_MAE_B3_minus_B0_hPa"]<0 for x in scored)
 for m in ("B0_UNCHANGED_ERA5_GRID_hPa","B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa",
           "B2_FIXED_LAPSE_SENSITIVITY_hPa","B3_OPENMETEO_PROVIDER_ELEVATION_SENSITIVITY_hPa"):
  data.setdefault("macros_unweighted_independent_site_season_MAE_hPa",{})[m]=(
    statistics.fmean(x["metrics"][m]["MAE_hPa"] for x in scored) if scored else None)
 (out/"p9_3b2_2024_original_station_absolute_pressure_validation.json").write_text(
     json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
 print("P93B2_ORIGINAL_STATION_PRESSURE_FINAL",json.dumps({
  "cases":len(scored),"source_hours":data["n_source_original_pressure_hours_on_common_support"],
  "B1_better":data["n_B1_better_than_B0"],"B1_worse":data["n_B1_worse_than_B0"],
  "B3_better":data["n_B3_better_than_B0"],"macro_MAE":data["macros_unweighted_independent_site_season_MAE_hPa"],
  "release":False}),flush=True)
 return data
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2-original-pressure")
 run(Path(p.parse_args().out))
