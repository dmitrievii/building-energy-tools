"""Small review archive; full hourly predictions stay beside the experiment."""
from pathlib import Path
import json
import zipfile
from ige_local.common import InputError,read_json

def create(c):
    root=Path(c['results']);runs=[]
    for name in ('LATEST_BASELINE.json','LATEST_URBAN.json','LATEST_EXPERIMENT.json'):
        p=root/name
        if p.exists():runs.append(Path(read_json(p)['path']))
    runs=sorted(set(runs))
    if not runs:raise InputError('No experiment reports to export')
    target=root/'FULL_CPU_REPORTS.zip';allow={'summary.json','specification.json','preflight.json','comparison.csv','REPORT_RU.md','result.json','coefficients.json','metrics.json','histogram.csv','station_strata.csv'}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for run in runs:
            sid=read_json(run/'summary.json')['store_id']
            matches=[p for p in (root/'stores').glob('*/manifest.json') if read_json(p).get('store_id')==sid]
            if matches:
                m=read_json(matches[0]);reference={k:m[k] for k in ('store_id','origin','full_calendar_ingestion','stations','qc_codebook','operator_codebook','years')}
                z.writestr(run.name+'/source_codebooks_and_geometry.json',json.dumps(reference,ensure_ascii=False,indent=2))
            for p in sorted(run.rglob('*')):
                if not p.is_file() or 'cache' in p.relative_to(run).parts or 'full_refit' in p.relative_to(run).parts:continue
                if p.name in allow or p.suffix in ('.png','.svg'):z.write(p,arcname=run.name+'/'+str(p.relative_to(run)))
    return target
