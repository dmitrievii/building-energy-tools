#!/usr/bin/env python3
"""IGE: common-output comparison of RH, log(e), and specific humidity q."""
import os
for _name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
    os.environ[_name]="1"
import argparse
from pathlib import Path
import sys
import traceback


def main(argv=None):
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(errors="backslashreplace")
    from ige_hum import VERSION
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version",action="version",version=VERSION)
    subs=parser.add_subparsers(dest="command",required=True)
    for name in ("run","prepare","check-config"):
        p=subs.add_parser(name)
        p.add_argument("--config",type=Path,default=Path(__file__).resolve().parent/"config_humidity_comparison.json")
        if name!="check-config":p.add_argument("--rehash",action="store_true")
    p=subs.add_parser("fit");p.add_argument("--config",type=Path,required=True);p.add_argument("--cube",type=Path,required=True)
    for name in ("resume","evaluate"):
        p=subs.add_parser(name);p.add_argument("--run",type=Path,required=True)
        if name=="evaluate":p.add_argument("--repeat",action="store_true")
    p=subs.add_parser("recover");p.add_argument("--run",type=Path,required=True)
    p.add_argument("--anchor",type=Path,help="Relocated original split file; its sealed contents must be identical")
    subs.add_parser("self-check")
    args=parser.parse_args(argv);root=None
    try:
        from ige_local.common import new_run,write_json,log,source_audit_failed
        if args.command=="check-config":
            from ige_hum.config import load
            h,c,anchor=load(args.config)
            import json
            print(json.dumps({"configuration_valid":True,"database":c["database"],"results":h["results"],
                "anchor_split_id":anchor["split_id"],"C_opened":False},ensure_ascii=True,indent=2));return 0
        if args.command=="self-check":
            import numpy as np,json
            from ige_hum.physics import q_from_e,e_from_q,restore,dewpoint_water
            from ige_auto.data import buck_water
            e=np.array([1.,5.,10.]);p=np.array([700.,900.,1013.25]);q=q_from_e(e,p)
            assert np.allclose(e_from_q(q,p),e,rtol=1e-12)
            assert abs(float(dewpoint_water(buck_water(10.)))-10.)<1e-10
            assert float(restore("RH",np.array([110.]),np.array([20.]),np.array([1000.]))["RH"][0])==110.
            print(json.dumps({"q_e_roundtrip":"PASS","Buck_inverse":"PASS","no_RH_clipping":"PASS","C_opened":False}));return 0
        from ige_hum.study import train,evaluate,create_spec
        if args.command=="recover":
            from ige_hum.recovery import fork_run
            root=fork_run(args.run,args.anchor)
            result=train(root)
            log("REPORT: "+str(root/"REPORT_RU.md"));log("SUMMARY: "+str(root/"summary.json"))
            return result["exit_code"]
        if args.command=="resume":return train(args.run)["exit_code"]
        if args.command=="evaluate":return evaluate(args.run,args.repeat)["exit_code"]
        from ige_hum.config import load
        from ige_auto.data import Cube,build
        from ige_auto.config import native_config
        h,c,anchor=load(args.config);root=new_run(h["results"])
        write_json(root/"effective_config.json",h);write_json(root/"base_config.resolved.json",c)
        log("IGE humidity comparison "+VERSION);log("Run: "+str(root));log("C remains computationally withheld")
        if args.command=="fit":cube=Cube(args.cube)
        else:
            from ige_local.audit import audit
            snapshot,report=audit(native_config(c),root/"E0",rehash=args.rehash)
            if source_audit_failed(report):
                write_json(root/"summary.json",{"exit_code":2,"status":"SOURCE_AUDIT_FAILED","holdout_opened":False})
                return 2
            cube=Cube(build(snapshot,c,root/"cube",audit_summary=report));del snapshot
        create_spec(cube,h,c,anchor,root)
        if args.command=="prepare":log("Prepared study: "+str(root));return 0
        result=train(root);log("REPORT: "+str(root/"REPORT_RU.md"));log("SUMMARY: "+str(root/"summary.json"))
        return result["exit_code"]
    except Exception as exc:
        print(type(exc).__name__+": "+str(exc))
        if root:
            from ige_local.common import write_json
            write_json(root/"failure.json",{"error":str(exc),"traceback":traceback.format_exc(),"C_opened":False})
        return 2


if __name__=="__main__":raise SystemExit(main())
