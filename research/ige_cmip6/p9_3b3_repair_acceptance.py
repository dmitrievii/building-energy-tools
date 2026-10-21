"""Compare new diagnostics with the immutable first B3 Actions artifact.

Previously revealed dates are regression assertions, never model parameters.
This gate cannot establish independent station accuracy or production readiness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def compare(baseline,repaired):
    if baseline["source"]["daily_csv_sha256"]!=repaired["source"]["daily_csv_sha256"]:
        raise AssertionError("P93B3_REPAIR_SOURCE_DRIFT")
    canonical=lambda r:[d["canonical_source_weather_sha256"] for d in r["donors"]]
    if canonical(baseline)!=canonical(repaired):raise AssertionError("P93B3_REPAIR_DONOR_DRIFT")
    after={(m["year"],m["variant"]):m for m in repaired["members"]}
    cells=[];old_exact=new_exact=certified=0
    for old in baseline["members"]:
        new=after[(old["year"],old["variant"])]
        if old["variant"].startswith("L0_"):
            for k in ("generated_including_boundary","blocked_including_boundary"):
                if old[k]!=new[k]:raise AssertionError("P93B3_REPAIR_LEGACY_BASELINE_CHANGED")
        if old["variant"]!="L3_JOINT_SOURCE_PHASE":continue
        od={d["date"]:d for d in old["days"]};nd={d["date"]:d for d in new["days"]}
        if len(od)!=366 or set(od)!=set(nd):raise AssertionError("P93B3_REPAIR_CENSUS_DRIFT")
        for date,o in od.items():
            n=nd[date]
            if o["status"]=="EXACT_DEFINED_OPERATORS":
                old_exact+=1
                if n["status"]!="EXACT_DEFINED_OPERATORS":raise AssertionError("P93B3_REPAIR_LOST_KNOWN_WITNESS")
                if n["physical_admissibility"]!="PASS_UNDER_DECLARED_DISCRETE_POLICY":
                    raise AssertionError("P93B3_REPAIR_INVALID_STATE")
                new_exact+=1;continue
            if o["status"]!="UNRESOLVED" or n["status"]!="CERTIFIED_INFEASIBLE":
                raise AssertionError("P93B3_REPAIR_UNRESOLVED_DIAGNOSIS_NOT_CLOSED")
            trials=n["trials"]
            if (len(trials)!=n["eligible_donors"] or not trials or
                    len({t["donor"] for t in trials})!=len(trials)):
                raise AssertionError("P93B3_REPAIR_CERTIFICATE_DID_NOT_COVER_ALL_DONORS")
            bounds=[]
            for t in trials:
                c=t["certificate"]
                if (t["status"]!="CERTIFIED_INFEASIBLE" or
                    c["domain"]!="FULL_SOURCE_TMIN_TMAX_RELAXING_DONOR_PRIOR" or
                    len(c["pressure_fingerprint"])!=64):
                    raise AssertionError("P93B3_REPAIR_CERTIFICATE_SCOPE")
                low,high,R=c["RH_mean_lower_pp"],c["RH_mean_upper_pp"],c["target_RH_mean_pp"]
                if not (R>high+1e-4 or R<low-1e-4):
                    raise AssertionError("P93B3_REPAIR_CERTIFICATE_NOT_SEPARATING_TARGET")
                bounds.append((low,high,R))
            certified+=1
            cells.append({"date":date,"status":"ALL_ELIGIBLE_PRESSURES_CERTIFIED_INCOMPATIBLE",
                "n_donors":len(trials),"source_RH_pp":bounds[0][2],
                "union_RH_lower_pp":min(b[0] for b in bounds),"union_RH_upper_pp":max(b[1] for b in bounds),
                "scope":"ONLY_REGISTERED_PRESSURES_SOURCE_PHASE_AND_DEFINED_DAILY_OPERATORS"})
    return {"status":"PASS_IMMUTABLE_BASELINE_AND_COMPLETE_CONDITIONAL_DIAGNOSIS",
        "previous_exact_states_retained":old_exact,"new_exact_states":new_exact,
        "previous_unresolved_now_certified":certified,"cells":cells,
        "original_NASA_values_modified":False,"independent_accuracy":"NOT_ESTABLISHED_BY_THIS_GATE",
        "operational_ready":False,"production_epw_ready":False}


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--baseline",required=True)
    ap.add_argument("--repaired",required=True);ap.add_argument("--out",required=True);a=ap.parse_args()
    old,new=Path(a.baseline).read_bytes(),Path(a.repaired).read_bytes()
    report=compare(json.loads(old),json.loads(new))
    report.update(baseline_sha256=hashlib.sha256(old).hexdigest(),repaired_sha256=hashlib.sha256(new).hexdigest())
    p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("x") as f:f.write(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print("P93B3_REPAIR_ACCEPTANCE",report["status"],report["previous_unresolved_now_certified"])


if __name__=="__main__":main()
