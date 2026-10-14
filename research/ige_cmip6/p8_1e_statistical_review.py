#!/usr/bin/env python3
"""P8.1E secondary transparency audit from paired STATION-level Swiss aggregates.

Station bootstrap is descriptive, not spatial-block independence. Paired target
station-month sets are identical across frozen alternatives; n_months weights
recover the month-weighted global MAE. No observed raw station series needed.
"""
import argparse,csv,io,json,zipfile
from pathlib import Path
import numpy as np

def review(artifact,output,reps=8000):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(artifact) as z:
        rows=list(csv.DictReader(io.StringIO(z.read('external_swiss_stations.csv').decode('utf8'))))
        total=list(csv.DictReader(io.StringIO(z.read('external_swiss_metrics.csv').decode('utf8'))))
        sources=json.loads(z.read('external_swiss_provenance.json'))
    station={}
    for x in rows:
        key=(int(x['buffer_km']),x['station_id']);p=station.setdefault(key,{})
        assert x['method'] not in p
        p[x['method']]={'mae':float(x['MAE_C']),'n':int(x['n_station_months']),
                        'elevation':float(x['elevation_m'])}
    rng=np.random.default_rng(20261014)
    results=[]
    for radius in [0,50]:
        rows2=[(sid,series) for (buf,sid),series in station.items() if buf==radius]
        rows2=sorted(rows2)
        for base in ['idw_fixed65','idw_raw']:
            target='idw_austria_regional'
            diff=np.array([x[base]['mae']-x[target]['mae'] for s,x in rows2],float)
            weights=np.array([x[base]['n'] for s,x in rows2],float)
            assert all(x[base]['n']==x[target]['n'] for s,x in rows2)
            mean=float(np.average(diff,weights=weights))
            ids=rng.integers(0,len(diff),size=(reps,len(diff)))
            boot=np.sum(diff[ids]*weights[ids],axis=1)/np.sum(weights[ids],axis=1)
            results.append({'buffer_km':radius,'baseline':base,'candidate':target,
              'n_stations':len(rows2),'n_station_months':int(np.sum(weights)),
              'mae_improvement_c':mean,'ci_95_c':[float(v) for v in np.quantile(boot,[.025,.975])],
              'stations_improved':int(np.sum(diff>0)),'stations_worsened':int(np.sum(diff<0)),
              'ci_method':'paired resampling of independent station IDs (not regional blocks)',
              'status':'positive only when lower CI > 0'})
    meta={'stage':'P8.1E','analysis':'paired station-cluster bootstrap on published aggregates',
          'validation_source':'MeteoSwiss original 2011-2020, fixed Austrian model 1991-2010',
          'source_train_excludes_test_country':sources['no_swiss_temperature_in_model_fit'],
          'n_qualified_stations':sources['n_qualified_stations'],
          'results':results,'limitations':['30 geographically correlated Swiss stations are not independent spatial blocks.',
            'Station-group averages summarize but cannot reproduce a full timestamp-level paired residual bootstrap.',
            'Site selection metadata-based rather than random; confidence intervals are conditional on selected network.',
            'Comparisons evaluate same-month spatial hindcasting, not forward climate prediction.']}
    (out/'swiss_cluster_bootstrap.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps(meta,indent=2));return meta

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--artifact',required=True);a.add_argument('--out',required=True);s=a.parse_args()
    review(s.artifact,s.out)