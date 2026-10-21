"""P9.3B3 CLI. No overwrite, hidden source relaxation, or production EPW."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

from p9_3b3_generator import ThermoDonor,generate
from p9_3b3_joint_solver import SolverPolicy
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import DailyTarget,audit_csv,fetch_metadata


def run(mode,manifest,out,policy_file=None):
    source=Path(manifest).read_bytes()
    m=json.loads(source)
    out=Path(out)
    if out.exists():raise ValueError("P93B3_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    out.mkdir(parents=True)
    started=time.monotonic()
    policy=SolverPolicy(**json.loads(Path(policy_file).read_text())) if policy_file else SolverPolicy()
    if mode=="audit-semantics":
        from concurrent.futures import ThreadPoolExecutor
        from p9_3b3_source_time_support import fetch_time_support
        def audit_one(pair):
            v,y=pair;meta=fetch_metadata(v,y)
            return meta,fetch_time_support(meta)
        with ThreadPoolExecutor(max_workers=4) as pool:
            evidence=list(pool.map(audit_one,[(v,y) for y in (2013,2014)
                for v in ("tas","tasmin","tasmax","hurs","huss")]))
        report={"mode":mode,"source_csv":audit_csv(m["csv_path"]),
                "metadata":[x[0] for x in evidence],"native_time_support":[x[1] for x in evidence],
                "all_variable_intervals_verified":all(x[1]["interval_semantics_verified"] for x in evidence),
                "time_bounds_not_inferred":True,"production_epw_ready":False}
    elif mode in ("strict","reconcile-research"):
        targets=[DailyTarget.from_dict(t) for t in m["targets"]]
        donors=[]
        for row in m["donors"]:
            d=dict(row);d["pressure"]=PressureReference(**d["pressure"])
            donors.append(ThermoDonor(**d))
        rows,summary=generate(targets,donors,seed=m.get("seed",7313),policy=policy,
                              reconcile=mode=="reconcile-research",wet_by_date=m.get("wet_by_date"),
                              pressure_by_date={d:PressureReference(**p) for d,p in m["pressure_by_date"].items()}
                              if "pressure_by_date" in m else None)
        report={"mode":mode,"days":rows,"summary":summary,
                "independent_accuracy":"NOT_TESTED","operational_ready":False}
    elif mode=="score-frozen":
        from p9_3b3_at_de_ch_validation import score_frozen
        report=score_frozen(m)
    else:
        raise ValueError("P93B3_UNKNOWN_CLI_MODE")
    report.update({"manifest_sha256":hashlib.sha256(source).hexdigest(),"policy_sha256":m.get("policy_sha256",policy.fingerprint) if mode=="score-frozen" else policy.fingerprint,
                   "elapsed_seconds":time.monotonic()-started,"production_epw_ready":False})
    (out/"p9_3b3_report.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode",choices=("audit-semantics","strict","reconcile-research","score-frozen"),required=True)
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--policy")
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    result=run(a.mode,a.manifest,a.out,a.policy)
    print("P93B3_RESULT",json.dumps({k:v for k,v in result.items() if k in (
        "mode","summary","independent_accuracy","production_epw_ready","elapsed_seconds")}))


if __name__=="__main__":main()
