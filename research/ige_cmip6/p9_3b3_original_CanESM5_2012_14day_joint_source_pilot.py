#!/usr/bin/env python3
"""P9.3B3 preregistered 14 original 2012 CanESM5 NASA source day pilot.

2012 is development inside previously read original 1995-2014 archive,
NOT new observations or independent actual 2012 station weather. Donor
2019/2020 original ERA5 24h blocks, first chronological matching
month+wet/dry selected BEFORE inspecting target q capacity. No tuning.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,hashlib,json,math,statistics,zipfile
from pathlib import Path
from p7c3_ensemble import read_source,HIST
from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year
from p9_2b_cmip6_daily_joint_regime_solver import native_target
from p9_3b3_joint_t_p_q_physical_projection import reconstruct_day,VERSION,PRESSURE_SOURCE

EXPECTED_NASA_SHA="77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef"
EXPECTED_ERA5_CANONICAL={
  2019:"ac9749eb1cee4d2246b60871f1a139d8920451e30b8ed54ea134431fa0de4c29",
  2020:"275804a076a81c3c8ae9a572e0359ca524ef9c90627ccca2c6862805093b019c"}
FROZEN_DATES=tuple(dt.date(2012,1,10)+dt.timedelta(days=i) for i in range(7))+tuple(
  dt.date(2012,7,10)+dt.timedelta(days=i) for i in range(7))

def registered_native(path):
 original,meta=read_source(path,"CanESM5",HIST)
 if meta["daily_csv_sha256"]!=EXPECTED_NASA_SHA:
  raise ValueError("P93B3_ORIGINAL_CanESM5_SOURCE_IMMUTABLE_SHA_CHANGED")
 bydate={r["date"]:r for r in original}
 if any(date not in bydate for date in FROZEN_DATES):
  raise ValueError("P93B3_FROZEN_14_GCM_2012_SOURCE_DAYS_MISSING")
 return [bydate[d] for d in FROZEN_DATES],meta

def run(sourcezip,out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 days,native_metadata=registered_native(sourcezip)
 donors=[];lineage=[]
 for year in (2019,2020):
  source,meta=original_era5_year(year)
  if meta["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL[year]:
   raise ValueError("P93B3_ORIGINAL_ERA5_DONOR_WEATHER_SHA_MISMATCH_"+str(year))
  donors.extend(source);lineage.append(meta)
 donors.sort(key=lambda d:d.date)
 report={"phase":"P93B3_2012_ORIGINAL_CANESM5_SOURCE_JOINT_T_P_Q_PROJECTION_FROZEN",
   "preregistered_target_dates":[d.isoformat() for d in FROZEN_DATES],
   "model":"CanESM5","member":"r1i1p1f1","scenario":"historical",
   "original_GCM_20y_registered_source_daily_sha256":EXPECTED_NASA_SHA,
   "original_GCM_2012_is_development_in_known_archive_not_independent_station_validation":True,
   "original_gcm_source_metadata":native_metadata,
   "source_ERA5_2019_2020_canonical_expected_SHA":EXPECTED_ERA5_CANONICAL,
   "source_ERA5_year_provenance":lineage,
   "source_ERA5_original_donor_n_days":len(donors),
   "pressure_source_not_native_GCM_ps":PRESSURE_SOURCE,
   "algorithm":VERSION,
   "no_skill_or_humidity_score_based_donor_selection":True,
   "frozen_donor_rule":"earliest_source_chronological_same_month_same_wet_dry",
   "source_water_mass_or_RH_error_did_not_affect_original_donor_selection":True,
   "no_2021_station_pressure_assimilation":True,
   "production_epw_ready":False,
   "real_original_2012_EnergyPlus_executed":False,
   "native_2012_8760_CET_EPW_created":False,
   "source_daily_cases":[]}
 for target in days:
  native=native_target(target)
  wet=native["pr_mm_day"]>0
  candidates=[donor for donor in donors if donor.date.month==target["date"].month and
        ((sum(x["precipitation"] for x in donor.vectors)>0)==wet)]
  case={"date":target["date"].isoformat(),"native_huss_kgkg":native["huss"],
        "native_hurs_percent":native["hurs"],
        "n_source_same_month_wet_dry_donors":len(candidates)}
  if not candidates:
   case["status"]="SOURCE_NO_MATCHING_NATIVE_WET_DRY_DONOR"
  else:
   donor=candidates[0]
   case["original_ERA5_donor_date"]=donor.date.isoformat()
   case["donor_source_original_sha256"]=donor.original_sha256
   try:
    result=reconstruct_day(target,donor)
    case["status"]=result["status"]
    case["physical_reconciliation_ledger"]=result["ledger"]
    # No provider raw original hourly data written to audit JSON.
    case["corrected_hourly_temperatures_pressure_q_RH_not_exported"]=True
   except (ValueError,ArithmeticError,OverflowError) as exc:
    case["status"]="PHYSICAL_OR_SOURCE_FAIL_CLOSED"
    case["reason"]=f"{type(exc).__name__}: {exc}"[:500]
  report["source_daily_cases"].append(case)
  print("P93B3_ORIGINAL_2012_FIXED_DONOR_DATE",json.dumps({
   "date":case["date"],"donor_date":case.get("original_ERA5_donor_date"),
   "status":case["status"],
   "native_huss_kgkg":case["native_huss_kgkg"],
   "native_hurs":case["native_hurs_percent"],
   "rh_residual_pp":case.get("physical_reconciliation_ledger",{}).get("native_hurs_residual_percentage_points"),
   "unavoidable_q_deficit_kgkg":case.get("physical_reconciliation_ledger",{}).get(
     "native_huss_unavoidable_absolute_daily_mean_correction_kgkg")}),flush=True)
 if len(report["source_daily_cases"])!=14:
  raise ValueError("P93B3_ORIGINAL_2012_FROZEN_SOURCE_CENSUS_LOST")
 cnt=collections.Counter(x["status"] for x in report["source_daily_cases"])
 accepted=[x for x in report["source_daily_cases"] if x["status"]=="C1_HARD_T_P_HUSS_PHYSICALLY_CLOSED"]
 rejected=[x for x in report["source_daily_cases"] if x["status"]=="C2_FAIL_CLOSED_DIAGNOSTIC_ONLY"]
 report["n_original_days_requested"]=14
 report["n_C1_hard_T_P_q_physically_closed"]=len(accepted)
 report["n_C2_physically_infeasible_at_original_fixed_pressure_T"]=len(rejected)
 report["n_other_source_or_T_shape_blocks"]=14-len(accepted)-len(rejected)
 report["source_status_census"]=dict(cnt)
 report["C1_mean_native_hurs_absolute_residual_pp"]=(
   statistics.fmean(abs(x["physical_reconciliation_ledger"]["native_hurs_residual_percentage_points"])
      for x in accepted) if accepted else None)
 report["C1_max_native_hurs_absolute_residual_pp"]=(
   max(abs(x["physical_reconciliation_ledger"]["native_hurs_residual_percentage_points"])
      for x in accepted) if accepted else None)
 report["n_C1_native_RH_proven_outside_conservative_bound"]=sum(
  x["physical_reconciliation_ledger"]["native_hurs_proven_outside_conservative_bound"]
  for x in accepted)
 report["C2_total_unavoidable_native_huss_mass_deficit_gkg_across_blocked_days"]=sum(
  x["physical_reconciliation_ledger"]["native_huss_unavoidable_absolute_daily_mean_correction_kgkg"]*1000
  for x in rejected)
 report["original_2014_previous_15_blocks_not_requalified_by_this_2012_pilot"]=True
 report["all_days_T_P_q_joint_qualified"]=len(accepted)==14
 report["pressure_station_ERA5_observation_skill_not_certified_by_this_GCM_source_pilot"]=True
 (out/"p9_3b3_original_CanESM5_2012_14day_joint_T_P_q_physical_audit.json").write_text(
  json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B3_ORIGINAL_SOURCE_2012_FINAL",json.dumps({
  "original_days":14,
  "C1_closed":len(accepted),"C2_blocked":len(rejected),
  "other_blocked":report["n_other_source_or_T_shape_blocks"],
  "mean_hurs_abs_residual_pp":report["C1_mean_native_hurs_absolute_residual_pp"],
  "max_hurs_abs_residual_pp":report["C1_max_native_hurs_absolute_residual_pp"],
  "RH_target_proven_outside_bound":report["n_C1_native_RH_proven_outside_conservative_bound"],
  "full_EPWs_qualified":False}),flush=True)
 return report
if __name__=="__main__":
 ap=argparse.ArgumentParser()
 ap.add_argument("--original-canesm5-registered-zip",required=True)
 ap.add_argument("--out",default="outputs/p93b3-original")
 a=ap.parse_args()
 run(Path(a.original_canesm5_registered_zip),Path(a.out))
