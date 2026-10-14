#!/usr/bin/env python3
"""Non-invasive P8.2E diagnostic: hourly absolute humidity [g/m3] and q [g/kg].

Reuses frozen P8.2D/E annual spatial predictor verbatim. MeteoSwiss target
hourly T, e, P, RH are used ONLY downstream in diagnostic validation. Swiss
monthly provider does not include an independently measured absolute humidity
field; rho_v observational reference here is derived from observed T and e.
No original hourly MeteoSwiss values, series, or target observations exported.
"""
from __future__ import annotations
import argparse, collections, csv, hashlib, json, math
from pathlib import Path
import numpy as np
from p8_2e_crossyear import (ROOT, POOL, TARGETS, MONTHS, METHODS, annual_hours,
    parse_swiss_year, donor_set, annual_predict)
from p8_1e_swiss_external import fetch, parse_meta
from p8_2b_humidity import swiss_monthly, train_austria_humidity


def absolute_humidity_gm3(e_hpa, t_c):
    """Partial vapour pressure e in hPa; drybulb T in Celsius; rho_v in g/m3."""
    e=np.asarray(e_hpa, dtype=float); t=np.asarray(t_c, dtype=float)
    if np.any(~np.isfinite(e)) or np.any(~np.isfinite(t)) or np.any(e<=0) or np.any(t<=-273.15):
        raise ValueError('Nonphysical vapour density input')
    return 216.7*e/(273.15+t)


def specific_humidity_gkg(e_hpa,p_hpa):
    """q of moist air in g/kg, unlike absolute humidity it depends on P."""
    e=np.asarray(e_hpa,float);p=np.asarray(p_hpa,float)
    if np.any(~np.isfinite(e)) or np.any(~np.isfinite(p)) or np.any(e<=0) or np.any(p<=e):
        raise ValueError('Nonphysical specific humidity input')
    return 1000*.621945*e/(p-.378055*e)


def scores(predicted, observed):
    a=np.asarray(predicted,float);b=np.asarray(observed,float)
    if a.shape!=b.shape or len(a)==0 or np.any(~np.isfinite(a)) or np.any(~np.isfinite(b)):
        raise ValueError('Incorrect paired diagnostics inputs')
    d=a-b
    return {'n_hours':int(len(d)),'MAE':float(np.abs(d).mean()),
            'RMSE':float(np.sqrt(np.mean(d*d))), 'bias':float(d.mean()),
            'mean_observed':float(b.mean()),'mean_predicted':float(a.mean()),
            'normalized_MAE_pct':float(100*np.abs(d).mean()/b.mean()),
            'P90_abs':float(np.quantile(np.abs(d),.90))}


def diagnose(pred,observed,indices,hours):
    """Target values are only accessible inside this scoring function."""
    rows=[observed[hours[i]] for i in indices]
    te=np.array([r['e'] for r in rows]);tt=np.array([r['T'] for r in rows]);tp=np.array([r['P'] for r in rows]);rh=np.array([r['RH'] for r in rows]);
    pe=pred['e'][indices];pt=pred['T'][indices];pp=pred['P'][indices]
    ref=absolute_humidity_gm3(te,tt)
    estimate=absolute_humidity_gm3(pe,pt)
    components={'rho_v_model':estimate,
                'rho_v_oracle_T':absolute_humidity_gm3(pe,tt),
                'rho_v_oracle_e':absolute_humidity_gm3(te,pt)}
    result={key:scores(val,ref) for key,val in components.items()}
    result['q_gkg_model']=scores(specific_humidity_gkg(pe,pp),specific_humidity_gkg(te,tp))
    mask=rh>=90
    if not np.any(mask):raise ValueError('No high humidity reference hours')
    result['rho_v_observed_RH_ge90']=scores(estimate[mask],ref[mask])
    result['high_rh_n_hours']=int(mask.sum())
    result['rh_observed_ge90_rate_pct']=float(100*mask.mean())
    result['rh_predicted_ge90_rate_pct']=float(100*np.mean(pred['RH'][indices]>=90))
    return result


