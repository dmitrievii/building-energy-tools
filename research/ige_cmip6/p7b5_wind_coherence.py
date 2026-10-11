#!/usr/bin/env python3
"""P7B.5: QC-approved observed wind-regime analogue, multivariate EPW readiness.
No event-date pairing, no invention of wind direction if original QC fails.
Original P7B.4 8760h GHI/DHI/DNI and all 34 other EPW columns are immutable.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,random
from collections import defaultdict,Counter
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import urlopen,Request

BASE='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h'
STATION=30
TRAIN=(2007,2008)
SELECT=(2009,)
VALIDATE=(2012,2013,2014)
SOURCE_YEARS=TRAIN+SELECT+VALIDATE
UTC_CET=timedelta(hours=1)
QC=frozenset((10,11,12,20,21,22))
INPUT_SHA='2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012'
N=8760; COLS=35
FIELDS=('dd','ff','tl','rf','rr')
UNITS={'dd':('°','deg'), 'ff':('m/s',),'tl':('°C','degC'), 'rf':('%',), 'rr':('mm',)}
SEASONS={1:'DJF',2:'DJF',12:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}
CALM=.5
WIND_COL=20;SPEED_COL=21


def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for piece in iter(lambda:f.read(1<<20),b''):h.update(piece)
 return h.hexdigest()


def fetch(url,maximum=18000000):
 with urlopen(Request(url,headers={'Accept':'application/json','User-Agent':'IGE-P7B5-research-qc-wind-2026'}),timeout=120) as f:
  raw=f.read(maximum+1)
  if f.status!=200 or not raw or len(raw)>maximum:raise ValueError('Original provider source absent or truncated')
 return raw,json.loads(raw)


def metadata(meta):
 params={p['name']:p for p in meta.get('parameters',[]) if isinstance(p,dict) and p.get('name')}
 for field in FIELDS:
  if field not in params or field+'_flag' not in params:raise ValueError('Original hourly QC field missing '+field)
  if params[field].get('unit') not in UNITS[field]:raise ValueError('Original hourly unit drift '+field)
 legend={int(x['key']):str(x.get('value','')) for x in meta.get('code_lists',{}).get('q21',[])
         if isinstance(x,dict) and x.get('key') is not None}
 if not QC<=set(legend) or 0 not in legend:raise ValueError('Official original q21 legend incomplete')
 if 'ungeprüft' not in legend[0].lower():raise ValueError('Quality code 0 semantics drift')
 stations={int(x['id']):x for x in meta.get('stations',[]) if x.get('id') is not None}
 if STATION not in stations:raise ValueError('Original station #30 missing from hourly source')
 return {'station':stations[STATION],'units':{key:params[key]['unit'] for key in FIELDS},
   'q21':legend,'timestamp_semantics':'unresolved_both_record_start_and_record_end'}


def decode(obj,year):
 stamps=obj.get('timestamps',[])
 begin=datetime(year,1,1,tzinfo=timezone.utc)
 count=int((datetime(year+1,1,1,tzinfo=timezone.utc)-begin).total_seconds()/3600)
 if len(stamps)!=count:raise ValueError('Incomplete station UTC year '+str(year))
 entries=obj.get('features',[])
 if len(entries)!=1:raise ValueError('Ambiguous original station feature')
 props=entries[0].get('properties',{})
 s=props.get('station');identity=int(s.get('id') if isinstance(s,dict) else s)
 if identity!=STATION:raise ValueError('Wrong original GeoSphere station ID')
 fields=props.get('parameters',{})
 for key in FIELDS:
  if key not in fields or key+'_flag' not in fields:raise ValueError('Missing original hourly wind/met flag '+key)
  if fields[key].get('unit') not in UNITS[key]:raise ValueError('Provider returned unexpected unit '+key)
  for suffix in ('','_flag'):
   if len(fields[key+suffix].get('data',[]))!=count:raise ValueError('Incomplete original source parameter')
 rows={}
 for i,s in enumerate(stamps):
  dt=datetime.fromisoformat(str(s).replace('Z','+00:00'))
  if dt.utcoffset()!=timedelta(0) or dt!=begin+timedelta(hours=i):raise ValueError('Original source UTC clock broken')
  vals={}
  for key in FIELDS:
   v=fields[key]['data'][i];flag=fields[key+'_flag']['data'][i]
   try:ok=flag is not None and int(flag) in QC and v is not None and math.isfinite(float(v))
   except (ValueError,TypeError):ok=False
   value=float(v) if ok else None
   if value is not None:
    if key=='ff' and not 0<=value<=50:ok=False
    if key=='dd' and not 0<=value<=360:ok=False
    if key=='tl' and not -70<=value<=60:ok=False
    if key=='rf' and not 0<=value<=100:ok=False
    if key=='rr' and not -1<=value<=200:ok=False
   vals[key]=value if ok else None
  rows[dt]=vals
 return rows


def load_observations(years=SOURCE_YEARS):
 meta_raw,meta=fetch(BASE+'/metadata',9000000)
 ref=metadata(meta)
 orig={'provider_original_metadata_sha256':hashlib.sha256(meta_raw).hexdigest()}
 observations={}
 for year in years:
  q=urlencode({'parameters':','.join(y for x in FIELDS for y in (x,x+'_flag')),
    'station_ids':str(STATION),'start':f'{year}-01-01T00:00',
    'end':f'{year}-12-31T23:00','output_format':'geojson'})
  url=BASE+'?'+q
  raw,obj=fetch(url)
  original=decode(obj,year)
  if set(observations)&set(original):raise ValueError('Original source time overlap')
  observations.update(original)
  orig[f'year_{year}_original_data_sha256']=hashlib.sha256(raw).hexdigest()
  print('P7B5 original GeoSphere hourly QC fetched:',year,len(original),flush=True)
 return observations,ref,orig


def local_times(obs,window):
 if window not in ('record_start','record_end'):raise ValueError('Unregistered clock hypothesis')
 delta=UTC_CET-(timedelta(hours=1) if window=='record_end' else timedelta(0))
 return {(utc.replace(tzinfo=None)+delta):dict(x) for utc,x in obs.items()}


def complete_days(obs,years):
 result={};calendar=defaultdict(dict)
 for dt,values in obs.items():
  if dt.year in years:calendar[dt.date()][dt.hour]=values
 for day,hours in calendar.items():
  if len(hours)!=24 or set(hours)!=set(range(24)):continue
  series=[hours[h] for h in range(24)]
  if any(v['ff'] is None or (v['ff']>=CALM and v['dd'] is None) for v in series):continue
  valid=[i for i,v in enumerate(series) if v['ff']>=CALM]
  if len(valid)<4:continue
  mean_speed=fmean(x['ff'] for x in series)
  weather_valid=all(x['tl'] is not None and x['rf'] is not None for x in series)
  rain_valid=all(x['rr'] is not None for x in series)
  wet=(sum(max(0.,x['rr']) for x in series)>=.1) if rain_valid else None
  result[day]={'day':day,'directions':tuple(x['dd'] if x['ff']>=CALM else None for x in series),
    'speed':tuple(x['ff'] for x in series), 'speed_mean':mean_speed,
    'temp_mean':fmean(x['tl'] for x in series) if weather_valid else None,
    'rh_mean':fmean(x['rf'] for x in series) if weather_valid else None,
    'wet':wet,'valid_direction_hours':len(valid)}
 return result


def read_epw(path):
 if sha(path)!=INPUT_SHA:raise ValueError('P7B.4 original EPW SHA mismatch')
 with open(path,encoding='utf-8',newline='') as f:rows=list(csv.reader(f))
 if len(rows)!=N+8 or any(len(x)!=COLS for x in rows[8:]):raise ValueError('Original EPW 8+8760 x35 contract failed')
 expect=datetime(2013,1,1)
 for i,row in enumerate(rows[8:]):
  dt=expect+timedelta(hours=i)
  if list(map(int,row[:5]))!=[dt.year,dt.month,dt.day,dt.hour+1,60]:
   raise ValueError('EPW clock/day mismatch')
  if row[WIND_COL]!='999':raise ValueError('Original EPW direction not missing; do not overwrite observed values')
  s=float(row[SPEED_COL])
  if not math.isfinite(s) or not 0<=s<40:raise ValueError('Original wind speed not physical')
 return rows[:8],rows[8:]


def epw_days(rows):
 out={}
 for i in range(0,N,24):
  subset=rows[i:i+24];d=date(int(subset[0][0]),int(subset[0][1]),int(subset[0][2]))
  speed=[float(r[SPEED_COL]) for r in subset]
  t=[float(r[6]) for r in subset];rh=[float(r[8]) for r in subset]
  rain=[float(r[33]) for r in subset]
  out[d]={'speed':speed,'speed_mean':fmean(speed),'temp_mean':fmean(t),
          'rh_mean':fmean(rh),'wet':sum(max(0.,x) for x in rain)>=.1}
 return out


def angular_delta(a,b):
 return abs(((a-b+180)%360)-180)


def choose(lib,dt,target,seed,k=20):
 pool=[p for p in lib.values() if SEASONS[p['day'].month]==SEASONS[dt.month]]
 if len(pool)<30:raise ValueError('Not enough QC approved same-season observed donor days')
 def dist(p):
  err=abs(p['speed_mean']-target['speed_mean'])/1.5
  if p['temp_mean'] is not None:err+=.2*abs(p['temp_mean']-target['temp_mean'])/7
  if p['rh_mean'] is not None:err+=.1*abs(p['rh_mean']-target['rh_mean'])/20
  if p['wet'] is not None:err+=.5*int(p['wet']!=target['wet'])
  return err
 ranked=sorted(pool,key=lambda p:(dist(p),p['day'].isoformat()))[:k]
 h=int.from_bytes(hashlib.sha256(f'P7B5:WIND:{seed}:{dt.isoformat()}'.encode()).digest()[:8],'big')
 return random.Random(h).choice(ranked)


def donor_direction(donor,h):
 values=donor['directions']
 if values[h] is not None:return values[h],0
 # Do not fabricate north when donor source is calm. Borrow nearest *verified*
 # donor direction, circular within a day; preserve provenance fallback count.
 candidates=[(min(abs(j-h),24-abs(j-h)),j) for j,d in enumerate(values) if d is not None]
 if not candidates:raise ValueError('Analogue has no qualified directional observation')
 _,nearest=min(candidates)
 return values[nearest],1


def wind_day(day,target,lib,seed):
 donor=choose(lib,day,target,seed)
 output=[];fallbacks=0
 for h,v in enumerate(target['speed']):
  if v<CALM:output.append(0.);continue
  direction,flag=donor_direction(donor,h)
  output.append(direction%360);fallbacks+=flag
 return output,{'analogue_date':donor['day'].isoformat(),'fallback_hours':fallbacks,
    'conditioning_speed_mean_abs_difference_ms':abs(donor['speed_mean']-target['speed_mean'])}


def bins(directions,speeds):
 tally=[0]*8;n=0
 for d,v in zip(directions,speeds):
  if v>=CALM and d is not None:
   tally[int((d%360+22.5)//45)%8]+=1;n+=1
 return [x/n for x in tally] if n else None


def turn_persistence(dirs,speeds):
 delta=[]
 for a,b,va,vb in zip(dirs[:-1],dirs[1:],speeds[:-1],speeds[1:]):
  if min(va,vb)>=CALM and a is not None and b is not None:
   delta.append(angular_delta(a,b))
 return fmean(delta) if delta else None


def validation_metrics(generated,observed):
 model_dirs=[];model_speeds=[];obs_dirs=[];obs_speeds=[]
 for day,g in generated.items():
  model_dirs.extend(g['dirs']);model_speeds.extend(g['speed'])
  if day in observed:
   ob=observed[day]
   obs_dirs.extend(ob['directions']);obs_speeds.extend(ob['speed'])
 # Model versus ground is climatological distribution only, not date matching.
 # 'observed' hours use actual observation solely for reference stats.
 bm=bins(model_dirs,model_speeds);bo=bins(obs_dirs,obs_speeds)
 if bm is None or bo is None:return {'eligible':False,'reason':'No valid noncalm observed wind directions'}
 return {'eligible':True,'model_8_sector_fraction':bm,'ground_8_sector_fraction':bo,
    'sector_total_variation':.5*sum(abs(a-b) for a,b in zip(bm,bo)),
    'mean_model_turn_deg':turn_persistence(model_dirs,model_speeds),
    'mean_ground_turn_deg':turn_persistence(obs_dirs,obs_speeds),
    'n_model_noncalm':sum(v>=CALM for v in model_speeds),
    'n_ground_noncalm':sum(v>=CALM for v in obs_speeds),
    'interpretation':'wind-rose distribution only; model and observed dates are NOT paired forecasts'}


def write_csv(path,rows):
 if not rows:raise ValueError('Empty derived csv')
 with open(path,'w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def audit_epw(rows):
 # Missing sentinels and known unrelated scientific shortcomings, explicit.
 missing={}
 for k,label,marker in [(20,'wind_direction','999'),(22,'total_sky_cover','99'),
                        (23,'opaque_sky_cover','99'),(24,'visibility','9999'),
                        (28,'precipitable_water','999')]:
  missing[label]=sum(r[k]==marker for r in rows)
 for r in rows:
  t=float(r[6]);td=float(r[7]);rh=float(r[8]);p=float(r[9]);v=float(r[21]);dir=float(r[20]);
  ghi=float(r[13]);dhi=float(r[15]);dni=float(r[14])
  if not(-70<t<70 and td<=t+1e-4 and 0<rh<=100 and 70000<p<110000 and
         0<=v<40 and (dir==999 or 0<=dir<=360) and min(ghi,dhi,dni)>=0):
   raise ValueError('EPW thermodynamic/wind/radiometric constraints fail')
 return missing


def run(original_epw,out_dir,seeds=8,source=None):
 if seeds<2 or seeds>20:raise ValueError('Expected 2..20 seeds')
 out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
 header,baseline=read_epw(original_epw)
 evidence,provider,original=source if source is not None else load_observations()
 model=epw_days(baseline)
 audits={};data=[];diagnostic=[];raw0=None
 for window in ('record_start','record_end'):
  local=local_times(evidence,window)
  train=complete_days(local,TRAIN);sel=complete_days(local,SELECT);hold=complete_days(local,VALIDATE)
  classes=Counter(SEASONS[d.month] for d in train)
  coverage={s:classes[s] for s in ('DJF','MAM','JJA','SON')}
  if min(coverage.values(),default=0)<30:raise ValueError('Insufficient provider-qualified original wind training days '+str(coverage))
  if len(sel)<180 or len(hold)<600:raise ValueError('Independent provider QC year coverage insufficient')
  rows=[];seeds_metrics=[]
  for seed in range(seeds):
   synth={};hours=[]
   for day,target in model.items():
    dirs,prov=wind_day(day,target,train,seed)
    synth[day]={'dirs':dirs,'speed':target['speed']}
    if seed==0 and window=='record_start':
     for h,d in enumerate(dirs):hours.append((day,h,d,prov['analogue_date'],prov['fallback_hours']))
   # Additional independent reference across actual observed validation days.
   # Use *observed day ff* as target, not actual dd, then compare distribution.
   reconstruction={}
   for day,x in hold.items():
    temp={'speed':x['speed'],'speed_mean':x['speed_mean'],
       'temp_mean':x['temp_mean'] if x['temp_mean'] is not None else 15.,
       'rh_mean':x['rh_mean'] if x['rh_mean'] is not None else 60.,
       'wet':x['wet'] if x['wet'] is not None else False}
    vals,_=wind_day(day,temp,train,seed)
    reconstruction[day]={'dirs':vals,'speed':x['speed']}
   m=validation_metrics(reconstruction,hold)
   if not m['eligible']:raise ValueError('Wind reference evaluation ineligible')
   seeds_metrics.append(m)
   if seed==0:
    for day,x in synth.items():
     for h in range(24):
      rows.append({'date':day.isoformat(),'hour':h,'window':window,'seed':seed,
       'wind_speed_original_ms':x['speed'][h], 'generated_wind_direction_deg':x['dirs'][h]})
    if window=='record_start':raw0=synth
  mean_tv=fmean(x['sector_total_variation'] for x in seeds_metrics)
  audits[window]={'train_complete_approved_days':len(train),'selection_complete_approved_days':len(sel),
    'validation_complete_approved_days':len(hold),'train_seasonal_days':coverage,
    '8_seed_or_more_wind_rose_reference_metrics':seeds_metrics,
    'mean_sector_TV_validation_known_speed':mean_tv,
    'unpaired_station_wind_direction_not_GCM_forecast':True}
  if window=='record_start':data=rows
 # Replace one *previously missing* field; any other output field MUST remain byte identical.
 if raw0 is None:raise ValueError('P7B5 no source-approved wind generated')
 output=[r.copy() for r in baseline]
 allinfo=[]
 for i,row in enumerate(output):
  d=date(2013,1,1)+timedelta(days=i//24)
  h=i%24
  v=raw0[d]['dirs'][h]
  row[WIND_COL]=f'{v:.3f}'
  if not 0<=v<=360:raise ValueError('Invalid wind direction')
  allinfo.append({'date':d.isoformat(),'hour':h,'wind_direction_deg':v,'wind_speed_ms':float(row[SPEED_COL])})
 for old,new in zip(baseline,output):
  if any(old[j]!=new[j] for j in range(COLS) if j!=WIND_COL):
   raise ValueError('P7B.5 modified source EPW non-wind direction field')
 outfile=out/'Graz_CanESM5_2013_IGE_P7B5_WIND_ANALOGUE_RESEARCH_ONLY.epw'
 newhead=[r.copy() for r in header]
 newhead[0][4]='IGE_P7B5_RESEARCH_ONLY';newhead[6]=['COMMENTS 2',
  'QC-trained Graz wind-direction day analogues, not measured model-weather events; wind speed P7B4 frozen; no DHI/DNI sensor validation; RESEARCH ONLY']
 with open(outfile,'w',newline='',encoding='utf-8') as f:
  w=csv.writer(f,lineterminator='\n');w.writerows(newhead);w.writerows(output)
 with open(outfile,newline='',encoding='utf-8') as f:check=list(csv.reader(f))
 if len(check)!=N+8 or any(len(r)!=35 for r in check[8:]):raise ValueError('Round-trip wind EPW syntax failure')
 for a,b in zip(baseline,check[8:]):
  if any(a[k]!=b[k] for k in range(COLS) if k!=WIND_COL):raise ValueError('Round-trip source values mutated')
 missing=audit_epw(check[8:]);prior_missing=audit_epw(baseline)
 write_csv(out/'p7b5_seed0_hourly_wind_direction.csv',allinfo)
 report={'stage':'IGE_P7B5_OBSERVED_QC_WIND_ANALOGUE_AND_MULTIVARIATE_EPW_READINESS',
  'technical_status':'ORIGINAL_SOURCE_QC_CONDITIONAL_WIND_DIRECTION_RESEARCH_GENERATED',
  'scientific_status':'REGIONAL_WIND_CLIMATOLOGY_REVIEW_REQUIRED',
  'production_epw_ready':False,'full_EnergyPlus_simulation_executed':False,
  'baseline_sha256':sha(original_epw),'baseline_hour_count':N,
  'wind_speed_unchanged_8760_hours':True,'P7B4_source_solar_and_thermodynamics_unchanged':True,
  'wind_source_provider':'GeoSphere Austria klima-v2-1h Graz #30 dd/ff/tl/rf/rr 2007-08',
  'original_provider_metadata':provider,'original_source_SHA':original,
  'training_years':list(TRAIN),'selection_years':list(SELECT), 'validation_years':list(VALIDATE),
  'time_hypothesis_used_for_generated_epw':'record_start (UNRESOLVED)',
  'both_unresolved_time_hypotheses':audits,
  'baseline_missing_counts':prior_missing,'candidate_missing_counts':missing,
  'candidate_radiation_not_DHI_DNI_observed':True,
  'candidate_wind_not_real_event_matched':True,
  'limitations':['Nearby observed hourly station wind directions do not establish GCM wind regime skill',
    'The EPW source pressure remains a proxy and existing hourly humidity is not instrument validated',
    'No independent DHI/DNI instrument and no EnergyPlus airflow validation',
    'Winds at 10m and station terrain might not match model-grid terrain or urban canopy',
    'GCM noleap and SSP 20-year climate scenarios have not been integrated into output',
    'The source timestamp record-start vs record-end interpretation requires provider confirmation',
    'EPW unknown total sky cover, opaque cover, visibility and precipitable water retained',
    'This is a conditional wind-direction analogue not a validated complete climate forecast'],
  'derived_sha256':{p.name:sha(p) for p in list(out.glob('*.csv'))+list(out.glob('*.epw'))} }
 (out/'p7b5_science_audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--original-epw',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True);p.add_argument('--seeds',type=int,default=8)
 a=p.parse_args();report=run(a.original_epw,a.out,a.seeds)
 print('P7B5 RESULT',json.dumps({'status':report['technical_status'],
  'train':report['both_unresolved_time_hypotheses']['record_start']['train_complete_approved_days'],
  'validation':report['both_unresolved_time_hypotheses']['record_start']['validation_complete_approved_days'],
  'mean_sector_tv':report['both_unresolved_time_hypotheses']['record_start']['mean_sector_TV_validation_known_speed'],
  'EPW_production_ready':report['production_epw_ready']}),flush=True)