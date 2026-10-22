#!/usr/bin/env python3
"""IGE P9.3B2D 2021 GERMAN independently held out pressure source test.

Station chosen ONLY by precommitted 2020 native DWD P availability protocol,
registered original census workflow #39743327312, NOT 2021 P observations
or ERA5 skill. No fallback if 2021 DWD source is not sufficient. Absolute P
hPa (never P0) vs raw Open-Meteo ERA5 grid p and external z/g correction.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,io,json,math,statistics,zipfile,hashlib
from pathlib import Path
import p9_1a_global_historical_backbone as era
from p9_3b2_hypsometric_pressure_model import correct_pressure
from p9_3b2c_arco_original_surface_geopotential_probe import read_arco
from p9_3b2d_dwd_2020_source_pressure_census import fetch,ROOT,MIN
FROZEN_CENSUS_RUN_ID=39743327312
FROZEN_SITE_ID="00433"
FROZEN_STATION="Berlin-Tempelhof"
FROZEN_STATION_COORD=(52.4676,13.402)
FROZEN_STATION_ALT=48.
YEAR=2021
WINDOWS=(("January","2021-01-10","2021-01-16"),
         ("July","2021-07-10","2021-07-16"))
def expected_times(start):
 first=dt.datetime.fromisoformat(start+"T00:00")
 return [(first+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
  for i in range(168)]
def load_registered_source_census(path):
 data=json.loads(Path(path).read_text())
 if (data.get("phase")!="P9_3B2D_FROZEN_DWD_2020_NATIVE_PRESSURE_SOURCE_CENSUS"
   or not data.get("not_read_any_2021_original_pressure_values")
   or data.get("selected_source_station",{}).get("id")!=FROZEN_SITE_ID
   or data.get("selection_QC_tier")!="ORIGINAL_DWD_QN8_3_OR_10_AUTOMATIC_QC"):
  raise ValueError("P93B2D_2021_HOLDOUT_SELECTED_SOURCE_NOT_FROZEN_2020")
 site=data["selected_source_station"]
 if abs(site["z_m"]-FROZEN_STATION_ALT)>.1 or any(
    abs(a-b)>1e-6 for a,b in zip((site["lat"],site["lon"]),FROZEN_STATION_COORD)):
  raise ValueError("P93B2D_2021_STATION_META_CHANGED_FROM_CENSUS")
 if not data.get("selected_source_sha256"):
  raise ValueError("P93B2D_SELECTED_SOURCE_SHA_MISSING")
 return site,data
def source_2021_absolute_P(site,registered):
 filename="stundenwerte_P0_{id}_{archive_start}_{archive_end}_hist.zip".format(**site)
 raw,digest=fetch(ROOT+filename,12_000_000)
 if digest!=registered["selected_source_sha256"]:
  raise ValueError("P93B2D_2021_RETRIEVED_ORIGINAL_STATION_ZIP_SHA_CHANGED")
 result={s:{"P_QN3_or_QN10":{},"original_QN_8_histogram":{},
           "n_raw_2021_hours":0,"n_P0_present":0,"n_P_missing":0}
         for s,start,end in WINDOWS}
 slots={s:set(expected_times(start)) for s,start,end in WINDOWS}
 with zipfile.ZipFile(io.BytesIO(raw)) as arc:
  if arc.testzip() is not None:raise ValueError("P93B2D_ORIGINAL_DWD_ZIP_BAD_CRC")
  members=[s for s in arc.namelist() if Path(s).name.startswith("produkt_p0_stunde_")
      and s.endswith(".txt")]
  if len(members)!=1:raise ValueError("P93B2D_DWD_EXPECTED_ONE_CSV_MEMBER")
  with io.TextIOWrapper(arc.open(members[0]),encoding="latin1") as fh:
   rdr=csv.DictReader(fh,delimiter=";")
   raw_header=list(rdr.fieldnames or [])
   rdr.fieldnames=[s.lstrip("\ufeff").strip() if s else s for s in raw_header]
   if not {"MESS_DATUM","STATIONS_ID","P","P0","QN_8"}.issubset(set(rdr.fieldnames)):
    raise ValueError("P93B2D_PRESSURE_CSV_ORIGINAL_FIELDS_INVALID")
   for row in rdr:
    native_time=(row.get("MESS_DATUM") or "").strip()
    try:time=dt.datetime.strptime(native_time,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
    except ValueError:continue
    period=next((name for name in slots if time in slots[name]),None)
    if period is None:continue
    if int(row["STATIONS_ID"])!=int(FROZEN_SITE_ID):
     raise ValueError("P93B2D_UNEXPECTED_DWD_STATION_IN_SOURCE")
    cell=result[period];cell["n_raw_2021_hours"]+=1
    qn=(row.get("QN_8") or "").strip()
    cell["original_QN_8_histogram"][qn]=cell["original_QN_8_histogram"].get(qn,0)+1
    try:p0=float(row["P0"])
    except (TypeError,ValueError):p0=float("nan")
    if 450<p0<1100:cell["n_P0_present"]+=1
    try:p=float(row["P"])
    except (TypeError,ValueError):p=float("nan")
    if not 450<p<1080:
     cell["n_P_missing"]+=1;continue
    if qn in ("3","10"):
     if time in cell["P_QN3_or_QN10"]:
      raise ValueError("P93B2D_DUPLICATE_SOURCE_HOUR")
     cell["P_QN3_or_QN10"][time]=p
 for cell in result.values():
  if cell["n_raw_2021_hours"]!=168:
   raise ValueError("P93B2D_FROZEN_HELDOUT_DWD_HOURS_MISSING")
 return result,{"original_DWD_ZIP_SHA":digest,"original_archive_name":filename,
   "header_before_whitespace_normalization":raw_header,
   "selected_station_from_2020_only":FROZEN_SITE_ID,
   "original_absolute_station_pressure_field":"P",
   "reduced_sealevel_field_P0_never_used_as_target":True}
def source_ERA5_original(st,start,end,expected_grid=None):
 lat,lon=st["lat"],st["lon"]
 request=era.request_url(lat,lon,start,end)
 raw=era.get_original_source(request,timeout=90)
 original,series,meta=era.parse_source(raw,lat,lon,start,end)
 coord=(float(meta["selected_cell_latitude"]),float(meta["selected_cell_longitude"]))
 if expected_grid is not None and any(abs(a-b)>1e-7 for a,b in zip(expected_grid,coord)):
  raise ValueError("P93B2D_SOURCE_OPENMETEO_GRID_CHANGED_BETWEEN_MONTHS")
 out={}
 for i,time in enumerate(original["hourly"]["time"]):
  p=series["surface_pressure"][i]
  temp=series["temperature_2m"][i]
  dp=series["dew_point_2m"][i]
  if any(a is None or not math.isfinite(float(a)) for a in (p,temp,dp)):continue
  out[time]=(float(p),float(temp),float(dp))
 return out,meta,coord
def score(obs,model,keys):
 errs=[model[t]-obs[t] for t in keys]
 return {"n":len(errs),"MAE_hPa":statistics.fmean(abs(e) for e in errs),
  "RMSE_hPa":math.sqrt(statistics.fmean(e*e for e in errs)),
  "bias_hPa":statistics.fmean(errs)}
def run(source_only_census,out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 station,selection=load_registered_source_census(source_only_census)
 # The selected station is now immutable. No 2021 P values read until
 # original 2020-only source selection is validated.
 originalP,station_prov=source_2021_absolute_P(station,selection)
 era1,meta1,cell1=source_ERA5_original(station,WINDOWS[0][1],WINDOWS[0][2])
 ar=read_arco({"DE_BERLIN_TEMPELHOF":cell1})
 z0=float(ar["points"]["DE_BERLIN_TEMPELHOF"]["ERA5_ARCO_surface_geopotential_height_m"])
 if abs(z0-float(meta1["response_elevation_m_unverified"]))>1:
  raise ValueError("P93B2D_ARCO_GEOPOTENTIAL_VS_PROVIDER_HEIGHT_MORE_THAN_1_M")
 res={"phase":"IGE_P9_3B2D_PRESPECIFIED_GERMANY_DWD_2021_NEW_QFE_HOLDOUT",
      "source_selection_census_run_id":FROZEN_CENSUS_RUN_ID,
      "source_only_selection_preceded_any_2021_pressure_read":True,
      "selected_station":station,
      "selected_2020_QC_tier":selection["selection_QC_tier"],
      "original_P_source_lineage":station_prov,
      "native_ARCO_ERA5_geopotential_ref":ar,
      "temperature_vapor_inputs_ERA5_not_observed_station":True,
      "source_station_P_not_used_for_model_calibration":True,
      "source_reduced_P0_not_used":True,
      "no_fallback_site_year_season":True,
      "production_EPWs_qualified":False,
      "cells":[]}
 for season,start,end in WINDOWS:
  observed=originalP[season]
  forecast,meta,grid=(era1,meta1,cell1) if season=="January" else source_ERA5_original(station,start,end,cell1)
  if abs(z0-float(meta["response_elevation_m_unverified"]))>1:
   raise ValueError("P93B2D_ERA5_PROVIDER_ALTITUDE_CROSS_SOURCE_DRIFT")
  pairs=[time for time in expected_times(start) if time in observed["P_QN3_or_QN10"] and time in forecast]
  item={"season":season,"status":"BLOCKED_INSUFFICIENT_SOURCE_PRESSURE" if len(pairs)<MIN else "INDEPENDENT_ORIGINAL_SOURCE_P_SCORED",
        "n_native_2021_QC_pressure_hours":len(observed["P_QN3_or_QN10"]),
        "n_exact_common_ERA5_DWD_QC_hours":len(pairs),
        "native_2021_QN8_histogram":observed["original_QN_8_histogram"],
        "model_ERA5_original_canonical_SHA":meta["canonical_hourly_weather_and_selected_cell_sha256"],
        "source_OpenMeteo_returned_model_elevation_m":meta["response_elevation_m_unverified"],
        "source_ARCO_surface_geopotential_height_m":z0,
        "original_GCM_CanESM5_ps_not_used_or_certified":True}
  if len(pairs)>=MIN:
   predict={}
   for t in pairs:
    p,T,dp=forecast[t]
    predict[t]={"B0_original_grid_pressure_hPa":p,
      "B3_hypsometric_ERA5_provider_height_hPa":correct_pressure(
         p,T,dp,station["z_m"],float(meta["response_elevation_m_unverified"]),"ISOTHERMAL_VIRTUAL_T"),
      "B4_hypsometric_ARCO_zdivg_hPa":correct_pressure(
         p,T,dp,station["z_m"],z0,"ISOTHERMAL_VIRTUAL_T")}
   item["metrics"]={method:score(observed["P_QN3_or_QN10"],
       {t:predict[t][method] for t in pairs},pairs)
       for method in next(iter(predict.values()))}
   item["delta_MAE_B4_minus_B0_hPa"]=(
      item["metrics"]["B4_hypsometric_ARCO_zdivg_hPa"]["MAE_hPa"]-
      item["metrics"]["B0_original_grid_pressure_hPa"]["MAE_hPa"])
   item["delta_MAE_B4_minus_B3_hPa"]=(
      item["metrics"]["B4_hypsometric_ARCO_zdivg_hPa"]["MAE_hPa"]-
      item["metrics"]["B3_hypsometric_ERA5_provider_height_hPa"]["MAE_hPa"])
  res["cells"].append(item)
  print("P93B2D_NEW_GERMAN_2021_TRUE_ABSOLUTE_PRESSURE",json.dumps({
   "season":season,"status":item["status"],"n":len(pairs),
   "original_QN8":item["native_2021_QN8_histogram"],
   "MAE":{m:round(a["MAE_hPa"],4) for m,a in item.get("metrics",{}).items()}}),flush=True)
 res["n_independent_pressure_2021_season_scored"]=sum(
    x["status"]=="INDEPENDENT_ORIGINAL_SOURCE_P_SCORED" for x in res["cells"])
 res["n_2021_original_pressure_QC_hours_on_support"]=sum(
    x["n_exact_common_ERA5_DWD_QC_hours"] for x in res["cells"])
 res["pressure_historical_model_fit_qualified_in_this_single_site"]=(
    res["n_independent_pressure_2021_season_scored"]==2)
 res["pressure_AT_DE_CH_multi_site_generalization_qualified"]=False
 (out/"p9_3b2d_Germany_2021_original_station_P_independent_holdout.json").write_text(
   json.dumps(res,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B2D_GERMANY_2021_PRESSURE_FINAL",json.dumps({
    "selected_original_station":FROZEN_SITE_ID,
    "n_scored_season":res["n_independent_pressure_2021_season_scored"],
    "n_original_h":res["n_2021_original_pressure_QC_hours_on_support"],
    "independent_skill_Germany_one_source":res["pressure_historical_model_fit_qualified_in_this_single_site"],
    "production":False}),flush=True)
 return res
if __name__=="__main__":
 ap=argparse.ArgumentParser()
 ap.add_argument("--census-json",required=True)
 ap.add_argument("--out",default="outputs/p93b2d-2021-pressure")
 a=ap.parse_args()
 run(a.census_json,a.out)
