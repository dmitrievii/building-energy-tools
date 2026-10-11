#!/usr/bin/env python3
"""P7B.3A: independent observed-hour GHI climatology; no model/observation event-date matching."""
from __future__ import annotations
import argparse, csv, hashlib, json, math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean

YEARS=(2012,2013,2014)
CALIBRATION=(2005,2006,2007,2008,2009)
EXCLUDED=(2010,2011)
CET=timedelta(hours=1)

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def percentile(values,p):
    if not values:return None
    v=sorted(values);z=(len(v)-1)*p;lo=math.floor(z);hi=math.ceil(z)
    return v[lo]+(v[hi]-v[lo])*(z-lo)

def moments(values):
    if not values:return {'n':0,'mean':None,'p10':None,'p50':None,'p90':None,'p95':None}
    return {'n':len(values),'mean':fmean(values),'p10':percentile(values,.1),
            'p50':percentile(values,.5),'p90':percentile(values,.9),
            'p95':percentile(values,.95)}

def paired_metrics(obs,model,threshold=.025):
    """Only comparable month-of-year by clock-hour climatological means."""
    rows=[]
    for key in sorted(set(obs)&set(model)):
        a=obs[key];b=model[key]
        if a and b:rows.append((key,fmean(a),fmean(b),len(a),len(b)))
    def evaluate(items):
        if not items:return {'cells':0,'mae_kwh_m2_hour':None,'rmse_kwh_m2_hour':None,'bias_kwh_m2_hour':None}
        dif=[m-o for _,o,m,_,_ in items]
        return {'cells':len(items),'mae_kwh_m2_hour':fmean(abs(d) for d in dif),
                'rmse_kwh_m2_hour':math.sqrt(fmean(d*d for d in dif)),
                'bias_kwh_m2_hour':fmean(dif)}
    return rows,evaluate(rows),evaluate([r for r in rows if r[1]>=threshold])

def consecutive_deltas(hour_records,only_daylight=False):
    out=[]
    for (t1,v1),(t2,v2) in zip(hour_records,hour_records[1:]):
        if t2-t1!=timedelta(hours=1):continue
        if only_daylight and not (8<=t1.hour<=17 and 8<=t2.hour<=17):continue
        out.append(abs(v2-v1))
    return out

