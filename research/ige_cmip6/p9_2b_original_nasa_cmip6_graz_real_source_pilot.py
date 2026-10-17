#!/usr/bin/env python3
"""One genuine-source P9.2B CanESM5 historical/SSP245 daily-to-hourly pilot.

Original NASA GCM daily source ZIPs: p7c3_ensemble.read_source SHA verified.
Hourly donor ERA5 via P9.1A/P9.2A original same-site source: 2019/2020.
Only Graz, original GCM 2013 and SSP245 2050, 10–16 Jan/July.
Every blocked native source constraint remains visible. No future observations.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,hashlib,json,statistics
from pathlib import Path

import p7c3_ensemble as p7c3
from p9_2a_real_era5_at_de_ch_pilot import original_days
from p9_2b_cmip6_daily_joint_regime_solver import (
    ALGORITHM,DAY_FIELDS,generate,summarize
)

MODEL="CanESM5"
SITE=("AT","Graz",47.0707,15.4395)
SEASONS=(("January","01-10","01-16"),("July","07-10","07-16"))
TRAINING_DONOR_YEARS=(2019,2020)
SCENARIOS=(("historical",p7c3.HIST,2013),
           ("ssp245", "ssp245-2040-2059",2050))
SEED=7313
EXPECTED_CSV_SHA_FILE=Path("research/ige_cmip6/p7c3_expected_daily_source_shas.json")
EXPECTED_ORIGINAL_REGISTERED_DAILY_TARGETS=28

def read_cmip6(archive_dir):
    expected=json.loads(EXPECTED_CSV_SHA_FILE.read_text())['source_sha256']
    loaded={}
    for label,window,year in SCENARIOS:
        key=MODEL+'_'+window
        file=archive_dir/('IGE_P7C3_SRC_'+key+'.zip')
        rows,prov=p7c3.read_source(file,MODEL,window)
        if prov["daily_csv_sha256"]!=expected[key] or prov["qa"]!="PASS":
            raise ValueError("P92B_GENUINE_NASA_P6_DAILY_SHA_QUALITY_GATE")
        days=[d for d in rows if d['date'].year==year and any(
              dt.date(year,int(season[:2]),int(season[3:])) if False else
              d['date'].month==mon and 10<=d['date'].day<=16 for mon in (1,7))]
        if len(days)!=14:
            raise ValueError("P92B_ORIGINAL_CANESM5_TARGET_14_DAYS_NOT_PRESENT_"+label)
        if any(d.get(k) is None for d in days for k in DAY_FIELDS):
            raise ValueError("P92B_AUTHENTIC_DAILY_CMIP6_REQUIRED_HUSS_OR_OTHER_FIELD_MISSING")
        loaded[label]={"year":year,"window":window,"rows":days,"provenance":prov}
    return loaded

def run(out,archive_dir):
    out.mkdir(parents=True,exist_ok=True)
    original_gcm=read_cmip6(archive_dir)
    report={"phase":"P9_2B_NASA_NEX_GDDP_CMIP6_V2_ORIGINAL_DAILY_CONSTRAINED_JOINT_HOURLY_GRAZ_PILOT",
      "algorithm":ALGORITHM,
      "gcm_model":MODEL,"member":"r1i1p1f1",
      "original_daily_grid_coordinate_lat_lon":[46.875,15.375],
      "ERA5_donor_station_graz_lat_lon":[SITE[2],SITE[3]],
      "original_GCM_grid_not_same_location_as_ERA5_donor_point":True,
      "registered_scenarios":[s[0] for s in SCENARIOS],
      "registered_target_years":[2013,2050],
      "registered_original_daily_targets":EXPECTED_ORIGINAL_REGISTERED_DAILY_TARGETS,
      "ERA5_original_hourly_donor_years":list(TRAINING_DONOR_YEARS),
      "trained_on_2022_P92A_validation":False,
      "target_source_original_NASA_GCM_not_date_synchronous_observations":True,
      "future_2050_not_a_forecast_for_individual_weather_dates":True,
      "one_fixed_seed":SEED,"n_new_countries":0,
      "GCM_no_native_cloud_cover":True,
      "derived_hourly_longwave_not_independently_measured":True,
      "native_huss_hard_hurs_soft_for_physical_thermodynamic_consistency":True,
      "artifacts_do_not_contain_original_weather_hourly_or_daily_rows":True,
      "members":[],"production_epw_ready":False,"no_global_validation":True}
    for scenario,asset in original_gcm.items():
        report.setdefault("original_CMIP6_SHA256",{})[scenario]={
          "window":asset["window"],"year":asset["year"],
          "registered_original_P6_daily_CSV_SHA256":asset["provenance"]["daily_csv_sha256"],
          "original_derived_source_ZIP_SHA256":asset["provenance"]["source_zip_sha256"],
          "original_quality_flag":asset["provenance"]["qa"]}
    sources={}
    for season,startpart,endpart in SEASONS:
        donors=[];prov=[]
        try:
            for yr in TRAINING_DONOR_YEARS:
                days,meta=original_days(SITE[2],SITE[3],yr,season,startpart,endpart)
                donors.extend(days)
                prov.append(meta)
            sources[season]={"days":donors,"provenance":prov}
            print("P92B_ERA5_ORIGINAL_SOURCE_PROVENANCE",
                  json.dumps({"season":season,"original_sha256":[x["original_provider_http_SHA256"] for x in prov],
                  "n_training_original_hours":len(donors)*24}),flush=True)
        except Exception as exc:
            sources[season]={"days":None,
                    "source_blocker":f"{type(exc).__name__}: {exc}"[:400]}
            print("P92B_ORIGINAL_DONOR_BLOCKED",season,
                  sources[season]["source_blocker"],flush=True)
    total_expected=0;success_total=0;blocked_total=0
    for scenario,window,year in SCENARIOS:
        for season,startpart,endpart in SEASONS:
            targets=[r for r in original_gcm[scenario]["rows"]
                     if r["date"].month==(1 if season=="January" else 7)]
            if len(targets)!=7:
                raise ValueError("P92B_UNEXPECTED_TARGET_ORIGINAL_SEASON_DAY_COUNT")
            total_expected+=len(targets)
            item={"scenario":scenario,"year":year,"season":season,
                  "n_original_CMIP6_native_days":len(targets),
                  "model_source_registered_CSV_SHA256":original_gcm[scenario]["provenance"]["daily_csv_sha256"]}
            if sources[season]["days"] is None:
                item["status"]="GENUINE_ERA5_SOURCE_BLOCKED"
                item["reason"]=sources[season]["source_blocker"]
                item["n_conserved_daily_targets"]=0
                item["n_blocked_daily_targets"]=7
                item["blocking_reasons"]=[{"target_date":x["date"].isoformat(),
                     "reason":item["reason"]} for x in targets]
                blocked_total+=7
            else:
                good,blocked=generate(targets,sources[season]["days"],
                                     SITE[2],SITE[3],seed=SEED)
                summary=summarize(good,blocked,len(targets))
                item.update(summary)
                item["n_conserved_daily_targets"]=len(good)
                item["n_blocked_daily_targets"]=len(blocked)
                success_total+=len(good);blocked_total+=len(blocked)
                item["status"]=("ALL_SEVEN_ORIGINAL_CMIP6_DAILY_CONSTRAINTS_CONSERVED"
                                 if len(good)==7 else
                                 "PARTIALLY_CONSERVED_PHYSICAL_SOURCE_BLOCKED")
                item["ERA5_hourly_donor_original_SHA256"]=[
                    p["original_provider_http_SHA256"] for p in sources[season]["provenance"]]
                item["n_days_humidity_HURS_abs_mismatch_over_10_pp"]=summary["n_days_hurs_mismatch_gt_10pp"]
                item["n_generated_wet_hours"]=sum(r["precipitation"]>0
                    for day,_,meta in good for r in day.vectors)
                item["n_generated_joint_donor_hours"]=24*len(good)
                item["original_wet_target_days"]=sum(x["pr_mm_day"]>0 for x in targets)
                item["mean_source_daily_huss_kg_kg"]=statistics.fmean(
                    x["huss"] for x in targets)
                item["n_blocks_original_cloud_hour_coupling_preserved"]=len(good)
                item["daily_solar_partition_and_radiation_semantics"]="DERIVED_FROM_DONOR_CLOUD_AND_TARGET_SOLAR_GEOMETRY"
            report["members"].append(item)
            print("P92B_GENUINE_CMIP6_DAILY_CONSERVATION",json.dumps({
               "scenario":scenario,"season":season,
               "status":item["status"],"n_conserved":item["n_conserved_daily_targets"],
               "n_blocked":item["n_blocked_daily_targets"],
               "soft_HURS_mismatch_mean_pp":item.get("hurs_soft_mean_abs_mismatch_pp"),
               "soft_HURS_max_pp":item.get("hurs_soft_max_abs_mismatch_pp"),
               "hard_abs_max":item.get("max_abs_daily_hard_residual_by_variable"),
               "blocked_reason_codes":dict(collections.Counter(
                   x["reason"].split(": ")[-1] for x in item.get("blocking_reasons",[])))
            }),flush=True)
    if total_expected!=EXPECTED_ORIGINAL_REGISTERED_DAILY_TARGETS:
        raise ValueError("P92B_NASA_SOURCE_EXPERIMENT_SAMPLE_INCOMPLETE")
    report["n_original_CMIP6_target_days"]=total_expected
    report["n_original_daily_multivariable_hard_conserved"]=success_total
    report["n_original_daily_physically_blocked"]=blocked_total
    report["all_original_daily_target_cases_accounted"]=success_total+blocked_total==total_expected
    report["genuine_original_CMIP6_conservation_full_success"]=success_total==total_expected
    report["scientific_independent_station_skill_qualified"]=False
    report["daily_native_RH_and_q_both_hard_qualified"]=False
    dest=out/"p9_2b_original_CanESM5_2013_2050_two_seasons_daily_joint_conservation.json"
    dest.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print("P92B_FINAL_ORIGINAL_NASA_CMIP6_SOURCE",json.dumps({
       "n_original_daily_targets":total_expected,"n_conserved":success_total,
       "n_blocked":blocked_total,"all_hard_conservation_PASSED":success_total==total_expected,
       "independent_station_skill_qualified":False,"production_epw_ready":False}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="outputs/p92b")
    p.add_argument("--canonical-archive-dir",default="inputs/p9_2b_original_CMIP6")
    args=p.parse_args()
    run(Path(args.out),Path(args.canonical_archive_dir))
