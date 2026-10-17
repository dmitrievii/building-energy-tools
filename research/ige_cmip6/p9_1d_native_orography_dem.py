#!/usr/bin/env python3
"""ERA5 native reduced Gaussian N320 surface geopotential and independent SRTM DEM.

Uses Google ARCO native gridded ERA5 representation, NOT authenticated CDS GRIB
bytes and NOT a verified height for Open-Meteo's regular 0.25 degree grid.
"""
import argparse,hashlib,json,math,time,urllib.parse,urllib.request,urllib.error
from pathlib import Path
import numpy as np
import p9_1b_geosphere_original_station_holdouts as station
import p9_1a_global_historical_backbone as era

NATIVE="gs://gcp-public-data-arco-era5/co/single-level-reanalysis.zarr-v2"
DEM="https://api.opentopodata.org/v1/srtm90m"
G0=9.80665

def is_geopotential_unit(v):
    u=str(v).lower().replace(" ","").replace("**","^").replace("²","2").replace("⁻","-")
    return u in {"m2s-2","m^2s^-2","m^2s-2","m2/s2","m^2/s^2","m2s^-2"}

def nearest_n320(lats,lons,lat,lon):
    la=np.asarray(lats,float);lo=np.asarray(lons,float)
    if la.ndim!=1 or la.size<200000 or lo.shape!=la.shape:
        raise ValueError("P9D_NOT_NATIVE_N320_GEOMETRY")
    if not (np.isfinite(la).all() and np.isfinite(lo).all()
            and np.all(np.abs(la)<=90) and np.all((lo>=-180)&(lo<=360))):
        raise ValueError("P9D_INVALID_NATIVE_COORDS")
    radlat=np.radians(la);radlon=np.radians(lo)
    cosine=(np.sin(math.radians(lat))*np.sin(radlat)
           +np.cos(math.radians(lat))*np.cos(radlat)
           *np.cos(radlon-math.radians(lon)))
    idx=int(np.argmax(cosine))
    gridlon=((float(lo[idx])+180)%360)-180
    km=era.haversine(lat,lon,float(la[idx]),gridlon)
    if km>100:raise ValueError("P9D_GRID_TOO_FAR")
    return idx,float(la[idx]),gridlon,km

def actual_native_geo(sites):
    import xarray as xr
    import gcsfs
    mapper=gcsfs.GCSFileSystem(token="anon").get_mapper(NATIVE)
    ds=xr.open_zarr(mapper,consolidated=None,chunks=None)
    try:
        candidates=[name for name in ("geopotential","geopotential_at_surface","z")
                    if name in ds.data_vars and "values" in ds[name].dims
                    and len(ds[name].dims)<=2]
        if len(candidates)!=1:
            raise ValueError("P9D_NO_UNIQUE_NATIVE_SURFACE_GEOPOTENTIAL "
                             +str(list(ds.data_vars)[:35]))
        name=candidates[0];var=ds[name]
        unit=var.attrs.get("units","")
        if not is_geopotential_unit(unit):
            raise ValueError("P9D_WRONG_NATIVE_Z_UNIT "+str(unit))
        # The earliest first stored time is missing for some ARCO fields;
        # explicitly inspect two frozen 2022 dates. No interpolation.
        candidates=[]
        if "time" in var.dims:
            for when in ("2022-01-10T00:00:00","2022-07-10T00:00:00"):
                sample=var.sel(time=np.datetime64(when))
                candidate=np.asarray(sample.values,dtype=np.float64)
                candidates.append((when,candidate))
        else:
            candidates=[("static",np.asarray(var.values,dtype=np.float64))]
        valid=[(when,x) for when,x in candidates if
               x.ndim==1 and len(x)>=200000 and np.isfinite(x).all()]
        if not valid:
            raise ValueError("P9D_NATIVE_N320_SURFACE_Z_UNAVAILABLE_AT_FIXED_TIMES "+
                             str([(t,x.shape,int(np.isfinite(x).sum()))
                                  for t,x in candidates]))
        if len(valid)>1 and not np.allclose(valid[0][1],valid[1][1],atol=1e-6,rtol=0):
            raise ValueError("P9D_N320_GEOPOTENTIAL_IS_NOT_STATIC_BETWEEN_SEASONS")
        sample_time,z=valid[0]
        if "latitude" not in ds or "longitude" not in ds:
            raise ValueError("P9D_NATIVE_LATLON_NOT_EXPOSED")
        lats=np.asarray(ds["latitude"].values,float)
        lons=np.asarray(ds["longitude"].values,float)
        if not (lats.shape==lons.shape==z.shape):
            raise ValueError("P9D_OROGRAPHY_COORD_SHAPE_MISMATCH")
        original=[]
        for p in sites:
            i,clat,clon,km=nearest_n320(lats,lons,p["lat"],p["lon"])
            value=float(z[i]);height=value/G0
            if not -500<height<9000:
                raise ValueError("P9D_IMPLAUSIBLE_N320_GEOPOTENTIAL_HEIGHT")
            original.append({"station_id":p["id"],"nearest_native_N320_lat":clat,
              "nearest_native_N320_lon":clon,"nearest_native_N320_km":km,
              "original_geopotential_m2s2":value,"native_z_div_g0_height_m":height,
              "native_gaussian_index":i})
        return {"source_uri":NATIVE,
                "native_N320_surface_geopotential_field":name,
                "actual_source_z_units":unit,"native_gaussian_grid_size":len(z),
                "native_N320_source_sample_time":sample_time,
                "native_N320_valid_sample_count":len(valid),
                "native_N320_array_values_sha256":hashlib.sha256(
                    z.astype("<f8").tobytes()).hexdigest(),
                "original_ECMWF_CDS_GRIB_file_bytes_verifed":False,
                "is_same_as_OpenMeteo_selected_0p25_grid":False,
                "sites":original}
    finally:
        ds.close()

