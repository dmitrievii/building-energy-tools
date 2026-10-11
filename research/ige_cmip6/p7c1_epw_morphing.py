#!/usr/bin/env python3
"""IGE P7C.1: pre-registered empirical EPW morphing using original NASA NEX-GDDP-CMIP6 v2 daily climate-change distributions.
RESEARCH ONLY: source EPW patterns are inherited; this does not synthesize independent future event sequences.
No unpaired individual GCM day is equated with a historical EPW day.
"""
from __future__ import annotations
import argparse,bisect,csv,hashlib,json,math,statistics,functools
from collections import defaultdict
from datetime import datetime,date,timedelta
from pathlib import Path

MODEL='CanESM5'
HIST='historical-1995-2014'
WINDOWS=('ssp245-2040-2059','ssp245-2080-2099','ssp585-2040-2059','ssp585-2080-2099')
COLUMNS=35
EDIT_FIELDS=(6,7,8,12,13,14,15,21,33)
SOURCE_THRESHOLDS={'max_distance_deg':.4,'T_delta_abs_c':30.,'dtr_ratio':(0.65,1.35),
                   'q_ratio':(0.35,2.5),'solar_ratio':(.4,1.8),
                   'wind_ratio':(.3,2.7),'rain_ratio':(.2,3.5),'longwave_ratio':(.6,1.6)}


def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 return h.hexdigest()

def mean(v):
 if not v:raise ValueError('Empty climate distribution')
 return statistics.fmean(v)

def quantile(a,p):
 if not a:raise ValueError('Empty quantile distribution')
 p=max(0.,min(1.,p));t=p*(len(a)-1);i=int(t)
 return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(t-i)

def verify_model_dir(folder,window):
 folder=Path(folder); qa=json.loads((folder/'quality_report.json').read_text())
 prov=json.loads((folder/'source_provenance.json').read_text())
 if any(s.get('status')!='PASS' or s.get('model')!=MODEL or s.get('member')!='r1i1p1f1' or s.get('window')!=window
        for s in (qa,prov)) or qa['csv_sha256']!=prov['csv_sha256']:
  raise ValueError('Immutable model member, window, or QA mismatch')
 if qa.get('calendar') not in ('noleap','365_day') or qa['days']!=7300 or qa['years']!=20 or tuple(qa['grid'])!=(46.875,15.375):
  raise ValueError('Different or incomplete original noleap climate source')
 if set(qa['csv_sha256']) != {'joint_daily_raw.csv','model_monthly.csv','model_annual.csv','model_monthly_climatology.csv'}:
  raise ValueError('Not all original source products listed')
 for filename,h in qa['csv_sha256'].items():
  if sha(folder/filename)!=h:raise ValueError('Immutable source SHA mismatch: '+filename)
 ds=[];dates=set(); expected_scenario='historical' if window==HIST else window.split('-')[0]
 lo,hi=(1995,2014) if window==HIST else tuple(map(int,window.split('-')[1:]))
 with (folder/'joint_daily_raw.csv').open(newline='') as f:
  for row in csv.DictReader(f):
   y=int(row['year']);m=int(row['month']);d=int(row['day'])
   if not lo<=y<=hi or (m==2 and d==29) or row['scenario']!=expected_scenario or row['model']!=MODEL or row['member']!='r1i1p1f1':
    raise ValueError('GCM identity/calendar mismatch')
   dt=(y,m,d)
   if dt in dates:raise ValueError('Duplicate native day')
   dates.add(dt)
   values={k:float(row[k]) for k in ('tas_c','tasmax_c','tasmin_c','hurs','huss','pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind')}
   if any(not math.isfinite(v) for v in values.values()) or not values['tasmin_c']<=values['tas_c']<=values['tasmax_c'] or not 0<values['huss']<.1 or not 0<=values['hurs']<=100 or any(values[k]<0 for k in ('pr_mm_day','rsds_kwh_m2_day','rlds_kwh_m2_day','sfcWind')):
    raise ValueError('Invalid original model physics: '+str(dt))
   ds.append({'year':y,'month':m,**values})
 if len(ds)!=7300 or len(set(d['year'] for d in ds))!=20 or any(sum(x['year']==y for x in ds)!=365 for y in range(lo,hi+1)):
  raise ValueError('GCM not 20 complete native noleap years')
 return ds,{'model':MODEL,'window':window,'native_calendar':qa['calendar'], 'original_source_sha256':qa['csv_sha256'], 'quality_status':'PASS', 'grid_lat_lon':qa['grid']}

