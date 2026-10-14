#!/usr/bin/env python3
"""P8.1F causal 12/24h-ahead inversion event prediction from PREVIOUS IGRA sounding.

Nothing from the target launch (including wind, T, dewpoint or vertical shape)
is permitted in predictors. Observed target profile is used to score Y only.
Site-blocked AND year-blocked evaluation. Compare to target-hour/month baseline.
The IGRA 0/12 nominal UTC represents schedule; release-time uncertainty remains.
"""
from __future__ import annotations
import argparse,collections,datetime,hashlib,io,json,math,zipfile
from pathlib import Path
import numpy as np
from p8_1e_igra_profiles import ROOT,SITES,START,END,http,parse_inventory,soundings,classify,season,savecsv

TRAIN_YEARS=(2017,2018)
TEST_YEARS=(2019,2020)
LEAD_MIN_H,LEAD_MAX_H=10,26
FEATURES=('hour12','annual_sin','annual_cos','lag_inv','lag_strength','lag_temp','lag_wind','lag_dpdp','lead_hours')

def date_utc(h):
    return datetime.datetime(h['year'],h['month'],h['day'],h['hour'],tzinfo=datetime.timezone.utc)

def features(last,dt,lead_h):
    angle=2*math.pi*(dt.timetuple().tm_yday-1)/365.2425
    return np.array([float(dt.hour==12),math.sin(angle),math.cos(angle),
       last['lag_inv'],min(12.,last['lag_strength']),last['lag_temp'],last['lag_wind'],last['lag_dpdp'],lead_h],float)

def build_pairs(heads,station_elevation):
    """heads [(header, IGRA raw level lines)], strictly chronological and causal."""
    ordered=sorted(heads,key=lambda v:date_utc(v[0]))
    pairs=[];issues=collections.Counter();prev=None
    for h,raw in ordered:
        if h['hour'] not in (0,12):issues['nonstandard_hour']+=1;continue
        date=date_utc(h)
        # Target truth based on current vertical sounding; never into predictors.
        from p8_1e_igra_profiles import level
        decoded=[v for ln in raw if (v:=level(ln.decode('ascii','replace') if isinstance(ln,bytes) else ln)) is not None]
        cur=classify(decoded,station_elevation)
        if cur is None:issues['target_profile_incomplete']+=1
        if prev is not None and cur is not None:
            older_time,older_raw,older_header=prev
            hours=(date-older_time).total_seconds()/3600
            if LEAD_MIN_H<=hours<=LEAD_MAX_H:
                last_levels=[v for ln in older_raw if (v:=level(ln.decode('ascii','replace') if isinstance(ln,bytes) else ln)) is not None]
                past=antecedent_from_lines(older_raw,last_levels,station_elevation)
                if past is not None:
                    pairs.append({'site':h['id'],'year':h['year'],'month':h['month'],
                     'target_hour':h['hour'],'lead_hours':hours,'target_timestamp':date.isoformat(),
                     'source_timestamp':older_time.isoformat(),
                     'features':features(past,date,hours),'y':int(cur['inversion']),
                     'strength_c':max(0.,cur['warmest_above_surface_C'])})
                else:issues['antecedent_profile_incomplete']+=1
            else:issues['gap_outside_10_to_26h']+=1
        # Preserve previous observed sounding even when target itself lacks enough levels;
        # next forecast may use a previous profile only if that earlier profile qualifies.
        prev=(date,raw,h)
    return pairs,dict(issues)

def antecedent_from_lines(raw,decoded,z0):
    p=classify(decoded,z0)
    if p is None:return None
    cand=[]
    for row in raw:
        if isinstance(row,bytes):row=row.decode('ascii','replace')
        if len(row)<51:continue
        try:z=int(row[16:21]);w=int(row[46:51]);d=int(row[34:39])
        except ValueError:continue
        if z0-40<=z<=z0+150:
            cand.append((abs(z-z0),w/10 if 0<=w<=2000 else float('nan'), d/10 if 0<=d<=900 else float('nan')))
    cand.sort(key=lambda t:t[0])
    w,dp=(cand[0][1],cand[0][2]) if cand else (float('nan'),float('nan'))
    return {'lag_inv':float(p['inversion']), 'lag_strength':max(0.,p['warmest_above_surface_C']),
     'lag_temp':float(p['surface_t_c']),'lag_wind':w,'lag_dpdp':dp}

