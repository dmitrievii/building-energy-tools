#!/usr/bin/env python3
"""P9.2D independent strict research-only joint-hourly weather -> EPW exporter.

All original model-generation input days are UTC; map to fixed local standard
CET (+01:00) without DST, using the previous-year UTC boundary hour. No
synthetic cloudy/solar illuminance or opaque sky-cover is invented. This code
is a FORMAT/PHYSICAL readback, NOT scientific forecast or release qualification.
"""
from __future__ import annotations
import csv,datetime as dt,hashlib,math,statistics
from pathlib import Path
from p9_2a_joint_weather_regimes import check_vector
from p9_2b_cmip6_daily_joint_regime_solver import sat_pa,SIGMA

YEAR=2013
TZ=1
LOCATION_LAT=47.0707
LOCATION_LON=15.4395
ELEVATION_M_UNVERIFIED_GCM_GRID_PROXY=366.
EPW_FIELDS=35
HOURS=8760

class EPWBlocked(ValueError):
    pass

def timestamp_rows(weather_days,longwave_per_day,year=YEAR):
    if len(weather_days)!=len(longwave_per_day):
        raise EPWBlocked("P92D_ORIGINAL_DAILY_SOURCE_LW_ALIGNMENT_MISMATCH")
    original={}
    for day,lw in zip(weather_days,longwave_per_day):
        if len(lw)!=24:
            raise EPWBlocked("P92D_LW_MISSING_NATIVE_HOURLY_24")
        for h,(v,ir) in enumerate(zip(day.vectors,lw)):
            check_vector(v)
            if not isinstance(ir,(float,int)) or not math.isfinite(ir) or not 50<ir<1000:
                raise EPWBlocked("P92D_GENERATED_LW_OUTSIDE_PHYSICAL_RANGE")
            utc=dt.datetime.combine(day.date,dt.time(hour=h),tzinfo=dt.timezone.utc)
            if utc in original:
                raise EPWBlocked("P92D_DUPLICATE_UTC_HOUR")
            original[utc]=(dict(v),float(ir))
    first=dt.datetime(year,1,1,0,0)
    intervals=[]
    for index in range(HOURS):
        local=first+dt.timedelta(hours=index)
        utc=(local-dt.timedelta(hours=TZ)).replace(tzinfo=dt.timezone.utc)
        if utc not in original:
            raise EPWBlocked("P92D_MISSING_CROSSYEAR_UTC_TO_CET_HOUR_"+utc.isoformat())
        intervals.append((local,utc,*original[utc]))
    if intervals[0][1]!=dt.datetime(year-1,12,31,23,tzinfo=dt.timezone.utc):
        raise EPWBlocked("P92D_WRONG_CET_PREVIOUS_YEAR_START")
    if intervals[-1][1]!=dt.datetime(year,12,31,22,tzinfo=dt.timezone.utc):
        raise EPWBlocked("P92D_WRONG_CET_FINAL_HOUR")
    return intervals

def epw_header(year=YEAR):
    if year not in (2013,2014):
        raise EPWBlocked("P92D_FIXED_PREREGISTERED_CALENDAR_ONLY_2013")
    return [
        ["LOCATION","Graz-IGE-P9.2D-JOINT-RESEARCH-ONLY","Styria","AUT",
         "IGE_NASA_CANESM5_OPENMETEO_ERA5_NONPRODUCTION","999999",
         LOCATION_LAT,LOCATION_LON,TZ,ELEVATION_M_UNVERIFIED_GCM_GRID_PROXY],
        ["DESIGN CONDITIONS",0],
        ["TYPICAL/EXTREME PERIODS",0],
        ["GROUND TEMPERATURES",0],
        ["HOLIDAYS/DAYLIGHT SAVINGS","No",0,0,0],
        ["COMMENTS 1","NASA NEX-GDDP-CMIP6 CanESM5 2013 daily + ERA5 2019/2020 joint analogues. Research only. NO independent station cloud/rain/solar validation."],
        ["COMMENTS 2","Fixed CET UTC+1, no DST; 2012-12-31 23:00 UTC required. GCM grid 46.875,15.375 differs donor 47.0707,15.4395. Opaque sky and photometry MISSING; LW derived proxy; sky donor analogues."],
        ["DATA PERIODS",1,1,f"P9.3A SYNTHETIC RESEARCH HISTORICAL YEAR {year}", "Tuesday" if year==2013 else "Wednesday","1/1","12/31"]
    ]

