"""CPU-only full-calendar preparation and controlled urban interpolation tests."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import argparse
import json
from pathlib import Path
import sys

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','preflight','urban','run','plot','import-pilot','export']);p.add_argument('--config',default='config_full_cpu.json');p.add_argument('--store');p.add_argument('--run');p.add_argument('--source-run');p.add_argument('--suite',choices=['all','baseline','urban'],default='all');p.add_argument('--rehash',action='store_true');args=p.parse_args()
    from ige_local.common import InputError,read_json
    from ige_full.config import load
    from ige_full.store import Store,prepare
    from ige_full.study import preflight,run
    try:
        if args.command=='plot':
            from ige_full.plots import create
            if not args.run:raise InputError('plot needs --run')
            print(json.dumps({'figures':create(args.run)},ensure_ascii=False));return 0
        c=load(args.config,require_database=args.command=='prepare')
        if args.command=='export':
            from ige_full.export import create
            print(create(c));return 0
        if args.command=='prepare':
            path=prepare(c,args.rehash);print(json.dumps({'store':str(path.resolve()),'full_calendar_ingestion':True,'C_evaluated':False},ensure_ascii=False,indent=2));return 0
        if args.command=='import-pilot':
            if not args.source_run:raise InputError('import-pilot needs --source-run')
            from ige_full.replay import import_cube
            path=import_cube(c,args.source_run);print(json.dumps({'store':str(path.resolve()),'full_calendar_ingestion':False,'scope':'SPARSE_ENGINEERING_REPLAY_ONLY','C_evaluated':False},ensure_ascii=False,indent=2));return 0
        storepath=args.store or read_json(Path(c['results'])/'LATEST_STORE.json')['path']
        if args.command=='preflight':print(json.dumps(preflight(Store(storepath,verify=True),c),ensure_ascii=False,indent=2));return 0
        if args.command=='urban':
            from ige_full.urban import collect
            print(collect(c,storepath));return 0
        out,summary=run(c,storepath,args.suite)
        from ige_full.plots import create
        create(out)
        print(json.dumps({'run':str(out.resolve()),'exit_code':summary['exit_code'],'completed_jobs':summary['completed_jobs'],'model_jobs':summary['model_jobs'],'C_evaluated':False,'GPU_used':False},ensure_ascii=False,indent=2));return summary['exit_code']
    except (InputError,OSError,ValueError,KeyError) as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
