#!/usr/bin/env python3
"""IGE P7B.3C: observationally trained conditional daily-cloud-analogue M2.

Research only. Fit 2007-2008 QC approved GeoSphere station30 data; select
blend on 2009; evaluate 2012-2014 as *previously consulted* external period.
M0, M2 use exactly the same 2013 CanESM5 corrected DAILY solar energies.
No model-weather vs measured-weather event-date pairing.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean

TRAIN_YEARS=(2007,2008)
SELECT_YEAR=(2009,)
EVAL_YEARS=(2012,2013,2014)
ALPHAS=(0.,.25,.5,.75,1.)
SEASONS={12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}
STATION_LAT=47.08
STATION_LON=15.45
CET=timedelta(hours=1)


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for piece in iter(lambda:f.read(1<<20),b''):h.update(piece)
    return h.hexdigest()


def percentile(vals,p):
    if not vals:return None
    v=sorted(vals);t=(len(v)-1)*p;low=math.floor(t);high=math.ceil(t)
    return v[low]+(v[high]-v[low])*(t-low)


def sun_cos_midpoint(local_hour, lat=STATION_LAT, lon=STATION_LON):
    """NOAA approximate solar ephemeris, local hour is interval START in CET.

    Geometric, not apparent/refraction-corrected zenith; declared approximation.
    """
    day=local_hour.timetuple().tm_yday
    frac=(local_hour.hour+.5-12)/24
    gamma=2*math.pi/(366 if local_hour.year%4==0 and
              (local_hour.year%100!=0 or local_hour.year%400==0) else 365)*(day-1+frac)
    decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)-
          .006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)-
          .002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    equation_time=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)-
                          .014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    ha=math.radians((local_hour.hour+.5)*15 + (equation_time+4*lon-60)/4 - 180)
    latr=math.radians(lat)
    return max(0.,min(1.,math.sin(latr)*math.sin(decl)+
                              math.cos(latr)*math.cos(decl)*math.cos(ha)))


def haurwitz(coszen):
    return 1098.*coszen*math.exp(-.059/coszen)/1000. if coszen>0 else 0.


def load_original_station(path,window,years):
    """Deduplicated station #30, q21 approved, 6/6 original ten-minute slots."""
    years=set(years); data={};counts=defaultdict(int)
    with open(path,newline='',encoding='utf8') as f:
        for r in csv.DictReader(f):
            if (r['station_id']!='30' or r['window']!=window or
                r['variable']!='cglo' or r['nasa_location']!='graz_station30'):
                continue
            dt=datetime.fromisoformat(r['timestamp_utc'])+CET
            dt=dt.replace(tzinfo=None)
            if dt.year not in years:continue
            if not (r['original_10min_count']=='6' and
                    r['qc_accepted_10min_count']=='6' and
                    r['ground_hour_qc_approved']=='True' and
                    r['ground_kwh_m2_hour']):continue
            v=float(r['ground_kwh_m2_hour'])
            if not math.isfinite(v) or v<0:continue
            if dt in data:raise ValueError('duplicate independent station hour')
            data[dt]=v;counts[dt.year]+=1
    return data,dict(sorted(counts.items()))


def complete_days(data):
    grouped=defaultdict(dict)
    for t,v in data.items():grouped[t.date()][t.hour]=v
    return {day:[v[h] for h in range(24)] for day,v in grouped.items()
            if len(v)==24 and set(v)==set(range(24))}


def source_year(path):
    byday=defaultdict(list)
    with open(path,newline='',encoding='utf8') as f:
        for r in csv.DictReader(f):
            t=datetime.fromisoformat(r['local_hour']).replace(tzinfo=None)
            cos=float(r['solar_coszen']);toa=float(r['toa_horizontal_Wh'])/1000
            val=float(r['ghi_Wh'])/1000
            if not (math.isfinite(cos+toa+val) and 0<=cos<=1 and
                    0<=val<=toa+1e-8):raise ValueError('source radiation invalid')
            byday[t.date()].append((t,val,toa,haurwitz(cos)))
    if len(byday)!=365 or sum(len(v) for v in byday.values())!=8760:
        raise ValueError('expected 365 source days with 24 hours each')
    if any(len(v)!=24 for v in byday.values()):raise ValueError('invalid source day')
    return dict(sorted(byday.items()))


