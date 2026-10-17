#!/usr/bin/env python3
"""P9.3A one prospective 2014 original CanESM5 full-year source evaluation.

Physical pressure is external original ERA5 hourly, not native NEX GCM ps.
One frozen source/day cohort, seed 7313, source bytes verified by P7C3.
No real 8760 EPW unless all original 365+UTC boundary targets physically
qualified. If full EPW exists, export strict CET UTC+1 2014. No GCM tuning.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,hashlib,json,statistics
from pathlib import Path

import p7c3_ensemble as gcm
from p9_2d_original_canesm5_2013_annual_source_epw_pilot import (
    original_era5_year,RESEARCH_EPW_NAME,DONOR_LAT,DONOR_LON,GRID_LAT,GRID_LON)
from p9_3a_pressure_temperature_q_joint import (
    generate,PRESSURE_MODE,VERSION,MAX_ADJUST_C,MAX_REPAIR_CANDIDATES,SEED)
from p9_2d_annual_cet_epw_export import raw_series_to_epw

YEAR=2014
SOURCE_HASH="77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef"
# Canonical selected-grid, 12-field hourly original weather digest:
# provider HTTP JSON envelope may change across requests (generation time etc.).
# Never accept altered canonical weather. Keep raw SHA as provenance too.
EXPECTED_ERA5_CANONICAL_SHA={
    2019:"ac9749eb1cee4d2246b60871f1a139d8920451e30b8ed54ea134431fa0de4c29",
    2020:"275804a076a81c3c8ae9a572e0359ca524ef9c90627ccca2c6862805093b019c"}
PRIOR_ERA5_RAW_RESPONSE_SHA={
    2019:"9c7a19d5ae018df41dc6045de4d5cc2e9e8ae37d63e361bad3e079e1d2c97576",
    2020:"1b18154ca9f0a774a500a9a4e4dab7744cc1866f590fef36ec1e2db09ee6c4b9"}
FILE="Graz_P93A_CanESM5_2014_ERA5_joint_pressure_T_q_CET_RESEARCH_ONLY.epw"

def native_2014(path):
    records,metadata=gcm.read_source(path,"CanESM5",gcm.HIST)
    if metadata["daily_csv_sha256"]!=SOURCE_HASH:
        raise ValueError("P93A_NATIVE_ORIGINAL_CANESM5_DAILY_SHA_NOT_REGISTERED")
    expected=[dt.date(YEAR-1,12,31)]+[
        dt.date(YEAR,1,1)+dt.timedelta(days=i) for i in range(365)]
    bydate={r["date"]:r for r in records if r["date"] in set(expected)}
    if len(bydate)!=366:
        raise ValueError("P93A_ORIGINAL_2013_BOUNDARY_2014_DAILY_SOURCE_INCOMPLETE")
    return [bydate[d] for d in expected],metadata

def run(zipfile,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    targets,source_metadata=native_2014(zipfile)
    report={"phase":"P9_3A_ORIGINAL_CANESM5_YEAR_2014_PROSPECTIVE_PRESSURE_T_Q_EPW_AUDIT",
        "model":"CanESM5","scenario":"historical","member":"r1i1p1f1",
        "native_source_2014_365_days_plus_2013_Dec31_UTC_boundary":366,
        "source_native_dailies_SHA256":SOURCE_HASH,
        "fixed_native_GCM_grid":[GRID_LAT,GRID_LON],
        "original_ERA5_hourly_donor_2019_2020_latlon":[DONOR_LAT,DONOR_LON],
        "source_ERA5_pressure_mode":PRESSURE_MODE,
        "NEX_GDDP_CMIP6_native_ps_variable_absent":True,
        "source_real_station_pressure_not_used_or_certified":True,
        "2014_is_one_preregistered_new_year_not_training":True,
        "algorithm":VERSION,"max_hourly_T_adjust_C":MAX_ADJUST_C,
        "max_numerical_repair_candidates":MAX_REPAIR_CANDIDATES,
        "seed":SEED,"source_ERA5_provenance":[],"native_gcm_metadata":source_metadata,
        "GCM_dailies_not_necessarily_joint_hourly_thermodynamic_states":True,
        "EPW_generated_only_on_366_of_366_physical_days":True,
        "production_epw_ready":False,"n_actual_independent_hourly_station_QC_validations":0}
    donors=[]
    for yr in (2019,2020):
        days,original=original_era5_year(yr)
        if original["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL_SHA[yr]:
            raise ValueError("P93A_DONOR_CANONICAL_ORIGINAL_HOURLY_WEATHER_SHA_DRIFT_"+str(yr))
        original["HTTP_response_SHA_differs_from_prior_but_weather_identical"]=(
            original["original_source_http_sha256"]!=PRIOR_ERA5_RAW_RESPONSE_SHA[yr])
        original["canonical_weather_byte_equivalence_verified"]=True
        donors.extend(days);report["source_ERA5_provenance"].append(original)
    good,blocked=generate(targets,donors,DONOR_LAT,DONOR_LON,SEED)
    if len(good)+len(blocked)!=366:
        raise ValueError("P93A_FULL_ORIGINAL_SOURCE_2014_NATIVE_DAILY_CENSUS_LOST")
    yr_days={d.date for d,lw,metadata in good if d.date.year==YEAR}
    status=collections.Counter(info["hurs_joint_status"] for d,lw,info in good)
    report.update({
        "original_native_daily_total":366,
        "n_original_native_daily_physically_closed":len(good),
        "n_original_native_daily_blocked":len(blocked),
        "n_original_native_YEAR_2014_365_days_closed":len(yr_days),
        "n_temperature_profiles_repaired":sum(
            bool(info["temperature_repaired"]) for d,lw,info in good),
        "n_days_original_q_and_hurs_joint_exact":status.get("FEASIBLE_BOTH_Q_AND_RH",0),
        "source_humidity_statuses":dict(status),
        "max_daily_hurs_target_abs_residual_pp":max(
            (abs(info["P92C_hurs_residual_pp"]) for d,lw,info in good),default=None),
        "blocked_source_days":blocked,
        "max_hourly_T_adjust_made_C":max(
            (info["T_max_abs_change_C"] for d,lw,info in good),default=None),
        "pressure_surface_values_original_ERA5_source_unmodified":True,
        "source_native_GCM_ps_absent_blocks_native_pressure_physical_validation":True,
        "source_total_ERA5_donor_days":len(donors),
        "EPW_filename":None,
        "real_original_CMIP6_weather_EnergyPlus_executed":False,
        "annual_native_daily_source_generator_research_qualified":False})
    if not blocked:
        file=out/FILE
        epw=raw_series_to_epw([x[0] for x in good],[x[1] for x in good],file,year=YEAR)
        report["EPW_filename"]=FILE
        report["EPW_research_strict_2014_readback"]=epw
        report["annual_native_daily_source_generator_research_qualified"]=True
    report["scientific_release_gates"]={
        "native_NASA_sha_registered":"PASS",
        "external_donor_ERA5_2019_2020_sha":"PASS",
        "native_NEX_GCM_ps_pressure_matched_to_T_and_q":"BLOCKED_OR_NOT_AVAILABLE",
        "native_2014_and_prev_UTC_day_complete":"PASS" if not blocked else "BLOCKED",
        "native_2014_8760x35_CET_epw_generated":"PASS" if report["EPW_filename"] else "BLOCKED",
        "real_2014_original_weather_EnergyPlus":"NOT_RUN_IN_SOURCE_GENERATION",
        "independent_measured_solar_rain_cloud_LW_quality":"NOT_QUALIFIED",
        "original_Meteonorm_28_P7C5B_source_bytes":"NOT_VERIFIED",
        "production_epw_ready":"BLOCKED"}
    fp=out/"p9_3a_preregistered_original_CanESM5_2014_pressure_T_q_census.json"
    fp.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P93A_FROZEN_2014_ORIGINAL_SOURCE_FINAL",json.dumps({
        "original_2014_native_days":365,
        "original_native_plus_boundary":366,
        "native_closed":len(good),"native_blocked":len(blocked),
        "2014_days_closed":len(yr_days),
        "temperature_repaired":report["n_temperature_profiles_repaired"],
        "native_hurs_huss_joint_exact":report["n_days_original_q_and_hurs_joint_exact"],
        "blocked_dates":[x["date"] for x in blocked],
        "epw_2014_genuine_original_written":bool(report["EPW_filename"]),
        "released":False}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--original-canesm5-registered-zip",required=True)
    p.add_argument("--out",default="outputs/p93a-2014")
    a=p.parse_args()
    run(Path(a.original_canesm5_registered_zip),Path(a.out))
