#!/usr/bin/env python3
"""P9.3B2C original remapped 0.25deg ERA5 surface geopotential z + DWD metadata.

Never substitute geopotential on pressure levels. Never claim native CDS GRIB
byte identity or ERA5 native spectral orography from 0.25deg ARCO regrid.
No new heldout original station P measurements read in this step.
"""
from __future__ import annotations
import argparse,hashlib,json,math,re,urllib.request
from pathlib import Path
G=9.80665
ARCO="gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
DWD_META="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/P0_Stundenwerte_Beschreibung_Stationen.txt"
FIXED={"AT":(47.,15.5),"CH":(46.75,9.75),"DE_2024_DEVELOPMENT":(47.5,10.25)}
def get_stations():
 req=urllib.request.Request(DWD_META,headers={"User-Agent":"IGE-P9.3B2C-source-metadata-before-2023-pressure/1.0"})
 with urllib.request.urlopen(req,timeout=75) as reply:raw=reply.read(800_000)
 if len(raw)>=800_000:raise ValueError("P93B2C_DWD_METADATA_TOO_LARGE")
 rows=[line for line in raw.decode("latin1").splitlines() if
       re.match(r"^\s*03987\s",line)]
 if len(rows)!=1:raise ValueError("P93B2C_REGISTERED_POTSDAM_STATION_MISSING")
 fields=rows[0].split(maxsplit=6)
 if len(fields)<6 or fields[0]!="03987":raise ValueError("P93B2C_POTSDAM_SOURCE_ID_INVALID")
 _,start,end,z,lat,lon=fields[:6]
 if not (start<="20230110" and end>="20230716"):raise ValueError("P93B2C_POTSDAM_2023_NOT_IN_METADATA")
 station={"station_id":"03987","source_station_record":rows[0],
       "source_raw_SHA256":hashlib.sha256(raw).hexdigest(),
       "station_height_m":float(z),"lat":float(lat),"lon":float(lon)}
 if not (30<station["station_height_m"]<200 and 50<station["lat"]<55 and 10<station["lon"]<16):
  raise ValueError("P93B2C_POTSDAM_EXPECTED_GEOGRAPHY_INVALID")
 print("P93B2C_FROZEN_NEW_DE_STATION_SOURCE",json.dumps(station),flush=True)
 return station
def read_arco(points):
 import xarray as xr
 import numpy as np
 ds=xr.open_zarr(ARCO,consolidated=True,chunks=None,storage_options={"token":"anon"})
 try:
  candidates=[v for v in ds.data_vars if v in ("geopotential_at_surface","surface_geopotential","geopotential")]
  if len(candidates)!=1 or candidates[0]!="geopotential_at_surface":
   raise ValueError("P93B2C_ORIGINAL_SURFACE_Z_MISSING_OR_AMBIGUOUS_"+str(candidates))
  da=ds[candidates[0]]
  if any(d not in ("time","latitude","longitude") for d in da.dims):
   raise ValueError("P93B2C_SURFACE_Z_IS_PRESSURE_LEVEL_OR_OTHER_DIMENSION_"+repr(da.dims))
  units=str(da.attrs.get("units","")).replace(" ","").lower()
  if units not in ("m2s-2","m**2s**-2","m^2s^-2","m2/s2","m**2/s**2","m2s^-2"):
   raise ValueError("P93B2C_GEOPOTENTIAL_UNITS_NOT_M2_S_2_"+str(da.attrs.get("units")))
  result={"arco_dataset":ARCO,"original_ARCO_variable":candidates[0],
      "original_variable_units":da.attrs.get("units"),
      "source_kind":"ECMWF_ERA5_DERIVED_REMAPPED_0p25_REGULAR_ZARR_NOT_NATIVE_CDS_GRIB",
      "selected_static_ERA5_surface_geopotential_as_orography":True,
      "raw_native_ERA5_CDS_geopotential_GRIB_verified":False,
      "source_dataset_attrs":{k:str(v)[:220] for k,v in ds.attrs.items()
                             if k in ("valid_time_start","valid_time_stop","source","title","institution")},
      "variable_attrs":{k:str(v)[:200] for k,v in da.attrs.items()
                       if k in ("long_name","standard_name","units","shortName","GRIB_paramId")},
      "points":{}}
  for name,(lat,lon) in points.items():
   selected=da.sel(latitude=lat,longitude=lon,method="nearest")
   xla=float(selected.latitude.values);xlo=float(selected.longitude.values)
   if abs(xla-lat)>1e-6 or abs((xlo-lon+180)%360-180)>1e-6:
    raise ValueError("P93B2C_ARCO_GRID_CENTER_DIFFERS_FROM_OPENMETEO_SELECTED")
   if "time" in selected.dims:
    a=selected.sel(time="2023-01-10T00:00:00",method="nearest")
    b=selected.sel(time="2023-07-10T00:00:00",method="nearest")
    z1=float(a.values);z2=float(b.values)
    if abs(z1-z2)>1e-3:raise ValueError("P93B2C_ERA5_STATIC_SURFACE_Z_NOT_STATIC_2023")
   else:
    z1=float(selected.values);z2=z1
   if not math.isfinite(z1) or not -1000<z1/G<5500:
    raise ValueError("P93B2C_ORIGINAL_ARCO_Z_NONPHYSICAL")
   result["points"][name]={"lat":lat,"lon":lon,
       "surface_geopotential_m2s2":z1,"ERA5_ARCO_surface_geopotential_height_m":z1/G,
       "static_original_ERA5_surface_z_Jan_Jul_consistent":abs(z1-z2)<1e-3}
   print("P93B2C_ORIGINAL_ERA5_SURFACE_GEOPOTENTIAL",name,
         json.dumps(result["points"][name]),flush=True)
  return result
 finally:ds.close()
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 report={"phase":"P93B2C_ORIGINAL_ERA5_0p25_SURFACE_GEOPOTENTIAL_RECOVERY_PROBE",
  "source_normalized_geopotential_g0":G,
  "no_heldout_2023_station_P_observations_read":True,
  "no_production_pressure_qualification":True}
 try:
  station=get_stations();report["frozen_DE_Potsdam_station_original_metadata"]=station
  # Open-Meteo closest regular grid is independently verified at the next
  # step before comparing these ARCO scalar cell values to provider p.
  lat=round(station["lat"]*4)/4
  lon=round(station["lon"]*4)/4
  points={**FIXED,"DE_NEW_2023_POTSDAM_EXPECTED_NEAREST":(lat,lon)}
  report["arco"]=read_arco(points)
  report["status"]="ORIGINAL_ARCO_SURFACE_GEOPOTENTIAL_0p25_FIELDS_READ"
 except Exception as e:
  report["status"]="ORIGINAL_SURFACE_GEOPOTENTIAL_OR_STATION_META_NOT_RECOVERED"
  report["reason"]=f"{type(e).__name__}: {e}"[:800]
  print("P93B2C_SOURCE_PROBE_BLOCKED",report["reason"],flush=True)
 (out/"p93b2c_original_arco_ERA5_surface_geopotential_and_Potsdam_metadata.json").write_text(
    json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B2C_METADATA_PROBE_FINAL",json.dumps({
    "status":report["status"],"native_grid_CDS_GRIB_verified":False,
    "points":list(report.get("arco",{}).get("points",{}))}),flush=True)
 return report
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2c-source")
 run(Path(p.parse_args().out))
