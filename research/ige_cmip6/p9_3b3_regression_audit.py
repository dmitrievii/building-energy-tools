"""Frozen 2013/2014 regressions and declared operator ablations, not holdouts.

Outputs are aggregates and source-linked diagnoses, never overwritten baselines.
No production EPW is emitted by P9.3B3.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

from p9_3b3_generator import generate,from_legacy_day
from p9_3b3_joint_solver import SolverPolicy
from p9_3b3_source_semantics import DailyTarget,SourceSemantics,REGISTERED_CSV_SHA
from p9_3b3_thermodynamics import BUCK,MK


def read_registered(path,window="historical-1995-2014"):
    import p7c3_ensemble as old
    # Source/QA archive validation remains unchanged, but use RAW humidity below:
    # old read_source marks hurs>100 missing; B3 must preserve native up to 105.
    _,metadata=old.read_source(path,"CanESM5",window)
    with zipfile.ZipFile(path) as z:
        raw=z.read("joint_daily_raw.csv")
    sha=hashlib.sha256(raw).hexdigest()
    registry=json.loads(Path(__file__).with_name("p7c3_expected_daily_source_shas.json").read_text())
    expected=registry["source_sha256"]["CanESM5_"+window]
    if sha!=expected:raise ValueError("P93B3_ORIGINAL_DAILY_SOURCE_SHA_DRIFT")
    return list(csv.DictReader(io.StringIO(raw.decode()))),metadata


def native_targets(rows,year,semantics):
    chosen=[r for r in rows if r["date"]==f"{year-1}-12-31" or r["date"][:4]==str(year)]
    expected=[f"{year-1}-12-31"]+[(dt.date(year,1,1)+dt.timedelta(days=i)).isoformat() for i in range(365)]
    if [r["date"] for r in chosen]!=expected:
        raise ValueError("P93B3_FROZEN_REGRESSION_CALENDAR_INCOMPLETE")
    return [DailyTarget(r["date"],float(r["tasmin"]),float(r["tasmax"]),float(r["tas"]),
                        float(r["huss"]),float(r["hurs"]),semantics) for r in chosen],{
                            r["date"]:float(r["pr_mm_day"])>0 for r in chosen}


def compact_day(row):
    # Retain diagnoses, not source hourly arrays or reconstructed weather files.
    keys=("date","status","reason","donor_date","eligible_donors","fixed_exact_donors",
          "screen_codes","elapsed_seconds","policy_sha256","method","journal",
          "global_optimality_certified","optimizer_trials","trials","certificate")
    d={k:row[k] for k in keys if k in row}
    if "validation" in row:
        v=row["validation"]
        d["physical_admissibility"]=v["physical_admissibility"]
        d["daily_residuals"]=v["daily_residuals"]
        d["T_time_mean_K"]=v["T_time_mean_K"]
        d["RH_water_max_pct"]=v["RH_water_max_pct"]
    return d


def legacy_28_audit(historical,future,donors):
    """Exactly the earlier 28-day B/C cohort, unchanged frozen algorithms."""
    import p7c3_ensemble as cmip
    import p9_2b_cmip6_daily_joint_regime_solver as B
    import p9_2c_physical_donor_and_humidity as C
    total_b=total_c=joint_c=0;cells=[]
    for path,window,year in ((historical,cmip.HIST,2013),(future,cmip.WINDOWS[0],2050)):
        rows,meta=cmip.read_source(path,"CanESM5",window)
        registered=json.loads(Path(__file__).with_name("p7c3_expected_daily_source_shas.json").read_text())["source_sha256"]["CanESM5_"+window]
        if meta["daily_csv_sha256"]!=registered:raise ValueError("P93B3_28_DAY_SOURCE_DRIFT")
        for month in (1,7):
            targets=[r for r in rows if r["date"].year==year and r["date"].month==month and 10<=r["date"].day<=16]
            ds=[d for d in donors if d.date.month==month and 10<=d.date.day<=16]
            if len(targets)!=7 or len(ds)!=14:raise ValueError("P93B3_28_DAY_FROZEN_COHORT_INCOMPLETE")
            gb,bb=B.generate(targets,ds,47.0707,15.4395,7313)
            gc,bc=C.generate(targets,ds,47.0707,15.4395,7313)
            both=sum(x[2]["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH" for x in gc)
            total_b+=len(gb);total_c+=len(gc);joint_c+=both
            cells.append({"year":year,"month":month,"B_accepted":len(gb),"B_blocked":len(bb),
                          "C_accepted":len(gc),"C_joint_q_RH":both,"C_blocked":len(bc)})
    if (total_b,total_c,joint_c)!=(27,28,17):
        raise ValueError(f"P93B3_FROZEN_28_DAY_REGRESSION_CHANGED_{total_b}_{total_c}_{joint_c}")
    return {"status":"PASS_UNCHANGED_28_DAY_B_C_COUNTS","B_accepted":total_b,
            "C_accepted":total_c,"C_joint_q_RH":joint_c,"cells":cells}


def run(path,out,include_reconciliation=True,legacy=True,years=(2013,2014),future_path=None):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    rows,source=read_registered(path)
    from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year
    from p9_3a_original_canesm5_2014_year_pressure_temperature_q import EXPECTED_ERA5_CANONICAL_SHA
    legacy_donors=[];provenance=[]
    for year in (2019,2020):
        ds,meta=original_era5_year(year)
        if meta["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL_SHA[year]:
            raise ValueError("P93B3_FROZEN_DONOR_CANONICAL_WEATHER_DRIFT")
        legacy_donors.extend(ds);provenance.append(meta)
    donors=[from_legacy_day(d) for d in legacy_donors]
    report={"phase":"P9.3B3_FROZEN_REGRESSIONS_NOT_INDEPENDENT_VALIDATION",
            "source":source,"donors":provenance,"members":[],"production_epw_ready":False,
            "pressure_model_qualified":False,"operational_ready":False,
            "source_phase":"WATER_ICE_CONFIRMED_IN_NEX_HEADER",
            "source_time_bounds":"NOT_PROVIDED_UTC_DAY_ASSUMED",
            "legacy_files_modified":False,"independent_accuracy":"NOT_TESTED"}
    report["legacy_28_day_pilot"]=(legacy_28_audit(path,future_path,legacy_donors)
                                  if future_path else {"status":"NOT_RUN_FUTURE_SOURCE_NOT_SUPPLIED"})
    # Stable order defined before scoring. No coefficient selection by these rows.
    variants=[("L1_AFFINE_WATER", "WATER",BUCK),
              ("L2A_JOINT_WATER_LEGACY_FORMULA", "WATER",BUCK),
              ("L2B_JOINT_WATER_MK", "WATER",MK),
              ("L3_JOINT_SOURCE_PHASE", "WATER_ICE",MK)]
    for year in years:
        if legacy:
            import p7c3_ensemble as cmip
            import p9_2c_physical_donor_and_humidity as D
            import p9_3a_pressure_temperature_q_joint as A
            old_rows,_=cmip.read_source(path,"CanESM5",cmip.HIST)
            target_old=[r for r in old_rows if r["date"]==dt.date(year-1,12,31) or r["date"].year==year]
            good,bad=(D.generate if year==2013 else A.generate)(target_old,legacy_donors,47.0707,15.4395,7313)
            expected=(360,6) if year==2013 else (351,15)
            if (len(good),len(bad))!=expected:
                raise ValueError(f"P93B3_LEGACY_REGRESSION_CHANGED_{year}_{len(good)}_{len(bad)}")
            report["members"].append({"year":year,"variant":"L0_FROZEN_D" if year==2013 else "L0_FROZEN_A",
                "generated_including_boundary":len(good),"blocked_including_boundary":len(bad),
                "regression":"PASS_UNCHANGED_FROZEN_COUNTS","blocked":bad})
        for name,phase,formula in variants:
            sem=SourceSemantics("DERIVED_TAS_MIDRANGE",phase)
            targets,wet=native_targets(rows,year,sem)
            start=time.monotonic()
            policy=SolverPolicy(formulation=formula,lower_bound_seconds=.25)
            if name=="L1_AFFINE_WATER":
                # L1 is capacity-only affine screening, not a joint q/RH claim.
                result,summary=_affine_capacity_audit(targets,donors,wet,policy)
            else:
                result,summary=generate(targets,donors,policy=policy,wet_by_date=wet)
            report["members"].append({"year":year,"variant":name,"summary":summary,
                "elapsed_seconds":time.monotonic()-start,"days":[compact_day(r) for r in result],
                "note":"L1 affine capacity only; L2A isolates joint solve; L2B isolates saturation formulation/constants; L3 isolates source phase"})
            print("P93B3_REGRESSION",json.dumps({"year":year,"variant":name,**summary}),flush=True)
            if name=="L3_JOINT_SOURCE_PHASE" and include_reconciliation:
                # Reuse successful strict results; project only failed days.
                recon=[]
                bydate={t.date:t for t in targets}
                for r in result:
                    if r["status"]=="EXACT_DEFINED_OPERATORS":
                        recon.append(r);continue
                    rr,_=generate([bydate[r["date"]]],donors,policy=policy,reconcile=True,
                                  wet_by_date=wet)
                    recon.extend(rr)
                counts={}
                for r in recon:counts[r["status"]]=counts.get(r["status"],0)+1
                report["members"].append({"year":year,"variant":"RECONCILED_RESEARCH",
                    "counts":counts,"days":[compact_day(r) for r in recon],
                    "source_modified_never_counted_exact":True})
        # Checkpoint new report after each year, never old scientific result files.
        (out/"regression_audit.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    return report


def _affine_capacity_audit(targets,donors,wet,policy):
    import numpy as np
    from p9_3b3_joint_solver import affine_temperature
    from p9_3b3_thermodynamics import q_saturation
    result=[]
    for t in targets:
        candidates=[d for d in donors if d.date[5:7]==t.date[5:7] and d.wet==wet[t.date]]
        caps=[float(np.mean(q_saturation(affine_temperature(d.T_K,t),d.pressure.values_Pa,policy.formulation))) for d in candidates]
        result.append({"date":t.date,"status":"Q_CAPACITY_POSSIBLE_RH_NOT_SOLVED" if caps and max(caps)>=t.q_mean_kgkg else "NO_FIXED_AFFINE_Q_CAPACITY",
                       "eligible_donors":len(candidates),"certificate":{"scope":"AFFINE_PROFILES_ONLY","best_q_capacity":max(caps) if caps else None}})
    counts={}
    for r in result:counts[r["status"]]=counts.get(r["status"],0)+1
    return result,{"total":len(targets),"counts":counts,"RH_joint_closure_not_claimed":True}


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--original-canesm5-registered-zip",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--no-reconciliation",action="store_true")
    ap.add_argument("--original-canesm5-future-zip")
    args=ap.parse_args()
    run(args.original_canesm5_registered_zip,args.out,not args.no_reconciliation,
        future_path=args.original_canesm5_future_zip)