def read_epw(path):
 with open(path,newline='',encoding='utf-8-sig') as f:r=list(csv.reader(f))
 if len(r)!=8768 or len(r[0])<10 or r[0][0]!='LOCATION' or len(r[7])<7 or r[7][0]!='DATA PERIODS':
  raise ValueError('EPW requires 8 headers + complete 8760 hourly records')
 h=r[:8];records=r[8:];lat=float(h[0][6]);lon=float(h[0][7]);tz=float(h[0][8]);y=int(records[0][0])
 if y%4==0 and (y%100!=0 or y%400==0):raise ValueError('P7C.1 requires an explicit 365-day EPW (leap-year mapping not available)')
 if len(set(row[0] for row in records))!=1 or len(records)!=8760 or any(len(row)!=COLUMNS for row in records):raise ValueError('EPW width/year mismatch')
 if abs(lat-46.875)>SOURCE_THRESHOLDS['max_distance_deg'] or abs(lon-15.375)>SOURCE_THRESHOLDS['max_distance_deg']:
  raise ValueError('Graz CMIP6 grid not representative of input EPW coordinates')
 for i,row in enumerate(records):
  dt=datetime(y,1,1)+timedelta(hours=i)
  if tuple(map(int,row[:5]))!=(y,dt.month,dt.day,dt.hour+1,60):raise ValueError('Non-contiguous nonleap hour labels or DST')
  for ix in (6,7,8,9,12,13,14,15,21,33):
   v=float(row[ix]);missing={6:99.9,7:99.9,8:999,9:999999,12:9999,13:9999,14:9999,15:9999,21:999,33:999}
   if not math.isfinite(v) or v>=missing[ix]-1e-10:raise ValueError('Missing critical baseline weather field '+str(ix))
  t,dp,rh,p=map(float,[row[6],row[7],row[8],row[9]])
  if not (-65<t<65 and -75<dp<=t+.12 and .1<rh<=100.5 and 30000<p<120000):raise ValueError('Invalid input EPW psychrometric state')
  for ix in (12,13,14,15,21,33):
   if float(row[ix])<0:raise ValueError('Negative baseline radiation/wind/rain')
  wd=float(row[20]);
  if wd!=999 and not 0<=wd<=360:raise ValueError('Invalid original wind direction')
  if float(row[13])>1600 or float(row[14])>1600 or float(row[15])>1600:raise ValueError('Solar values unreasonable')
 return h,records,{'baseline_epw_sha256':sha(path),'calendar':'365-day fixed EPW hours, no DST','base_epw_year':y,'epw_lat':lat,'epw_lon':lon,'epw_tz':tz,'baseline_missing_wind_direction_hours':sum(float(r[20])==999 for r in records)}