def build_library(data):
    lib=defaultdict(list)
    for day,obs in complete_days(data).items():
        dt=datetime.combine(day,datetime.min.time())
        clear=[haurwitz(sun_cos_midpoint(dt+timedelta(hours=h))) for h in range(24)]
        ec=sum(clear)
        if ec<.1:continue
        kt=sum(obs)/ec
        ratios=[min(1.6,max(0.,v/max(.025,c))) if c>.005 else 0.
                for v,c in zip(obs,clear)]
        lib[SEASONS[day.month]].append({'day':day.isoformat(),'kt':kt,
                       'ratios':ratios,'observed_energy':sum(obs)})
    for season,items in lib.items():items.sort(key=lambda x:x['day'])
    if any(len(lib[s])<30 for s in ('DJF','MAM','JJA','SON')):
        raise ValueError('insufficient complete approved source days in training')
    return lib


def project_energy(raw,target,caps):
    """Bounded projection preserving exact corrected source-day GHI."""
    if len(raw)!=24 or len(caps)!=24:raise ValueError('expected 24 hours')
    if not math.isfinite(target) or target<0 or target>sum(caps)+1e-8:
        raise ValueError('target cannot be preserved under physics limits')
    if target==0:return [0.]*24
    w=[max(.0000001*c,v) if c>0 else 0 for v,c in zip(raw,caps)]
    hi=1.
    while sum(min(hi*v,c) for v,c in zip(w,caps))<target:
        hi*=2
        if hi>1e15:raise ValueError('energy projection not bracketed')
    lo=0.
    for _ in range(55):
        mid=(hi+lo)/2
        if sum(min(mid*v,c) for v,c in zip(w,caps))<target:lo=mid
        else:hi=mid
    out=[min(hi*v,c) for v,c in zip(w,caps)]
    if abs(sum(out)-target)>1e-9:raise ValueError('source energy closure lost')
    return out


def generate(days, library,alpha,seed):
    """Condition analogue choice on seasonal class and daily clearness index.

    Alpha selected ONLY from 2009; variation generated independently of 2013
    ground measurements. We reuse a day-level cloud pattern, not source code.
    """
    if not 0<=alpha<=1:raise ValueError('invalid blend')
    output={};maximum_residual=0.;selection_distance=[]
    for day,rows in days.items():
        base=[r[1] for r in rows]
        toas=[r[2] for r in rows]
        clear=[r[3] for r in rows]
        tgt=sum(base)
        if alpha==0:
            values=base
        else:
            kt=tgt/max(.1,sum(clear))
            pool=library[SEASONS[day.month]]
            candidates=sorted(pool,key=lambda x:(abs(x['kt']-kt),x['day']))[:15]
            hashseed=int.from_bytes(hashlib.sha256(f'{seed}:{day}'.encode()).digest()[:8],'big')
            analogue=random.Random(hashseed).choice(candidates)
            selection_distance.append(abs(analogue['kt']-kt))
            # At sunrise Haurwitz -> 0 too fast; source M0 retains known
            # source geometry, Haurwitz is only the higher-sun cloud reference.
            cloud=[max(0.,c*ratio) for c,ratio in zip(clear,analogue['ratios'])]
            raw=[(1-alpha)*v+alpha*x for v,x in zip(base,cloud)]
            # 1.25 Haurwitz away from horizon; 0.65 TOA floor near horizon.
            # Restriction does not increase original source radiation.
            caps=[min(toa,max(1.25*c,.65*toa)) for c,toa in zip(clear,toas)]
            values=project_energy(raw,tgt,caps)
        maximum_residual=max(maximum_residual,abs(sum(values)-tgt))
        for (t,_,_,_),v in zip(rows,values):output[t]=v
    return output,{'max_daily_energy_residual':maximum_residual,
                   'mean_analogue_kt_distance':fmean(selection_distance) if selection_distance else None}


