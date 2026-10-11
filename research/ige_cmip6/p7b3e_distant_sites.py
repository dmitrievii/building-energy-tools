#!/usr/bin/env python3
"""P7B.3E climate-region observational transfer (Austria only).
Original GeoSphere 10-minute QC, no refitting of Graz frozen M2 cloud library.
No observations are ever treated as GCM event-matched weather forecasts.
"""
from __future__ import annotations
import argparse,csv,hashlib,json
from collections import Counter
from pathlib import Path
from p7b3c_conditional_solar import build_library,load_original_station,sha
from p7b3d_crosssite_generalization import (
    BASE_URL,QUALITY,EVAL_YEARS,ALPHA,CET,
    aggregate_6of6,decode_station_year,fetch_source,run_evaluation
)
from urllib.parse import urlencode

# Distinct-climate Austrian regions; coordinates from ORIGINAL frozen provider
# 10-minute metadata, NOT search rankings selected using M2 outcomes.
SITES={
 105:('Wien_Hohe_Warte',48.24861,16.35639,198.0),
 39:('Innsbruck_Universitaet',47.25986,11.38425,578.0),
 48:('Klagenfurt_Flughafen',46.64833,14.31833,450.0),
 56:('Linz_Stadt',48.29639,14.28528,262.0),
 213:('Sonnblick',47.05417,12.9575,3109.0)
}
YEARS=(2012,2013,2014)
SEEDS=8

def check_original_metadata(meta):
    params={p['name']:p for p in meta.get('parameters',[])}
    if params.get('cglo',{}).get('unit') not in ('W/m²','W/m2','W m-2','W/m^2') or 'cglo_flag' not in params:
        raise ValueError('GeoSphere original GHI/QC metadata incompatible')
    code={int(q['key']):q['value'] for q in meta.get('code_lists',{}).get('q21',[])}
    if not QUALITY<=set(code) or 0 not in code:raise ValueError('original provider QC legend drift')
    stations={int(s['id']):s for s in meta.get('stations',[]) if s.get('id') is not None}
    for sid,(_,lat,lon,height) in SITES.items():
        s=stations.get(sid)
        if not s or not s.get('has_global_radiation'):
            raise ValueError(f'missing original provider site {sid}')
        if any(abs(float(s[k])-v)>t for k,v,t in [('lat',lat,.015),('lon',lon,.015),('altitude',height,20.)]):
            raise ValueError(f'station metadata drift for {sid}')
        if s.get('group_id') in (30,'30'):
            raise ValueError('Graz child station is not independent')
    return True


def summarize(scores):
    rows=[]
    for r in scores:
        rows.append({'site':SITES[r['station_id']][0],
          'station_id':r['station_id'],'year':r['year'],'window':r['window'],
          'approved_complete_days':r['evaluated_days'],
          'M0_monthhour_MAE':r['M0']['climatology_mae'],
          'M2_monthhour_MAE_mean':r['M2']['mean_climatology_mae'],
          'M0_mean_seasonal_p95_rel_error':r['M0']['mean_season_p95_rel_error'],
          'M2_mean_seasonal_p95_rel_error':r['M2']['mean_season_p95_rel_error'],
          'observed_JJA_p95_delta':r['observed']['GHI_p95_jja'],
          'M0_JJA_p95_delta':r['M0']['JJA_p95_delta_model'],
          'M2_JJA_p95_delta':r['M2']['mean_JJA_p95_delta'],
          'max_M2_daily_energy_residual':r['M2']['maximum_energy_residual']})
    return rows


