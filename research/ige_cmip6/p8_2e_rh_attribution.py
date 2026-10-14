#!/usr/bin/env python3
"""IGE P8.2E post-hoc, no-retuning T versus vapour e attribution of RH error.

Runs frozen P8.2E annual_predict with ONLY donor station meteorology.
Target T, e, P, RH are made available only to score four counterfactual
states. No source hourly observed series are exported. The counterfactuals are
not deployable predictions, and can exceed RH=100% (never silently clipped).
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,math
from pathlib import Path
import numpy as np

VARIANTS=("model_T_model_e","observed_T_model_e","model_T_observed_e","observed_T_observed_e")
METHOD="full_multidonor_shape"


def esat(t):
    """Buck (1981) liquid-water saturation, hPa; same as P8.2A-D reference."""
    a=np.asarray(t,float)
    return 6.1121*np.exp((18.678-a/234.5)*(a/(257.14+a)))


def psychrometric_states(mt,me,ot,oe,mp,op,rh,model_rh=None):
    """Return unmodified RH counterfactuals (not clipped) on identical hours."""
    inp=[np.asarray(x,float) for x in (mt,me,ot,oe,mp,op,rh)]
    if len({x.shape for x in inp})!=1 or inp[0].ndim!=1 or len(inp[0])==0:
        raise ValueError('All arrays must be paired one-dimensional hourly series')
    if any(not np.isfinite(x).all() for x in inp):raise ValueError('Nonfinite station observations or estimates')
    mt,me,ot,oe,mp,op,ref=inp
    if np.any(me<=0) or np.any(oe<=0) or np.any(mp<=me) or np.any(op<=oe):
        raise ValueError('Nonphysical input pressure or vapour')
    if np.any(mt<=-70) or np.any(ot<=-70):raise ValueError('Nonphysical temperature')
    sm=esat(mt);so=esat(ot)
    states={"model_T_model_e":100*me/sm,
            "observed_T_model_e":100*me/so,
            "model_T_observed_e":100*oe/sm,
            "observed_T_observed_e":100*oe/so}
    if model_rh is not None and not np.allclose(states['model_T_model_e'],model_rh,atol=1e-8,rtol=1e-10):
        raise AssertionError('Frozen model RH does not close against model e/T')
    # Pressure P cancels IDENTICALLY from RH(e,T); pressure coupling to e only
    # through P8.2D reconciler e<0.98 P bound, measured by cap_margin below.
    return states


def indicators(estimate,observed,threshold=90.0):
    estimate=np.asarray(estimate,float);observed=np.asarray(observed,float)
    if estimate.shape!=observed.shape or not len(estimate):raise ValueError('Unpaired events')
    pp=estimate>=threshold;oo=observed>=threshold
    tp=int(np.count_nonzero(pp&oo));fp=int(np.count_nonzero(pp&~oo));fn=int(np.count_nonzero(~pp&oo))
    return {'tp':tp,'fp':fp,'fn':fn,'obs_count':int(oo.sum()),'pred_count':int(pp.sum()),
        'precision':tp/(tp+fp) if tp+fp else 0.,
        'recall':tp/(tp+fn) if tp+fn else 0.,
        'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.}


def scores(estimate,reference):
    d=np.asarray(estimate,float)-np.asarray(reference,float)
    return {'sum_absolute_error':float(np.abs(d).sum()),'sum_square_error':float(np.square(d).sum()),
            'sum_signed_error':float(d.sum()),'MAE_pp':float(np.abs(d).mean()),
            'RMSE_pp':float(np.sqrt(np.square(d).mean())),'bias_pp':float(d.mean())}


def analyze(mt,me,ot,oe,mp,op,rh,model_rh=None):
    states=psychrometric_states(mt,me,ot,oe,mp,op,rh,model_rh)
    n=len(states['model_T_model_e']);out={}
    for name,pred in states.items():
        ev=indicators(pred,rh);err=scores(pred,rh)
        out[name]={'n_hours':n,**err,**ev,'n_supersaturated_counterfactual':int(np.count_nonzero(pred>100.0+1e-8))}
    # Fair symmetric path-average attribution on the MAE loss vs reported RH.
    # Contributions may be negative when errors compensate; sum is exact.
    f=lambda k:out[k]['MAE_pp']
    base=f('model_T_model_e'); tfix=f('observed_T_model_e');efix=f('model_T_observed_e');perfect=f('observed_T_observed_e')
    temp_contrib=.5*((base-tfix)+(efix-perfect))
    vapour_contrib=.5*((base-efix)+(tfix-perfect))
    if abs((temp_contrib+vapour_contrib)-(base-perfect))>1e-8:
        raise AssertionError('Symmetric attribution does not sum to excess MAE')
    cap=np.minimum(esat(mt),.98*np.asarray(mp,float))
    return out,{
       'n_hours':n, 'model_rh_mae_pp':base,'measured_eT_vs_published_RH_mae_pp':perfect,
       'fix_T_only_mae_gain_pp':base-tfix,'fix_e_only_mae_gain_pp':base-efix,
       'symmetric_T_MAE_contribution_pp':temp_contrib,
       'symmetric_e_MAE_contribution_pp':vapour_contrib,
       'n_model_atmospheric_pressure_capacity_limited':int(np.count_nonzero(.98*np.asarray(mp,float)<esat(mt))),
       'max_predicted_e_over_P':float(np.max(np.asarray(me,float)/np.asarray(mp,float))),
       'max_observed_e_over_P':float(np.max(np.asarray(oe,float)/np.asarray(op,float)))
    }


def grouped(results):
    """Aggregate from sums and contingency counts, not arithmetic mean of F1."""
    groups=collections.defaultdict(list)
    for r in results:groups[(r['year'],r['method'],r['variant'])].append(r)
    totals=[]
    for (year,method,variant),part in sorted(groups.items()):
        n=sum(r['n_hours'] for r in part);tp=sum(r['tp'] for r in part);fp=sum(r['fp'] for r in part);fn=sum(r['fn'] for r in part)
        se=sum(r['sum_absolute_error'] for r in part);sse=sum(r['sum_square_error'] for r in part);signed=sum(r['sum_signed_error'] for r in part)
        totals.append({'year':year,'method':method,'variant':variant,'n_sites':len(part),'n_hours':n,
          'MAE_pp':se/n,'RMSE_pp':math.sqrt(sse/n),'bias_pp':signed/n,
          'observed_rate_pct':100*sum(r['obs_count'] for r in part)/n,
          'predicted_rate_pct':100*sum(r['pred_count'] for r in part)/n,
          'frequency_bias_pp':100*(sum(r['pred_count'] for r in part)-sum(r['obs_count'] for r in part))/n,
          'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else 0.,
          'recall':tp/(tp+fn) if tp+fn else 0.,'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
          'counterfactual_supersaturated_hours':sum(r['n_supersaturated_counterfactual'] for r in part)})
    return totals


def emit(path,rows):
    if not rows:raise ValueError('Empty diagnostic output')
    with open(path,'w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(normals,year,out,targets=('ABO','BER','PAY')):
    """Historical test only, complete single year. Reuses original donor predictor."""
    if year not in (2018,2019,2020):raise ValueError('Only previously evaluated audit years accepted')
    from p8_2e_crossyear import ROOT,POOL,annual_hours,parse_swiss_year,donor_set,annual_predict
    from p8_1e_swiss_external import fetch,parse_meta
    from p8_2b_humidity import swiss_monthly,train_austria_humidity
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(raw);sites={k:metadata[k] for k in POOL if k in metadata}
    if not set(targets).issubset(sites):raise RuntimeError('Missing requested Swiss stations')
    hours=annual_hours(year);weather={};monthly={};source=[];unavailable=[]
    decade='2020-2029' if year>=2020 else '2010-2019'
    for s in sites:
        try:
            b,h=fetch(f'{ROOT}/{s.lower()}/ogd-smn_{s.lower()}_h_historical_{decade}.csv',max_bytes=37000000)
            weather[s],q=parse_swiss_year(b,s,year)
            source.append({'station':s,'type':'hourly','sha256':h,'n_hours':len(weather[s])})
            b,h=fetch(f'{ROOT}/{s.lower()}/ogd-smn_{s.lower()}_m.csv',max_bytes=20000000)
            monthly[s],q=swiss_monthly(b,s)
            source.append({'station':s,'type':'monthly','sha256':h})
        except Exception as exc:
            unavailable.append({'station':s,'error_type':type(exc).__name__,'message':str(exc)[:160]})
    loge,tslope,train=train_austria_humidity(normals)
    detailed=[];contributions=[];coverage=[]
    for sid in targets:
        donors_weather={s:x for s,x in weather.items() if s!=sid}
        donors_monthly={s:x for s,x in monthly.items() if s!=sid}
        donors=donor_set(sites[sid],sites,donors_weather,donors_monthly,year=year)
        pred_all,diagnostics=annual_predict(sites[sid],donors,hours,donors_weather,donors_monthly,loge,tslope,year=year)
        if diagnostics['target_meteorology_read_for_prediction'] is not False:raise AssertionError('Target leakage')
        target=weather[sid]
        indices=np.asarray([i for i,stamp in enumerate(hours) if stamp in target and all(target[stamp].get(k) is not None for k in ('T','P','e','RH'))],dtype=int)
        if len(indices)<.95*len(hours):raise ValueError('Too few independent evaluation hours')
        mt=np.asarray(pred_all[METHOD]['T'])[indices];me=np.asarray(pred_all[METHOD]['e'])[indices];mp=np.asarray(pred_all[METHOD]['P'])[indices];
        ot=np.array([target[hours[i]]['T'] for i in indices]);oe=np.array([target[hours[i]]['e'] for i in indices]);
        op=np.array([target[hours[i]]['P'] for i in indices]);rh=np.array([target[hours[i]]['RH'] for i in indices])
        parts,contrib=analyze(mt,me,ot,oe,mp,op,rh,pred_all[METHOD]['RH'][indices]);
        for variant,metrics in parts.items():detailed.append({'year':year,'site':sid,'method':METHOD,'variant':variant,**metrics})
        contributions.append({'year':year,'site':sid,'method':METHOD,**contrib})
        coverage.append({'site':sid,'n_scored_hours':len(indices),'no_target_data_passed_to_predictor':True,
                         'donors':[s['station_id'] for d,s in donors]})
    totals=grouped(detailed)
    emit(dest/'rh_attribution_site.csv',detailed)
    emit(dest/'rh_attribution_year.csv',totals)
    emit(dest/'rh_attribution_MAE_components.csv',contributions)
    manifest={'phase':'P8.2E_RH_ORACLE_DIAGNOSTIC','year':year,'test_period_used_previously':True,
        'scenarios':list(VARIANTS),'method':METHOD,'source':'MeteoSwiss original hourly T/e/RH/P',
        'reference_RH':'Provider ure200h0, not synthetic from observed e/T',
        'frozen_model':'IGE P8.2E annual_predict without fit or parameter updates',
        'n_scored_hours':sum(x['n_scored_hours'] for x in coverage),
        'coverage':coverage,'metrics':totals,'contributions':contributions,
        'atmospheric_pressure_direct_RH_influence':'Exactly zero at fixed e,T; 0.98P cap assessed separately',
        'source_checksums':source,'station_metadata_sha256':meta_sha,'Austrian_training':train,
        'no_original_provider_observations_published':True,
        'limits':['Oracle T/e counterfactuals are diagnostic, not deployable or leakage-free predictions',
                  'Counterfactuals are deliberately NOT saturated/clipped and may be above 100 percent RH',
                  'RH reference field need not exactly equal e/saturation(T) because of provider rounding and measurement conventions',
                  'Symmetric MAE attribution is descriptive and can be negative under error compensation; not a causal physical decomposition',
                  'Already-seen 2018-2020 testing years are not an untouched independent test set',
                  'Test station is excluded from predictor inputs; donor readings are from SAME real-world year and hour']}
    (dest/'rh_attribution_provenance.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('IGE_RH_ATTRIBUTION_RESULT',json.dumps({'year':year,'metrics':totals,'components':contributions,'n_hours':manifest['n_scored_hours']},ensure_ascii=False),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True)
    p.add_argument('--austria-station-normals',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args();run(a.austria_station_normals,a.year,a.out)