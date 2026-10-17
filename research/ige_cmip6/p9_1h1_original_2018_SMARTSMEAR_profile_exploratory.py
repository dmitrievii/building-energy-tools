#!/usr/bin/env python3
"""P9.1H1 independent ORIGINAL SmartSMEAR 2018 tower exploratory source audit.

Real sensor values are read but their native QC is not authenticated; ALL
inversion descriptive results are provisional. No ERA5 fitting or holdout read.
"""
from __future__ import annotations
import collections
import datetime as dt
import hashlib
import json
import math
import statistics
import urllib.parse
import urllib.request
from pathlib import Path

BASE="https://smear-backend.2.rahtiapp.fi/search/timeseries"
COLUMNS={"T42":"HYY_META.T42","T672":"HYY_META.T672"}
PERIODS=(("2018_JAN_10_TO_16","2018-01-10T00:00:00","2018-01-17T00:00:00"),
         ("2018_JUL_10_TO_16","2018-07-10T00:00:00","2018-07-17T00:00:00"))
LOCAL_STANDARD_TZ=dt.timezone(dt.timedelta(hours=2))
MIN_REAL_PAIRS_PER_HOUR=45
SOURCE_READ_LIMIT=3_000_000

def read_original_data(variable:str,start:str,end:str):
    if variable not in COLUMNS.values() or (start,end) not in ((x[1],x[2]) for x in PERIODS):
        raise ValueError("P9H1_UNREGISTERED_SOURCE_SENSOR_OR_DATE_WINDOW")
    params={"tablevariable":variable,"from":start,"to":end}
    url=BASE+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={
        "User-Agent":"IGE-P9.1H1-HYY-2018-actual-development-source-QC-unqualified",
        "Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r:
        if r.geturl()!=url:
            raise ValueError("P9H1_UNREGISTERED_SOURCE_REDIRECT")
        original=r.read(SOURCE_READ_LIMIT+1)
    if len(original)>SOURCE_READ_LIMIT:
        raise ValueError("P9H1_ORIGINAL_SOURCE_RESPONSE_TOO_LARGE")
    content=json.loads(original)
    if not isinstance(content,dict) or not isinstance(content.get("data"),list):
        raise ValueError("P9H1_SMARTSMEAR_ORIGINAL_SOURCE_DATA_STRUCTURE_CHANGED")
    if len(content["data"])<720 or len(content["data"])>11000:
        raise ValueError("P9H1_NO_EXPECTED_ORIGINAL_7DAY_CADENCE_SUPPORT")
    return content,{
        "source_original_payload_SHA256":hashlib.sha256(original).hexdigest(),
        "source_original_length_bytes":len(original),
        "registered_source_variable":variable,
        "registered_request_parameters":params,
        "provider_returned_aggregation":content.get("aggregation"),
        "provider_returned_aggregation_interval":content.get("aggregationInterval"),
        "provider_returned_recordCount":content.get("recordCount"),
        "provider_returned_startTime":content.get("startTime"),
        "provider_returned_endTime":content.get("endTime"),
        "source_native_original_bytes_NOT_uploaded":True,
    }

def native_timestamp(stamp):
    if not isinstance(stamp,str):
        raise ValueError("P9H1_UNEXPECTED_SMARTSMEAR_NATIVE_TIMESTAMP_TYPE")
    parsed=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
    if parsed.tzinfo is None:
        # SMEAR database documented *local standard UTC+2, no DST*.
        parsed=parsed.replace(tzinfo=LOCAL_STANDARD_TZ)
    elif parsed.utcoffset()!=LOCAL_STANDARD_TZ.utcoffset(None):
        # Do not silently reinterpret a Z or DST stamp as Helsinki standard time.
        raise ValueError("P9H1_NATIVE_TIMESTAMP_OFFSET_CONFLICT_WITH_SMARTSMEAR_DOC")
    if parsed.second or parsed.microsecond:
        raise ValueError("P9H1_NOT_EXACT_NATIVE_MINUTE_TIMESTAMPS")
    return parsed.astimezone(dt.timezone.utc)

def measured_valid_temp(value):
    if value is None: return False
    if isinstance(value,bool): return False
    try: val=float(value)
    except (TypeError,ValueError): return False
    return math.isfinite(val) and -90<=val<=60 and val != -999.0

def parse_native_series(payload,variable,start,end):
    lower=dt.datetime.fromisoformat(start).replace(tzinfo=LOCAL_STANDARD_TZ).astimezone(dt.timezone.utc)
    upper=dt.datetime.fromisoformat(end).replace(tzinfo=LOCAL_STANDARD_TZ).astimezone(dt.timezone.utc)
    entries={}
    excluded_outside=0;missing=0
    for row in payload["data"]:
        if not isinstance(row,dict) or "samptime" not in row or variable not in row:
            raise ValueError("P9H1_ORIGINAL_SMARTSMEAR_ROW_COLUMNS_CHANGED")
        t=native_timestamp(row["samptime"])
        if not lower<=t<upper:
            excluded_outside+=1
            continue
        if t in entries:
            raise ValueError("P9H1_DUPLICATE_NATIVE_SENSOR_TIMESTAMP")
        value=row[variable]
        if measured_valid_temp(value):
            entries[t]=float(value)
        else:
            entries[t]=None;missing+=1
    return entries,{"n_native_time_support":len(entries),
                    "n_unusable_native_values":missing,
                    "n_provider_rows_outside_registered_window":excluded_outside}

def sample_2018_site():
    out=[]
    for name,start,end in PERIODS:
        series={};prov={};nmeta={}
        for var in COLUMNS.values():
            body,metadata=read_original_data(var,start,end)
            one,flags=parse_native_series(body,var,start,end)
            series[var]=one;prov[var]=metadata;nmeta[var]=flags
        m1=series[COLUMNS["T42"]];m2=series[COLUMNS["T672"]]
        raw_pairs=[]
        for stamp in sorted(m1.keys() & m2.keys()):
            a,b=m1[stamp],m2[stamp]
            if a is None or b is None:
                continue
            delta=b-a
            raw_pairs.append((stamp,delta))
        byhour=collections.defaultdict(list)
        for stamp,delta in raw_pairs:
            byhour[stamp.replace(minute=0)].append((stamp.minute,delta))
        qualified_hourly=[]
        for stamp,values in sorted(byhour.items()):
            minutes=[m for m,_ in values]
            if len(minutes)!=len(set(minutes)):
                raise ValueError("P9H1_DUPLICATE_SYNCHRONOUS_MINUTE_PAIR")
            if len(values)<MIN_REAL_PAIRS_PER_HOUR:
                continue
            mean_delta=statistics.fmean(x for _,x in values)
            qualified_hourly.append((stamp,mean_delta))
        if not raw_pairs or not qualified_hourly:
            raise ValueError("P9H1_NO_REAL_ORIGINAL_SIMULTANEOUS_TEMPERATURE_PROFILES")
        delta_values=[delta for _,delta in raw_pairs]
        hours_delta=[x for _,x in qualified_hourly]
        out.append({
            "period":name,
            "original_response_provenance":prov,
            "native_original_timestep_QC_unknown":nmeta,
            "native_timezone_fixed_UTC_plus_2":True,
            "paired_vertical_sensor_height_AGL_m":[4.2,67.2],
            "dz_m":63.,
            "n_actual_synchronous_unfilled_original_api_temperature_pairs":len(raw_pairs),
            "n_hourly_pairs_ge_45_of_60_real_simultaneous_samples":len(hours_delta),
            "original_api_unqualified_sample_delta_mean_K":statistics.fmean(delta_values),
            "original_api_unqualified_hourly_delta_mean_K":statistics.fmean(hours_delta),
            "original_api_unqualified_hourly_delta_min_K":min(hours_delta),
            "original_api_unqualified_hourly_delta_max_K":max(hours_delta),
            "original_api_unqualified_hourly_fraction_positive_0p1K":
                statistics.fmean(x>0.10 for x in hours_delta),
            "original_api_unqualified_hourly_fraction_negative_below_neg0p1K":
                statistics.fmean(x< -0.10 for x in hours_delta),
            "all_metrics_descriptive_only_no_ERA5_or_model_fit":True,
            "provider_QC_not_verified":True,
        })
    return {
        "phase":"P9.1H1_ORIGINAL_INDEPENDENT_2018_HYYTIALA_DEVELOPMENT_SENSOR_PROFILE_EXPLORATORY",
        "provider":"University_of_Helsinki_SMEAR_II",
        "observational_source":"HYY_META.T42 HYY_META.T672",
        "n_registered_periods":len(PERIODS),
        "periods":out,
        "2021_temporal_holdout_unread":True,
        "sensor_source_original_sha256_authenticated":True,
        "provider_native_sensor_QC_tier_qualified":False,
        "ERA5_vs_observed_temperature_skill_not_scored":True,
        "near_surface_inversion_model_qualified":False,
        "global_arbitrary_point_weather_qualified":False,
        "production_epw_ready":False,
    }

def main():
    folder=Path("outputs/p9h1")
    folder.mkdir(parents=True,exist_ok=True)
    x=sample_2018_site()
    path=folder/"smartsmear_2018_real_measured_temp_profile_EXPLORATORY_QC_UNQUALIFIED.json"
    path.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n")
    print("P9H1_REAL_2018_ORIGINAL_SOURCE_PROVISIONAL",json.dumps(x,ensure_ascii=False))
if __name__=="__main__":
    main()
