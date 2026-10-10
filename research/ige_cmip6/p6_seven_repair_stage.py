#!/usr/bin/env python3
"""Stage exactly 28 prior passing and 7 repaired P6.1 artifacts for final audit.

Preserves bytewise original source CSV, provenance and SHA-256 in separate CI runs.
Never promotes failed/truncated outputs or treats job success as valid data.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil

from p6_seven_daily import MODELS, WINDOWS

REPAIR = {
    ('EC-Earth3','historical-1995-2014'),
    ('EC-Earth3','ssp245-2040-2059'),
    ('IPSL-CM6A-LR','historical-1995-2014'),
    ('IPSL-CM6A-LR','ssp245-2080-2099'),
    ('MPI-ESM1-2-HR','historical-1995-2014'),
    ('MPI-ESM1-2-HR','ssp245-2040-2059'),
    ('MPI-ESM1-2-HR','ssp585-2040-2059'),
}

def stage(prior, repaired, destination):
    if len(REPAIR)!=7 or len(MODELS)*len(WINDOWS)!=35:
        raise ValueError('Invalid repair scope')
    report={'status':'IN_PROGRESS','prior_run_id':38072042977,
            'repaired':[],'retained':[]}
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Destination must be empty')
    destination.mkdir(parents=True,exist_ok=True)
    for model in MODELS:
        for window in WINDOWS:
            name=f'ige-p6-{model}-{window}'
            category='repaired' if (model,window) in REPAIR else 'retained'
            src=(repaired if category=='repaired' else prior)/name
            if not src.is_dir():
                raise ValueError(f'Missing {category} artifact: {src}')
            quality=src/'quality_report.json'
            prov=src/'source_provenance.json'
            if not quality.is_file() or not prov.is_file():
                raise ValueError(f'Incomplete {category} artifact: {src}')
            qa=json.loads(quality.read_text())
            p=json.loads(prov.read_text())
            if qa.get('status')!='PASS' or p.get('status')!='PASS':
                raise ValueError(f'Cannot promote invalid {category} artifact: {src}')
            if qa.get('model')!=model or qa.get('window')!=window:
                raise ValueError('Model/window folder metadata mismatch')
            shutil.copytree(src,destination/name)
            report[category].append(name)
    if len(report['repaired'])!=7 or len(report['retained'])!=28:
        raise ValueError('Wrong staging totals')
    report['status']='PASS'
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--prior',type=Path,default=Path('p6_prior'))
    p.add_argument('--repaired',type=Path,default=Path('p6_repaired'))
    p.add_argument('--destination',type=Path,default=Path('p6_downloaded'))
    p.add_argument('--report',type=Path,default=Path('outputs/p6_seven_repair_stage.json'))
    a=p.parse_args()
    report={'status':'NOT_RUN'}
    try:report=stage(a.prior,a.repaired,a.destination)
    except Exception as exc:
        report={'status':'FAIL','error':str(exc)}
        raise
    finally:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,indent=2)+'\n')
        print('Staging P6.1 seven-model artifacts:',report['status'],flush=True)

if __name__=='__main__':
    main()