def run(graz,output,seeds=SEEDS):
    if not 2<=seeds<=20:raise ValueError('seed number not registered')
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    libraries={};training={}
    for w in ('record_start','record_end'):
        original,counts=load_original_station(graz,w,(2007,2008))
        libraries[w]=build_library(original);training[w]=counts
    original,meta=fetch_source(BASE_URL+'/metadata')
    check_original_metadata(meta)
    src={'original_Graz_QC_source_sha256':sha(graz),
         'provider_10min_metadata_sha256':hashlib.sha256(original).hexdigest(),
         'official_provider_URL':BASE_URL}
    coverage=[];eligible=[];errors=[];sites_done=[]
    for sid,(name,lat,lon,height) in SITES.items():
        for year in YEARS:
            params={'parameters':'cglo,cglo_flag','station_ids':str(sid),
              'start':f'{year}-01-01T00:00','end':f'{year}-12-31T23:50','output_format':'geojson'}
            url=BASE_URL+'?'+urlencode(params)
            try:
                raw,obj=fetch_source(url)
                times=decode_station_year(obj,sid,year)
                src[f'{sid}_{year}_original_sha256']=hashlib.sha256(raw).hexdigest()
                print('P7B3E fetched original quality-labelled station:',sid,year,len(times),flush=True)
            except Exception as exc:
                errors.append({'station_id':sid,'year':year,'error':str(exc)[:300]})
                print('P7B3E source unavailable: ',sid,year,str(exc)[:150],flush=True)
                continue
            for window in ('record_start','record_end'):
                hourly,qc=aggregate_6of6(times,window,year)
                hourly={dt:v for dt,v in hourly.items() if dt.year==year}
                coverage.append({'site':name,'station_id':sid,'year':year,'window':window,
                        'qualified_original_10min_based_hours':len(hourly),
                        'per_parameter_original_QC':qc})
                try:
                    res=run_evaluation(sid,year,window,lat,lon,hourly,libraries[window],seeds)
                    eligible.append(res)
                    print('P7B3E site-year accepted',sid,year,window,res['evaluated_days'],flush=True)
                except Exception as exc:
                    errors.append({'station_id':sid,'year':year,'window':window,'error':str(exc)[:300]})
    ext={(r['station_id'],r['year']) for r in eligible}
    station_count=len({sid for sid,y in ext});years=len({y for sid,y in ext})
    coverage_pass=(station_count>=2 and years>=2 and len(ext)>=4)
    rows=summarize(eligible)
    if rows:
        with (out/'p7b3e_distant_austria_site_year_scores.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary={'stage':'IGE_P7B3E_DISTANT_AUSTRIAN_REGION_QC_GHI_GENERALIZATION',
       'scientific_status':'OBSERVED_DAILY_KNOWN_ENERGY_HOURLY_RECONSTRUCTION_ONLY',
       'production_epw_ready':False,'geographic_coverage_pass':coverage_pass,
       'new_distinct_site_year_groups':len(ext),'distinct_sites':station_count,'distinct_years':years,
       'frozen_training_Graz':[2007,2008],'frozen_alpha_selection_Graz_2009':ALPHA,
       'test_has_no_site_or_year_parameter_fitting':True,
       'target_known_observed_daily_energy_not_GCM_prediction':True,
       'ground_observed_DHI_or_DNI_validated':False,
       'observation_timestamp_semantics':'UNRESOLVED_REPORT_BOTH',
       'original_source_sha256':src,'coverage':coverage,'failures_or_unavailable':errors,
       'registered_sites':{str(k):list(v) for k,v in SITES.items()},
       'observed_hourly_benchmark':rows,
       'limitations':['All test sites Austria only; no warm desert/maritime/tropical climates',
            'Actual GCM daily radiation bias, timing, model-native calendars not tested here',
            'Historic holdout 2012-14 previously inspected by project for Graz',
            'GHI QC accepted does not imply measured DHI/DNI availability',
            'No geographic site or evaluation-year refitting',
            'The original record-start/end ten-minute convention is unresolved'],
       'derived_files_sha256':{p.name:sha(p) for p in out.glob('*.csv')}}
    (out/'p7b3e_distant_sites_audit.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graz-original',required=True);p.add_argument('--out',required=True)
    p.add_argument('--seeds',type=int,default=SEEDS)
    a=p.parse_args();j=run(a.graz_original,a.out,a.seeds)
    print('P7B3E geographic result',json.dumps({k:j[k] for k in ('geographic_coverage_pass','new_distinct_site_year_groups','distinct_sites','distinct_years')}),flush=True)
    if not j['geographic_coverage_pass']:
        raise SystemExit('P7B3E fail-closed geographic original-QC coverage condition not met')