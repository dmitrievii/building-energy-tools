#!/usr/bin/env python3
"""P9.3B3 retrospective original-source 2014 15 known P9.3A blockers.

This is NOT an unseen holdout. Purpose is regression: the new exact capped
mass projection must not silently 'resolve' previously proven fixed-P/T
physical impossibility by modifying pressure or native huss.
All original NASA and ERA5 weather sha validated BEFORE testing cases.
"""
from __future__ import annotations
import argparse,json,collections,datetime as dt
from pathlib import Path
from p9_3b3_original_CanESM5_2012_14day_joint_source_pilot import (
    EXPECTED_NASA_SHA,EXPECTED_ERA5_CANONICAL)
from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year
from p7c3_ensemble import read_source,HIST
from p9_3a_2014_fixed_pressure_temperature_lp_diagnosis import KNOWN_BLOCKED_2014
from p9_2b_cmip6_daily_joint_regime_solver import native_target
from p9_3b3_joint_t_p_q_physical_projection import reconstruct_day
EXPECTED_N=15
def run(source,out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 originals,meta=read_source(source,"CanESM5",HIST)
 if meta["daily_csv_sha256"]!=EXPECTED_NASA_SHA:
  raise ValueError("P93B3_2014_ORIGINAL_REGISTRY_SHA_CHANGED")
 index={r["date"].isoformat():r for r in originals}
 if len(KNOWN_BLOCKED_2014)!=EXPECTED_N or any(d not in index for d in KNOWN_BLOCKED_2014):
  raise ValueError("P93B3_PRIOR_2014_SOURCE_FAILURES_NOT_COMPLETE")
 donors=[];origins=[]
 for yr in (2019,2020):
  ds,m=original_era5_year(yr)
  if m["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL[yr]:
   raise ValueError("P93B3_PRIOR_2014_ORIGINAL_ERA5_WEATHER_SHA_CHANGED")
  donors.extend(ds);origins.append(m)
 donors.sort(key=lambda x:x.date)
 rows=[]
 for date in KNOWN_BLOCKED_2014:
  t=index[date];native=native_target(t)
  wet=native["pr_mm_day"]>0
  eligible=[d for d in donors if d.date.month==t["date"].month and
    (sum(x["precipitation"] for x in d.vectors)>0)==wet]
  record={"date":date,"prior_original_P93A_verified_LP_fixed_T_P_infeasibility":True,
          "number_original_ERA5_donors_same_month_wetdry":len(eligible)}
  if eligible:
   source_day=eligible[0]
   record["original_source_donor_date"]=source_day.date.isoformat()
   try:
    proj=reconstruct_day(t,source_day)
    record["status"]=proj["status"]
    ledger=proj["ledger"]
    record["certified_minimum_native_water_mass_deficit_gkg"] = (
       ledger.get("native_huss_unavoidable_absolute_daily_mean_correction_kgkg",0)*1000)
    record["hourly_accepted"]=proj["hourly"] is not None
   except Exception as exc:
    record["status"]="SOURCE_OR_TEMP_SHAPE_REJECTED"
    record["reason"]=f"{type(exc).__name__}: {exc}"[:350]
  else:record["status"]="NO_ORIGINAL_SOURCE_REGIME"
  rows.append(record)
  print("P93B3_PRIOR_2014_REGRESSION",json.dumps(record),flush=True)
 cnt=collections.Counter(x["status"] for x in rows)
 report={"phase":"P93B3_RETROSPECTIVE_ORIGINAL_2014_15_PREVIOUSLY_LP_CERTIFIED_SOURCE_BLOCKS",
   "original_native_CanESM5_registrar_SHA256":EXPECTED_NASA_SHA,
   "ERA5_source_donor_lineage":origins,
   "previous_2014_negative_set_known_before_this_stage":True,
   "this_is_NOT_fresh_validation":True,
   "registered_number_of_previous_physically_blocked_days":15,
   "status_counts":dict(cnt),
   "n_original_prior_blocked_days_falsely_accepted_as_hard_closed":sum(
       r.get("hourly_accepted",False) for r in rows),
   "new_C2_did_not_override_native_GCM_huss":all(not r.get("hourly_accepted",False) for r in rows),
   "native_CanESM5_ps_newly_discovered":False,
   "production_epw_ready":False,
   "cases":rows}
 (out/"p9_3b3_original_2014_prior_fixedP_T_LP_rejections_retrospective_regression.json").write_text(
     json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93B3_PRIOR_2014_FAIL_CLOSED_FINAL",json.dumps({
  "prior_2014_original_source_failures":15,
  "falsely_hard_closed_days":report["n_original_prior_blocked_days_falsely_accepted_as_hard_closed"],
  "rejection_counter":dict(cnt)}),flush=True)
 return report
if __name__=="__main__":
 ap=argparse.ArgumentParser()
 ap.add_argument("--original-canesm5-registered-zip",required=True)
 ap.add_argument("--out",default="outputs/p93b3-prior2014")
 a=ap.parse_args();run(a.original_canesm5_registered_zip,a.out)
