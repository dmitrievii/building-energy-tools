"""Source-independent temporal quadrature and pressure stress diagnostic.

Fixed analytic curves, not fitted to 2013/2014 or any station. No GPU or EPW.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import numpy as np

from p9_3b3_joint_solver import solve_day,SolverPolicy
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import SourceSemantics,DailyTarget
from p9_3b3_thermodynamics import saturation,q_from_e,relative_humidity


def run():
    report={"kind":"ANALYTIC_DEVELOPMENT_NOT_OBSERVED_CLIMATE","quadrature":[],"pressure_stress":[],
            "pressure_stress_is_not_confidence_interval":True,"production_epw_ready":False}
    for case in range(28):
        values={}
        for n in (24,48,96):
            x=np.arange(n)*2*np.pi/n
            T=265+case+4*np.sin(x)+.8*np.sin(2*x)
            P=97000+200*np.cos(x)
            RH=.6+.1*np.sin(x+.4)
            q=q_from_e(saturation(T)*RH,P)
            values[n]={"q_mean":float(q.mean()),"RH_mean":float(np.mean(relative_humidity(T,P,q))),
                       "T_mean":float(T.mean()),"Tmin":float(T.min()),"Tmax":float(T.max())}
        delta={k:abs(values[24][k]-values[96][k]) for k in values[24]}
        passed=delta["RH_mean"]<=.1 and delta["q_mean"]<=1e-7 and max(delta[k] for k in ("T_mean","Tmin","Tmax"))<=.05
        report["quadrature"].append({"case":case,"node_aggregate_values":values,"delta_24_vs_96":delta,
                                      "numeric_quadrature_gate":"PASS" if passed else "FAIL_REFINEMENT_REQUIRED"})
        # Stress on 24 nodes, fixed source constraints for all pressure branches.
        n=24;x=np.arange(n)*2*np.pi/n;T=265+case+4*np.sin(x)+.8*np.sin(2*x)
        P=97000+200*np.cos(x);q=q_from_e(saturation(T)*(.6+.1*np.sin(x+.4)),P)
        sem=SourceSemantics("DERIVED_TAS_MIDRANGE","WATER",time_support="ANALYTIC_NODE_QUADRATURE",verified=True)
        target=DailyTarget("2014-01-02",float(T.min()),float(T.max()),float((T.min()+T.max())/2),
                           float(q.mean()),float(np.mean(relative_humidity(T,P,q))),sem)
        ref=PressureReference(tuple(P),"ANALYTIC_SOURCE","ANALYTIC_SURFACE")
        for delta_p in (-500,0,500):
            started=time.monotonic()
            r=solve_day(T,q,target,ref.stress(delta_p),policy=SolverPolicy(lower_bound_seconds=.1))
            report["pressure_stress"].append({"case":case,"delta_p_Pa":delta_p,"status":r["status"],
                                              "seconds":time.monotonic()-started})
    report["quadrature_passed"]=all(x["numeric_quadrature_gate"]=="PASS" for x in report["quadrature"])
    report["scope"]="ONLY_THESE_ANALYTIC_CURVES_NOT_GENERAL_HOURLY_WEATHER"
    return report


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--out",required=True);args=ap.parse_args()
    p=Path(args.out)
    if p.exists():raise ValueError("P93B3_NO_BENCHMARK_OVERWRITE")
    p.parent.mkdir(parents=True,exist_ok=True);r=run();p.write_text(json.dumps(r,indent=2)+"\n")
    print("P93B3_DEVELOPMENT_QUADRATURE",r["quadrature_passed"])
