#!/usr/bin/env python3
"""P9.3B2 one metadata-only original pressure source and DEM discovery.

No 2024 hourly pressure observations read here. Source schemas before a
registered original-observation pressure holdout, never inspect scores.
"""
from __future__ import annotations
import json,hashlib,urllib.request,urllib.parse,re,io,csv
from pathlib import Path
import p9_1b_geosphere_original_station_holdouts as geo
import p8_1e_swiss_external as swiss
import p9_1a_global_historical_backbone as era

DWD_P="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"
DEM="https://api.opentopodata.org/v1/srtm90m"
SITES={"AT":(47.0707,15.4395),"DE":(47.408,10.280),"CH":(46.801,9.830)}
def fetch(url,limit=6_000_000):
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.3B2-Pressure-Science-Metadata/1.0"})
    with urllib.request.urlopen(req,timeout=45) as r:
        raw=r.read(limit+1)
    if len(raw)>limit:raise ValueError("P93B2_PROBE_RESPONSE_TOO_LARGE")
    return raw,hashlib.sha256(raw).hexdigest()
def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    r={"stage":"P93B2_PRESSURE_SCHEMA_AND_GEOMETRY_ONLY","no_2024_station_observation_hours_read":True,
       "no_model_skill_scored":True,"data":{}}
    try:
        meta,sha=geo.source_json(geo.BASE+"/metadata")
        s=next(x for x in meta["stations"] if int(x["id"])==30)
        ps=[{k:x.get(k) for k in ("name","unit","description","long_name") if k in x}
            for x in meta["parameters"] if re.search("druck|pressure|^p\\d?|_flag",str(x),re.I)]
        r["data"]["AT"]={"status":"METADATA_READ","original_sha":sha,
            "station":{k:s.get(k) for k in ("id","name","lat","lon","altitude")},
            "pressure_parameter_candidates":ps[:85]}
        print("P93B2_SCHEMA_AT",json.dumps(r["data"]["AT"]),flush=True)
    except Exception as e:
        r["data"]["AT"]={"status":"METADATA_BLOCKED","reason":str(e)[:400]}
    try:
        raw,sha=fetch(DWD_P+"P0_Stundenwerte_Beschreibung_Stationen.txt",1_000_000)
        station=[x for x in raw.decode("latin1").splitlines() if re.match(r"^\s*03730\s",x)]
        listing,sha_listing=fetch(DWD_P,3_000_000)
        names=sorted(set(re.findall(r"stundenwerte_P0_03730_[0-9]{8}_[0-9]{8}_hist\.zip",listing.decode("utf8",errors="replace"),re.I)))
        r["data"]["DE"]={"status":"PRESSURE_METADATA_READ","meta_sha":sha,
             "listing_sha":sha_listing,"station_metadata_lines":station[:3],"pressure_zip_assets":names[:4]}
        print("P93B2_SCHEMA_DE",json.dumps(r["data"]["DE"]),flush=True)
    except Exception as e:r["data"]["DE"]={"status":"METADATA_BLOCKED","reason":str(e)[:400]}
    try:
        raw,sha=swiss.fetch("https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv",max_bytes=12_000_000)
        stations,cols=swiss.parse_meta(raw)
        station=stations["DAV"]
        url="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/dav/ogd-smn_dav_h_historical_2020-2029.csv"
        request=urllib.request.Request(url,headers={"User-Agent":"IGE-P93B2-Swiss-header-probe/1.0","Range":"bytes=0-8000"})
        with urllib.request.urlopen(request,timeout=55) as fh:
            chunk=fh.read(8192)
        header=chunk.splitlines()[0].decode("utf-8-sig",errors="replace")
        r["data"]["CH"]={"status":"METADATA_AND_HOURLY_CSV_HEADER_READ","original_station_sha":sha,
            "station":station,"station_csv_url":url,"columns":header.split(";")[:180],
            "header_sample_sha":hashlib.sha256(chunk).hexdigest()}
        print("P93B2_SCHEMA_CH",json.dumps(r["data"]["CH"]),flush=True)
    except Exception as e:r["data"]["CH"]={"status":"METADATA_BLOCKED","reason":str(e)[:400]}
    # DEM at selected 0.25-degree Open-Meteo nearest ERA5 grid coordinates,
    # NEVER confuse station-site terrain with the grid column surface.
    try:
        grids={"AT":(47.0,15.5),"DE":(47.5,10.25),"CH":(46.75,9.75)}
        pointlist="|".join(f"{la:.6f},{lo:.6f}" for la,lo in grids.values())
        raw,sha=fetch(DEM+"?"+urllib.parse.urlencode({"locations":pointlist}),90000)
        obj=json.loads(raw)
        if obj.get("status")!="OK" or len(obj.get("results",[]))!=3:
            raise ValueError("P93B2_ORIGINAL_SRTM_GRID_HEIGHT_MISSING")
        r["ERA5_grid_center_SRTM90"]={"source":"OpenTopoData SRTM90m","sha256":sha,
            "by_country":{country:{"requested_grid_latlon":list(grids[country]),
                  "elevation_m":obj["results"][j]["elevation"]}
                  for j,country in enumerate(grids)}}
        print("P93B2_DEM_GRID",json.dumps(r["ERA5_grid_center_SRTM90"]),flush=True)
    except Exception as e:
        r["ERA5_grid_center_SRTM90"]={"status":"BLOCKED","reason":str(e)[:300]}
    for country,(lat,lon) in SITES.items():
        try:
            url=era.request_url(lat,lon,"2024-01-10","2024-01-10")
            raw=era.get_original_source(url,timeout=55)
            orig,arr,meta=era.parse_source(raw,lat,lon,"2024-01-10","2024-01-10")
            r["data"].setdefault(country,{})["ERA5_provider_grid"]={
              "source_canonical_sha":meta.get("canonical_hourly_weather_and_selected_cell_sha256"),
              "actual_grid_latlon":[meta.get("selected_cell_latitude"),meta.get("selected_grid_longitude",meta.get("selected_cell_longitude"))],
              "response_elevation":orig.get("elevation"),
              "actual_ERA5_model_surface_geopotential_height_available":False}
            print("P93B2_ERA5_GEOMETRY",country,json.dumps(r["data"][country]["ERA5_provider_grid"]),flush=True)
        except Exception as e:
            r["data"].setdefault(country,{})["ERA5_provider_grid"]={"status":"BLOCKED","reason":str(e)[:270]}
    try:
        pointlist="|".join(f"{la:.6f},{lo:.6f}" for la,lo in SITES.values())
        raw,sha=fetch(DEM+"?"+urllib.parse.urlencode({"locations":pointlist}),90000)
        d=json.loads(raw)
        r["DEM_reference_request"]={"source":"OpenTopoData SRTM90m public API",
            "sha256":sha,"status":d.get("status"),"results":d.get("results"),
            "warning":"At requested station coordinates only; ERA5 grid elevations separately require query at selected source grid"}
        print("P93B2_SRTM90_REFERENCE",json.dumps(r["DEM_reference_request"]),flush=True)
    except Exception as e:r["DEM_reference_request"]={"status":"BLOCKED","reason":str(e)[:320]}
    p=out/"p9_3b2_station_pressure_source_schema_probe.json"
    p.write_text(json.dumps(r,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    return r
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2-schema")
 run(p.parse_args().out)