def execute(out,normals,year,targets=TARGETS):
    if year not in (2018,2019,2020):raise ValueError('Year not frozen in P8.2D/E baseline')
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw,meta_digest=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    meta,_=parse_meta(raw)
    sel={sid:meta[sid] for sid in POOL if sid in meta}
    if not set(targets).issubset(sel):raise ValueError('Missing targets in observed station metadata')
    hours=annual_hours(year)
    weather={};monthly={};source=[];excluded=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for sid in sel:
        try:
            hblob,dig=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            weather[sid],_ = parse_swiss_year(hblob,sid,year)
            source.append({'site':sid,'type':'hourly','sha256':dig,'n_source_hours':len(weather[sid])})
            mblob,dig=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid]=swiss_monthly(mblob,sid)[0]
            source.append({'site':sid,'type':'monthly','sha256':dig})
        except Exception as ex:
            excluded.append({'site':sid,'error_type':type(ex).__name__,'message':str(ex)[:150]})
    loge,tslopes,cal=train_austria_humidity(normals)
    detailed=[];diagnostics=[]
    for site in targets:
        if site not in weather:raise ValueError('Missing site for diagnostic '+site)
        # Prevent target meteorology from entering model, including monthly inputs.
        donor_weather={s:v for s,v in weather.items() if s!=site}
        donor_monthly={s:v for s,v in monthly.items() if s!=site}
        donors=donor_set(meta[site],sel,donor_weather,donor_monthly,year=year)
        predictions,diag=annual_predict(meta[site],donors,hours,donor_weather,donor_monthly,
                                         loge,tslopes,year=year)
        indices=np.array([i for i,t in enumerate(hours) if t in weather[site] and all(
            weather[site][t].get(k) is not None for k in ('T','e','P','RH'))],dtype=int)
        if len(indices)<.95*len(hours):raise ValueError('Insufficient complete target validation hours')
        for method,pred in predictions.items():
            values=diagnose(pred,weather[site],indices,hours)
            for variant,item in values.items():
                if not isinstance(item,dict):continue
                detailed.append({'year':year,'site':site,'method':method,'metric':variant,**item})
        diagnostics.append({'site':site,'n_valid':len(indices),
                            'donor_ids':[s['station_id'] for _,s in donors],
                            'no_target_used_for_model':diag['target_meteorology_read_for_prediction'] is False})
    out_rows=[]
    for method in METHODS:
        for metric in ('rho_v_model','rho_v_oracle_T','rho_v_oracle_e','rho_v_observed_RH_ge90','q_gkg_model'):
            a=[x for x in detailed if x['method']==method and x['metric']==metric]
            if len(a)!=len(targets):raise ValueError('Missing site metrics '+str((method,metric)))
            total=sum(x['n_hours'] for x in a)
            out_rows.append({'year':year,'method':method,'metric':metric,'n_hours':total,
                             'n_sites':len(a),'MAE':sum(x['MAE']*x['n_hours'] for x in a)/total,
                             'RMSE':math.sqrt(sum(x['RMSE']**2*x['n_hours'] for x in a)/total),
                             'bias':sum(x['bias']*x['n_hours'] for x in a)/total,
                             'mean_observed':sum(x['mean_observed']*x['n_hours'] for x in a)/total,
                             'mean_predicted':sum(x['mean_predicted']*x['n_hours'] for x in a)/total})
    def emit(filename,rows):
        with (dest/filename).open('w',newline='',encoding='utf-8') as f:
            wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
    emit('absolute_humidity_station_metrics.csv',detailed)
    emit('absolute_humidity_annual_metrics.csv',out_rows)
    manifest={'stage':'P8.2E_ABSOLUTE_HUMIDITY_POSTHOC_DIAGNOSTIC','year':year,
       'n_source_year_hours':len(hours), 'target_sites':list(targets),
       'reference':'MeteoSwiss observed hourly e and T transformed to absolute humidity g/m3; not independently measured density',
       'e_unit':'hPa','T_unit':'degC','P_unit':'hPa','rho_v_unit':'g/m3','q_unit':'g/kg moist air',
       'frozen_original_model':'P8.2D/P8.2E donor-only annual_predict without edits or additional fit',
       'predictor_excludes_target':True,'oracle_T_and_e_are_diagnostics_not_deployable_models':True,
       'source_station_digest':meta_digest,'provider_checksums':source,
       'austria_calibration':cal,'diagnostics':diagnostics,'source_errors':excluded,
       'no_original_observation_series_exported':True,'metrics':out_rows,
       'caveats':['Vapour density reference is derived from two Swiss fields; not an independent absolute-humidity sensor.',
                  'This is post-hoc verification on previously seen 2018-2020 test years, not new generalization.',
                  'Atmospheric pressure does not enter vapour density, but enters specific humidity.',
                  'Conditioning on observed target high RH is FOR DIAGNOSTICS ONLY and was never provided to predictors.']}
    (dest/'absolute_humidity_provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('IGE_P8_2E_ABSOLUTE_HUMIDITY',json.dumps({'year':year,'n_sites':len(targets),
      'n_hours':sum(x['n_valid'] for x in diagnostics),
      'full_multidonor':[x for x in out_rows if x['method']=='full_multidonor_shape'],
      'diagnostics':diagnostics},ensure_ascii=False),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',required=True,type=int)
    p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    execute(args.out,args.austria_station_normals,args.year)