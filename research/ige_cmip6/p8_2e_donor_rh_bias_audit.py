#!/usr/bin/env python3
"""IGE P8.2E post-hoc donor-RH versus temperature-bias audit, no refitting.

Run unmodified P8.2E annual_predict for Swiss heldout sites and 2018-2020.
Predictor inputs never contain target hourly or monthly observations.
Donor RH features use *only actual stations used by the original temperature
predictor at each hour*, with exactly the same distance weights. Results contain
aggregated station/month/season/daypart/donor-bin statistics, NO raw provider
hourly values, names/timestamps/temperature series or learned corrections.

This is an explored test set: correlation is not deployable causal validation.
"""
from __future__ import annotations
import argparse, collections, csv, json, math, datetime as dt
from pathlib import Path
import numpy as np

METHOD='full_multidonor_shape'
# Frozen bins defined before examining the result, in % RH.
BIN_EDGES=(0.,60.,70.,80.,90.,95.,106.)
BIN_LABELS=('0-<60','60-<70','70-<80','80-<90','90-<95','95-105')
SEASONS={12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}


def donor_humidity_at_hour(when,donors,weather,monthly,year):
    """Exact same eligible T/P/e donor set and weights as frozen P8.2E.

    Fail closed for RH missing at *any* donor used to predict target T; never
    substitute target RH or change donor weights to improve correlations.
    """
    from p8_2e_crossyear import weights
    stamp=f'{year}-{when.month:02d}';eligible=[]
    for distance,station in donors:
        sid=station['station_id'];row=weather.get(sid,{}).get(when)
        month=monthly.get(sid,{}).get(stamp)
        if row is None or any(row.get(k) is None for k in ('T','P','e')) or not month or month.get('e') is None:
            continue
        rh=row.get('RH')
        if rh is None or not math.isfinite(rh) or not 0<=rh<=105:
            return None
        eligible.append((distance,float(rh)))
    if len(eligible)<2:return None
    d=np.array([x[0] for x in eligible]);rh=np.array([x[1] for x in eligible]);w=weights(d)
    return {'donor_RH_weighted_pct':float(np.dot(w,rh)),
            'donor_wet_fraction_weighted':float(np.dot(w,(rh>=90).astype(float))),
            'donor_wet_count':int(np.count_nonzero(rh>=90)),
            'n_donors':len(eligible),'donor_RH_max_pct':float(np.max(rh))}


def bin_index(rh):
    if not math.isfinite(rh) or rh<0 or rh>105:raise ValueError('RH outside provider domain')
    return int(min(len(BIN_LABELS)-1,max(0,np.searchsorted(np.array(BIN_EDGES[1:-1]),rh,side='right'))))


