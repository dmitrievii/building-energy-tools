#!/usr/bin/env python3
"""IGE P9.1E: REAL ARCO ERA5 0.25 degree geopotential tied to Open-Meteo selected cells.

A matching LAT/LON of an ARCO-regridded ERA5 geopotential field and a
provider-selected 0.25 degree ERA5 weather cell is spatial correspondence;
it does NOT by itself prove providers used the same regridding algorithm or
model orography. Never infer height from Open-Meteo elevation=nan (often 0).
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import numpy as np

import p9_1a_global_historical_backbone as era
import p9_1d_native_orography_dem as n320
import p9_1b_geosphere_original_station_holdouts as station

ARCO_REGULAR="gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
PARAM_NAME="geopotential_at_surface"
G0=9.80665
ORO_TIME="2021-01-10T00:00:00"
CHECK_TIME="2021-07-10T00:00:00"
EXCLUDED_PREVIOUS_SITE_IDS=frozenset((30,39,196,119,14305,28,17005,66,184))
LOWLAND_TARGETS={
    "Vienna":(48.249,16.356),
    "Linz":(48.300,14.300),
    "Salzburg":(47.803,13.043),
    "Klagenfurt":(46.624,14.305),
    "Bregenz":(47.503,9.746),
    "Eisenstadt":(47.842,16.525),
}
GLOBAL_PROBES={
    "Graz":(47.0707,15.4395),
    "Singapore":(1.3521,103.8198),
    "LaPaz":(-16.5000,-68.1500),
    "Reykjavik":(64.1466,-21.9426),
    "Riyadh":(24.7136,46.6753),
}


def select_new_stations(meta):
    """Deterministic geography-only site selection, before temperature retrieval."""
    catalog=meta.get("stations",[])
    if not isinstance(catalog,list):raise ValueError("P9E_SOURCE_STATION_METADATA_MISSING")
    chosen={}
    used=set()
    for label,(lat,lon) in LOWLAND_TARGETS.items():
        candidate=[]
        for src in catalog:
            try:
                sid=int(src["id"])
                slat=float(src["lat"]);slon=float(src["lon"])
                altitude=float(src["altitude"])
            except (KeyError,TypeError,ValueError):
                continue
            if sid in EXCLUDED_PREVIOUS_SITE_IDS or sid in used:continue
            distance=era.haversine(lat,lon,slat,slon)
            if distance<=25 and math.isfinite(altitude):
                candidate.append((distance,sid,src))
        if not candidate:
            chosen[label]={"status":"NO_AUTHENTIC_NEARBY_STATION_25KM",
                           "target_lat":lat,"target_lon":lon}
            continue
        distance,sid,src=min(candidate,key=lambda t:(t[0],t[1]))
        used.add(sid)
        chosen[label]={
            "status":"ORIGINAL_GEOSPHERE_STATION_SELECTED_BY_GEOMETRY_ONLY",
            "target_lat":lat,"target_lon":lon,
            "station_id":sid,"station_name":src.get("name"),
            "station_lat":float(src["lat"]),
            "station_lon":float(src["lon"]),
            "site_altitude_official_m":float(src["altitude"]),
            "distance_target_to_station_km":distance,
        }
    return chosen


def normalize_lon(x):
    return float(x)%360.


def regular_coordinate_index(coords,selected,step=.25,wrap=False):
    """Exact geopotential grid center, not nearest requested site coordinate."""
    arr=np.asarray(coords,dtype=float)
    if arr.ndim!=1 or len(arr)<500 or not np.isfinite(arr).all():
        raise ValueError("P9E_ARCO_INVALID_025_GRID_AXIS")
    if wrap:
        differences=np.abs(((arr-normalize_lon(selected)+180.)%360.)-180.)
    else:
        differences=np.abs(arr-selected)
    idx=int(np.argmin(differences))
    if float(differences[idx])>1e-4:
        raise ValueError("P9E_PROVIDER_GRID_CENTER_NOT_EXACT_ARCO_025_GRID_POINT")
    if not np.allclose(np.abs(np.diff(arr)),step,atol=1e-6,rtol=0):
        raise ValueError("P9E_ARCO_GRID_NOT_NATIVE_025_LATLON")
    return idx


def read_real_regular_z(points):
    import xarray as xr
    import gcsfs
    fs=gcsfs.GCSFileSystem(token="anon")
    ds=xr.open_zarr(fs.get_mapper(ARCO_REGULAR),chunks=None,
                    consolidated=None)
    try:
        if PARAM_NAME not in ds.data_vars:
            raise ValueError("P9E_ARCO_025_SURFACE_Z_MISSING_"+repr(list(ds.data_vars)[:20]))
        var=ds[PARAM_NAME]
        if "latitude" not in var.dims or "longitude" not in var.dims:
            raise ValueError("P9E_ARCO_025_Z_NOT_REGULAR_LATLON")
        units=str(var.attrs.get("units",""))
        if not n320.is_geopotential_unit(units):
            raise ValueError("P9E_ARCO_025_GEOPOTENTIAL_M2S2_UNIT_REQUIRED_"+units)
        lats=np.asarray(ds.latitude.values)
        lons=np.asarray(ds.longitude.values)
        if len(lats)!=721 or len(lons)!=1440:
            raise ValueError("P9E_NOT_721_X_1440_OROGRAPHY_GRID")
        if not (abs(min(lats)+90)<1e-5 and abs(max(lats)-90)<1e-5
                and abs(min(lons))<1e-5 and abs(max(lons)-359.75)<1e-5):
            raise ValueError("P9E_ARCO_025_LATLON_EXTENT_INCORRECT")
        selected=[(regular_coordinate_index(lats,p["grid_lat"]),
                    regular_coordinate_index(lons,p["grid_lon"],wrap=True))
                  for p in points]
        # Two frozen distinct original time coordinates: model surface height
        # should be temporally static. Never substitute a missing source value.
        sources=[]
        for stamp in (ORO_TIME,CHECK_TIME):
            v=var.sel(time=np.datetime64(stamp)) if "time" in var.dims else var
            xidx=xr.DataArray(np.asarray([i for i,j in selected]),dims="point")
            yidx=xr.DataArray(np.asarray([j for i,j in selected]),dims="point")
            values=np.asarray(v.isel(latitude=xidx,longitude=yidx).values,dtype=float)
            if values.shape!=(len(points),) or not np.isfinite(values).all():
                raise ValueError("P9E_NONFINITE_ORIGINAL_ARCO_REGULAR_GEOPOTENTIAL")
            sources.append(values)
        if not np.allclose(sources[0],sources[1],atol=.2,rtol=0):
            raise ValueError("P9E_025_MODEL_SURFACE_GEOPOTENTIAL_NOT_STATIONARY")
        vals=sources[0];mapped=[]
        for k,p in enumerate(points):
            row={"source_id":p["id"],"OpenMeteo_returned_lat":p["grid_lat"],
                 "OpenMeteo_returned_lon":p["grid_lon"],
                 "original_ARCO_lat":float(lats[selected[k][0]]),
                 "original_ARCO_lon":float(lons[selected[k][1]]),
                 "ARCO_025_original_surface_geopotential_m2s2":float(vals[k]),
                 "ARCO_025_original_model_height_m":float(vals[k]/G0),
                 "ARCO_grid_sample_latitude_index":int(selected[k][0]),
                 "ARCO_grid_sample_longitude_index":int(selected[k][1]),
                 "source_2021_1h_geopotential_temporally_stationary":True,
                 "same_ERA5_grid_node_coordinate_as_OpenMeteo":True,
                 "same_model_topographic_interpolation_proven":False}
            if not -800<row["ARCO_025_original_model_height_m"]<9000:
                raise ValueError("P9E_REGULAR_MODEL_HEIGHT_UNPHYSICAL")
            mapped.append(row)
        frozen={
            "dataset":ARCO_REGULAR,"source_z_variable":PARAM_NAME,
            "geopotential_units":units,"validated_original_UTC_hours":[ORO_TIME,CHECK_TIME],
            "grid_shape":[len(lats),len(lons)],"regular_step_degrees":0.25,
            "native_CDS_GRIB_original_bytes_verified":False,
            "ARCO_ERA5_processing_same_as_OpenMeteo_not_proven":True,
            "cell_height_is_ARCO_regridded_proxy_not_necessarily_provider_internal_height":True,
            "digest_selected_original_grid_lat_lon_z_sha256":hashlib.sha256(
                json.dumps(mapped,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "points":mapped,
        }
        return frozen
    finally:
        ds.close()


def collect_grid_centers(sites):
    """Get original returned selected grid center without site elevation adjustment."""
    gathered=[]
    for p in sites:
        # one unmodified day; explicit fixed ERA5, nearest grid, no DEM
        start="2021-01-10";end="2021-01-10"
        url=era.request_url(p["lat"],p["lon"],start,end)
        raw=era.get_original_source(url)
        _,_,meta=era.parse_source(raw,p["lat"],p["lon"],start,end)
        gathered.append({
            "id":p["id"],"lat":p["lat"],"lon":p["lon"],
            "grid_lat":meta["selected_cell_latitude"],
            "grid_lon":meta["selected_cell_longitude"],
            "distance_km":meta["selected_cell_distance_km"],
            "original_ERA5_provider_hourly_sample_SHA256":
                meta["canonical_hourly_weather_and_selected_cell_sha256"],
        })
    return gathered


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    original_metadata,msha=station.source_json(station.BASE+"/metadata")
    selected=select_new_stations(original_metadata)
    sites=[{"id":str(x["station_id"]),"lat":x["station_lat"],
            "lon":x["station_lon"]}
           for x in selected.values() if "station_id" in x]
    sites += [{"id":"global_"+name,"lat":lat,"lon":lon}
              for name,(lat,lon) in GLOBAL_PROBES.items()]
    if len(sites)<9:raise ValueError("P9E_INADEQUATE_GLOBAL_AND_AUSTRIAN_GEOMETRY_SITES")
    grid=collect_grid_centers(sites)
    original_regular=read_real_regular_z(grid)
    original_native=n320.actual_native_geo([{"id":p["id"],"name":p["id"],
                                          "lat":p["lat"],"lon":p["lon"]} for p in sites])
    old={str(x["station_id"]):x for x in original_native["sites"]}
    regular={str(x["source_id"]):x for x in original_regular["points"]}
    met={str(p["id"]):p for p in grid}
    all_sites=[]
    for site in sites:
        k=str(site["id"])
        reg=regular[k];ng=old[k]
        all_sites.append({
            **site,
            "regular_025_cell_lat":reg["original_ARCO_lat"],
            "regular_025_cell_lon":reg["original_ARCO_lon"],
            "regular_025_z_m2s2":reg["ARCO_025_original_surface_geopotential_m2s2"],
            "regular_025_z_g0_height_m":reg["ARCO_025_original_model_height_m"],
            "nearest_native_N320_z_g0_height_m":ng["native_z_div_g0_height_m"],
            "regular_minus_nearest_native_height_m":reg["ARCO_025_original_model_height_m"]-ng["native_z_div_g0_height_m"],
            "native_N320_grid_distance_km":ng["nearest_native_N320_km"],
            "regular_grid_center_distance_km":met[k]["distance_km"],
            "same_grid_center_coordinate_verified":True,
            "same_grid_regridding_pipeline_not_verified":True,
        })
    output={
        "phase":"IGE_P9_1E_REAL_ARCO_025_OROGRAPHY_SELECTED_GRID_MAPPING",
        "source_original_GeoSphere_metadata_SHA256":msha,
        "new_lowland_station_selection":selected,
        "regular_source":original_regular,
        "native_N320_source":{
            "source_uri":original_native["source_uri"],
            "source_z_array_sha256":original_native["native_N320_array_values_sha256"],
        },
        "n_all_grid_source_points":len(all_sites),
        "mapped_points":all_sites,
        "actual_original_ERA5_025_geopotential_values_read":True,
        "same_selected_025_coordinate_as_source_verified":True,
        "exact_provider_internal_OpenMeteo_grid_height_verified":False,
        "independent_global_station_weather_skill_validated":False,
        "production_epw_ready":False,
    }
    (root/"p9_1e_actual_regular_025_selected_grid_mapping.json").write_text(
        json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    for q in all_sites:
        print("P9_1E_GRID",json.dumps({
            "site":q["id"],"OpenMeteo_grid":[q["regular_025_cell_lat"],q["regular_025_cell_lon"]],
            "z_regular_m":round(q["regular_025_z_g0_height_m"],1),
            "z_N320_nearest_m":round(q["nearest_native_N320_z_g0_height_m"],1),
            "difference_m":round(q["regular_minus_nearest_native_height_m"],1),
        }),flush=True)
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",required=True)
    run(parser.parse_args().out)
