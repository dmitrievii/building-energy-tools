#!/usr/bin/env python3
"""IGE P9.1A: provenance-first GLOBAL ERA5-reanalysis historical-hourly backbone.

This is NOT native ECMWF CDS ERA5 data: Open-Meteo redistributes ERA5-derived
meteorology. Explicitly request the *fixed* ERA5 model, grid-scale conditions
(elevation=nan, no provider DEM/downscaling), nearest cell, UTC, canonical units.
The provider may process/deaggregate radiation and other variables: these are
provider-delivered ERA5 derivatives, not authenticated native GRIB fields.

P9.1A source-backbone probe, NOT arbitrarily accurate local weather, NOT EPW.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import statistics
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SOURCE_URL="https://archive-api.open-meteo.com/v1/archive"
MODEL="era5"
SOURCE_SCOPE="OPEN_METEO_DERIVED_ERA5_0p25_DEG_NOT_NATIVE_CDS_ERA5"
TIMEZONE="GMT"  # UTC offset 0, never derive local EPW hour-ending from it
HOURLY=(
    "temperature_2m","dew_point_2m","relative_humidity_2m","surface_pressure",
    "precipitation","cloud_cover","shortwave_radiation","direct_radiation",
    "diffuse_radiation","direct_normal_irradiance",
    "wind_speed_10m","wind_direction_10m",
)
EXPECTED_UNITS={
    "temperature_2m":"°C","dew_point_2m":"°C",
    "relative_humidity_2m":"%","surface_pressure":"hPa",
    "precipitation":"mm","cloud_cover":"%",
    "shortwave_radiation":"W/m²","direct_radiation":"W/m²",
    "diffuse_radiation":"W/m²","direct_normal_irradiance":"W/m²",
    "wind_speed_10m":"m/s","wind_direction_10m":"°",
}
LIMIT_BYTES=12*1024*1024
EARTH_KM=6371.0088


def haversine(lat1,lon1,lat2,lon2):
    a,b,c,d=map(math.radians,(lat1,lon1,lat2,lon2))
    x=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return EARTH_KM*2*math.asin(min(1.,math.sqrt(x)))


def validate_request(lat,lon,start,end):
    if (not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (lat,lon))
            or not -90<=lat<=90 or not -180<=lon<=180):
        raise ValueError("P9_1_INVALID_WGS84_COORDINATE")
    s=dt.date.fromisoformat(start);e=dt.date.fromisoformat(end)
    if s>e or s<dt.date(1950,1,1) or e>dt.date(2025,12,31):
        raise ValueError("P9_1_INVALID_OR_UNAVAILABLE_ERA5_HISTORICAL_PERIOD")
    if (e-s).days>370:
        raise ValueError("P9_1_PILOT_PER_REQUEST_LIMIT_ONE_YEAR")
    return s,e


def request_url(lat,lon,start,end):
    validate_request(lat,lon,start,end)
    params={
        "latitude":f"{lat:.6f}","longitude":f"{lon:.6f}",
        "start_date":start,"end_date":end,
        "hourly":",".join(HOURLY),
        "timezone":TIMEZONE,
        "models":MODEL,
        "elevation":"nan",  # provider statistical height correction DISABLED
        "cell_selection":"nearest",  # no elevation-based cell selection
        "wind_speed_unit":"ms","temperature_unit":"celsius",
        "precipitation_unit":"mm","timeformat":"iso8601",
    }
    return SOURCE_URL+"?"+urllib.parse.urlencode(params)


def _no_redirect_opener():
    class ForbidRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            raise ValueError("P9_1_EXTERNAL_HTTP_REDIRECT_NOT_ALLOWED")
    return urllib.request.build_opener(ForbidRedirect)


def get_original_source(url,timeout=60):
    parsed=urllib.parse.urlsplit(url)
    if (parsed.scheme!="https" or parsed.hostname!="archive-api.open-meteo.com"
            or parsed.path!="/v1/archive" or parsed.port is not None):
        raise ValueError("P9_1_SOURCE_HOST_NOT_ALLOWLISTED")
    with _no_redirect_opener().open(
        urllib.request.Request(url,headers={
            "User-Agent":"IGE-independent-P9.1A-research/0.1",
            "Accept":"application/json",
        }),timeout=timeout) as fp:
        size=fp.headers.get("Content-Length")
        if size and int(size)>LIMIT_BYTES:
            raise ValueError("P9_1_SOURCE_RESPONSE_TOO_LARGE")
        data=fp.read(LIMIT_BYTES+1)
        if len(data)>LIMIT_BYTES:
            raise ValueError("P9_1_SOURCE_RESPONSE_TOO_LARGE")
    return data


def parse_source(original_bytes,latitude,longitude,start,end):
    """Fail closed on time/units/source scope, report meteorological violations.

    Only *explicitly requested* canonical ERA5 model can be trusted. Open-Meteo
    has no model fingerprint in its JSON response; this is source-request
    provenance rather than an independently verified ERA5 GRIB digest.
    """
    s,e=validate_request(latitude,longitude,start,end)
    obj=json.loads(original_bytes)
    if not isinstance(obj,dict) or obj.get("error"):
        raise ValueError("P9_1_PROVIDER_ERROR_RESPONSE")
    hours=obj.get("hourly")
    units=obj.get("hourly_units")
    if not isinstance(hours,dict) or not isinstance(units,dict):
        raise ValueError("P9_1_HOURLY_SOURCE_OR_UNITS_MISSING")
    if obj.get("utc_offset_seconds")!=0 or obj.get("timezone") not in ("GMT","UTC"):
        raise ValueError("P9_1_RESPONSE_NOT_GMT_UTC")
    for name,u in EXPECTED_UNITS.items():
        if units.get(name)!=u:
            raise ValueError("P9_1_SOURCE_UNITS_DRIFT_"+name)
    times=hours.get("time")
    expected=[(dt.datetime.combine(s,dt.time())+dt.timedelta(hours=i)).strftime(
        "%Y-%m-%dT%H:%M") for i in range(((e-s).days+1)*24)]
    if times!=expected:
        raise ValueError("P9_1_SOURCE_MISSING_DUPLICATED_SHIFTED_OR_DST_HOURS")
    arrays={}
    for var in HOURLY:
        data=hours.get(var)
        if not isinstance(data,list) or len(data)!=len(expected):
            raise ValueError("P9_1_VARIABLE_INCOMPLETE_"+var)
        arrays[var]=data
    try:
        slat=float(obj["latitude"]);slon=float(obj["longitude"])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError("P9_1_NO_RESPONSE_SELECTED_GRID_CENTER") from exc
    if not (-90<=slat<=90 and -180<=slon<=180):
        raise ValueError("P9_1_INVALID_RETURNED_GRID_CENTER")
    distance=haversine(latitude,longitude,slat,slon)
    if distance>150:
        raise ValueError("P9_1_UNEXPECTED_DISTANT_REANALYSIS_GRID")
    return obj,arrays,{
        "selected_cell_latitude":slat,
        "selected_cell_longitude":slon,
        "requested_latitude":latitude,
        "requested_longitude":longitude,
        "selected_cell_distance_km":distance,
        "response_elevation_m_unverified":obj.get("elevation"),
        "provider_elevation_field_cannot_certify_native_grid_or_site_height":True,
        "user_altitude_or_terrain_DEM_applied":False,
        "provider_statistical_elevation_downscaling_disabled":True,
        "raw_original_response_sha256":hashlib.sha256(original_bytes).hexdigest(),
        "n_received_hourly_rows":len(expected),
        "dates_UTC_contiguous":True,
        "original_hourly_payload_all_variables_same_time_axis":True,
    }


def statistics_and_coherence(arrays):
    """Diagnostic metrics, conditional on a common source and SAME month/hour.

    Do not demand Meteonorm rain-cloud regression values as fixed truths.
    Pairwise daily/annual distributions require observations for validation.
    """
    n=len(arrays["temperature_2m"])
    bad=collections.Counter();warn=collections.Counter()
    scalars=collections.defaultdict(list)
    monthly=collections.defaultdict(lambda:collections.defaultdict(list))
    grouped=collections.defaultdict(lambda:{"wet":[],"dry":[]})
    wet_mask=[]
    selected=0
    paired_hour=0
    for i in range(n):
        vals={k:arrays[k][i] for k in HOURLY}
        if any(v is None or isinstance(v,bool)
               or not isinstance(v,(float,int)) or not math.isfinite(v)
               for v in vals.values()):
            bad["provider_missing_nonfinite_hourly_components"]+=1
            continue
        t=vals["temperature_2m"];td=vals["dew_point_2m"];rh=vals["relative_humidity_2m"]
        p=vals["surface_pressure"];rain=vals["precipitation"];cc=vals["cloud_cover"]
        ghi=vals["shortwave_radiation"];dir_h=vals["direct_radiation"]
        dhi=vals["diffuse_radiation"];dni=vals["direct_normal_irradiance"]
        w=vals["wind_speed_10m"];angle=vals["wind_direction_10m"]
        if not (-90<t<65 and -100<td<65 and 0<=rh<=100 and 350<p<1120):
            bad["invalid_temperature_RH_or_surface_pressure"]+=1
        if td>t+.5:bad["dewpoint_above_drybulb"]+=1
        if (rain<-.01 or not 0<=cc<=100 or w<0 or not 0<=angle<=360
                or min(ghi,dir_h,dhi,dni)<-1):
            bad["invalid_precipitation_cloud_wind_or_radiation"]+=1
        if dhi>ghi+5:
            bad["DHI_exceeds_GHI"]+=1
        if abs(ghi-(dir_h+dhi))>max(8.,.035*max(ghi,1.)):
            warn["GHI_horizontal_components_inconsistent"]+=1
        if dir_h>dni+8:
            bad["direct_horizontal_exceeds_direct_normal"]+=1
        if w>=.5 and not 0<=angle<=360:
            bad["noncalm_missing_wind_direction"]+=1
        # A second psychrometric source consistency check; no silent "fix".
        es_t=611.21*math.exp((18.678-t/234.5)*t/(257.14+t))
        es_td=611.21*math.exp((18.678-td/234.5)*td/(257.14+td))
        calc_rh=100*es_td/es_t
        if abs(calc_rh-rh)>4.0:warn["RH_dewpoint_provider_rounding_or_bias"]+=1
        m=(i//24) # actual month supplied from declared base period in caller
        for k,v in vals.items():scalars[k].append(v)
        wet=rain>.01
        wet_mask.append(wet)
        # fixed UTC calendar clock class; provide year/month grouping in caller.
        scalars["_rain_is_wet"].append(int(wet))
        scalars["_rain_daylight_ratio"].append(
            dhi/ghi if ghi>20 else math.nan)
        selected+=1
    metrics={"hourly_records_scored":selected,"hourly_records_expected":n,
             "hard_QC_failures":dict(bad),"diagnostic_warnings":dict(warn),
             "hard_QC_pass":not any(bad.values()),
             "rain_positive_hour_count":sum(wet_mask),
             "mean_temperature_C":statistics.fmean(scalars["temperature_2m"]) if selected else None,
             "mean_RH_percent":statistics.fmean(scalars["relative_humidity_2m"]) if selected else None,
             "mean_cloud_percent":statistics.fmean(scalars["cloud_cover"]) if selected else None,
             "rain_total_recorded_mm":sum(scalars["precipitation"]),
             "annual_or_window_GHI_kWh_m2":sum(scalars["shortwave_radiation"])/1000,
             "mean_wind_speed_ms":statistics.fmean(scalars["wind_speed_10m"]) if selected else None,
             "monthly_hour_eligible_rain_cloud_RH_comparison":False,
             "independent_station_observation_QA_performed":False,
            }
    # Requested period timestamp context is provided separately by caller:
    # avoid using a fictitious month where UTC offsets differ.
    return metrics


def grouped_month_hour(arrays,times):
    group=collections.defaultdict(lambda:{"wet":[],"dry":[]})
    for i,stamp in enumerate(times):
        if any(arrays[k][i] is None for k in ("precipitation","cloud_cover","relative_humidity_2m",
                                               "shortwave_radiation","diffuse_radiation")):
            continue
        month=int(stamp[5:7]);hour=int(stamp[11:13])
        wet=arrays["precipitation"][i]>.01
        cc=arrays["cloud_cover"][i];rh=arrays["relative_humidity_2m"][i]
        ghi=arrays["shortwave_radiation"][i];dhi=arrays["diffuse_radiation"][i]
        group[(month,hour)]["wet" if wet else "dry"].append(
            (cc,rh,dhi/ghi if ghi>20 else None))
    contrasts=[];weights=[]
    for d in group.values():
        if not d["wet"] or not d["dry"]:continue
        byfeature=[]
        for j in range(3):
            wa=[x[j] for x in d["wet"] if x[j] is not None]
            da=[x[j] for x in d["dry"] if x[j] is not None]
            byfeature.append(statistics.fmean(wa)-statistics.fmean(da)
                             if wa and da else None)
        contrasts.append(byfeature);weights.append(len(d["wet"]))
    return {
        "eligible_month_UTC_hour_comparison_cells":len(contrasts),
        "rain_minus_dry_same_month_UTC_hour_cloud_percentage_points":
            _weighted([(c[0],w) for c,w in zip(contrasts,weights)]),
        "rain_minus_dry_same_month_UTC_hour_RH_percentage_points":
            _weighted([(c[1],w) for c,w in zip(contrasts,weights)]),
        "rain_minus_dry_same_month_UTC_hour_diffuse_fraction":
            _weighted([(c[2],w) for c,w in zip(contrasts,weights)]),
        "conditional_rain_cloud_physics_qualified_against_observations":False,
    }


def _weighted(items):
    good=[(v,w) for v,w in items if v is not None and w>0]
    return sum(v*w for v,w in good)/sum(w for _,w in good) if good else None


def run(lat,lon,start,end,name,out):
    url=request_url(lat,lon,start,end)
    src=get_original_source(url)
    obj,arr,meta=parse_source(src,lat,lon,start,end)
    check=statistics_and_coherence(arr)
    check.update(grouped_month_hour(arr,obj["hourly"]["time"]))
    out_obj={
        "phase":"IGE_P9_1A_GLOBAL_HISTORICAL_SOURCE_BACKBONE",
        "name":name,
        "source_scope":SOURCE_SCOPE,
        "exact_original_requested_URL":url,
        "meta":meta,
        "source_physical_QC":check,
        "climate_model_requested":MODEL,
        "ERA5_CDS_native_grid_files_directly_queried":False,
        "provider_site_height_accepted_as_authentic_DEM":False,
        "future_climate_projection_performed":False,
        "EPW_export_verified":False,
        "source_hourly_records_archived":False,
        "target_site_weather_skill_independently_validated":False,
        "global_coverage_provider_capability_not_independently_validated":True,
        "production_epw_ready":False,
    }
    if not check["hard_QC_pass"]:
        # retain audit even if physically invalid
        status="P9_1A_SOURCE_QC_FAIL"
    else:
        status="P9_1A_SOURCE_QC_PASS"
    out_obj["source_QC_decision"]=status
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    f=p/(name+".json")
    f.write_text(json.dumps(out_obj,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("IGE_P9_1A",json.dumps({"site":name,"QC":status,
          "hours":meta["n_received_hourly_rows"],"grid_km":round(
          meta["selected_cell_distance_km"],3),
          "source_sha256":meta["raw_original_response_sha256"],
          "cloud_mean_percent":check["mean_cloud_percent"],
          "rain_hours":check["rain_positive_hour_count"],
          "production_ready":False}),flush=True)
    if not check["hard_QC_pass"]:
        raise RuntimeError("P9_1A_SOURCE_PHYSICAL_QC_FAIL_READ_AGGREGATE")
    return out_obj


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--lat",type=float,required=True)
    p.add_argument("--lon",type=float,required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--name",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    run(a.lat,a.lon,a.start,a.end,a.name,a.out)