def monthly_signals(hist,future):
 hist_m=defaultdict(list);future_m=defaultdict(list)
 for d in hist:hist_m[d['month']].append(d)
 for d in future:future_m[d['month']].append(d)
 results={}
 for m in range(1,13):
  x=hist_m[m];y=future_m[m]
  if len(x)<560 or len(y)<560:raise ValueError('Incomplete native monthly observations')
  def av(rows,key):return mean([r[key] for r in rows])
  delta=av(y,'tas_c')-av(x,'tas_c')
  dtr0=mean([r['tasmax_c']-r['tasmin_c'] for r in x]);dtr1=mean([r['tasmax_c']-r['tasmin_c'] for r in y])
  if dtr0<=0:raise ValueError('No source daily temperature range')
  def ratio(key):
   a=av(x,key);b=av(y,key)
   if a<=0:raise ValueError('No positive historical '+key)
   return b/a
  vals={'T_mean_delta_c':delta,'T_daily_range_ratio':dtr1/dtr0,
        'specific_humidity_ratio':ratio('huss'),
        'solar_ghi_ratio':ratio('rsds_kwh_m2_day'),
        'rainfall_amount_ratio':ratio('pr_mm_day'),
        'wind_speed_ratio':ratio('sfcWind'),
        'longwave_ratio':ratio('rlds_kwh_m2_day'),
        'historical_GCM_mean_T_c':av(x,'tas_c'), 'future_GCM_mean_T_c':av(y,'tas_c'),
        'historical_GCM_mean_GHI_kwh_m2_day':av(x,'rsds_kwh_m2_day'),
        'future_GCM_mean_GHI_kwh_m2_day':av(y,'rsds_kwh_m2_day'),
        'historical_daily_tas_sorted':sorted(d['tas_c'] for d in x),
        'future_daily_tas_sorted':sorted(d['tas_c'] for d in y)}
  if abs(delta)>SOURCE_THRESHOLDS['T_delta_abs_c']:raise ValueError('Invalid temperature climate change')
  for k,bounds in [('T_daily_range_ratio','dtr_ratio'),('specific_humidity_ratio','q_ratio'),('solar_ghi_ratio','solar_ratio'),('rainfall_amount_ratio','rain_ratio'),('wind_speed_ratio','wind_ratio'),('longwave_ratio','longwave_ratio')]:
   if not SOURCE_THRESHOLDS[bounds][0]<=vals[k]<=SOURCE_THRESHOLDS[bounds][1]:raise ValueError(f'Climate signal outside registered bounds month {m}: {k}={vals[k]}')
  results[m]=vals
 return results

def saturation_pa(t):
 return 611.2*math.exp(17.67*t/(t+243.5))

def q_from_rh(t,rh,p):
 e=saturation_pa(t)*rh/100.
 return .62198*e/(p-(1-.62198)*e)

def rh_from_q(t,q,p):
 e=q*p/(.62198+(1-.62198)*q)
 return 100*e/saturation_pa(t)

def dewpoint_from_rh(t,rh):
 e=saturation_pa(t)*rh/100
 z=math.log(e/611.2)
 return 243.5*z/(17.67-z)

def solarcos(dt,lat,lon,timezone):
 doy=dt.timetuple().tm_yday; n=365;hour=dt.hour+dt.minute/60+dt.second/3600
 gamma=2*math.pi/n*(doy-1+(hour-12)/24)
 decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)-.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)-.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
 eq=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)-.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
 solar_minutes=(hour*60+eq+4*lon-60*timezone)%1440
 ha=math.radians(solar_minutes/4-180)
 c=math.sin(math.radians(lat))*math.sin(decl)+math.cos(math.radians(lat))*math.cos(decl)*math.cos(ha)
 return max(0.,min(1.,c))

@functools.lru_cache(maxsize=420)
def solar_geometry(day,lat,lon,tz):
 result=[];mid=datetime(day.year,day.month,day.day)
 ecc=1+.033*math.cos(2*math.pi*(day.timetuple().tm_yday-3)/365.25)
 for hour in range(24):
  cs=[solarcos(mid+timedelta(hours=hour,minutes=(n+.5)*5),lat,lon,tz) for n in range(12)]
  c=mean(cs);toa=1.361*ecc*c
  result.append((c,toa))
 return result

def project_solar(shape,target,caps):
 if len(shape)!=24 or len(caps)!=24 or not math.isfinite(target) or target<0 or target>sum(caps)+1e-8:raise ValueError('Solar energy target outside TOA-bounded day')
 if target==0:return [0.]*24
 if all(-1e-8<=v<=c+1e-8 for v,c in zip(shape,caps)) and abs(sum(shape)-target)<1e-8:return list(shape)
 weights=[max(v,1e-10*c) if c>0 else 0 for v,c in zip(shape,caps)]
 lo,hi=0.,1.
 while sum(min(c,hi*w) for c,w in zip(caps,weights))<target-1e-12:
  hi*=2
  if hi>1e14:raise ValueError('No bracket for physical solar projection')
 for _ in range(60):
  mid=(hi+lo)/2
  if sum(min(c,mid*w) for c,w in zip(caps,weights))<target:lo=mid
  else:hi=mid
 out=[min(c,hi*w) for c,w in zip(caps,weights)]
 if abs(sum(out)-target)>1e-8:raise ValueError('Solar daily conservation lost')
 return out

