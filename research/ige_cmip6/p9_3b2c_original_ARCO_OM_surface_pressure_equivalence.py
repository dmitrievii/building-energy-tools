#!/usr/bin/env python3
"""P9.3B2C source-reference cross-product test (NOT station-skill tuning).

Does actual 0.25° ARCO ERA5-derived surface pressure p relate to Open-Meteo
'models=era5' 0.25° selected grid surface pressure at identical UTC hours?
Fixed AT Graz, CH Davos, DE Potsdam 2023 Jan10+Jul10 00:00 UTC. Also
independently audit why registered original DWD Potsdam P had zero QC pairs.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,io,json,math,re,zipfile
from pathlib import Path
import p9_1a_global_historical_backbone as era
from p9_3b2c_arco_original_surface_geopotential_probe import ARCO,G,get_stations
from p9_3b2c_original_geopotential_and_Potsdam_2023_pressure_validation import (
    DWD_PRESS_ROOT,_download_DWD_pressure)
FIXED={"AT_GRAZ":(47.0800,15.448056,(47.0,15.5)),
       "CH_DAVOS":(46.812969,9.843558,(46.75,9.75))}
HOURS=(("2023-01-10","00:00"),("2023-07-10","00:00"))
def equivalent_pressure_original():
 import xarray as xr
 ds=xr.open_zarr(ARCO,consolidated=True,chunks=None,storage_options={"token":"anon"})
 try:
  if "surface_pressure" not in ds.data_vars:
   raise ValueError("P93B2C_ORIGINAL_ARCO_SURFACE_PRESSURE_ABSENT")
  da=ds["surface_pressure"]
  if set(da.dims)!={"time","latitude","longitude"} or "level" in da.dims:
   raise ValueError("P93B2C_P_NOT_GENUINE_SURFACE_PRESSURE")
  units=str(da.attrs.get("units","")).lower().strip()
  if units not in ("pa","pascal","pascals"):raise ValueError("P93B2C_ARCO_SURFACE_P_UNITS_NOT_PA_"+units)
  station=get_stations()
  coords={**FIXED,"DE_POTSDAM":(station["lat"],station["lon"],None)}
  matched=[]
  for location,(lat,lon,guess) in coords.items():
   for day,h in HOURS:
    url=era.request_url(lat,lon,day,day)
    raw=era.get_original_source(url,timeout=85)
    response,arrays,meta=era.parse_source(raw,lat,lon,day,day)
    cell=(meta["selected_cell_latitude"],meta["selected_cell_longitude"])
    if guess and any(abs(a-b)>1e-6 for a,b in zip(cell,guess)):
     raise ValueError("P93B2C_ERA5_SELECTED_GRID_CHANGED")
    when=day+"T"+h
    if response["hourly"]["time"][0]!=when:
     raise ValueError("P93B2C_SOURCE_UTC_LABEL_NOT_00")
    native=float(da.sel(latitude=cell[0],longitude=cell[1],time=when,
                        method="nearest").values)
    om=float(arrays["surface_pressure"][0])*100
    if not 40000<native<110000 or not 40000<om<110000:
     raise ValueError("P93B2C_ARCO_OR_OM_SOURCE_P_NONPHYSICAL")
    case={"place":location,"timeUTC":when,
          "grid_cell_latlon":list(cell),
          "original_ARCO_ERA5_remapped_surface_pressure_Pa":native,
          "original_OpenMeteo_ERA5_derived_surface_pressure_Pa":om,
          "original_source_difference_OM_minus_ARCO_hPa":(om-native)/100,
          "OpenMeteo_canonical_source_SHA":meta["canonical_hourly_weather_and_selected_cell_sha256"],
          "OpenMeteo_returned_elevation_m":meta["response_elevation_m_unverified"],
          "ARCO_remapped_0p25_NOT_native_CDS_GRIB":True}
    print("P93B2C_ARCO_OM_NATIVE_PRESSURE_REFERENCE",json.dumps(case),flush=True)
    matched.append(case)
  return {"n_same_hour_same_grid_cases":len(matched),
          "MAE_two_ERA5_derived_pressure_source_products_hPa":sum(abs(x["original_source_difference_OM_minus_ARCO_hPa"]) for x in matched)/len(matched),
          "max_abs_cross_source_pressure_difference_hPa":max(abs(x["original_source_difference_OM_minus_ARCO_hPa"]) for x in matched),
          "surface_p_variable_attrs":{k:str(v)[:150] for k,v in da.attrs.items() if k in ("units","standard_name","long_name")},
          "original_matched_cases":matched,
          "source_grid_equivalence_NOT_native_CDS_GRIB_certification":True}
 finally:ds.close()
def dwd_missingness():
 station=get_stations()
 listing,listing_sha=_download_DWD_pressure(DWD_PRESS_ROOT,2_500_000)
 matching=sorted(set(re.findall(r"stundenwerte_P0_03987_(\d{8})_(\d{8})_hist\.zip",listing.decode("utf-8",errors="replace"),re.I)))
 suitable=[(a,b) for a,b in matching if a<="20230110" and b>="20230716"]
 if len(suitable)!=1:raise ValueError("P93B2C_REGISTERED_POTSDAM_SOURCE_ZIP_CHANGED")
 a,b=suitable[0]
 fname=f"stundenwerte_P0_03987_{a}_{b}_hist.zip"
 raw,sha=_download_DWD_pressure(DWD_PRESS_ROOT+fname,9_000_000)
 period={name:(start.replace("-","")+"00",end.replace("-","")+"23")
      for name,start,end in (("January","2023-01-10","2023-01-16"),
                             ("July","2023-07-10","2023-07-16"))}
 result={"original_station":"Potsdam 03987","native_source_ZIP_sha256":sha,
         "source_filename":fname,"native_field_P_IS_abs_pressure_station":True,
         "native_field_P0_IS_reduced_sealevel_NOT_USED":True,"seasons":{}}
 for season in period:
  result["seasons"][season]={"n_native_hours":0,"QN8_histogram":{},"P_native_empty_or_sentinel":0,
    "P0_native_empty_or_sentinel":0,"P_valid_observation_hours":0}
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  if z.testzip():raise ValueError("P93B2C_POTSDAM_NATIVE_ZIP_CRC_FAILED")
  members=[p for p in z.namelist() if Path(p).name.startswith("produkt_p0_stunde_") and p.lower().endswith(".txt")]
  if len(members)!=1:raise ValueError("P93B2C_POTSDAM_NATIVE_MEMBER_MISSING")
  with io.TextIOWrapper(z.open(members[0]),encoding="latin1") as fp:
   reader=csv.DictReader(fp,delimiter=";")
   if not {"P","P0","QN_8","MESS_DATUM"}.issubset({x.strip() for x in reader.fieldnames or []}):
    raise ValueError("P93B2C_DWD_ABS_AND_SEALEVEL_COLS_UNAVAILABLE")
   for row in reader:
    day=(row.get("MESS_DATUM") or "").strip()
    season=next((s for s,(start,end) in period.items() if start<=day<=end),None)
    if season is None:continue
    r=result["seasons"][season];r["n_native_hours"]+=1
    q=(row.get("QN_8") or "").strip();r["QN8_histogram"][q]=r["QN8_histogram"].get(q,0)+1
    for field,attr in (("P","P_native_empty_or_sentinel"),("P0","P0_native_empty_or_sentinel")):
     val=(row.get(field) or "").strip()
     try:okay=450<float(val)<1100
     except (TypeError,ValueError):okay=False
     if not okay:r[attr]+=1
     if field=="P" and okay:r["P_valid_observation_hours"]+=1
 for k,v in result["seasons"].items():
  if v["n_native_hours"]!=168:raise ValueError("P93B2C_POTSDAM_NATIVE_HOUR_COUNT_INCOMPLETE")
  print("P93B2C_DWD_POTSDAM_SOURCE_MISSINGNESS",k,json.dumps(v),flush=True)
 return result
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 obj={"phase":"P9_3B2C_ORIGINAL_SAME_GRID_PRESSURE_REFERENCE_AND_HELDOUT_DWD_CAUSAL_DIAGNOSTIC",
      "NO_new_station_model_calibration":True,"production_epw_ready":False}
 for title,fn in (("same_grid_ARCO_OpenMeteo_original_surface_pressure",equivalent_pressure_original),
                  ("DWD_Potsdam_2023_original_absolute_pressure_missingness",dwd_missingness)):
  try:obj[title]=fn();obj[title]["source_status"]="VERIFIED"
  except Exception as exc:
   obj[title]={"source_status":"BLOCKED","reason":f"{type(exc).__name__}: {exc}"[:600]}
   print("P93B2C_SECONDARY_SOURCE_AUDIT_BLOCKED",title,obj[title]["reason"],flush=True)
 (out/"p93b2c_original_samegrid_surface_pressure_and_DWD_2023_source_audit.json").write_text(
    json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B2C_REFERENCE_SOURCE_FINAL",json.dumps({
  "ARCO_OM_pressure_cross_source":obj["same_grid_ARCO_OpenMeteo_original_surface_pressure"]["source_status"],
  "DWD_original_P_missingness":obj["DWD_Potsdam_2023_original_absolute_pressure_missingness"]["source_status"]}),flush=True)
 return obj
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2c-srccross")
 run(Path(p.parse_args().out))
