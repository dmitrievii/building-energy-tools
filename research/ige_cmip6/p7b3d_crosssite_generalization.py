#!/usr/bin/env python3
"""IGE P7B.3D: pre-registered independent year/site M2 conditional disaggregation.

Graz original 2007-08 observations supply cloud library, Graz 2009 selected
alpha .75 in frozen P7B.3C. Site-year 2012-14 hourly ground observations
supply a DAILY known energy; no observed-hour within that day enters synthesis.
Compare modelled hourly *distributions*, not event-date deterministic forecast.
Neither future climate nor 8-GCM generalization is claimed.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,random,sys,time
from collections import defaultdict,Counter
from functools import lru_cache
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from urllib.error import HTTPError,URLError
from p7b3c_conditional_solar import (
    build_library,load_original_station,generate,project_energy,
    sun_cos_midpoint,haurwitz,seasonal_p95,month_hour_score,sha,SEASONS
)

DONORS={53:('Lassnitzhoehe',47.07361,15.59222),
        94:('St_Radegund',47.18211,15.48978),
       200:('Gleisdorf',47.11556,15.70806)}
GRAZ=(30,'Graz_Universitaet',47.08,15.448056)
EVAL_YEARS=(2012,2013,2014)
TRAIN_YEARS=(2007,2008)
SELECT_YEAR=2009
ALPHA=.75
QUALITY={10,11,12,20,21,22}
CET=timedelta(hours=1)
BASE_URL='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min'
REPLICATES=20


def fetch_source(url,max_size=35000000):
    problems=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'IGE-P7B3D-observed-independent-site-validation/2026',
                                              'Accept':'application/json'}),timeout=120) as r:
                data=r.read(max_size+1)
                if r.status!=200 or len(data)>max_size:
                    raise ValueError('GeoSphere response status/size invalid')
            obj=json.loads(data)
            if not isinstance(obj,dict):raise ValueError('provider returned no object')
            return data,obj
        except (HTTPError,URLError,OSError,TimeoutError,ValueError) as exc:
            problems.append(str(exc)[:300])
            if isinstance(exc,HTTPError) and exc.code in (400,401,403,404,422):break
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError('provider source NOT retrieved: '+str(problems))


def metadata_station_check(metadata):
    stations={int(s['id']):s for s in metadata.get('stations',[]) if s.get('id') is not None}
    for sid,(name,lat,lon) in DONORS.items():
        s=stations.get(sid)
        if not s or not s.get('has_global_radiation'):
            raise ValueError('pre-registered station radiation metadata absent: '+str(sid))
        if abs(float(s['lat'])-lat)>.01 or abs(float(s['lon'])-lon)>.01:
            raise ValueError('pre-registered independent-site coordinates drifted '+str(sid))
        if s.get('group_id') in (30,'30'):
            raise ValueError('station alias of Graz not independently valid')
    names={p['name']:p for p in metadata['parameters']}
    if 'cglo' not in names or 'cglo_flag' not in names:
        raise ValueError('original GHI / QC channel absent')
    if names['cglo'].get('unit') not in ('W/m²','W/m2','W m-2','W/m^2'):
        raise ValueError('original radiation units modified')
    legend={int(q['key']):str(q['value']) for q in metadata.get('code_lists',{}).get('q21',[]) if q.get('key') is not None}
    if not QUALITY<=set(legend) or 0 not in legend:
        raise ValueError('official quality code meanings unavailable')
    return stations


def decode_station_year(obj,station,year):
    start=datetime(year,1,1,tzinfo=timezone.utc)
    n=(datetime(year+1,1,1,tzinfo=timezone.utc)-start).days*144
    times=obj.get('timestamps',[])
    if len(times)!=n:
        raise ValueError(f'incomplete 10-minute indexed provider time {station}/{year}: {len(times)}/{n}')
    prop=[f.get('properties',{}) for f in obj.get('features',[])]
    if len(prop)!=1:raise ValueError('station response not exactly one original station')
    sid=prop[0].get('station')
    if isinstance(sid,dict):sid=sid.get('id')
    if int(sid)!=station:raise ValueError('station id changed in original response')
    p=prop[0].get('parameters',{})
    for key in ('cglo','cglo_flag'):
        if key not in p or len(p[key].get('data',[]))!=n:
            raise ValueError('missing or truncated station radiation/QC')
    if p['cglo'].get('unit') not in ('W/m²','W/m2','W m-2','W/m^2'):
        raise ValueError('raw GHI unit drift')
    result=[]
    for i,stamp in enumerate(times):
        dt=datetime.fromisoformat(str(stamp).replace('Z','+00:00'))
        if dt.utcoffset()!=timedelta(0) or dt!=start+timedelta(minutes=10*i):
            raise ValueError('non-UTC original clock/10min interval gap')
        q=p['cglo_flag']['data'][i]
        x=p['cglo']['data'][i]
        approved=(q is not None and int(q) in QUALITY and x is not None and math.isfinite(float(x))
                  and float(x)>=0)
        result.append((dt,float(x) if approved else None,approved))
    return result


def aggregate_6of6(rows,window,year):
    if window not in ('record_start','record_end'):raise ValueError('unknown original time hypothesis')
    bins=defaultdict(list)
    shift=timedelta(minutes=10) if window=='record_end' else timedelta(0)
    for timestamp,value,approved in rows:
        hour=(timestamp-shift).replace(minute=0)
        bins[hour].append((timestamp,value,approved))
    complete={}
    counts=Counter()
    for t,group in bins.items():
        if t.year!=year:continue
        counts['hour_bins']+=1
        if len(group)!=6 or len({z[0] for z in group})!=6 or not all(z[2] for z in group):
            counts['unqualified']+=1;continue
        hour=t+CET
        # GeoSphere 10-min numbers are W/m2 mean powers, 10-min -> kWh/m2
        complete[hour.replace(tzinfo=None)]=sum(z[1] for z in group)/6000.
        counts['qualified']+=1
    return complete,dict(counts)


def full_days(data):
    group=defaultdict(dict)
    for dt,x in data.items():group[dt.date()][dt.hour]=x
    return {d:[vals[i] for i in range(24)] for d,vals in group.items()
            if set(vals)==set(range(24))}


@lru_cache(maxsize=4096)
def geometry(date0,lat,lon):
    # 5-minute sampling integrates interval crossing at sunrise/sunset rather
    # than incorrectly treating mid-hour solar cosine as a whole-hour cap.
    results=[]
    for hour in range(24):
        t=datetime.combine(date0,datetime.min.time())+timedelta(hours=hour)
        cos=[]
        for sub in range(12):
            # P7B3C NOAA solar cosine function uses +0.5-hour midpoint.
            # Adjust the input clock to place midpoint at each 5-min midpoint.
            cos.append(solar_cos(t+timedelta(minutes=5*(sub+.5)),lat,lon))
        day=t.timetuple().tm_yday
        e0=1+0.033*math.cos(2*math.pi*(day-3)/365.25)
        toa=1.361*e0*fmean(cos)
        clear=fmean(haurwitz(x) for x in cos)
        results.append((t,toa,clear))
    return results


def solar_cos(local,lat,lon):
    doy=local.timetuple().tm_yday
    n=366 if local.year%4==0 and (local.year%100!=0 or local.year%400==0) else 365
    clock=local.hour+local.minute/60+local.second/3600
    g=2*math.pi/n*(doy-1+(clock-12)/24)
    dec=(.006918-.399912*math.cos(g)+.070257*math.sin(g)-.006758*math.cos(2*g)+
         .000907*math.sin(2*g)-.002697*math.cos(3*g)+.00148*math.sin(3*g))
    eq=229.18*(.000075+.001868*math.cos(g)-.032077*math.sin(g)-.014615*math.cos(2*g)-.040849*math.sin(2*g))
    ha=math.radians((clock*60+eq+4*lon-60)/4-180)
    p=math.radians(lat)
    return max(0.,min(1.,math.sin(p)*math.sin(dec)+math.cos(p)*math.cos(dec)*math.cos(ha)))


def build_daily_models(measured_days,lat,lon,cap_fraction=.65):
    model={};truth={};excluded=[]
    for day,values in sorted(measured_days.items()):
        geom=geometry(day,lat,lon)
        toas=[v[1] for v in geom];clears=[v[2] for v in geom]
        caps=[min(toa,max(1.25*c,cap_fraction*toa)) for toa,c in zip(toas,clears)]
        target=sum(values)
        if target>sum(caps)+1e-9:
            excluded.append({'day':day.isoformat(),'reason':'DAILY_OBS_GHI_EXCEEDS_REGISTERED_CAP',
                             'daily_obs_ghi':target,'daily_cap':sum(caps)})
            continue
        base=project_energy(clears,target,caps)
        model[day]=[(geom[h][0],base[h],toas[h],clears[h]) for h in range(24)]
        for h in range(24):truth[geom[h][0]]=values[h]
    return model,truth,excluded


def consecutive_p95(data):
    return seasonal_p95(data)


def comparison(truth,model):
    if len(truth)<240*24:raise ValueError('too few original qualified full days')
    am,cell=month_hour_score(truth,model)
    p=consecutive_p95(truth)
    mp=consecutive_p95(model)
    err=fmean(abs(mp[s]/p[s]-1) for s in p)
    return {'climatology_mae':am,'climatology_cell_count':cell,
            'mean_season_p95_rel_error':err,
            'JJA_p95_delta_observed':p['JJA'],
            'JJA_p95_delta_model':mp['JJA'],
            'season_p95_observed':p,'season_p95_model':mp}


def solar_cloud_persistence(records,lat,lon):
    # Cloudiness is defined only when clear-sky irradiance >= 0.1 kWh/m²/h.
    # Missing observations break runs (do not join separate days).
    byday=defaultdict(dict)
    for t,v in records.items():byday[t.date()][t.hour]=v
    run_lengths=[]
    for day,values in byday.items():
        g=geometry(day,lat,lon)
        r=0
        for h in range(24):
            clear=g[h][2]
            cloud=(h in values and clear>=.1 and values[h]/clear<.5)
            if cloud:r+=1
            else:
                if r:run_lengths.append(r)
                r=0
        if r:run_lengths.append(r)
    return {'cloud_run_count':len(run_lengths),
            'mean_cloud_run_hours':fmean(run_lengths) if run_lengths else None,
            'p95_cloud_run_hours':pct(run_lengths,.95) if run_lengths else None}


def pct(v,p):
    if not v:return None
    s=sorted(v);z=(len(s)-1)*p;k=math.floor(z)
    return s[k]+(s[min(k+1,len(s)-1)]-s[k])*(z-k)


def run_evaluation(site_id,year,window,lat,lon,measured,library,seeds=20):
    days=full_days(measured)
    if len(days)<240:
        raise ValueError(f'insufficient approved full days station {site_id} {year}: {len(days)}')
    daily,truth,excluded=build_daily_models(days,lat,lon)
    if len(daily)<240:raise ValueError('less than 240 eligible full days after caps')
    m0={t:v for d,rows in daily.items() for t,v,*_ in rows}
    obs=comparison(truth,m0)
    all_scores=[]
    for seed in range(seeds):
        realization,audit=generate(daily,library,ALPHA,seed)
        if len(realization)!=len(truth):raise ValueError('incomplete generated hours')
        if audit['max_daily_energy_residual']>1e-9:
            raise ValueError('M2 did not conserve known daily energy')
        m=comparison(truth,realization)
        all_scores.append({'seed':seed,'climatology_mae':m['climatology_mae'],
            'mean_season_p95_rel_error':m['mean_season_p95_rel_error'],
            'JJA_p95_delta':m['JJA_p95_delta_model'],
            'daily_energy_residual':audit['max_daily_energy_residual'],
            'cloud_persistence':solar_cloud_persistence(realization,lat,lon)})
    return {'station_id':site_id,'year':year,'window':window,'valid_qc_full_days':len(days),
        'evaluated_days':len(daily),'excluded_under_cap':len(excluded),
        'missing_or_unqualified_days':(366 if year%4==0 else 365)-len(days),
        'cap_fraction':.65,'observed':{
            'GHI_p95_jja':obs['JJA_p95_delta_observed'],
            'persistence':solar_cloud_persistence(truth,lat,lon)},
        'M0':obs,'M2':{
            'seeds':seeds,'mean_climatology_mae':fmean(s['climatology_mae'] for s in all_scores),
            'mean_season_p95_rel_error':fmean(s['mean_season_p95_rel_error'] for s in all_scores),
            'mean_JJA_p95_delta':fmean(s['JJA_p95_delta'] for s in all_scores),
            'maximum_energy_residual':max(s['daily_energy_residual'] for s in all_scores),
            'climatology_mae_seed_range':[min(s['climatology_mae'] for s in all_scores),max(s['climatology_mae'] for s in all_scores)],
            'p95_error_seed_range':[min(s['mean_season_p95_rel_error'] for s in all_scores),max(s['mean_season_p95_rel_error'] for s in all_scores)],
            'mean_cloud_run_hours':fmean(s['cloud_persistence']['mean_cloud_run_hours'] for s in all_scores if s['cloud_persistence']['mean_cloud_run_hours'] is not None),
            'seed_records':all_scores},
        'excluded_reason_counts':dict(Counter(x['reason'] for x in excluded))}


def run(graz_original,output,live=True,seeds=20,only_graz=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    # use original frozen 2007-2008 Graz data solely for analogue training;
    # never modify frozen alpha selection, even when other sites perform worse.
    stations={};libs={}
    for window in ('record_start','record_end'):
        train,traincounts=load_original_station(graz_original,window,TRAIN_YEARS)
        libs[window]=build_library(train)
    current_source={'frozen_graz_original_hourly_sha256':sha(graz_original)}
    site_years={};site_source_failures=[]
    if live and not only_graz:
        original_meta,meta=fetch_source(BASE_URL+'/metadata')
        metadata_station_check(meta)
        current_source['live_original_metadata_sha256']=hashlib.sha256(original_meta).hexdigest()
        current_source['live_metadata_url']=BASE_URL+'/metadata'
        for sid in DONORS:
            for y in EVAL_YEARS:
                query=urlencode({'parameters':'cglo,cglo_flag','station_ids':str(sid),
                    'start':f'{y}-01-01T00:00','end':f'{y}-12-31T23:50','output_format':'geojson'})
                url=BASE_URL+'?'+query
                try:
                    raw,record=fetch_source(url)
                    values=decode_station_year(record,sid,y)
                except (RuntimeError,ValueError) as e:
                    site_source_failures.append({'station_id':sid,'year':y,'reason':str(e)[:350]})
                    print('P7B.3D independently required original source UNAVAILABLE',sid,y,str(e)[:150],flush=True)
                    continue
                site_years[sid,y]=values
                current_source[f'geo_{sid}_{y}_source_sha256']=hashlib.sha256(raw).hexdigest()
                print('P7B.3D original ground fetched station/year:',sid,y,'n10min',len(values),flush=True)
    results=[];coverage=[];flags=[]
    # Important: Graz evaluation years from 2005-2014 original archived source.
    for window in ('record_start','record_end'):
        archived,counts=load_original_station(graz_original,window,EVAL_YEARS)
        for year in EVAL_YEARS:
            measurements={t:v for t,v in archived.items() if t.year==year}
            coverage.append({'station_id':GRAZ[0],'year':year,'window':window,
                             'qc_complete_hours':len(measurements),'source':'IMMUTABLE_P6_3F'})
            try:
                scores=run_evaluation(GRAZ[0],year,window,GRAZ[2],GRAZ[3],measurements,libs[window],seeds)
                results.append(scores)
            except ValueError as e:
                flags.append({'station_id':GRAZ[0],'year':year,'window':window,'reason':str(e)})
        for sid,(_,lat,lon) in DONORS.items():
            for year in EVAL_YEARS:
                if (sid,year) not in site_years:continue
                measurements,tally=aggregate_6of6(site_years[sid,year],window,year)
                # Reassigned local CET (one-hour UTC shift) may put the
                # boundary hour in adjacent year; no invented neighboring data.
                measurements={t:v for t,v in measurements.items() if t.year==year}
                coverage.append({'station_id':sid,'year':year,'window':window,
                    'qc_complete_hours':len(measurements),'source':'LIVE_GEOSPHERE_10MIN',
                    'provider_hour_counts':tally})
                try:
                    res=run_evaluation(sid,year,window,lat,lon,measurements,libs[window],seeds)
                    results.append(res)
                except ValueError as e:
                    flags.append({'station_id':sid,'year':year,'window':window,'reason':str(e)})
    flat=[]
    for r in results:
        flat.append({'station_id':r['station_id'],'year':r['year'],'window':r['window'],
           'valid_full_days':r['valid_qc_full_days'],'evaluated_days':r['evaluated_days'],
           'source_daily_cap_excluded':r['excluded_under_cap'],
           'observed_JJA_p95_delta':r['observed']['GHI_p95_jja'],
           'M0_monthhour_MAE':r['M0']['climatology_mae'],
           'M2_monthhour_MAE_mean':r['M2']['mean_climatology_mae'],
           'M0_mean_seasonal_p95_rel_error':r['M0']['mean_season_p95_rel_error'],
           'M2_mean_seasonal_p95_rel_error':r['M2']['mean_season_p95_rel_error'],
           'M0_JJA_p95_delta':r['M0']['JJA_p95_delta_model'],
           'M2_JJA_p95_delta':r['M2']['mean_JJA_p95_delta'],
           'M2_max_daily_energy_residual':r['M2']['maximum_energy_residual']})
    flat.sort(key=lambda x:(x['station_id'],x['year'],x['window']))
    report={'stage':'IGE_P7B3D_CROSS_YEAR_CROSS_SITE_M2_GENERALIZATION',
        'source_periods':{'train_graz':[2007,2008],'alpha_selection_graz':[2009],
                          'evaluation':[2012,2013,2014]},
        'scientific_status':'EXPLORATORY_PHYSICALLY_CONSTRAINED_OBSERVED_DAILY_TO_HOURLY_BENCHMARK',
        'epw_production_ready':False,'alpha_p7b3c_frozen':ALPHA,
        'M2_has_no_test_site_or_evaluation_year_fitting':True,
        'evaluation_conditions_on_known_measured_daily_energy':True,
        'model_weather_realization_skill_not_inferred':True,
        'frozen_Graz_train_not_independent_geographical_transfer':True,
        'actual_model_GCM_interannual_transfer_not_tested':True,
        'Graz_2012_2014_previously_consulted':True,
        'site_ids_pre_registered':list(DONORS),
        'observation_clock_hypotheses':['record_start','record_end'],
        'no_provider_QC_zero_data_as_ground':True,
        'seeds':seeds,'source_SHA':current_source,
        'coverage':coverage,'failed_or_ineligible':flags,'original_source_failures':site_source_failures,
        'results':flat,
        'limitations':[
          'Test uses known observed daily GHI; isolates conditional hourly-disaggregation skill, not independent day-level solar prediction',
          'M0-clear-sky deterministic daily disaggregation is not identical to full P7B.2 CanESM5 hourly profile',
          'Graz test period was already consulted earlier; external site-year data were not used to tune alpha',
          'Observed 10-minute record_start/end time convention unresolved; report both',
          'TOA and Haurwitz based on approximate geometric solar position and 5-minute quadrature',
          '0.65 TOA near-horizon floor is engineering assumption not a validated clear-sky law',
          'No observed DHI/DNI, no building loads, no future SSP or other-GCM validation']}
    csv_path=output/'p7b3d_crossyear_crosssite_scores.csv'
    if flat:
        with csv_path.open('w',newline='',encoding='utf8') as f:
            w=csv.DictWriter(f,fieldnames=list(flat[0]))
            w.writeheader();w.writerows(flat)
        report['scores_SHA256']=sha(csv_path)
    report['site_year_groups_pass']=len({(r['station_id'],r['year']) for r in results})
    report['external_site_year_groups_pass']=len({(r['station_id'],r['year']) for r in results if r['station_id']!=30})
    ext={(r['station_id'],r['year']) for r in results if r['station_id']!=30}
    report['external_distinct_stations']=len({s for s,y in ext})
    report['external_distinct_years']=len({y for s,y in ext})
    report['coverage_gate_pass']=(len(ext)>=4 and report['external_distinct_stations']>=2
                                  and report['external_distinct_years']>=2)
    (output/'p7b3d_science_audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graz-frozen-hourly',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--seeds',type=int,default=20)
    parser.add_argument('--only-graz',action='store_true')
    args=parser.parse_args()
    if not 2<=args.seeds<=40:raise ValueError('scientific ensemble must use 2..40 fixed seeds')
    r=run(args.graz_frozen_hourly,args.out,not args.only_graz,args.seeds,args.only_graz)
    print(json.dumps({'source_groups':r['site_year_groups_pass'],
                      'external_site_year_groups':r['external_site_year_groups_pass'],
                      'crosssite_gate_pass':r['coverage_gate_pass'],
                      'failures':r['failed_or_ineligible'],'results':r['results']},indent=2),flush=True)
    if not args.only_graz and not r['coverage_gate_pass']:
        raise SystemExit('original independent external station QC threshold unavailable; no cross-site validity claim')

if __name__=='__main__':main()