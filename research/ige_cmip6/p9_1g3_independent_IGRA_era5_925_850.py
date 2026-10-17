#!/usr/bin/env python3
"""IGE P9.1G3: genuine NOAA IGRA2 original 925/850hPa radiosonde vs ERA5 ARCO.

Source-only 28 predeclared 2019 sounding slots. Independent vertical QA,
no radiosonde source data used for site selection or model correction.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import io
import json
import math
import statistics
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
import numpy as np

import p9_1a_global_historical_backbone as era
import p9_1e_regular_grid_orography as grid
import p9_1g_era5_pressure_stability as physics

STATION="GMM00010393"
LIST_URL="https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt"
ZIP_URL="https://www.ncei.noaa.gov/pub/data/igra/data/data-por/"+STATION+"-data.txt.zip"
MAX_ZIP_SIZE=115*1024*1024
LEVELS=(925,850)
TIMEBLOCKS=(("winter_2019","2019-01-10","2019-01-16"),
            ("autumn_2019","2019-10-10","2019-10-16"))
KAPPA=.286
G0=9.80665


def archive_source(url,max_size):
    p=urllib.parse.urlsplit(url)
    if p.scheme!="https" or p.hostname!="www.ncei.noaa.gov" or (
       p.path not in ("/pub/data/igra/igra2-station-list.txt",
                      "/pub/data/igra/data/data-por/"+STATION+"-data.txt.zip")):
        raise ValueError("P9G3_ONLY_ORIGINAL_IGRA_NOAA_ALLOWLISTED_SOURCE")
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.1G3-original-2019-IGRA2-QC-stability"})
    with urllib.request.urlopen(req,timeout=180) as response:
        raw=response.read(max_size+1)
    if len(raw)>max_size:
        raise ValueError("P9G3_SOURCE_DATA_TOO_LARGE")
    return raw


def parse_metadata(blob):
    matched=[row for row in blob.decode("latin1").splitlines()
             if row.startswith(STATION+" ")]
    if len(matched)!=1:
        raise ValueError("P9G3_ORIGINAL_IGRA_STATION_MISSING")
    parts=matched[0].split()
    latitude=float(parts[1]);longitude=float(parts[2]);height=float(parts[3])
    if not (48<latitude<56 and 9<longitude<17 and -100<height<2500):
        raise ValueError("P9G3_ORIGINAL_LINDENBERG_STATION_GEOGRAPHY_INVALID")
    return {"site_id":STATION,"lat":latitude,"lon":longitude,
            "station_original_elevation_m":height,
            "original_station_record":matched[0]}


def fixed_slots():
    return {t for name,start,end in TIMEBLOCKS
            for t in physics.hours_for_season(start,end)}


def extract_original_igra_925_850(raw,official_site_elev):
    """Walk real compressed multiline IGRA v2.2 fixed-width station records.

    Each record belongs to an IGRA sounding header. Decodes only two ORIGINAL
    reported standard pressure levels, never interpolates missing/QA-deleted.
    """
    selected=fixed_slots()
    actual={};headers_seen=set();quality_hist={}
    with zipfile.ZipFile(io.BytesIO(raw)) as container:
        paths=[x for x in container.namelist() if x.endswith("-data.txt")]
        if len(paths)!=1 or STATION not in paths[0]:
            raise ValueError("P9G3_EXPECTED_REAL_IGRA_SOUNDING_FILE_MISSING")
        name=paths[0]
        active=None
        with container.open(name,"r") as stream:
            for line in stream:
                if line.startswith(b"#"):
                    record=line.decode("ascii",errors="replace")
                    if record[1:12]!=STATION:
                        raise ValueError("P9G3_SOUNDING_SOURCE_SITE_ID_MISMATCH")
                    try:
                        year=int(record[13:17])
                        month=int(record[18:20])
                        day=int(record[21:23])
                        hour=int(record[24:26])
                        nlev=int(record[32:36])
                    except ValueError as exc:
                        raise ValueError("P9G3_ORIGINAL_IGRA2_HEADER_COLUMNS_DRIFT") from exc
                    if not 0<nlev<2000:
                        raise ValueError("P9G3_UNREALISTIC_SOURCE_SOUNDING_LEVEL_COUNT")
                    active=None
                    if year==2019 and hour in (0,12):
                        stamp=f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00"
                        if stamp in selected:
                            if stamp in headers_seen:
                                raise ValueError("P9G3_DUPLICATE_IGRA_ORIGINAL_NOMINAL_SOUNDING")
                            headers_seen.add(stamp)
                            active=stamp
                            actual[stamp]={}
                    continue
                if active is None:continue
                source=line.decode("ascii",errors="replace")
                try:
                    standard=int(source[0])
                    pressure_pa=int(source[9:15])
                    height_m=int(source[16:21])
                    temperature_tenth_c=int(source[22:27])
                except ValueError:continue
                pressure_hpa=pressure_pa/100.
                if standard!=1 or pressure_hpa not in LEVELS:continue
                flag=source[27:28] if len(source)>27 else ""
                quality_hist[flag]=quality_hist.get(flag,0)+1
                if temperature_tenth_c in (-8888,-9999) or height_m in (-8888,-9999):
                    continue
                if not(-90<temperature_tenth_c/10<50 and
                       official_site_elev+50<height_m<6000):
                    continue
                if flag not in (" ","A","B"):
                    continue
                if pressure_hpa in actual[active]:
                    raise ValueError("P9G3_DUPLICATE_REPORTED_925_850_PRESSURE_LEVEL")
                actual[active][pressure_hpa]={
                    "temperature_c":temperature_tenth_c/10.,
                    "geopotential_height_m":float(height_m),
                    "temperature_IGRA_QA_flag":flag,
                }
    complete={stamp:row for stamp,row in actual.items()
              if set(row)==set(LEVELS)}
    return complete,{
        "real_original_IGRA_file_member":name,
        "n_expected_2019_UTC_sounding_slots":len(selected),
        "n_true_source_headers_at_registered_nominal_hours":len(headers_seen),
        "n_true_soundings_both_original_925_850_pressure_t_and_height":
            len(complete),
        "original_IGRA_T925_T850_QA_flags":quality_hist,
        "all_source_missing_or_deletions_unfilled":True,
        "original_radiosonde_NOMINAL_hour_not_exact_release_or_measurement_at_level":True,
        "source_zip_sha256":hashlib.sha256(raw).hexdigest(),
    }


def sampled_original_ARCO_ERA5_925_850(station,slots):
    import xarray as xr
    import gcsfs
    start="2019-01-10";end="2019-01-10"
    orig=era.get_original_source(era.request_url(station["lat"],station["lon"],start,end))
    _,_,m=era.parse_source(orig,station["lat"],station["lon"],start,end)
    fs=gcsfs.GCSFileSystem(token="anon")
    ds=xr.open_zarr(fs.get_mapper(grid.ARCO_REGULAR),consolidated=None,chunks=None)
    try:
        if "temperature" not in ds or "geopotential" not in ds:
            raise ValueError("P9G3_NOT_ORIGINAL_ARCO_ERA5_PRESSURE_SOURCE")
        if str(ds["temperature"].attrs.get("units","")).strip().lower() not in ("k","kelvin"):
            raise ValueError("P9G3_ARCO_PRESSURE_TEMPERATURE_NOT_K")
        if not grid.n320.is_geopotential_unit(ds["geopotential"].attrs.get("units","")):
            raise ValueError("P9G3_ARCO_PRESSURE_GEOPOTENTIAL_UNITS")
        latidx=grid.regular_coordinate_index(ds.latitude.values,m["selected_cell_latitude"])
        lonidx=grid.regular_coordinate_index(ds.longitude.values,m["selected_cell_longitude"],wrap=True)
        times=np.array(sorted(slots),dtype="datetime64[ns]")
        array_t=np.asarray(ds["temperature"].sel(time=times,level=list(LEVELS)).
                           isel(latitude=latidx,longitude=lonidx).
                           transpose("time","level").values,float)
        array_z=np.asarray(ds["geopotential"].sel(time=times,level=list(LEVELS)).
                           isel(latitude=latidx,longitude=lonidx).
                           transpose("time","level").values,float)/G0
        if array_t.shape!=(len(times),2) or array_z.shape!=array_t.shape:
            raise ValueError("P9G3_PRESSURE_LEVEL_MODEL_TIMESTAMP_MISMATCH")
        if not np.isfinite(array_t).all() or not np.isfinite(array_z).all():
            raise ValueError("P9G3_UNAVAILABLE_SOURCE_ERA5_PRESSURE_LEVEL")
        result={}
        for i,stamp in enumerate(sorted(slots)):
            result[stamp]={
                lev:{
                    "temperature_c":float(array_t[i,j]-273.15),
                    "geopotential_height_m":float(array_z[i,j])
                } for j,lev in enumerate(LEVELS)}
        source_digest=hashlib.sha256(array_t.astype("<f8").tobytes()+
                                     array_z.astype("<f8").tobytes()).hexdigest()
        return result,{
            "ARCO_original_source":grid.ARCO_REGULAR,
            "actual_ERA5_selected_025_lat":m["selected_cell_latitude"],
            "actual_ERA5_selected_025_lon":m["selected_cell_longitude"],
            "original_ARCO_kelvin_and_original_geopotential_selected_values_SHA256":
                source_digest,
            "ERA5_00_12_hour_nominal_sounding_time_not_physically_exact_same_air_column":True,
        }
    finally:
        ds.close()


def profile_gradient(levels):
    lower=levels[925];upper=levels[850]
    dz=upper["geopotential_height_m"]-lower["geopotential_height_m"]
    if not 100<dz<1600:
        raise ValueError("P9G3_INVALID_925_850_VERTICAL_HEIGHT_SEPARATION")
    low_t=lower["temperature_c"];high_t=upper["temperature_c"]
    low_theta=(low_t+273.15)*(1000./925.)**physics.KAPPA
    hi_theta=(high_t+273.15)*(1000./850.)**physics.KAPPA
    return {"temperature_gradient_K_km":(high_t-low_t)/dz*1000,
            "theta_gradient_K_km":(hi_theta-low_theta)/dz*1000,
            "model_resolved_positive_temp_gradient":high_t>low_t,
            "theta_statically_stable_above5_K_per_km":(hi_theta-low_theta)/dz*1000>5.,
            "two_levels_above_IGRA_station_surface_verified":True}


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    station_meta=archive_source(LIST_URL,2500000)
    site=parse_metadata(station_meta)
    blob=archive_source(ZIP_URL,MAX_ZIP_SIZE)
    obs,obsprov=extract_original_igra_925_850(
        blob,site["station_original_elevation_m"])
    print("P9G3_IGRA_ORIGINAL_SOURCE",json.dumps({
        "station":STATION,
        "official_site_lat_lon":[site["lat"],site["lon"]],
        "original_sounding_slots":obsprov["n_true_source_headers_at_registered_nominal_hours"],
        "original_925_850_qualified_sounding_pairs":len(obs),
    }),flush=True)
    # Preserve real independent observations source scope BEFORE touching ARCO.
    pre={
        "phase":"IGE_P9G3_INDEPENDENT_NOAA_ORIGINAL_RADIOSONDE_READBACK",
        "original_IGRA_station_location_and_height":site,
        "source_station_metadata_SHA256":hashlib.sha256(station_meta).hexdigest(),
        "source_original_IGRA_925_850":obsprov,
        "no_original_individual_radiosonde_temperatures_published":True,
        "n_independent_original_soundings_complete":len(obs),
        "production_epw_ready":False}
    (root/"p9_1g3_original_IGRA_sounding_source_only.json").write_text(
        json.dumps(pre,indent=2,ensure_ascii=False)+"\n")
    if len(obs)<14:
        raise ValueError("P9G3_INDEPENDENT_RADIOSONDE_AT_TWO_PRESSURES_NOT_QUALIFIED")
    model,orig_source=sampled_original_ARCO_ERA5_925_850(site,fixed_slots())
    paired=[];qualified=0
    for stamp in sorted(obs):
        try:
            obs_profile=profile_gradient(obs[stamp])
            era_profile=profile_gradient(model[stamp])
        except ValueError:
            continue
        qualified+=1
        pair={"original_UTC_nominal_sounding_time":stamp,
              "original_IGRA_T925_C":obs[stamp][925]["temperature_c"],
              "original_IGRA_T850_C":obs[stamp][850]["temperature_c"],
              "original_ERA5_T925_C":model[stamp][925]["temperature_c"],
              "original_ERA5_T850_C":model[stamp][850]["temperature_c"],
              "observed_925_to_850_K_km":obs_profile["temperature_gradient_K_km"],
              "model_925_to_850_K_km":era_profile["temperature_gradient_K_km"],
              "observed_theta_gradient_K_km":obs_profile["theta_gradient_K_km"],
              "model_theta_gradient_K_km":era_profile["theta_gradient_K_km"],
              "observed_warm_above_cold":obs_profile["model_resolved_positive_temp_gradient"],
              "model_warm_above_cold":era_profile["model_resolved_positive_temp_gradient"],
              "observed_theta_stable":obs_profile["theta_statically_stable_above5_K_per_km"],
              "model_theta_stable":era_profile["theta_statically_stable_above5_K_per_km"]}
        paired.append(pair)
    if len(paired)<14:raise ValueError("P9G3_ORIGINAL_SONDE_ERA5_SHARED_QC_TOO_FEW")
    def MAE(a,b):return statistics.fmean(abs(x[a]-x[b]) for x in paired)
    result={
        "phase":"IGE_P9_1G3_ORIGINAL_INDEPENDENT_IGRA_ERA5_2019_925_850_POTENTIAL_TEMPERATURE",
        "real_radiosonde_station":site,"source_IGRA":obsprov,
        "source_original_ERA5":orig_source,
        "n_predeclared_2019_00_12UTC_slots":len(fixed_slots()),
        "n_paired_true_original_IGRA_and_ARCO_soundings":len(paired),
        "MAE_ERA5_925hPa_T_against_IGRA_C":MAE("original_IGRA_T925_C","original_ERA5_T925_C"),
        "MAE_ERA5_850hPa_T_against_IGRA_C":MAE("original_IGRA_T850_C","original_ERA5_T850_C"),
        "MAE_ERA5_vs_IGRA_T_gradient_K_km":MAE("observed_925_to_850_K_km","model_925_to_850_K_km"),
        "MAE_ERA5_vs_IGRA_theta_gradient_K_km":MAE("observed_theta_gradient_K_km","model_theta_gradient_K_km"),
        "n_original_IGRA_actual_warm_upper_than_lower_free_air":sum(
            x["observed_warm_above_cold"] for x in paired),
        "n_model_ERA5_warm_upper_than_lower_free_air":sum(
            x["model_warm_above_cold"] for x in paired),
        "n_original_IGRA_theta_stable_above5_K_km":sum(
            x["observed_theta_stable"] for x in paired),
        "n_model_ERA5_theta_stable_above5_K_km":sum(
            x["model_theta_stable"] for x in paired),
        "theta_stability_threshold_confusion_counts":{
            "both_IGRA_and_ERA5_stable":sum(
                x["observed_theta_stable"] and x["model_theta_stable"] for x in paired),
            "IGRA_only_stable":sum(
                x["observed_theta_stable"] and not x["model_theta_stable"] for x in paired),
            "ERA5_only_stable":sum(
                not x["observed_theta_stable"] and x["model_theta_stable"] for x in paired),
            "neither_stable":sum(
                not x["observed_theta_stable"] and not x["model_theta_stable"] for x in paired),
        },
        "ERA5_vs_IGRA_temperature_gradient_sign_agreement_fraction":
            sum(x["observed_warm_above_cold"]==x["model_warm_above_cold"] for x in paired)/len(paired),
        "ERA5_vs_IGRA_theta_above5_threshold_agreement_fraction":
            sum(x["observed_theta_stable"]==x["model_theta_stable"] for x in paired)/len(paired),
        "independent_IGRA_did_not_fit_ERA5_pressure_or_site_temperature":True,
        "radiosonde_nominal_UTC_vs_actual_launch_and_level_time_not_harmonized":True,
        "this_is_free_air_vertical_skill_not_surface_cold_air_pool_validation":True,
        "new_geographical_multi_continent_validation":False,
        "production_epw_ready":False,
        # ORIGINAL hourly IGRA and ERA5 individual observations intentionally NOT emitted
    }
    (root/"p9_1g3_independent_original_IGRA_vs_ERA5_pressure_skill.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("P9G3_INDEPENDENT_TRUE_RADIOSONDE",json.dumps({
        "source_pairs":len(paired),
        "T925_MAE_C":result["MAE_ERA5_925hPa_T_against_IGRA_C"],
        "T850_MAE_C":result["MAE_ERA5_850hPa_T_against_IGRA_C"],
        "gradient_MAE_Kkm":result["MAE_ERA5_vs_IGRA_T_gradient_K_km"],
        "theta_stability_regime_agreement":
            result["ERA5_vs_IGRA_theta_above5_threshold_agreement_fraction"],
        "production_ready":False}),flush=True)
    return result


if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--out",required=True)
    run(a.parse_args().out)