def make_record(local,v,ir):
    t=float(v["temperature_2m"]);td=float(v["dew_point_2m"])
    rh=float(v["relative_humidity_2m"]);p=float(v["surface_pressure"])*100
    ghi=float(v["shortwave_radiation"]);dni=float(v["direct_normal_irradiance"])
    dhi=float(v["diffuse_radiation"]);direct=float(v["direct_radiation"])
    rain=float(v["precipitation"])
    # Original reanalysis fields are irradiances W/m² averaged over one
    # hour. EPW solar fields are Wh/m² integrated over the reporting hour:
    # factor = 1 h. No performance claims about provider interval support.
    if abs(ghi-direct-dhi)>1.e-5:
        raise EPWBlocked("P92D_SOLAR_GHI_DHI_DIRECT_H_DIFFERENCE")
    if not -95<t<65 or td>t+0.51 or not 0<=rh<=100:
        raise EPWBlocked("P92D_EPWAIR_INVALID")
    if not 0<ghi+1 or not 0<=dni<1600 or not 0<=dhi<1600 or not 50<ir<1000:
        raise EPWBlocked("P92D_EPWRADIATION_INVALID")
    if 100*sat_pa(td)/sat_pa(t)>100.5:
        raise EPWBlocked("P92D_HOURLY_DEWPOINT_ABOVE_SATURATION")
    wind_dir=float(v["wind_direction_10m"])
    if not 0<=wind_dir<=360:
        raise EPWBlocked("P92D_WIND_DIRECTION_SOURCE_MISSING")
    cloud=float(v["cloud_cover"])
    sky_tenths=int(round(cloud/10))
    row=[local.year,local.month,local.day,local.hour+1,60,
         "?9"*22,
         round(t,3),round(td,3),round(rh,3),round(p,1),
         9999,9999,round(ir,3),
         round(ghi,3),round(dni,3),round(dhi,3),
         999999,999999,999999,9999,
         round(wind_dir,2),round(float(v["wind_speed_10m"]),3),
         sky_tenths,99,
         9999,99999,9,"999999999",999,0.999,999,99,999,
         round(rain,5),1 if rain>0 else 0]
    if len(row)!=35:
        raise EPWBlocked("P92D_EPW_35_FIELD_SCHEMA_FAILED")
    return row

def raw_series_to_epw(weather_days,lw_per_day,output,year=YEAR):
    intervals=timestamp_rows(weather_days,lw_per_day,year)
    records=[make_record(local,v,ir) for local,utc,v,ir in intervals]
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("w",newline="",encoding="utf8") as f:
        writer=csv.writer(f,lineterminator="\n")
        writer.writerows(epw_header(year));writer.writerows(records)
    result=readback(output,year=year)
    if result["n_records"]!=HOURS:
        raise EPWBlocked("P92D_POSTEXPORT_HOURLY_SOURCE_COUNT_WRONG")
    return result