def month_hour_score(obs,model):
    sums=defaultdict(lambda:[0.,0]); measured=defaultdict(lambda:[0.,0])
    for t,v in obs.items():
        z=measured[t.month,t.hour];z[0]+=v;z[1]+=1
    for t,v in model.items():
        z=sums[t.month,t.hour];z[0]+=v;z[1]+=1
    errors=[]
    for key,z in measured.items():
        if key in sums and z[0]/z[1]>=.025:
            errors.append(abs(z[0]/z[1]-sums[key][0]/sums[key][1]))
    if len(errors)<120:raise ValueError('insufficient monthly-hour comparison cells')
    return fmean(errors),len(errors)


def seasonal_p95(data):
    pairs=defaultdict(list)
    rows=sorted(data.items())
    for (ta,va),(tb,vb) in zip(rows,rows[1:]):
        if (tb-ta==timedelta(hours=1) and
            SEASONS[ta.month]==SEASONS[tb.month] and
            8<=ta.hour<=17 and 8<=tb.hour<=17):
            pairs[SEASONS[ta.month]].append(abs(vb-va))
    if any(len(pairs[x])<100 for x in ('DJF','MAM','JJA','SON')):
        raise ValueError('insufficient seasonal approved consecutive hours')
    return {s:percentile(pairs[s],.95) for s in ('DJF','MAM','JJA','SON')}


def compare(obs,model):
    mae,n=month_hour_score(obs,model)
    op=seasonal_p95(obs);mp=seasonal_p95(model)
    err=fmean(abs(mp[s]/op[s]-1) for s in op)
    return {'daylight_month_hour_mae':mae,'daylight_cells':n,
            'seasonal_mean_abs_rel_p95_error':err,
            'ground_p95':op,'generated_p95':mp,
            'composite_score':None}