def select_observations(path,window):
    """One independent ground series and strict six-of-six source approved QC."""
    data={};accepted=Counter();allhours=Counter();months=Counter();rejects=Counter()
    with open(path,newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if (r['station_id']!='30' or r['window']!=window or r['variable']!='cglo'
                or r['nasa_location']!='graz_station30'):continue
            dt=datetime.fromisoformat(r['timestamp_utc'])+CET
            if dt.year not in YEARS:continue
            t=dt.replace(tzinfo=None);allhours[dt.year]+=1
            complete=(r['original_10min_count']=='6' and r['qc_accepted_10min_count']=='6'
                      and r['ground_hour_qc_approved']=='True')
            if not complete:rejects['no_complete_source_qc_hour']+=1;continue
            if not r['ground_kwh_m2_hour']:rejects['missing_energy']+=1;continue
            v=float(r['ground_kwh_m2_hour'])
            if not math.isfinite(v) or v<0:rejects['invalid_ghi']+=1;continue
            if t in data:raise ValueError('Duplicate original station/hour after filtering')
            data[t]=v;accepted[dt.year]+=1;months[(dt.year,dt.month)]+=1
    return data,{'qc_accepted_years':dict(sorted(accepted.items())),
                 'total_source_calendar_hours':dict(sorted(allhours.items())),
                 'qc_month_year_counts':{f'{y}-{m:02d}':v for (y,m),v in sorted(months.items())},
                 'rejection_counts':dict(rejects)}

def synthetic(path,field):
    data={}
    with open(path,newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            dt=datetime.fromisoformat(r['local_hour']);t=dt.replace(tzinfo=None)
            if dt.year!=2013 or t in data:raise ValueError('Synthetic calendar must be unique 2013')
            v=float(r[field])/1000
            if not math.isfinite(v) or v<0:raise ValueError('Invalid synthetic GHI')
            data[t]=v
    if len(data)!=8760:raise ValueError('Expected exactly 8760 synthetic hours')
    if min(data)!=datetime(2013,1,1) or max(data)!=datetime(2013,12,31,23):
        raise ValueError('Unexpected 2013 model calendar bounds')
    return data

def groups_hours(data):
    out=defaultdict(list)
    for t,v in data.items():out[(t.month,t.hour)].append(v)
    return out

def full_days(data):
    dd=defaultdict(dict)
    for t,v in data.items():dd[t.date()][t.hour]=v
    return {d:sum(h.values()) for d,h in dd.items()
            if len(h)==24 and set(h)==set(range(24))}

def season(m):
    return {12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',
            7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}[m]

def sample_distribution(data,metric):
    out={}
    for s in ('DJF','MAM','JJA','SON'):
        if metric=='hourly':
            a=[v for t,v in data.items() if season(t.month)==s and 8<=t.hour<=18]
        elif metric=='daily':
            a=[v for d,v in full_days(data).items() if season(d.month)==s]
        elif metric=='delta':
            a=consecutive_deltas(sorted((t,v) for t,v in data.items()
                       if season(t.month)==s),only_daylight=True)
        else:raise ValueError('Unknown metric')
        out[s]=moments(a)
    return out

def lag1_daily(data):
    ds=sorted(full_days(data).items());result={}
    for s in ('DJF','MAM','JJA','SON'):
        pairs=[(a[1],b[1]) for a,b in zip(ds,ds[1:])
               if season(a[0].month)==s and season(b[0].month)==s and
               (b[0]-a[0]).days==1]
        if len(pairs)<3:result[s]={'n_pairs':len(pairs),'pearson_r':None};continue
        xx=[x for x,_ in pairs];yy=[y for _,y in pairs]
        mx=fmean(xx);my=fmean(yy)
        num=sum((x-mx)*(y-my) for x,y in pairs)
        den=math.sqrt(sum((x-mx)**2 for x in xx)*sum((y-my)**2 for y in yy))
        result[s]={'n_pairs':len(pairs),'pearson_r':num/den if den else None}
    return result

def write_csv(path,rows):
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(obs_path,p7b_path,p7b2_path,outdir):
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    models={'p7b_original':synthetic(p7b_path,'ghi_Wh'),
            'p7b2_corrected':synthetic(p7b2_path,'ghi_Wh')}
    profiles=[];scores=[];distributions=[];coverage=[];reports={}
    for window in ('record_start','record_end'):
        obs,qc=select_observations(obs_path,window)
        if not obs:raise ValueError('No QC-approved original ground GHI')
        if max(qc['qc_accepted_years'].values())>8784:
            raise ValueError('Duplicate station evidence suspected')
        og=groups_hours(obs)
        observed_days=full_days(obs)
        for name,model in models.items():
            curves,allcells,daycells=paired_metrics(og,groups_hours(model))
            for (month,hour),o,m,no,nm in curves:
                profiles.append({'window':window,'model':name,'month':month,'hour_cet':hour,
                    'observed_qc_hours':no,'model_hours':nm,'observed_mean_kwh_m2_hour':o,
                    'model_mean_kwh_m2_hour':m,'model_minus_observed_kwh_m2_hour':m-o})
            for selection,stat in (('all_hour_cells',allcells),
                                  ('obs_daylight_cells_ge_0p025',daycells)):
                scores.append({'window':window,'model':name,'selection':selection,**stat})
            for metric in ('hourly','daily','delta'):
                ss=sample_distribution(obs,metric);mm=sample_distribution(model,metric)
                for s in ('DJF','MAM','JJA','SON'):
                    distributions.append({'window':window,'model':name,'metric':metric,'season':s,
                        **{f'observed_{k}':v for k,v in ss[s].items()},
                        **{f'model_{k}':v for k,v in mm[s].items()}})
            model_days=full_days(model)
            for month in range(1,13):
                oh=[v for t,v in obs.items() if t.month==month]
                mh=[v for t,v in model.items() if t.month==month]
                coverage.append({'window':window,'model':name,'month':month,
                    'obs_qc_hours':len(oh),'model_hours':len(mh),
                    'obs_mean_hourly_kwh_m2':fmean(oh) if oh else None,
                    'model_mean_hourly_kwh_m2':fmean(mh) if mh else None,
                    'obs_full_days':sum(d.month==month for d in observed_days),
                    'model_full_days':sum(d.month==month for d in model_days)})
            reports[f'{window}__{name}']={
                'mean_diurnal_cell_metrics':{'all':allcells,'obs_daylight':daycells},
                'lag1_daily_complete_days':{'ground':lag1_daily(obs),'synthetic':lag1_daily(model)},
                'complete_qc_ground_days':len(observed_days),'synthetic_days':len(model_days)}
        reports[window+'__qc']={'source':qc,'selected_station':'30','qc_channel':'cglo',
            'quality_policy':'strict six-of-six provider q21-approved original intervals',
            'not_selected':'station16412 duplicate; chim QC0; NASA POWER not ground',
            'timestamp_hypothesis':window}
    written={
        'p7b3a_month_hour_climatology.csv':profiles,
        'p7b3a_climatology_scores.csv':scores,
        'p7b3a_seasonal_distributions.csv':distributions,
        'p7b3a_monthly_coverage.csv':coverage,
    }
    for name,records in written.items():write_csv(outdir/name,records)
    result={
        'stage':'IGE_P7B3A_INDEPENDENT_OBSERVED_HOURLY_GHI',
        'technical_status':'COMPUTED_FROM_IMMUTABLE_ORIGINAL_SOURCE_CSV',
        'scientific_status':'EXPLORATORY_SINGLE_GCM_SINGLE_SYNTHETIC_YEAR_NOT_VALIDATED_FOR_PRODUCTION',
        'epw_production_ready':False,
        'calendar_semantics':'fixed CET model and one-hour-shifted UTC observations; both original interval interpretations retained',
        'synthetic_2013_dates_are_not_matched_to_observed_2013_weather':True,
        'single_synthetic_year_vs_three_year_observed_holdout_not_sampling_equivalent':True,
        'original_model_training':list(CALIBRATION),
        'excluded_conflict_years':list(EXCLUDED),
        'untouched_observed_holdout':list(YEARS),
        'source_original_sha256':{'geosphere_hourly_pairwise_csv':sha(obs_path),
            'p7b_original_hourly_csv':sha(p7b_path),'p7b2_final_hourly_csv':sha(p7b2_path)},
        'comparison':reports,
        'limits':['No event-date pairing / paired-hour weather skill estimates',
                  'Two original unresolved interval timestamp hypotheses retained',
                  'No independent original QC-approved DHI/DNI validation; chim QC0',
                  'One model year vs three observed years are not sample equivalent',
                  '2012–2014 was previously used for P7B.2 daily GHI holdout evaluation',
                  'Already NASA-BCSD-adjusted NEX model and additional local correction'],
    }
    result['output_sha256']={name:sha(outdir/name) for name in sorted(written)}
    (outdir/'p7b3a_science_audit.json').write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--geosphere-hourly',required=True)
    p.add_argument('--p7b-hourly',required=True)
    p.add_argument('--p7b2-hourly',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    d=run(a.geosphere_hourly,a.p7b_hourly,a.p7b2_hourly,a.out)
    for w in ('record_start','record_end'):
        for name in ('p7b_original','p7b2_corrected'):
            print(w,name,d['comparison'][f'{w}__{name}']['mean_diurnal_cell_metrics']['obs_daylight'])
    print('P7B.3A',d['technical_status'],'production',d['epw_production_ready'])

if __name__=='__main__':main()