def fit_logit(rows,reg=10.):
    if len(rows)<40:raise ValueError('Insufficient train pairs')
    X=np.array([r['features'] for r in rows],float); y=np.array([r['y'] for r in rows],float)
    if len(set(y))<2:raise ValueError('Single class training data')
    med=np.array([float(np.median(x[np.isfinite(x)])) if np.isfinite(x).any() else 0. for x in X.T])
    X=np.where(np.isfinite(X),X,med[None,:]);avg=X.mean(0);std=np.maximum(X.std(0),1.)
    Z=np.column_stack([np.ones(len(X)),(X-avg)/std]);coef=np.zeros(Z.shape[1]);eye=np.eye(len(coef));eye[0,0]=0
    for k in range(45):
        t=np.clip(Z@coef,-30,30);p=1/(1+np.exp(-t));w=np.maximum(p*(1-p),1e-6)
        grad=Z.T@(p-y)+reg*eye@coef
        hess=(Z.T*w)@Z+reg*eye
        d=np.linalg.solve(hess,grad);coef-=d
        if np.linalg.norm(d)<1e-7:break
    return {'med':med,'avg':avg,'std':std,'coef':coef}

def predict_logit(model,rows):
    X=np.array([r['features'] for r in rows]);X=np.where(np.isfinite(X),X,model['med'][None,:])
    x=np.column_stack([np.ones(len(X)),(X-model['avg'])/model['std']]);t=np.clip(x@model['coef'],-30,30)
    return 1/(1+np.exp(-t))

def climatology(train,test):
    """Prior event climatology by hour and season from training sites ONLY."""
    mean=(sum(r['y'] for r in train)+1)/(len(train)+2)
    by=collections.defaultdict(list)
    for r in train:by[(r['target_hour'],season(r['month']))].append(r['y'])
    return np.array([(sum(by[(r['target_hour'],season(r['month']))])+8*mean)/(len(by[(r['target_hour'],season(r['month']))])+8) for r in test])

def scores(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return {'n':int(len(y)),'positive':int(sum(y)), 'prevalence':float(y.mean()),
     'brier':float(np.mean((p-y)**2)),
     'logloss':float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),
     'mean_probability':float(p.mean())}

def evaluate_folds(pairs,min_test=40):
    sites=sorted({x['site'] for x in pairs});out=[];excluded=[]
    for target in sites:
        train=[x for x in pairs if x['site']!=target and x['year'] in TRAIN_YEARS]
        test=[x for x in pairs if x['site']==target and x['year'] in TEST_YEARS]
        if len(train)<50 or len(test)<min_test or len({r['y'] for r in train})<2:
            excluded.append({'site':target,'n_train':len(train),'n_test':len(test),'reason':'not_enough_events_or_training'});continue
        model=fit_logit(train);pc=climatology(train,test);pp=predict_logit(model,test)
        yy=[x['y'] for x in test]
        sc=scores(yy,pc);sp=scores(yy,pp)
        # Persistence is an additional available-data baseline (prior profile).
        persistence=np.clip(np.array([r['features'][3] for r in test],float)*.80+.1,.01,.99)
        sper=scores(yy,persistence)
        out.append({'heldout_site':target,'train_sites':sorted(set(x['site'] for x in train)),
            'n_train':len(train),'n_test':len(test),'n_positive':sum(yy),
            'forecast_horizon_h':[LEAD_MIN_H,LEAD_MAX_H],
            'climatology_brier':sc['brier'],'causal_logit_brier':sp['brier'],
            'persistence_brier':sper['brier'],'brier_skill_vs_climatology':1-sp['brier']/sc['brier'] if sc['brier']>0 else None,
            'brier_skill_vs_persistence':1-sp['brier']/sper['brier'] if sper['brier']>0 else None,
            'climatology_logloss':sc['logloss'],'causal_logit_logloss':sp['logloss'],
            'persistence_logloss':sper['logloss'], 'model_type':'L2 logistic regression, no target-site or 2019-2020 training'})
    return out,excluded