def erbs_diffuse_fraction(kt):
 if kt<=.22:return min(1.,max(0.,1-.09*kt))
 if kt<=.8:return min(1.,max(0.,.9511-.1604*kt+4.388*kt**2-16.638*kt**3+12.336*kt**4))
 return .165

def split_ghi(ghi,cos,toa):
 if ghi<0 or ghi>toa+1e-7:raise ValueError('GHI above conservative extraterrestrial bound')
 if ghi<=1e-12:return (0.,0.)
 if cos<.065 or toa<=1e-9:return (0.,ghi)
 kt=ghi/toa;kd=erbs_diffuse_fraction(kt)
 dni=min(ghi/cos,toa/cos,ghi*(1-kd)/cos)
 dhi=max(0.,ghi-dni*cos)
 if abs(ghi-(dhi+dni*cos))>1e-9:raise ValueError('DNI DHI identity failed')
 return dni,dhi

def daily_delta_by_quantile(records,signal):
 days={};by_month=defaultdict(list)
 for d,k in enumerate(range(0,8760,24)):
  rows=records[k:k+24];m=int(rows[0][1]);day=(int(rows[0][1]),int(rows[0][2]));t=mean([float(r[6]) for r in rows]);days[day]=t;by_month[m].append((day,t))
 daily={}
 for m,day_temps in by_month.items():
  temps=sorted(t for _,t in day_temps)
  x=signal[m]['historical_daily_tas_sorted'];y=signal[m]['future_daily_tas_sorted'];raw={}
  for day,t in day_temps:
   q=(bisect.bisect_left(temps,t)+bisect.bisect_right(temps,t)-1)/(2*(len(temps)-1)) if len(temps)>1 else .5
   raw[day]=quantile(y,q)-quantile(x,q)
  adj=signal[m]['T_mean_delta_c']-mean(list(raw.values()))
  for day in raw:daily[day]=raw[day]+adj
 return daily

