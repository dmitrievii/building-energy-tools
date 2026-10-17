#!/usr/bin/env python3
"""IGE P9.2D single original CanESM5 2013 full-year physical EPW gate pilot.

Native NASA NEX-GDDP-CMIP6 original 2012-12-31 UTC boundary and full 2013
daily records, single model/member; Open-Meteo fixed-grid ERA5 2019 and 2020
original hourly annual donors. No missing source filling. 8760 CET EPW emitted
only if every day physically qualified; full source/QA kept as aggregates.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
import p7c3_ensemble as cmip
import p9_1a_global_historical_backbone as era
from p9_2a_joint_weather_regimes import canonical_days
from p9_2c_physical_donor_and_humidity import generate
from p9_2d_annual_cet_epw_export import raw_series_to_epw,EPWBlocked

YEAR=2013
GRID_LAT=46.875;GRID_LON=15.375
DONOR_LAT=47.0707;DONOR_LON=15.4395
P6_WINDOW=cmip.HIST
MODEL="CanESM5"
SEED=7313
N_NATIVE_DAYS=365
N_GENERATED_WITH_BOUNDARY=366
RESEARCH_EPW_NAME="Graz_IGE_P92D_CanESM5_2013_joint_hourly_CET_RESEARCH_ONLY.epw"

def original_gcm(source):
    original,meta=cmip.read_source(source,MODEL,P6_WINDOW)
    registered=json.loads(Path("research/ige_cmip6/p7c3_expected_daily_source_shas.json").read_text())["source_sha256"]["CanESM5_"+P6_WINDOW]
    if meta["daily_csv_sha256"]!=registered:
        raise ValueError("P92D_ORIGINAL_NASA_REGISTERED_DAILY_DATA_SHA_MISMATCH")
    # GCM noleap native historical original; 2012 Dec31 valid regardless
    # Gregorian leap calendar, source native 365_day keeps Feb29 absent.
    desired={dt.date(YEAR-1,12,31)}|{dt.date(YEAR,1,1)+dt.timedelta(days=i) for i in range(N_NATIVE_DAYS)}
    found={r["date"]:r for r in original if r["date"] in desired}
    if len(found)!=len(desired):
        raise ValueError("P92D_ORIGINAL_CMIP6_BOUNDARY_2012_AND_ALL_2013_MISSING")
    return [found[d] for d in sorted(desired)],meta

def original_era5_year(year):
    start=f"{year}-01-01";end=f"{year}-12-31"
    url=era.request_url(DONOR_LAT,DONOR_LON,start,end)
    raw=era.get_original_source(url,timeout=95)
    obj,arrays,meta=era.parse_source(raw,DONOR_LAT,DONOR_LON,start,end)
    source_sha=meta["raw_original_response_sha256"]
    donors=canonical_days([x+"Z" for x in obj["hourly"]["time"]],arrays,source_sha)
    if len(donors) not in (365,366):
        raise ValueError("P92D_AUTHENTIC_ORIGINAL_ERA5_YEAR_INCOMPLETE")
    if len(donors)!=((dt.date(year+1,1,1)-dt.date(year,1,1)).days):
        raise ValueError("P92D_AUTHENTIC_ERA5_LEAP_CALENDAR_BAD")
    print("P92D_ORIGINAL_ERA5_YEAR",json.dumps({
         "year":year,"n_days":len(donors),"n_hours":len(obj["hourly"]["time"]),
         "source_sha256":source_sha,
         "canonical_hourly_sha256":meta["canonical_hourly_weather_and_selected_cell_sha256"],
         "selected_grid_latitude":meta["selected_cell_latitude"],
         "selected_grid_longitude":meta["selected_cell_longitude"]
         }),flush=True)
    return donors,{"year":year,"original_source_http_sha256":source_sha,
        "canonical_source_weather_sha256":meta["canonical_hourly_weather_and_selected_cell_sha256"],
        "selected_grid_lat_lon":[meta["selected_cell_latitude"],meta["selected_cell_longitude"]],
        "original_era5_hourly_source_count":len(obj["hourly"]["time"]),
        "source_kind":era.SOURCE_SCOPE}

def run(original_csv_zip,out):
    out.mkdir(parents=True,exist_ok=True)
    targets,meta=original_gcm(original_csv_zip)
    report={"phase":"IGE_P9_2D_2013_FULL_ANNUAL_GRAZ_GENUINE_NASA_CANESM5_EPWCET_SOURCE_PILOT",
            "source_kind":"ORIGINAL_NASA_NEX_GDDP_CMIP6_V2_CMIP6_DAILY_PLUS_ERA5_OPENMETEO_HOURLY",
            "model":MODEL,"member":"r1i1p1f1","scenario":"historical",
            "target_year":YEAR,"input_native_calendar":meta["calendar"],
            "input_GCM_grid_lat_lon":[GRID_LAT,GRID_LON],
            "donor_ERA5_point_lat_lon":[DONOR_LAT,DONOR_LON],
            "source_original_registered_SHA256":meta["daily_csv_sha256"],
            "model_CanESM5_selected_native_year_count":N_NATIVE_DAYS,
            "extra_native_source_boundary":"2012-12-31T23:00UTC",
            "source_native_daily_target_count_including_boundary":N_GENERATED_WITH_BOUNDARY,
            "2019_2020_hourly_openmeteo_donors_are_not_native_ECMWF_CDS_grib":True,
            "year_is_not_TMY_and_not_future_forecast":True,
            "expected_local_EPWCET_hours":8760,
            "EPW_timezone_CET_no_DST":True,"random_seed":SEED,
            "source_photometric_illuminance_unavailable":True,
            "source_opaque_cloud_cover_unavailable":True,
            "source_cloud_ERA5_analogue_not_native_CMIP6_cloud":True,
            "climate_2025_observed_T_RH_negative_vs_ERA5_is_unchanged":True,
            "EPW_only_created_if_all_source_days_physically_closed":True,
            "production_epw_ready":False,
            "original_CMIP6_source_sha256_and_qc":meta,
            "source_ERA5_original_2019_2020_sha256":[],
            "epw_file":None}
    donors=[]
    for y in (2019,2020):
        d,m=original_era5_year(y)
        donors.extend(d);report["source_ERA5_original_2019_2020_sha256"].append(m)
    report["number_of_original_ERA5_donor_days"]=len(donors)
    print("P92D_START_SOURCE_DONOR_GENERATOR",json.dumps({
         "n_target_days":len(targets),"n_source_days":len(donors),
         "registered_source_sha256":meta["daily_csv_sha256"]}),flush=True)
    good,bad=generate(targets,donors,DONOR_LAT,DONOR_LON,SEED)
    n= len(targets)
    if len(good)+len(bad)!=n:raise ValueError("P92D_SOURCE_DAY_CENSUS_NOT_ACCOUNTED")
    report["n_qualified_original_native_days_including_boundary"]=len(good)
    report["n_physically_blocked_original_native_days_including_boundary"]=len(bad)
    report["full_original_native_source_daily_hard_conservation_qualified"]=len(bad)==0
    report["blocked_source_days"]=[{"date":x["date"],"status":x["status"],
              "candidate_rejection_codes":x["candidate_rejection_codes"]} for x in bad]
    original_native_days={d.date for d,lw,info in good if d.date.year==YEAR}
    report["n_original_native_2013_days_hard_conserved"]=len(original_native_days)
    report["n_hurs_huss_joint_physically_closed_days"]=sum(
        info["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH" for _,lw,info in good)
    report["n_native_hurs_unresolved_days"]=sum(
        info["hurs_joint_status"]!="FEASIBLE_BOTH_Q_AND_RH" for _,lw,info in good)
    report["hurs_status_histogram"]=dict(collections.Counter(
        info["hurs_joint_status"] for _,lw,info in good))
    report["n_source_donors_prequalified"]=sum(info["n_physically_admissible_donors"] for _,_,info in good)
    report["native_daily_hurs_max_absolute_residual_pp"]=max(
       (abs(info["P92C_hurs_residual_pp"]) for _,lw,info in good),default=None)
    report["cross_day_temperature_seam_absolute_jump_C"]=None
    if len(good)>1:
        report["cross_day_temperature_seam_absolute_jump_C"]=statistics.fmean(
            abs(a[0].vectors[-1]["temperature_2m"]-b[0].vectors[0]["temperature_2m"])
            for a,b in zip(good,good[1:]) if (b[0].date-a[0].date).days==1)
    if len(bad)==0:
        epw=out/RESEARCH_EPW_NAME
        audit=raw_series_to_epw([d for d,lw,inf in good],
                      [lw for d,lw,inf in good],epw,year=YEAR)
        report["epw_file"]=RESEARCH_EPW_NAME
        report["epw_original_hourly_readback"]=audit
        report["annual_epw_source_generator_status"]="GENUINE_SOURCE_RESEARCH_EPW_WRITTEN_FORMAT_PASS"
    else:
        report["annual_epw_source_generator_status"]="ORIGINAL_CMIP6_ANNUAL_SOURCE_SOME_DAYS_PHYSICALLY_BLOCKED_NO_EPW_WRITTEN"
        report["epw_original_hourly_readback"]=None
    gates={"G0_registered_original_daily_and_hourly_SHA":"PASS",
       "G1_registered_365_gcm_days_plus_2012_boundary":"PASS",
       "G2_all_native_366_days_physically_closed":"PASS" if not bad else "BLOCKED",
       "G3_CET_8760x35_EPWAudit":"PASS" if report["epw_file"] else "BLOCKED",
       "G4_native_annual_hurs_and_huss_simultaneously_closed":"PASS" if not report["n_native_hurs_unresolved_days"] and not bad else "BLOCKED",
       "G5_original_license_28_P7C5B_byte_source_recensus":"BLOCKED",
       "G6_original_private_28_EnergyPlus":"BLOCKED",
       "G7_original_station_2025_T_RH_superior_to_ERA5":"FAIL",
       "G8_AT_DE_CH_native_measured_solar_rain_cloud_LW_independent_QC":"NOT_QUALIFIED",
       "G9_generated_opaque_cloud_and_illuminance_measured":"NOT_AVAILABLE",
       "G10_arbitrary_point_full_weather_generalization":"NOT_QUALIFIED",
       "G11_production_EPWB_released":"BLOCKED"}
    report["scientific_release_gates"]=gates
    (out/"p9_2d_annual_original_CanESM5_2013_epw_physics_census.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print("P92D_ORIGINAL_ANNUAL_FINAL",json.dumps({
        "target_days":n,"generated_days":len(good),"blocked_days":len(bad),
        "joint_huss_hurs_days":report["n_hurs_huss_joint_physically_closed_days"],
        "epw_written":bool(report["epw_file"]),
        "epw_sha256":report.get("epw_original_hourly_readback",{}).get("sha256") if report["epw_file"] else None,
        "native_source_status":report["annual_epw_source_generator_status"],
        "no_production_release":True}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--canonical-original-canesm5-zip",required=True)
    p.add_argument("--out",default="outputs/p92d-annual")
    a=p.parse_args()
    run(Path(a.canonical_original_canesm5_zip),Path(a.out))
