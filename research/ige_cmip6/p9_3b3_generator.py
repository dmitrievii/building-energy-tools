"""Thermodynamic day generator, NOT a complete cloud/rain/radiation EPW.

All fixed-profile donors are screened first. At most eight source-ranked donors
receive a joint NLP. Stations and revealed errors are not solver inputs.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass,replace

import numpy as np

from p9_3b3_daily_feasibility import fixed_profile_feasibility
from p9_3b3_joint_solver import JointProblem,SolverPolicy,affine_temperature,solve_day
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_reconciliation import reconcile_day
from p9_3b3_thermodynamics import MK,q_from_e,q_saturation,saturation
from p9_3b3_joint_bounds import joint_domain_bounds


@dataclass(frozen=True)
class ThermoDonor:
    date: str
    T_K: tuple
    q_kgkg: tuple
    pressure: PressureReference
    wet: bool = False

    def __post_init__(self):
        dt.date.fromisoformat(self.date)
        object.__setattr__(self,"T_K",tuple(float(x) for x in self.T_K))
        object.__setattr__(self,"q_kgkg",tuple(float(x) for x in self.q_kgkg))
        if len(self.T_K)!=len(self.q_kgkg) or len(self.T_K)!=len(self.pressure.values_Pa):
            raise ValueError("P93B3_DONOR_ARRAY_ALIGNMENT")
        if not self.T_K or any(not math.isfinite(t) or not 173<t<332 for t in self.T_K):
            raise ValueError("P93B3_DONOR_TEMPERATURE_K_DOMAIN")
        if any(not math.isfinite(q) or not 0<=q<1 for q in self.q_kgkg):
            raise ValueError("P93B3_DONOR_SPECIFIC_HUMIDITY_DOMAIN")


def from_legacy_day(day,frame="ERA5_GRID_47.0_15.5",height_m=None):
    t=tuple(v["temperature_2m"]+273.15 for v in day.vectors)
    p=tuple(v["surface_pressure"]*100 for v in day.vectors)
    # Provider dew point refers to liquid water. Its conversion is explicit;
    # source RH is retained by the original reader, not enforced as an identity.
    q=tuple(q_from_e(saturation([v["dew_point_2m"]+273.15 for v in day.vectors]),p))
    ref=PressureReference(p,"OPEN_METEO_DERIVED_ERA5_DONOR",frame,height_m=height_m,
                          source_sha256=day.original_sha256,time_support="INSTANTANEOUS_SOURCE_HOURLY_NODES",
                          reference_date=day.date.isoformat())
    return ThermoDonor(day.date.isoformat(),t,q,ref,any(v["precipitation"]>0 for v in day.vectors))


def _rank(donor,target,previous):
    loss=abs(float(np.mean(donor.T_K))-target.tas_K)/10
    if previous and "T_K" in previous:
        loss+=.2*((donor.T_K[0]-previous["T_K"][-1])/6)**2
        loss+=.2*((donor.pressure.values_Pa[0]-previous["p_Pa"][-1])/1000)**2
    return loss


def _choose(candidates,target,previous,seed):
    # Stable ordering prevents dictionary/list arrival order from changing a draw.
    cand=sorted(candidates,key=lambda x:x[0].date)
    weights=[math.exp(-min(35,_rank(d,target,previous))) for d,_ in cand]
    value=random.Random(f"P93B3|{seed}|{target.date}").random()*sum(weights)
    for pair,w in zip(cand,weights):
        value-=w
        if value<=0:return pair
    return cand[-1]


def generate(targets,donors,seed=7313,policy=None,reconcile=False,wet_by_date=None,pressure_by_date=None):
    policy=policy or SolverPolicy()
    if len({t.date for t in targets})!=len(targets) or not targets or not donors:
        raise ValueError("P93B3_EMPTY_OR_DUPLICATE_TARGETS")
    if [t.date for t in targets]!=sorted(t.date for t in targets):
        raise ValueError("P93B3_TARGETS_NOT_CHRONOLOGICAL")
    if len({d.date for d in donors})!=len(donors):
        raise ValueError("P93B3_DUPLICATE_DONOR_DATE")
    if {d.date[:4] for d in donors}&{t.date[:4] for t in targets}:
        raise ValueError("P93B3_TARGET_YEAR_DONOR_LEAKAGE")
    if pressure_by_date is not None:
        if set(pressure_by_date)!={t.date for t in targets}:
            raise ValueError("P93B3_TARGET_PRESSURE_DATES_MUST_MATCH_EXACTLY")
        for date,p in pressure_by_date.items():
            if not isinstance(p,PressureReference) or p.mode=="OBSERVED_SITE_VALIDATION_ONLY":
                raise ValueError("P93B3_OBSERVATIONS_FORBIDDEN_IN_GENERATION")
            if p.reference_date!=date:
                raise ValueError("P93B3_TARGET_PRESSURE_TIME_REFERENCE_MISMATCH")
    output=[];previous=None;previous_date=None
    for target in targets:
        if previous_date and (dt.date.fromisoformat(target.date)-dt.date.fromisoformat(previous_date)).days!=1:
            previous=None
        previous_date=target.date
        started=time.monotonic()
        eligible=[d for d in donors if d.date[5:7]==target.date[5:7]
                  and (wet_by_date is None or d.wet==wet_by_date[target.date])]
        if pressure_by_date is not None:
            eligible=[replace(d,pressure=pressure_by_date[target.date]) for d in eligible]
        exact=[];ranked=[];screen_codes={}
        if target.semantics.rh_phase=="UNKNOWN":
            output.append({"date":target.date,"status":"SOURCE_BLOCKED","reason":"SOURCE_PHASE_UNKNOWN"})
            previous=None;continue
        for d in eligible:
            try:
                T=affine_temperature(d.T_K,target)
                f=fixed_profile_feasibility(T,d.pressure.values_Pa,target.q_mean_kgkg,target.RH_mean_pct,
                    target.semantics.rh_phase,policy.formulation,lower_time_limit=0)
                if (f["status"]=="FEASIBLE" and (
                    target.semantics.temperature_operator!="TIME_MEAN_TAS" or abs(np.mean(T)-target.tas_K)<=1e-6)):
                    exact.append((d,f))
                else:
                    qdef=max(0,target.q_mean_kgkg-f["capacity_q_mean"])*1000
                    rhdef=max(0,target.RH_mean_pct-f.get("RH_max_pp",target.RH_mean_pct))/100
                    ranked.append((qdef+rhdef,d.date,d))
                screen_codes[f["reason"]]=screen_codes.get(f["reason"],0)+1
            except ValueError as exc:
                screen_codes[str(exc)]=screen_codes.get(str(exc),0)+1
        if exact:
            donor,witness=_choose(exact,target,previous,seed)
            problem=JointProblem(donor.T_K,donor.q_kgkg,target,donor.pressure,policy=policy)
            result={**problem.package(problem.T0,np.asarray(witness["witness_q"])),
                    "status":"EXACT_DEFINED_OPERATORS","method":"FIXED_PROFILE_Q_RH_WITNESS"}
        else:
            trials=[]
            pending=[]
            # All donors receive cheap sound outer bounds. The eight-NLP budget
            # applies only to non-certified candidates, never to a union proof.
            for _,_,d in sorted(ranked):
                bound=joint_domain_bounds(np.full(len(d.T_K),target.Tmin_K),
                    np.full(len(d.T_K),target.Tmax_K),d.pressure.values_Pa,
                    target.q_mean_kgkg,target.RH_mean_pct,target.semantics.rh_phase,policy.formulation)
                if bound["status"]=="CERTIFIED_INFEASIBLE":
                    trials.append((d,{"status":"CERTIFIED_INFEASIBLE","reason":bound["reason"],
                        "certificate":{**bound,"domain":"FULL_SOURCE_TMIN_TMAX_RELAXING_DONOR_PRIOR",
                            "pressure_fingerprint":d.pressure.fingerprint}}))
                else:pending.append(d)
            for d in pending[:8]:
                r=solve_day(d.T_K,d.q_kgkg,target,d.pressure,policy=policy)
                trials.append((d,r))
            success=[x for x in trials if x[1]["status"]=="EXACT_DEFINED_OPERATORS"]
            if success:
                donor,result=_choose(success,target,previous,seed)
            elif reconcile and trials:
                donor,strict=min(trials,key=lambda x:(_rank(x[0],target,previous),x[0].date))
                result=reconcile_day(donor.T_K,donor.q_kgkg,target,donor.pressure,
                                     policy=policy,strict_result=strict)
            else:
                donor=None
                # Certificates for eight candidates do not prove the rest impossible.
                all_cert=(len(trials)==len(eligible)>0 and all(
                    r["status"]=="CERTIFIED_INFEASIBLE" for _,r in trials))
                result={"status":"CERTIFIED_INFEASIBLE" if all_cert else "UNRESOLVED",
                        "reason":"ALL_ELIGIBLE_DONORS_CERTIFIED" if all_cert else (
                            "NO_ELIGIBLE_DONOR" if not eligible else "SEARCH_LIMITED_OR_NUMERICALLY_UNRESOLVED"),
                        "trials":[{"donor":d.date,"status":r["status"],"reason":r.get("reason"),
                                   "certificate":r.get("certificate")} for d,r in trials]}
        result.update({"date":target.date,"donor_date":donor.date if donor else None,
                       "eligible_donors":len(eligible),"fixed_exact_donors":len(exact),
                       "screen_codes":screen_codes,"elapsed_seconds":time.monotonic()-started,
                       "policy_sha256":policy.fingerprint,"production_epw_ready":False,
                       "operational_ready":False,"pressure_model_qualified":False})
        result["pressure_time_alignment"]=("EXTERNAL_TARGET_DAY_FIXED" if pressure_by_date is not None
                                            else "DONOR_DATE_NOT_SYNCHRONOUS_WITH_TARGET")
        output.append(result)
        previous=result if "T_K" in result else None
    counts={}
    for r in output:counts[r["status"]]=counts.get(r["status"],0)+1
    if sum(counts.values())!=len(targets):raise AssertionError("P93B3_CENSUS_NOT_EXHAUSTIVE")
    return output,{"total":len(targets),"counts":counts,"seed":seed,
                   "source_semantics_verified":all(t.semantics.verified for t in targets),
                   "pressure_model_qualified":False,"independent_accuracy":"NOT_TESTED",
                   "operational_ready":False,"production_epw_ready":False,
                   "full_weather_radiation_cloud_rain_requalification":"NOT_PERFORMED"}