def morph_epw(headers,rows,signal,scenario,window,base_meta):
 year=int(rows[0][0]);lat,lon,tz=base_meta['epw_lat'],base_meta['epw_lon'],base_meta['epw_tz']
 old=rows;new=[r.copy() for r in rows];shift=daily_delta_by_quantile(old,signal)
 report=[];saturated=0;max_solar=0.;max_thermal_delta=0.;max_identity=0.;base_q=[];new_q=[]
 for day_idx in range(365):
  start=day_idx*24;source=old[start:start+24];dest=new[start:start+24];m=int(source[0][1]);d=int(source[0][2]);s=signal[m]
  day=date(year,m,d);geo=solar_geometry(day,lat,lon,tz)
  base_ghi=[float(r[13])/1000 for r in source];energy=sum(base_ghi)
  target=energy*s['solar_ghi_ratio'];caps=[t for c,t in geo]
  ghis=project_solar([g*s['solar_ghi_ratio'] for g in base_ghi],target,caps)
  max_solar=max(max_solar,abs(sum(ghis)-target));oldtemps=[float(r[6]) for r in source];tavg=mean(oldtemps)
  daily_sats=0
  for h,(r,row,g,geom) in enumerate(zip(source,dest,ghis,geo)):
   c,toa=geom;oldT=float(r[6]);newT=tavg+shift[(m,d)]+(oldT-tavg)*s['T_daily_range_ratio']
   if not -70<newT<70:raise ValueError('Future morph T outside EPW physical range')
   p=float(r[9]);q0=q_from_rh(oldT,float(r[8]),p);futureq=q0*s['specific_humidity_ratio'];rhraw=rh_from_q(newT,futureq,p)
   if rhraw>100:saturated+=1;daily_sats+=1
   rh=max(1.,min(100.,rhraw));dp=dewpoint_from_rh(newT,rh)
   if dp>newT+1e-7:raise ValueError('Dew point exceeds dry bulb')
   dni,dhi=split_ghi(g,c,toa)
   row[6]=f'{newT:.3f}';row[7]=f'{dp:.3f}';row[8]=f'{rh:.3f}'
   row[12]=f'{float(r[12])*s["longwave_ratio"]:.3f}'
   row[13]=f'{g*1000:.8f}';row[14]=f'{dni*1000:.8f}';row[15]=f'{dhi*1000:.8f}'
   row[21]=f'{float(r[21])*s["wind_speed_ratio"]:.3f}'
   row[33]=f'{float(r[33])*s["rainfall_amount_ratio"]:.5f}'
   for ix in EDIT_FIELDS:
    if not math.isfinite(float(row[ix])):raise ValueError('Nonfinite future EPW field')
   for ix in range(COLUMNS):
    if ix not in EDIT_FIELDS and row[ix]!=r[ix]:raise ValueError('Non-morphed baseline EPW field changed')
   if abs(g-dni*c-dhi)>1e-9:raise ValueError('Solar radiometric closure failed')
   max_identity=max(max_identity,abs(g-dni*c-dhi));max_thermal_delta=max(max_thermal_delta,abs(newT-oldT));base_q.append(q0);new_q.append(q_from_rh(newT,rh,p))
  report.append({'date':day.isoformat(),'base_epw_ghi_kwh_m2_day':energy,'monthly_gcm_ghi_multiplier':s['solar_ghi_ratio'],
      'morphed_epw_ghi_kwh_m2_day':sum(ghis),'expected_morphed_ghi_kwh_m2_day':target,
      'ghi_conservation_residual':sum(ghis)-target,'daily_T_shift_c':shift[(m,d)],
      'clipped_to_saturation_hours':daily_sats})
 h=[r.copy() for r in headers];h[0][4]='IGE_P7C1_RESEARCH_ONLY'
 h[5]=['COMMENTS 1',f'IGE P7C1 MORPHED from original EPW hour pattern: {MODEL} {scenario} {window}. Research-only; not observed future weather.']
 h[6]=['COMMENTS 2','Inherited baseline wind direction and wet event timing; missing baseline flags remain missing; GCM daily climatological deltas, not event-day pairing.']
 missing_counts={ix:sum(r[ix]==marker for r in new) for ix,marker in [(20,'999'),(22,'99'),(23,'99'),(24,'9999'),(28,'999')]}
 return h,new,report,{'max_daily_GHI_residual_kwh_m2':max_solar,'max_hourly_GHI_DNI_DHI_residual_kwh_m2':max_identity,
                      'max_hourly_T_shift_C':max_thermal_delta,'moisture_saturation_clipping_hours':saturated,
                      'baseline_mean_q':mean(base_q),'future_actual_mean_q':mean(new_q),
                      'missing_hours_by_epw_column':missing_counts, 'wind_direction_inherited_unchanged':True,
                      'precipitation_occurrence_inherited_unchanged':True,'rh_pressure_consistency_checked':True}

def write_epw(path,headers,rows):
 with open(path,'w',newline='',encoding='utf8') as f:
  w=csv.writer(f,lineterminator='\n');w.writerows(headers);w.writerows(rows)