def execute(out,sites=SITES):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rawindex=http(ROOT+'/igra2-station-list.txt',1000000);inv=parse_inventory(rawindex)
    all_pairs=[];coverage=[];sources=[]
    for sid in sites:
        if sid not in inv:raise RuntimeError('Unrecognized IGRA site '+sid)
        url=f'{ROOT}/data/data-por/{sid}-data.txt.zip';archive=http(url)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipf:
            entries=[x for x in zipf.namelist() if x.endswith('.txt')]
            if len(entries)!=1:raise ValueError('IGRA ZIP has different station members')
            from p8_1e_igra_profiles import header
            heads=[]
            with zipf.open(entries[0]) as fh:
                it=iter(fh)
                for chunk in it:
                    if not chunk.startswith(b'#'):continue
                    h=header(chunk.decode('ascii','replace'))
                    lines=[]
                    for _ in range(h['nlev']):
                        ln=next(it,None)
                        if ln is None:raise ValueError('Truncated radiosonde archive')
                        lines.append(ln)
                    if 2017<=h['year']<=2020:heads.append((h,lines))
        pairs,issues=build_pairs(heads,inv[sid]['elev_m'])
        all_pairs.extend(pairs);coverage.append({'site':sid,'n_soundings':len(heads),'n_pairs':len(pairs),**issues})
        sources.append({'site':sid,'archive_sha256':hashlib.sha256(archive).hexdigest(),'bytes':len(archive)})
    results,excluded=evaluate_folds(all_pairs)
    # Provenance and sample sufficiency are always exported before a scientific
    # coverage gate fails. This does not change fold membership or thresholds.
    diagnostic={'phase':'P8.1F_EVENT_COVERAGE_AUDIT','sites':coverage,
      'n_total_pairs':len(all_pairs),'train_years':list(TRAIN_YEARS),
      'test_years':list(TEST_YEARS),'per_site_year':[
        {'site':sid,'year':year,'n_pairs':sum(v['site']==sid and v['year']==year for v in all_pairs),
         'n_inversions':sum(v['y'] for v in all_pairs if v['site']==sid and v['year']==year)}
        for sid in sites for year in (*TRAIN_YEARS,*TEST_YEARS)],
      'independent_fold_results':results,'excluded_folds':excluded,
      'required_n_folds':2,'required_n_test':120,
      'scientific_status':'INSUFFICIENT_COVERAGE' if len(results)<2 or sum(r['n_test'] for r in results)<120 else 'COVERAGE_PASS'}
    (out/'event_coverage_diagnostic.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
    print('IGE_P8_1F_EVENT_COVERAGE',json.dumps(diagnostic),flush=True)
    if len(results)<2 or sum(r['n_test'] for r in results)<120:
        raise RuntimeError('Not enough independent site- and time-held-out inversion predictions; see event_coverage_diagnostic.json')
    savecsv(out/'inversion_site_holdouts.csv',results)
    report={'phase':'P8.1F_EVENT_CAUSAL_12_TO_26_H','status':'EVENTS_VALIDATED_NOT_PRODUCTION',
     'sites':coverage,'sources':sources,'trained_on_years':list(TRAIN_YEARS),'test_years':list(TEST_YEARS),
     'train_sites_exclude_target':True,'uses_only_previous_launch_as_predictor':True,
     'forecast_horizon_hours':[LEAD_MIN_H,LEAD_MAX_H],
     'feature_names':FEATURES,'fold_results':results,'excluded':excluded,
     'limitations':['Nominal sounding times are not exact release times; time horizon approximate.',
       'Prior sounding is upper-air observation, not readily available at arbitrary EPW locations.',
       'Only 4 IGRA stations, two with sparse profiles; independent climate-region generalization unproven.',
       'No event prediction using pre-event synoptic forecasts, radiation and cloud model inputs.',
       'Performance could be worse than baseline; candidate is not adopted automatically.'],
     'raw_provider_observations_published':False}
    (out/'inversion_event_provenance.json').write_text(json.dumps(report,indent=2)+'\n')
    print('IGE_P8_1F_EVENT_RESULT',json.dumps({'coverage':coverage,'results':results,'excluded':excluded}),flush=True)
    return report

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--sites',nargs='*',default=SITES)
    x=a.parse_args();execute(x.out,x.sites)