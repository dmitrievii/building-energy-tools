#!/usr/bin/env python3
"""P9.3B2C independent Potsdam original 2023 DWD absolute pressure holdout.

Model B4 uses authenticated Google ARCO 0.25° ERA5-derived surface geopotential
as orography, original Open-Meteo ERA5-derived pressure as 2m station profile,
and preregistered virtual-temperature hydrostatics. No station P in prediction.
AT/CH 2024 cases are already-seen P9.3B2 retrospective source-only diagnostics,
NOT new independent holdouts.
"""
from __future__ import annotations
import argparse,datetime as dt,csv,hashlib,io,json,math,re,statistics,zipfile
from collections import Counter
from pathlib import Path

import p9_1a_global_historical_backbone as era
from p9_3b2c_arco_original_surface_geopotential_probe import read_arco,get_stations,G
from p9_3b2_hypsometric_pressure_model import correct_pressure
from p9_3b2_original_AT_DE_CH_2024_pressure_validation import (
    obs_AT,obs_CH,PERIODS as OLD_PERIODS,SCHEMAS,metric,
    source_ERA5,_download_DWD_pressure,DWD_PRESS_ROOT,MIN)
STATION_ID="03987"
YEAR=2023
FROZEN=(("January","2023-01-10","2023-01-16"),
        ("July","2023-07-10","2023-07-16"))