def cet_daypart(hour):
    if not 0<=hour<24:raise ValueError('Invalid UTC timestamp hour')
    h=(hour+1)%24
    return ('00-05','06-11','12-17','18-23')[h//6]


def aggregate(rows,key_fields):
    """Aggregate weighted means and missed events from accumulated sufficient stats."""
    group=collections.defaultdict(list)
    for r in rows:group[tuple(r[x] for x in key_fields)].append(r)
    out=[]
    sums=('sum_temperature_error_C','sum_abs_temperature_error_C','sum_e_error_hpa',
          'sum_model_T_C','sum_observed_T_C','sum_donor_RH_pct',
          'observed_wet_hours','model_wet_hours','missed_wet_hours','correct_wet_hours',
          'positive_temperature_error_hours','donor_some_wet_hours','donor_all_wet_hours')
    for key,items in sorted(group.items()):
        n=sum(r['n_hours'] for r in items)
        if n==0:continue
        row={k:v for k,v in zip(key_fields,key)}
        row.update({x:sum(r[x] for r in items) for x in sums})
        row['n_hours']=n
        row['T_bias_C']=row['sum_temperature_error_C']/n
        row['T_MAE_C']=row['sum_abs_temperature_error_C']/n
        row['e_bias_hpa']=row['sum_e_error_hpa']/n
        row['mean_donor_RH_pct']=row['sum_donor_RH_pct']/n
        row['observed_wet_rate_pct']=100*row['observed_wet_hours']/n
        row['predicted_wet_rate_pct']=100*row['model_wet_hours']/n
        row['wet_recall']=row['correct_wet_hours']/row['observed_wet_hours'] if row['observed_wet_hours'] else None
        row['missed_wet_rate_pct_of_all_hours']=100*row['missed_wet_hours']/n
        row['warm_error_rate_pct']=100*row['positive_temperature_error_hours']/n
        row['some_wet_donors_rate_pct']=100*row['donor_some_wet_hours']/n
        out.append(row)
    return out


def build_audit_rows(site,year,hours,donors,donor_weather,donor_monthly,pred,target,minimum_coverage=.95):
    """Target observations used *only* for numerical scoring, never as features."""
    site_records=[];missing_donor_rh=0;missing_target=0
    if site in donor_weather or site in donor_monthly or any(s['station_id']==site for _,s in donors):
        raise AssertionError('TARGET_STATION_LEAKAGE')
    for i,t in enumerate(hours):
        features=donor_humidity_at_hour(t,donors,donor_weather,donor_monthly,year)
        if features is None:missing_donor_rh+=1;continue
        observed=target.get(t)
        if not observed or any(observed.get(k) is None for k in ('T','e','RH')):
            missing_target+=1;continue
        pb=float(pred['T'][i]);pe=float(pred['e'][i]);prh=float(pred['RH'][i])
        if not all(math.isfinite(x) for x in (pb,pe,prh)):
            raise ValueError('NONFINITE_FROZEN_PREDICTION')
        oe=float(observed['e']);ot=float(observed['T']);orh=float(observed['RH'])
        wet=orh>=90;detected=prh>=90
        label=BIN_LABELS[bin_index(features['donor_RH_weighted_pct'])]
        err=pb-ot
        site_records.append({'site':site,'year':year,'month':t.month,'season':SEASONS[t.month],
             'CET_daypart':cet_daypart(t.hour),'donor_RH_bin':label,
             'n_hours':1,'sum_temperature_error_C':err,'sum_abs_temperature_error_C':abs(err),
             'sum_e_error_hpa':pe-oe,'sum_model_T_C':pb,'sum_observed_T_C':ot,
             'sum_donor_RH_pct':features['donor_RH_weighted_pct'],
             'observed_wet_hours':int(wet),'model_wet_hours':int(detected),
             'missed_wet_hours':int(wet and not detected),'correct_wet_hours':int(wet and detected),
             'positive_temperature_error_hours':int(err>0),
             'donor_some_wet_hours':int(features['donor_wet_count']>0),
             'donor_all_wet_hours':int(features['donor_wet_count']==features['n_donors'])})
    if len(site_records)<minimum_coverage*len(hours):
        raise RuntimeError(f'UNQUALIFIED_DONOR_RH_COVERAGE {site} {year} {len(site_records)}/{len(hours)}')
    return site_records,{'site':site,'year':year,'n_qualified_hours':len(site_records),
            'missing_donor_RH_hours':missing_donor_rh,'missing_target_hours':missing_target,
            'donors':[s['station_id'] for _,s in donors],'target_meteorology_used_as_feature':False}


def make_csv(path,rows):
    if not rows:raise ValueError('No aggregate metrics')
    fields=list(rows[0]);with_file=Path(path)
    with with_file.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)


