#!/usr/bin/env python3
"""P9.2C finite original NASA CanESM5 2013/2050 28-day development-set replay.

All station observation 2025 holdout rows are out-of-scope here.
No fitting or cherry-picked climates; compare donor feasibility and RH q joint.
"""
from __future__ import annotations
import argparse,collections,json,statistics
from pathlib import Path
import p9_2b_original_nasa_cmip6_graz_real_source_pilot as old
from p9_2a_real_era5_at_de_ch_pilot import original_days
from p9_2c_physical_donor_and_humidity import generate as conditioned

def run(archive,out):
    out.mkdir(parents=True,exist_ok=True)
    source=old.read_cmip6(archive)
    pools={}
    report={"phase":"P9_2C_DONOR_FEASIBILITY_28_NATIVE_CANESM5_DEVELOPMENT_DAYS",
            "not_new_holdout":True,"scenario_sources":{},"seasons":[],
            "registered_days":28,"original_P92B_result_conserved_days":27,
            "original_P92B_result_blocked_days":1,
            "frozen_source_and_seed":7313,
            "production_epw_ready":False}
    for name,asset in source.items():
        report["scenario_sources"][name]={
          "sha_original_nasa_daily_csv":asset["provenance"]["daily_csv_sha256"],
          "model":old.MODEL,"year":asset["year"]}
    for season,start,end in old.SEASONS:
        donors=[];shas=[]
        for year in old.TRAINING_DONOR_YEARS:
            days,m=original_days(old.SITE[2],old.SITE[3],year,season,start,end)
            donors.extend(days)
            shas.append(m["original_provider_http_SHA256"])
        pools[season]={"donors":donors,"shas":shas}
    total=0;success=0;block=0;exact=0;worse=0
    for name,window,year in old.SCENARIOS:
        for season,start,end in old.SEASONS:
            native=[x for x in source[name]["rows"]
                    if x["date"].month==(1 if season=="January" else 7)]
            successful,failed=conditioned(native,pools[season]["donors"],
                         old.SITE[2],old.SITE[3],7313)
            if len(successful)+len(failed)!=7:raise ValueError("P92C_DEVELOPMENT_COHORT_LOST_DAYS")
            item={"scenario":name,"season":season,"year":year,
                "n_native_original_NASA_CMIP6_days":7,"n_daily_hard_closed":len(successful),
                "n_failed_physical_donor_days":len(failed),
                "n_days_joint_native_q_and_RH_closed":sum(
                    x[2]["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH" for x in successful),
                "n_days_with_RH_incompatibility_or_unclassified":sum(
                    x[2]["hurs_joint_status"]!="FEASIBLE_BOTH_Q_AND_RH" for x in successful),
                "max_abs_RH_target_residual_pp":max(
                    (abs(x[2]["P92C_hurs_residual_pp"]) for x in successful),default=None),
                "mean_abs_RH_residual_pp":statistics.fmean(
                    abs(x[2]["P92C_hurs_residual_pp"]) for x in successful)
                    if successful else None,
                "blocked_cases":failed,
                "candidate_rejection_histogram":dict(collections.Counter(
                    k for d,lw,m in successful for k,n in m["candidate_rejection_codes"].items()
                    for _ in range(n))),
                "original_era5_donor_shas":pools[season]["shas"]}
            report["seasons"].append(item)
            total+=7;success+=len(successful);block+=len(failed)
            exact+=item["n_days_joint_native_q_and_RH_closed"]
            print("P92C_ORIGINAL_CMIP6_PHYSICS",json.dumps({
                k:item[k] for k in ("scenario","season","n_daily_hard_closed",
                      "n_failed_physical_donor_days","n_days_joint_native_q_and_RH_closed",
                      "max_abs_RH_target_residual_pp","blocked_cases")}),flush=True)
    if total!=28:raise ValueError("P92C_ORIGINAL_COHORT_NOT_28")
    report.update({"n_original_days":total,
       "n_physically_closed":success,"n_physically_blocked":block,
       "n_exact_native_RH_and_huss_days":exact,
       "scientific_station_skill_qualified":False})
    (out/"p9_2c_original_CanESM5_28_development_day_feasible_donor_results.json").write_text(
       json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P92C_ORIGINAL_GCM_FINAL",json.dumps({
        "total":total,"closed":success,"blocked":block,"joint_RH_huss_days":exact}),flush=True)
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source-root",default="inputs/p92c-original-GCM")
    parser.add_argument("--out",default="outputs/p92c-original-GCM")
    options=parser.parse_args()
    run(Path(options.source_root),Path(options.out))