def hours(start):
    d=dt.datetime.fromisoformat(start+"T00:00")
    return [(d+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(168)]

def load_potsdam_station_P(original_meta):
    """Unaltered original station-level P; NEVER substitute original P0."""
    listing,listing_sha=_download_DWD_pressure(DWD_PRESS_ROOT,2_500_000)
    versions=sorted(set(re.findall(r"stundenwerte_P0_03987_(\d{8})_(\d{8})_hist\.zip",
                       listing.decode("utf-8",errors="replace"),re.I)))
    matches=[(a,b) for a,b in versions if a<="20230110" and b>="20230716"]
    if len(matches)!=1:
        raise ValueError("P93B2C_DWD_POTSDAM_ORIGINAL_2023_PRESSURE_ZIP_MISSING_OR_AMBIGUOUS")
    a,b=matches[0];filename=f"stundenwerte_P0_03987_{a}_{b}_hist.zip"
    raw,archive_sha=_download_DWD_pressure(DWD_PRESS_ROOT+filename,9_000_000)
    out={n:{"values_final_QC10":{},"values_automatic_QC3":{},
            "source_qn8":Counter(),"n_P_missing":0,"n_P0_present":0}
         for n,_,_ in FROZEN}
    periods={n:set(hours(start)) for n,start,end in FROZEN}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip():raise ValueError("P93B2C_DWD_ORIGINAL_PRESSURE_ZIP_CRC_BAD")
        fname=[x for x in z.namelist() if Path(x).name.startswith("produkt_p0_stunde_") and x.endswith(".txt")]
        if len(fname)!=1:raise ValueError("P93B2C_DWD_NATIVE_PRESSURE_TABLE_MISSING")
        with io.TextIOWrapper(z.open(fname[0]),encoding="latin1") as f:
            reader=csv.DictReader(f,delimiter=";")
            if not {"STATIONS_ID","MESS_DATUM","QN_8","P","P0"}.issubset(
                        {x.strip() for x in reader.fieldnames or []}):
                raise ValueError("P93B2C_DWD_PRESSURE_FIELDS_NOT_CERTIFIED")
            for r in reader:
                key=(r["MESS_DATUM"] or "").strip()
                try:tt=dt.datetime.strptime(key,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
                except ValueError:continue
                name=next((n for n in periods if tt in periods[n]),None)
                if name is None:continue
                if int(r["STATIONS_ID"])!=3987:raise ValueError("P93B2C_DWD_OTHER_STATION")
                q=int(r["QN_8"]);out[name]["source_qn8"][str(q)]+=1
                txt=(r.get("P") or "").strip()
                sea=(r.get("P0") or "").strip()
                try:
                    if 450<float(sea)<1100:out[name]["n_P0_present"]+=1
                except ValueError:pass
                try:p=float(txt)
                except (ValueError,TypeError):
                    out[name]["n_P_missing"]+=1;continue
                if not 450<p<1100:out[name]["n_P_missing"]+=1;continue
                if q==10:
                    out[name]["values_final_QC10"][tt]=p
                elif q==3:
                    out[name]["values_automatic_QC3"][tt]=p
    for n in out:
        out[n]["source_qn8"]=dict(out[n]["source_qn8"])
        out[n]["station_original_ZIP_SHA256"]=archive_sha
        out[n]["source_listing_SHA256"]=listing_sha
        out[n]["source_filename"]=filename
    return out

def original_era5(lat,lon,start,end,expected_grid=None):
    url=era.request_url(lat,lon,start,end)
    raw=era.get_original_source(url,timeout=95)
    obj,values,meta=era.parse_source(raw,lat,lon,start,end)
    grid=(meta["selected_cell_latitude"],meta["selected_cell_longitude"])
    if expected_grid is not None and any(abs(a-b)>1e-6 for a,b in zip(grid,expected_grid)):
        raise ValueError("P93B2C_SOURCE_SELECTED_GRID_DIFFERS_FROM_ARCO_ORIGINAL_Z")
    if not (0<=float(obj["elevation"])<4000):
        raise ValueError("P93B2C_ERA5_PROVIDER_GRID_HEIGHT_MISSING")
    dataset={}
    for i,t in enumerate(obj["hourly"]["time"]):
        p=values["surface_pressure"][i]
        T=values["temperature_2m"][i]
        dp=values["dew_point_2m"][i]
        if any(v is None or not math.isfinite(v) for v in (p,T,dp)):continue
        dataset[t]=(float(p),float(T),float(dp))
    return dataset,meta

def _predictions(src,station_height,ARCO_grid_z,SRTM_grid_z,provider_z):
    p,t,td=src
    # Both the verified surface field and the OpenMeteo input are ERA5-
    # derived REMAPPED sources. Their coupling is still a source hypothesis.
    return {
        "B0_unmodified_OM_ERA5_surface_p":
            p,
        "B1_SRTM90_isothermal":
            correct_pressure(p,t,td,station_height,SRTM_grid_z,"ISOTHERMAL_VIRTUAL_T"),
        "B2_SRTM90_fixed_lapse":
            correct_pressure(p,t,td,station_height,SRTM_grid_z,"FIXED_LAPSE_0065_SENSITIVITY"),
        "B3_OM_returned_height_sensitivity":
            correct_pressure(p,t,td,station_height,provider_z,"ISOTHERMAL_VIRTUAL_T"),
        "B4_ARCO_ERA5_surface_z_geopotential_height":
            correct_pressure(p,t,td,station_height,ARCO_grid_z,"ISOTHERMAL_VIRTUAL_T")
    }

def evaluate(year,country,season,station_obs,orig_era5,grid_z,station_z,dem_grid_z,provider_z):
    keys=sorted(set(station_obs)&set(orig_era5))
    result={"country":country,"season":season,"year":year,
            "n_original_observed_pressure_hours":len(station_obs),
            "n_common_station_QC_and_ERA5_hours":len(keys),"min_pairs":MIN,
            "original_station_reference":"Measured true station-level absolute P, not sea-level P0",
            "source_pressure_orography_z_m":grid_z,"station_altitude_m":station_z}
    if len(keys)<MIN:
        result["status"]="INSUFFICIENT_ORIGINAL_QFE_STATION_PRESSURE"
        result["metrics"]={}
        return result
    fields={key:_predictions(orig_era5[key],station_z,grid_z,dem_grid_z,provider_z)
            for key in keys}
    methods=tuple(fields[keys[0]].keys())
    results={m:metric(station_obs,{key:fields[key][m] for key in keys},keys) for m in methods}
    result["status"]="ORIGINAL_STATION_PRESSURE_EVALUATED"
    result["metrics"]=results
    ref=results["B0_unmodified_OM_ERA5_surface_p"]["MAE_hPa"]
    result["delta_MAE_B4_minus_B0_hPa"]=results["B4_ARCO_ERA5_surface_z_geopotential_height"]["MAE_hPa"]-ref
    result["delta_MAE_B4_minus_B3_hPa"]=(
        results["B4_ARCO_ERA5_surface_z_geopotential_height"]["MAE_hPa"]-
        results["B3_OM_returned_height_sensitivity"]["MAE_hPa"])
    return result

def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    report={"phase":"P9_3B2C_ORIGINAL_ARCO_ERA5_SURFACE_GEOPOTENTIAL_REF_DE_POTSDAM_2023",
      "fresh_heldout":"DE Potsdam 03987 January and July 2023",
      "other_AT_CH_2024_cases_posthoc_already_seen_only":True,
      "native_CDS_original_GRIB_verified":False,
      "original_data_kind":"ARCO ERA5-derived remapped 0.25deg z, OM ERA5-derived p",
      "native_CanESM5_gcm_pressure_qualified":False,
      "production_epw_ready":False,"cells":[]}
    station=get_stations()
    report["DWD_Potsdam_source_metadata"]=station
    # Query provider station coordinate FIRST, then the authentic ARCO
    # original 0.25deg z at that exact returned grid (no guessed grid).
    lat,lon=station["lat"],station["lon"]
    e0,src0=original_era5(lat,lon,FROZEN[0][1],FROZEN[0][2])
    degrid=(src0["selected_cell_latitude"],src0["selected_cell_longitude"])
    points={"AT_2024_OLD":(47.,15.5),"CH_2024_OLD":(46.75,9.75),
            "DE_NEW_2023_POTSDAM":degrid}
    # One same-source ARCO geopotential harvest for all locations.
    aero=read_arco(points)
    report["ARCO_original_geopotential_source"]=aero
    report["DE_source_OpenMeteo_grid_2023_Jan"]={
       "latlon":list(degrid),"original_ERA5_weather_canonical_SHA":src0["canonical_hourly_weather_and_selected_cell_sha256"],
       "model_source":"OpenMeteo ERA5-derived, not CDS native GRIB",
       "provider_grid_elevation_m_unverified":src0["response_elevation_m_unverified"]}
    from p9_3b2_original_AT_DE_CH_2024_pressure_validation import source_ERA5
    # Fixed German station meta z; station pressure must not influence it.
    zstation=station["station_height_m"]
    # External SRTM90 at the TRUE OM point (not guessed rounded latlon).
    import urllib.parse,urllib.request
    uri="https://api.opentopodata.org/v1/srtm90m?"+urllib.parse.urlencode({
        "locations":f"{degrid[0]:.6f},{degrid[1]:.6f}"})
    with urllib.request.urlopen(urllib.request.Request(uri,headers={
        "User-Agent":"IGE-P93B2C-DE-2023-Terrain-Source/1.0"}),timeout=40) as response:
        raw=response.read(15000)
    terrain=json.loads(raw)
    if terrain.get("status")!="OK" or len(terrain.get("results",[]))!=1:
        raise ValueError("P93B2C_DE_ERA5_GRID_SRTM_TERRAIN_UNAVAILABLE")
    zSRTM=float(terrain["results"][0]["elevation"])
    report["DE_original_SRTM90_geographic_center_source"]={
        "elevation_m":zSRTM,"original_response_SHA256":hashlib.sha256(raw).hexdigest(),
        "ERA5_GRID_CENTER_IS_NOT_NATIVE_ERA5_OROGRAPHY":True}
    originalP=load_potsdam_station_P(station)
    for season,start,end in FROZEN:
        observed=originalP[season]
        forecast,metas=(e0,src0) if season==FROZEN[0][0] else original_era5(lat,lon,start,end,degrid)
        zARCO=aero["points"]["DE_NEW_2023_POTSDAM"]["ERA5_ARCO_surface_geopotential_height_m"]
        dev=evaluate(YEAR,"DE",season,observed["values_final_QC10"],
                 forecast,zARCO,zstation,zSRTM,float(metas["response_elevation_m_unverified"]))
        dev["station_original_P_QC10_count"]=len(observed["values_final_QC10"])
        dev["station_original_P_QC3_count"]=len(observed["values_automatic_QC3"])
        dev["native_source_QN8_histogram"]=observed["source_qn8"]
        dev["DWD_original_P_QFE_source_SHA"]=observed["station_original_ZIP_SHA256"]
        dev["original_station_level_P_from_ZIP_not_P0"]=True
        dev["original_ERA5_source_hourly_SHA"]=metas["canonical_hourly_weather_and_selected_cell_sha256"]
        # Predeclared automatic-only P QC3 sensitivity, never silently
        # substitute for final-QC10 heldout primary.
        if observed["values_automatic_QC3"]:
            diagnostic=evaluate(YEAR,"DE",season,observed["values_automatic_QC3"],
                            forecast,zARCO,zstation,zSRTM,float(metas["response_elevation_m_unverified"]))
            dev["automatic_only_QC3_diagnostic_not_primary"]=diagnostic
        report["cells"].append(dev)
        print("P93B2C_GENUINE_DE_POTSDAM_2023",json.dumps({
            "season":season,"status":dev["status"],
            "n_final_QC10":dev["station_original_P_QC10_count"],
            "n_automatic_QC3":dev["station_original_P_QC3_count"],
            "MAE":{m:round(a["MAE_hPa"],3) for m,a in dev["metrics"].items() if a}}),flush=True)
    # Existing AT/CH 2024 were examined in P9.3B2. New B4 is a
    # retrospective scientific ORIGINS DIAGNOSTIC, not additional holdout.
    for country,fetch in (("AT",obs_AT),("CH",obs_CH)):
        original_metadata,observations=fetch()
        cfg=SCHEMAS[country]
        zARCO=aero["points"][country+"_2024_OLD"]["ERA5_ARCO_surface_geopotential_height_m"]
        for season,start,end in OLD_PERIODS:
            pred,source=source_ERA5(country,season,start,end)
            # Source_ERA5 returns model B0+other models, NOT primitive p,T,dp.
            # Need genuinely original 12-variable hourly ERA5 source.
            grid,metas=original_era5(*cfg["requested_coords"],start,end,
                                     cfg["selected_grid"])
            row=evaluate(2024,country,season,observations[season]["values"],
                          grid,zARCO,cfg["z_station_m"],
                          cfg["SRTM90_grid_z_m"],float(metas["response_elevation_m_unverified"]))
            row["independent_holdout"]=False
            row["source_original_station_P_SHA"]=observations[season]["original_sha256"]
            report["cells"].append(row)
            print("P93B2C_PREVIOUSLY_SEEN_AT_CH_DIAGNOSTIC",json.dumps({
                "country":country,"season":season,
                "B4_MAE":row["metrics"].get(
                    "B4_ARCO_ERA5_surface_z_geopotential_height",{}).get("MAE_hPa")}),flush=True)
    held=[x for x in report["cells"] if x["country"]=="DE"]
    report["DE_2023_new_source_pressure_final_QC10_site_seasons_scored"]=sum(
       x["status"]=="ORIGINAL_STATION_PRESSURE_EVALUATED" for x in held)
    report["n_DE_2023_new_source_final_QC10_original_pressure_hours"]=sum(
       x.get("n_common_station_QC_and_ERA5_hours",0) for x in held)
    report["source_H_ARCO_geopotential_not_model_native_CDS_grid"]=True
    report["scientific_pressure_reference_qualified_AT_DE_CH"]=False
    result=out/"p93b2c_original_ERA5_surface_geopotential_and_DE_pressure_validation.json"
    result.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P93B2C_FINAL",json.dumps({
       "new_DE_scored":report["DE_2023_new_source_pressure_final_QC10_site_seasons_scored"],
       "DE_original_pressure_hours":report["n_DE_2023_new_source_final_QC10_original_pressure_hours"],
       "ARCO_source_points":len(aero["points"]),
       "full_native_CDS_ERA5_orography_claim":False,
       "production":False}),flush=True)
    return report
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2c-full")
    args=p.parse_args();run(Path(args.out))