def run(year,normals,out,targets=('ABO','BER','PAY')):
    if year not in (2018,2019,2020):raise ValueError('Only pre-examined P8.2E audit years allowed')
    from p8_2e_crossyear import ROOT,POOL,annual_hours,parse_swiss_year,donor_set,annual_predict
    from p8_1e_swiss_external import fetch,parse_meta
    from p8_2b_humidity import swiss_monthly,train_austria_humidity
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    blob,station_meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    meta,_=parse_meta(blob)
    sites={k:meta[k] for k in POOL if k in meta}
    if not set(targets).issubset(sites):raise RuntimeError('MISSING_TARGET_STATIONS')
    hours=annual_hours(year);weather={};monthly={};source=[];missing=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for site in sites:
        try:
            blob,sha=fetch(f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            weather[site],_=parse_swiss_year(blob,site,year)
            source.append({'site':site,'type':'hourly','sha256':sha,'bytes':len(blob)})
            blob,sha=fetch(f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_m.csv',max_bytes=20000000)
            monthly[site],_=swiss_monthly(blob,site)
            source.append({'site':site,'type':'monthly','sha256':sha,'bytes':len(blob)})
        except Exception as exc:
            missing.append({'site':site,'type':type(exc).__name__,'message':str(exc)[:160]})
    loge,tslope,cal=train_austria_humidity(normals)
    all_details=[];coverage=[]
    for site in targets:
        dw={s:w for s,w in weather.items() if s!=site}
        dm={s:w for s,w in monthly.items() if s!=site}
        donors=donor_set(sites[site],sites,dw,dm,year=year)
        pred,provenance=annual_predict(sites[site],donors,hours,dw,dm,loge,tslope,year=year)
        if provenance.get('target_meteorology_read_for_prediction') is not False:raise AssertionError('PREDICTOR_LEAKED')
        details,counts=build_audit_rows(site,year,hours,donors,dw,dm,pred[METHOD],weather[site])
        all_details.extend(details);coverage.append(counts)
    groups={
      'rh_bin_overall':aggregate(all_details,['donor_RH_bin']),
      'rh_bin_by_site':aggregate(all_details,['site','donor_RH_bin']),
      'rh_bin_by_season':aggregate(all_details,['season','donor_RH_bin']),
      'rh_bin_by_daypart':aggregate(all_details,['CET_daypart','donor_RH_bin']),
      'rh_bin_by_site_month':aggregate(all_details,['site','month','donor_RH_bin']),
      'site_season':aggregate(all_details,['site','season']),
      'site_overall':aggregate(all_details,['site'])}
    for name,rows in groups.items():make_csv(dest/(name+'.csv'),rows)
    manifest={'phase':'IGE_P8_2E_DONOR_RH_CONDITIONAL_TEMPERATURE_BIAS','year':year,
        'model':'P8.2E full_multidonor_shape FROZEN; NO CORRECTION/FITTING',
        'target_meteorology_used_to_construct_donor_features':False,
        'time_basis':'Nominal MeteoSwiss UTC end-of-hour; CET UTC+1 modulo 24 (no DST)',
        'donor_rh':'Same donors and inverse-square distance weights as predicted T; discard if any used donor RH missing',
        'bins':list(BIN_LABELS),'n_total_scored':sum(c['n_qualified_hours'] for c in coverage),
        'coverage':coverage,'metrics':groups['rh_bin_overall'],
        'Austrian_training':cal,'station_metadata_sha256':station_meta_sha,
        'source_sha256':source,'source_failures':missing,'raw_hourly_provider_data_exported':False,
        'scientific_limits':['Already inspected years 2018-2020; no new independent validation',
           'Association of donor RH with temperature residual need not be causal or monotone',
           'Target RH used only to report event scoring, never as donor feature or model input',
           'A correction fitted after this analysis needs new heldout geographic/year targets',
           'Only three Swiss target stations are evaluated']}
    (dest/'donor_rh_audit_provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('IGE_DONOR_RH_T_BIAS',json.dumps({'year':year,'n_hours':manifest['n_total_scored'],
          'bins':groups['rh_bin_overall'],'sites':groups['site_overall'],
          'coverage':coverage},ensure_ascii=False),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True)
    p.add_argument('--austria-station-normals',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.year,a.austria_station_normals,a.out)