def independent_dem(sites):
    locations="|".join(f"{s['lat']:.6f},{s['lon']:.6f}" for s in sites)
    url=DEM+"?"+urllib.parse.urlencode({"locations":locations,"interpolation":"bilinear"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={
                    "User-Agent":"IGE-P9.1D-original-SRTM-DEM"}),timeout=65) as fp:
                raw=fp.read(200000)
            break
        except (TimeoutError,urllib.error.URLError):
            if attempt==2:raise
            time.sleep(2**attempt)
    payload=json.loads(raw)
    if payload.get("status")!="OK" or len(payload.get("results",[]))!=len(sites):
        raise ValueError("P9D_INDEPENDENT_DEM_RESPONSE_INVALID")
    out=[]
    for s,p in zip(sites,payload["results"]):
        if p.get("dataset")!="srtm90m" or p.get("elevation") is None:
            raise ValueError("P9D_NOT_VERIFIED_SRTM_V3")
        x=p.get("location",{})
        if era.haversine(s["lat"],s["lon"],float(x["lat"]),float(x["lng"]))>.05:
            raise ValueError("P9D_DEM_LOCATION_MISMATCH")
        height=float(p["elevation"])
        if not -500<=height<=9000:raise ValueError("P9D_DEM_HEIGHT_INVALID")
        out.append({"station_id":s["id"],"SRTM_v3_90m_elevation_m":height,
                    "station_official_altitude_m":s["altitude_m"],
                    "DEM_minus_station_metadata_m":height-s["altitude_m"]})
    return {"source":"SRTM_V3_90M_OPENTOPODATA_BILINEAR",
            "response_sha256":hashlib.sha256(raw).hexdigest(),
            "source_query":url,"original_DEM_raster_tile_bytes_verified":False,
            "vertical_datum_cross_source_independently_harmonized":False,
            "sites":out}

def run(out):
    metadata,msha=station.source_json(station.BASE+"/metadata")
    info=station.extract_metadata(metadata)
    sites=[info[i] for i in station.IDS]
    dem=independent_dem(sites)
    native=actual_native_geo(sites)
    byid={a["station_id"]:a for a in native["sites"]}
    combined=[]
    for p in dem["sites"]:
        n=byid[p["station_id"]]
        combined.append({**p,**n,
             "station_minus_native_N320_height_m":
                 p["station_official_altitude_m"]-n["native_z_div_g0_height_m"],
             "dem_minus_native_N320_height_m":
                 p["SRTM_v3_90m_elevation_m"]-n["native_z_div_g0_height_m"],
             "native_grid_is_not_OpenMeteo_0p25_grid":True})
    report={"phase":"IGE_P9_1D_NATIVE_N320_AND_INDEPENDENT_SRTM_DEM",
            "source_station_metadata_sha256":msha,"native_grid":native,
            "DEM":dem,"sites":combined,"genuinely_read_original_native_N320_geopotential":True,
            "independently_queried_DEM":True,
            "0p25_open_meteo_exact_cell_orography_qualified":False,
            "independent_new_site_weather_skill_qualified":False,
            "production_epw_ready":False}
    o=Path(out);o.mkdir(parents=True,exist_ok=True)
    (o/"p9_1d_original_native_N320_independent_dem.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    for x in combined:print("P9_1D_NATIVE_DEM",json.dumps({
        "station":x["station_id"],"native_m":round(x["native_z_div_g0_height_m"],2),
        "SRTM_m":x["SRTM_v3_90m_elevation_m"],
        "station_m":x["station_official_altitude_m"],
        "native_km":round(x["nearest_native_N320_km"],2)}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