def readback(path,year=YEAR):
    path=Path(path)
    if not path.is_file():raise EPWBlocked("P92D_RESEARCH_EPW_FILE_MISSING")
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.reader(f);headers=[next(reader) for _ in range(8)]
        rows=list(reader)
    if len(rows)!=HOURS or any(len(row)!=EPW_FIELDS for row in rows):
        raise EPWBlocked("P92D_READBACK_NOT_8760x35")
    if not headers[0] or headers[0][0]!="LOCATION":
        raise EPWBlocked("P92D_READBACK_LOCATION_HEADER_INVALID")
    if not all((len(h)>0 and h[0] in [
            "LOCATION","DESIGN CONDITIONS","TYPICAL/EXTREME PERIODS",
            "GROUND TEMPERATURES","HOLIDAYS/DAYLIGHT SAVINGS",
            "COMMENTS 1","COMMENTS 2","DATA PERIODS"]) for h in headers):
        raise EPWBlocked("P92D_READBACK_EIGHT_EPWHDRS_INVALID")
    if float(headers[0][8])!=TZ or float(headers[0][6])!=LOCATION_LAT:
        raise EPWBlocked("P92D_WRONG_STANDARD_TIME_OR_LOCATION")
    stats={"missing_opaque_cloud_count":0,"missing_illuminance_count":0,
           "missing_visibility_count":0,"no_future_wind_direction_source":True,
           "wind_direction_value_count":0,"valid_total_sky_cover_hours":0,
           "wet_hours":0,"saturated_RH_hours":0}
    mismatches=[]
    for i,row in enumerate(rows):
        exp=dt.datetime(year,1,1)+dt.timedelta(hours=i)
        if [int(x) for x in row[:5]] != [year,exp.month,exp.day,exp.hour+1,60]:
            raise EPWBlocked("P92D_READBACK_WRONG_NON_DST_CET_CALENDAR")
        if str(row[23])=="99":stats["missing_opaque_cloud_count"]+=1
        if str(row[16])=="999999":stats["missing_illuminance_count"]+=1
        if str(row[24])=="9999":stats["missing_visibility_count"]+=1
        if not 0<=float(row[22])<=10 or not 0<=float(row[20])<=360:
            raise EPWBlocked("P92D_READBACK_WIND_OR_SKYCOVER_DOMAIN")
        stats["wind_direction_value_count"]+=1
        stats["valid_total_sky_cover_hours"]+=1
        if float(row[33])>0:stats["wet_hours"]+=1
        if float(row[8])>=99.995:stats["saturated_RH_hours"]+=1
        v=[float(row[j]) for j in (6,7,8,9,12,13,14,15,20,21,22,33,34)]
        if any(not math.isfinite(vj) for vj in v):
            raise EPWBlocked("P92D_READBACK_NONFINITE_ORIGINAL_FIELD")
        t,td,rh,p,ir,ghi,dni,dhi,wdir,wspd,sky,rain,hours=v
        if not (-95<t<65 and td<=t+.51 and 0<=rh<=100 and 30000<p<115000):
            raise EPWBlocked("P92D_READBACK_THERMODYNAMICS_INVALID")
        if not (0<=ghi<=1600 and 0<=dni<=1600 and 0<=dhi<=1600
                and 0<=wspd<=90 and 50<ir<1000):
            raise EPWBlocked("P92D_READBACK_ENERGY_OR_WIND_INVALID")
        if hours!=(1 if rain>0 else 0):
            raise EPWBlocked("P92D_LIQUID_PRECIPITATION_HOURS_OR_DEPTH_WRONG")
    header_bytes=path.read_bytes()
    return {"status":"RESEARCH_EPW_FORMAT_AND_PHYSICAL_READBACK_PASS",
      "sha256":hashlib.sha256(header_bytes).hexdigest(),
      "year":year,"time_zone_hours":TZ,
      "DST":"DISABLED","n_records":len(rows),"fields_per_record":EPW_FIELDS,
      "n_headers":8,"first_local_row":rows[0][:5],"last_local_row":rows[-1][:5],
      "has_required_prev_year_UTC_boundary":True,
      "source_original_total_cloud_as_EPW_total_sky_only":True,
      "opaque_sky_cover_NOT_PROVIDED":True,
      "global_direct_diffuse_illuminance_NOT_PROVIDED":True,
      "precipitation_measurement_period_h":1,
      "EPW_standard_time_offset_and_GCM_daily_UTC_calendar_are_different":True,
      "weather_source_is_stochastic_GCM_reanalysis_reconstruction":True,
      "cross_field_observation_skill_qualified":False,
      "production_epw_ready":False,**stats}