def write_csv(path,rows):
 if not rows:raise ValueError('Empty report')
 with open(path,'w',newline='',encoding='utf8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(baseline,source_root,out,windows=WINDOWS):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 headers,rows,base_meta=read_epw(baseline)
 root=Path(source_root)
 historical,hprov=verify_model_dir(root/'P6_CanESM5_historical',HIST)
 report={'stage':'IGE_P7C1_EPW_BASED_FUTURE_MORPHING','version':'2026-10-11-research',
 'status':'SOURCE_AUDITED_STRUCTURAL_AND_CLIMATE_MORPH_RESEARCH_ONLY','production_epw_ready':False,
 'morph_not_independent_future_day_forecast':True,'CMIP6_native_noleap_20_year_windows':True,
 'baseline_is_real_measured_Graz_EPW':False,'baseline_type':('SYNTHETIC_P7B4_CANESM5_2013_NOT_METEONORM_CONTEMPORARY' if 'P7B4' in headers[0][4] else 'USER_SUPPLIED_EPW_SOURCE_REQUIRES_PROVENANCE'),
 'baseline':base_meta,'historical_source':hprov,'results':{},'remaining_failures_or_limits':[
 'A genuine original Graz-hour_contemporary_seed1.epw has not been source-audited in this pilot; substituted P7B4 synthetic 2013 EPW is only a reproducibility baseline' if 'P7B4' in headers[0][4] else 'User-provided baseline EPW provenance must be independently audited',
 'No independent future weather validation; historical hourly event patterns inherited',
 'Unknown wind-direction hours inherited from baseline: do not claim suitability for wind-driven natural ventilation where source directions are missing',
 'Rain event frequency and exact storm timing inherited; monthly rainfall amount only is morphed',
 'Missing sky cover, visibility and precipitable water remain missing',
 'Future pressure change not in original nine-variable daily NASA data, P7B4 standard-pressure proxy retained',
 'RH saturation clips simulated q change, quantitative loss explicitly recorded',
 'Erbs direct/diffuse partition is empirical, not measured independent DNI/DHI',
 'T daily quantile delta applies daily-mean source distribution to EPW daily means; diurnal amplitude ratio from GCM daily DTR',
 'No EnergyPlus building simulation or Meteonorm future truth benchmark',
 'No future scenario event-day matching. Each output retains its baseline EPW calendar year, not actual year 2050 or 2090.']}
 for window in windows:
  if window not in WINDOWS:raise ValueError('Unregistered climate window')
  future,fprov=verify_model_dir(root/f'P6_CanESM5_{window.replace("-","_")}',window)
  sig=monthly_signals(historical,future)
  h,r,daily,numeric=morph_epw(headers,rows,sig,window.split('-')[0],window,base_meta)
  stem=f'Graz_CanESM5_{window}_EPW_MORPH_P7C1_RESEARCH_ONLY'
  p=out/(stem+'.epw');write_epw(p,h,r)
  ph,pr,mt=read_epw(p)
  if len(pr)!=8760 or any(any(pr[i][ix]!=rows[i][ix] for ix in range(COLUMNS) if ix not in EDIT_FIELDS) for i in range(8760)):
   raise ValueError('Read-back EPW drift in untouched hourly fields')
  if max(abs(float(pr[i][13])-float(pr[i][14])*solar_geometry(date(base_meta['base_epw_year'],int(pr[i][1]),int(pr[i][2])),base_meta['epw_lat'],base_meta['epw_lon'],base_meta['epw_tz'])[int(pr[i][3])-1][0]-float(pr[i][15])) for i in range(8760))>1e-5:
   raise ValueError('Readback radiometric closure failed')
  detailed=[{'window':window,'month':m,**{k:v for k,v in s.items() if not k.endswith('_sorted')}} for m,s in sig.items()]
  month_csv=out/(stem+'_monthly_delta.csv');daily_csv=out/(stem+'_daily_audit.csv')
  write_csv(month_csv,detailed);write_csv(daily_csv,daily)
  report['results'][window]={'monthly_signals':detailed,'numeric':numeric,'source':fprov,
                             'files_sha256':{x.name:sha(x) for x in (p,month_csv,daily_csv)},
                             'source_8760_hours_preserved':True,'annual_mean_T_delta_morphed_c':mean([float(a[6])-float(b[6]) for a,b in zip(r,rows)]),
                             'base_annual_ghi_kwh_m2':sum(float(x[13]) for x in rows)/1000,
                             'future_annual_ghi_kwh_m2':sum(float(x[13]) for x in r)/1000}
 report['output_file_count']=len(list(out.glob('*.epw')))
 (out/'p7c1_source_science_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps({'output_file_count':report['output_file_count'],'metrics':{k: {'temperature_delta_c':v['annual_mean_T_delta_morphed_c'],'GHI_base_kwh_m2':v['base_annual_ghi_kwh_m2'],'GHI_future_kwh_m2':v['future_annual_ghi_kwh_m2'],'saturation_hours':v['numeric']['moisture_saturation_clipping_hours']} for k,v in report['results'].items()},'production_epw_ready':False},indent=2))
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--baseline-epw',required=True);p.add_argument('--source-root',required=True);p.add_argument('--out',required=True)
 opts=p.parse_args();run(opts.baseline_epw,opts.source_root,opts.out)