#!/usr/bin/env python3
"""Sequential, resumable interpolation experiments; never evaluates C."""
import os
# The study is deliberately single process, including native BLAS thread pools.
for _name in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
    os.environ[_name]="1"
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="command",required=True)
    for command in ("prepare","run"):
        q=sub.add_parser(command);q.add_argument("--config",default="config_interpolation_v030.json")
        q.add_argument("--source-run");q.add_argument("--out")
    q=sub.add_parser("resume");q.add_argument("--run",required=True)
    args=p.parse_args(argv)
    from ige_local.common import InputError
    try:
        from ige_next.config import load
        from ige_next.study import prepare,train
        if args.command=="resume":result=train(args.run)
        else:
            c=load(args.config)
            if args.source_run:c["source_run"]=str(Path(args.source_run).resolve())
            if args.out:c["results"]=str(Path(args.out).resolve())
            out=prepare(c)
            if args.command=="prepare":print(json.dumps({"run_directory":str(out),"C_evaluation_implemented":False},indent=2));return 0
            result=train(out)
        print(json.dumps(result,ensure_ascii=False,indent=2));return result["exit_code"]
    except (InputError,ValueError,OSError) as exc:
        print(type(exc).__name__+": "+str(exc),file=sys.stderr);return 2


if __name__=="__main__":sys.exit(main())
