"""Explicit research-only lexicographic LOCAL projection; original forcing frozen.

Stages minimize mean-q error, mean-RH error, then shape at achieved diagnostics.
Unless independently certified, do not claim the globally nearest climate.
"""
from __future__ import annotations
import hashlib
import json
import numpy as np

from p9_3b3_joint_solver import JointProblem, solve_day


def reconcile_day(donor_T,donor_q,target,pressure,weights=None,policy=None,strict_result=None):
    before=json.dumps(target.to_dict(),sort_keys=True,allow_nan=False)
    exact=strict_result if strict_result is not None else solve_day(donor_T,donor_q,target,pressure,weights,policy)
    if exact["status"] == "EXACT_DEFINED_OPERATORS":
        return {**exact,"reconciliation":"NOT_NEEDED","source_modified":False}
    if exact["status"] == "SOURCE_BLOCKED":
        return exact
    problem=JointProblem(donor_T,donor_q,target,pressure,weights,policy)
    def mass_objective(x):
        d=float(problem.w@x[problem.k:]-target.q_mean_kgkg*1000)
        return d*d, np.r_[np.zeros(problem.k),2*d*problem.w]
    one=problem.optimize(mass_objective)
    T,q=problem.unpack(one.x)
    Q=float(problem.w@q)
    def rh_objective(x):
        r,j=problem.humidity(x)
        d=(r-target.RH_mean_pct)/100
        return d*d,2*d*j/100
    two=problem.optimize(rh_objective,Q=Q,start=one.x)
    t2,q2=problem.unpack(two.x)
    try:
        # Validate first two hierarchy stages, irrespective of solver success flags.
        problem.package(t2,q2,strict=False)
        if abs(problem.w@q2-Q)>1e-9:
            raise ValueError("P93B3_RECONCILIATION_Q_STAGE_NOT_PRESERVED")
        R,_=problem.humidity(two.x)
        three=problem.optimize(Q=Q,RH=R,start=two.x)
        t3,q3=problem.unpack(three.x)
        try:
            result=problem.package(t3,q3,strict=False)
            if abs(problem.w@q3-Q)>1e-9 or abs(problem.humidity(three.x)[0]-R)>1e-4:
                raise ValueError("P93B3_RECONCILIATION_HIERARCHY_NOT_PRESERVED")
        except ValueError:
            result=problem.package(t2,q2,strict=False)
    except ValueError as exc:
        return {"status":"UNRESOLVED","reason":str(exc),"date":target.date,
                "source_modified":False,"production_epw_ready":False}
    if json.dumps(target.to_dict(),sort_keys=True,allow_nan=False)!=before:
        raise AssertionError("P93B3_ORIGINAL_FORCING_MUTATED")
    achieved=result["validation"]
    # A secondary search can discover a genuine exact witness. Do not label an
    # unchanged source as modified merely because the first search missed it.
    from p9_3b3_state_validation import validate_state
    try:
        exact_check=validate_state(result["T_K"],result["p_Pa"],result["q_kgkg"],target,
                                   result["weights"],problem.policy.formulation,strict=True)
    except ValueError:
        exact_check=None
    if exact_check is not None:
        return {**result,"validation":exact_check,"date":target.date,"status":"EXACT_DEFINED_OPERATORS",
                "source_modified":False,"method":"EXACT_WITNESS_FOUND_BY_SECONDARY_RECONCILIATION_SEARCH",
                "reconciliation":"SOURCE_DIAGNOSTICS_UNCHANGED"}
    journal=[]
    for name,src,val in (("q_mean_kgkg",target.q_mean_kgkg,achieved["q_mean_kgkg"]),
                         ("RH_mean_pct",target.RH_mean_pct,achieved["RH_source_mean_pct"])):
        journal.append({"operator":name,"source_value":src,"reconciled_value":val,
                        "delta":val-src,"cause":exact.get("reason",exact["status"]),
                        "pressure_reference":pressure.fingerprint,
                        "science_status":"RESEARCH_ONLY_SOURCE_MODIFIED"})
    return {**result,"date":target.date,"status":"LOCAL_RECONCILIATION_CANDIDATE",
            "source_modified":True,"research_only":True,"production_eligible":False,
            "reconciliation_science_qualified":False,"global_optimality_certified":False,
            "optimality_gap":None,"source_target_sha256":hashlib.sha256(before.encode()).hexdigest(),
            "strict_source_result":exact["status"],"journal":journal,
            "optimizer_successes":[bool(s.success) for s in (one,two,three)]}