def run(model_path,station_path,out_path,tune_seeds=8,test_seeds=20):
    root=Path(out_path);root.mkdir(parents=True,exist_ok=True)
    source=source_year(model_path)
    baseline={r[0]:r[1] for day in source.values() for r in day}
    all_reports={};seed_data=[];selection=[]
    # For both original timestamp hypotheses separately (never select the
    # hypothesis that happens to yield the lowest observational error).
    observations={};libraries={}
    for window in ('record_start','record_end'):
        obs,counts=load_original_station(station_path,window,
                                       TRAIN_YEARS+SELECT_YEAR+EVAL_YEARS)
        train={t:v for t,v in obs.items() if t.year in TRAIN_YEARS}
        libraries[window]=build_library(train)
        observations[window]={
            'selection':{t:v for t,v in obs.items() if t.year in SELECT_YEAR},
            'evaluation':{t:v for t,v in obs.items() if t.year in EVAL_YEARS}}
        all_reports[window]={'qc_counts':counts,
                             'training_analogues':sum(map(len,libraries[window].values()))}
    # Single alpha across both timestamp hypotheses; tune against 2009 only.
    # No 2012-14 data enters this operation, even indirectly through scores.
    candidates=[]
    for alpha in ALPHAS:
        fold_scores=[]
        for window in ('record_start','record_end'):
            sel=observations[window]['selection']
            base_score=compare(sel,baseline)
            vals=[]
            for seed in range(tune_seeds):
                generated,_=generate(source,libraries[window],alpha,seed)
                m=compare(sel,generated)
                vals.append(.35*m['daylight_month_hour_mae']/base_score['daylight_month_hour_mae']+
                            .65*m['seasonal_mean_abs_rel_p95_error'])
            fold_scores.append(fmean(vals))
        candidates.append({'alpha':alpha,'mean_2009_score':fmean(fold_scores),
                           'record_start_score':fold_scores[0],
                           'record_end_score':fold_scores[1]})
    winner=min(candidates,key=lambda x:(x['mean_2009_score'],x['alpha']))['alpha']
    for window in ('record_start','record_end'):
        ground=observations[window]['evaluation']
        selection_ground=observations[window]['selection']
        base_eval=compare(ground,baseline)
        base_sel=compare(selection_ground,baseline)
        run_stats=[]
        for seed in range(test_seeds):
            model,quality=generate(source,libraries[window],winner,seed)
            stats=compare(ground,model)
            score=.35*stats['daylight_month_hour_mae']/base_eval['daylight_month_hour_mae']+\
                  .65*stats['seasonal_mean_abs_rel_p95_error']
            run_stats.append({'seed':seed,'window':window,'alpha':winner,
                             'evaluation_years':'2012,2013,2014','score':score,
                             'mean_hour_mae':stats['daylight_month_hour_mae'],
                             'seasonal_abs_rel_p95_error':stats['seasonal_mean_abs_rel_p95_error'],
                             'jja_p95':stats['generated_p95']['JJA'],
                             'max_daily_energy_residual':quality['max_daily_energy_residual'],
                             'mean_analogue_kt_distance':quality['mean_analogue_kt_distance']})
            if seed==0:
                with (root/f'p7b3c_M2_seed0_{window}_hourly.csv').open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['local_hour','M0_kwh_m2','M2_kwh_m2'])
                    for t in sorted(model):w.writerow([t.isoformat(),baseline[t],model[t]])
        seed_data.extend(run_stats)
        all_reports[window].update({
            'M0_selection_2009':base_sel,'M0_evaluation_2012_2014':base_eval,
            'M2_evaluation_20seed_mean_hour_mae':fmean(x['mean_hour_mae'] for x in run_stats),
            'M2_evaluation_20seed_p95_rel_error':fmean(x['seasonal_abs_rel_p95_error'] for x in run_stats),
            'M2_evaluation_JJA_p95_mean':fmean(x['jja_p95'] for x in run_stats),
            'M2_seed0_max_daily_residual':run_stats[0]['max_daily_energy_residual']})
    def write_rows(filename,rows):
        with (root/filename).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    write_rows('p7b3c_2009_alpha_selection.csv',candidates)
    write_rows('p7b3c_2012_2014_M2_seed_scores.csv',seed_data)
    result={'stage':'P7B.3C_CONDITIONAL_DAY_ANALOGUE_M2','production_ready':False,
            'trained_only_on_qc_geosphere_years':list(TRAIN_YEARS),
            'alpha_selected_only_on':list(SELECT_YEAR),
            'evaluation_previously_consulted_years':list(EVAL_YEARS),
            'eval_is_virgin_holdout':False,
            'synthetic_dates_not_paired_to_measured_events':True,
            'two_unresolved_timestamp_hypotheses':True,
            'm2_not_meteonorm_implementation':True,
            'clearsky_reference':'HAURWITZ_1098_EXP_NEG0P059_NOAA_GEOMETRIC_ZENITH',
            'cloud_analogue_algorithm':'SEASON_AND_DAY_KT_15_NEAREST_APPROVED_DAY_BOOTSTRAP',
            'source_2013_daily_energy_immutable':True,
            'selected_alpha':winner,'selection_candidates':candidates,
            'seed_count_tuning':tune_seeds,'seed_count_final':test_seeds,
            'source_sha256':{'original_geosphere':sha(station_path),'original_p7b2_model':sha(model_path)},
            'limitations':['Haurwitz is a simple geometric clear-sky reference, not ESRA/Solis',
                           'Training station local only; no independent second station',
                           '2009 selects alpha but is not a new physical-event verification',
                           '2012-2014 has already been inspected in P7B.2/3A/3B',
                           'No observed DHI/DNI verification and no model interannual spread',
                           'Near-horizon cap uses 0.65 extraterrestrial horizontal irradiance floor'],
            'reports':all_reports}
    result['derived_sha256']={p.name:sha(p) for p in sorted(root.glob('*.csv'))}
    (root/'p7b3c_science_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--model-hourly',required=True)
    p.add_argument('--station-hourly',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--tune-seeds',type=int,default=8)
    p.add_argument('--test-seeds',type=int,default=20)
    args=p.parse_args()
    result=run(args.model_hourly,args.station_hourly,args.out,args.tune_seeds,args.test_seeds)
    print(json.dumps({'selected_alpha':result['selected_alpha'],
                      'reports':result['reports']},indent=2))