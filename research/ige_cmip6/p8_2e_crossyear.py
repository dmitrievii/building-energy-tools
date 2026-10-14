#!/usr/bin/env python3
"""IGE P8.2E: frozen P8.2D model on independent Swiss 2018 & 2020 years.
Donor observed contemporaneous weather is allowed; no target T/P/e/RH/Td/monthly weather
in any predictor. This is retrospective spatial reconstruction, NOT advance forecasting.
Exports derived statistical metrics only; no provider time series, no fake complete EPW.
"""
from __future__ import annotations
import argparse,calendar,collections,csv,datetime as dt,hashlib,json,math,statistics
from pathlib import Path
import numpy as np
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2b_humidity import swiss_monthly,safe_number,train_austria_humidity
from p8_2c_hourly import reconcile_monthly,score
from p8_2a_humidity import esat_water_hpa
from p8_2b_hourly import dew_point_from_vapour

ROOT='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn'
YEAR=2019 # Preserves original P8.2D defaults; new API always passes explicit year.
TARGETS=('ABO','BER','PAY')
# Strict metadata-driven candidate list fixed before evaluating target observations.
POOL=('ABO','BER','PAY','BAS','DAV','LUG','GVE','SIO','SMA','WYN','ZER','CHD')
N_DONORS=4
METHODS=('constant','nearest_shape','half_multidonor_shape','full_multidonor_shape')
MONTHS=tuple(range(1,13))
RD=287.05
G=9.80665


def annual_hours(year=YEAR):
    # Keep ALL 8784 physical UTC hours for leap-year scientific scoring.
    start=dt.datetime(year,1,1)
    return [start+dt.timedelta(hours=i) for i in range(8784 if calendar.isleap(year) else 8760)]


def parse_swiss_year(raw,site,year=YEAR):
    """Read real-hour T/P/e/RH/Td for donors or evaluation. Timestamps are nominal MeteoSwiss UTC.
    Missing entries remain unavailable; no implicit infilling or duplicated timezone hours.
    """
    text=raw.decode('utf-8-sig',errors='strict')
    reader=csv.DictReader(text.splitlines(),delimiter=';')
    required={'station_abbr','reference_timestamp','tre200h0','prestah0','pva200h0','ure200h0','tde200h0'}
    if not required.issubset(reader.fieldnames or []):raise ValueError('SWISS_HOURLY_CONTRACT_CHANGED')
    rows={};q=collections.Counter()
    for r in reader:
        if r['station_abbr'].strip().upper()!=site:continue
        try:when=dt.datetime.strptime(r['reference_timestamp'],'%d.%m.%Y %H:%M')
        except ValueError:q['bad_timestamp']+=1;continue
        if when.year!=year:continue
        if when in rows:raise ValueError('DUPLICATE_SOURCE_HOUR '+site+' '+str(when))
        rows[when]={'T':safe_number(r['tre200h0'],-75,65),
           'P':safe_number(r['prestah0'],450,1150),
           'e':safe_number(r['pva200h0'],.001,80),
           'RH':safe_number(r['ure200h0'],0,105),
           'Td':safe_number(r['tde200h0'],-90,65)}
    return rows,dict(q)


def donor_set(target,all_sites,weather,monthly,min_donors=2,max_donors=N_DONORS,year=YEAR):
    """Site identity and donor availability only, never target meteorological values."""
    nearest=sorted(((float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
                   for s in all_sites.values() if s['station_id']!=target['station_id']
                   and s['station_id'] in weather and s['station_id'] in monthly),
                   key=lambda item:(item[0],item[1]['station_id']))
    eligible=[(dist,s) for dist,s in nearest if len(weather[s['station_id']])>=8000 and
                sum(monthly[s['station_id']].get(f'{year}-{m:02d}',{}).get('e') is not None for m in MONTHS)>=12]
    if len(eligible)<min_donors:raise ValueError('INSUFFICIENT_INDEPENDENT_DONOR_STATIONS')
    return eligible[:max_donors]


def hypsometric_pressure(donor_p_hpa,donor_t_c,dz_m):
    """Predict pressure by hypsometric reduction from donor altitude to target.
    Dry-temperature approximation only; tested directly on heldout target pressure.
    """
    p=float(donor_p_hpa);t=float(donor_t_c)
    if not(300<p<1150 and -75<t<65 and abs(dz_m)<5000):raise ValueError('Invalid hypsometric input')
    tm=t+273.15-G*dz_m/(2*1004.0)
    if tm<175:raise ValueError('Atmospheric layer temperature unrealistic')
    return p*math.exp(-G*dz_m/(RD*tm))


def weights(distances):
    d=np.asarray(distances,float)
    if not len(d) or np.any(~np.isfinite(d)) or np.any(d<0):raise ValueError('Invalid donor distances')
    w=1/np.maximum(d,.25)**2
    return w/w.sum()


def donor_month_datum(monthly,site,stamp):
    value=monthly[site][stamp]['e']
    if value is None or value<=0:raise ValueError('Missing monthly donor vapour')
    return value


def annual_predict(target,donors,hours,weather,monthly,loge_slopes,t_slopes, min_hourly_donors=2,year=YEAR):
    """Construct complete native 8760/8784 T/P/e/RH/Td from donor observations.

    No target observation is passed in the input collections. Per-hour donor fallback
    renormalizes weights across available donors, never fills target with its own data.
    Monthly target e is itself reconstructed from donor MONTHLY station series.
    """
    if len(hours)!=(8784 if calendar.isleap(year) else 8760) or len(set(hours))!=len(hours) or hours!=annual_hours(year):raise ValueError('Expected exact contiguous native UTC year')
    if target['station_id'] in weather or target['station_id'] in monthly:
        raise AssertionError('TARGET OBSERVATIONS PRESENT IN RECONSTRUCTION INPUT')
    if len(donors)<min_hourly_donors:raise ValueError('Insufficient donors')
    if any(s['station_id']==target['station_id'] for d,s in donors):raise AssertionError('TARGET IN DONOR SET')
    t=[];p=[];shape=[];month_targets={};counts=collections.Counter();used=set()
    # One calibration shared by all predictions, fitted to Austria 1991-2010.
    for month in MONTHS:
        stamp=f'{year}-{month:02d}'
        available=[(d,s) for d,s in donors if stamp in monthly.get(s['station_id'],{})
                   and monthly[s['station_id']][stamp].get('e') is not None]
        if len(available)<min_hourly_donors:raise ValueError('MISSING_MONTHLY_DONORS '+stamp)
        w=weights([d for d,s in available]);z=target['hoehe_m']
        vals=np.array([math.log(donor_month_datum(monthly,s['station_id'],stamp))+
                       loge_slopes[month-1]*(z-s['hoehe_m']) for d,s in available])
        month_targets[month]=float(math.exp(w@vals))
    for when in hours:
        available=[]
        stamp=f'{when.year}-{when.month:02d}'
        for distance,s in donors:
            row=weather.get(s['station_id'],{}).get(when)
            if row is None or any(row.get(k) is None for k in ('T','P','e')):continue
            if stamp not in monthly.get(s['station_id'],{}) or monthly[s['station_id']][stamp].get('e') is None:continue
            available.append((distance,s,row))
        if len(available)<min_hourly_donors:
            raise ValueError('NO_INDEPENDENT_HOURLY_DONOR_COVERAGE '+when.isoformat())
        w=weights([d for d,s,r in available]);z=target['hoehe_m']
        t.append(float(w@np.array([r['T']+t_slopes[when.month-1]*(z-s['hoehe_m']) for d,s,r in available])))
        p.append(float(w@np.array([hypsometric_pressure(r['P'],r['T'],z-s['hoehe_m']) for d,s,r in available])))
        shape.append(float(math.exp(w@np.log([r['e']/donor_month_datum(monthly,s['station_id'],stamp)
                                                for d,s,r in available]))))
        for d,s,r in available:used.add(s['station_id'])
        counts[len(available)]+=1
    t=np.asarray(t);p=np.asarray(p);shape=np.asarray(shape)
    if not np.isfinite(t).all() or not np.isfinite(p).all():raise AssertionError('Not physical annual T/P')
    result={n:{'T':t.copy(),'P':p.copy(),'e':np.zeros(len(hours)),
               'RH':np.zeros(len(hours)),'Td':np.zeros(len(hours))} for n in METHODS}
    month_diag=[]
    for mon in MONTHS:
        indexes=[i for i,stamp in enumerate(hours) if stamp.month==mon]
        t0=t[indexes];p0=p[indexes];a=shape[indexes]
        shapes={'constant':np.ones(len(indexes)),'nearest_shape':a, # nearest_shape generated below if requested
                'half_multidonor_shape':np.sqrt(a),'full_multidonor_shape':a}
        # nearest donor is fixed in metadata order (and available at every hour)
        nearest=donors[0][1]['station_id']
        near=[]
        for i in indexes:
            r=weather.get(nearest,{}).get(hours[i]);d=monthly[nearest][f'{year}-{mon:02d}']['e']
            if r is None or r.get('e') is None:
                # No interpolated or substituted donor shape; mark its candidate unavailable.
                near=None;break
            near.append(r['e']/d)
        if near is not None:shapes['nearest_shape']=np.asarray(near)
        else:shapes.pop('nearest_shape')
        for name,sh in shapes.items():
            e=reconcile_monthly(month_targets[mon],sh,t0,p0)
            rh=np.asarray([100*v/esat_water_hpa(temp) for v,temp in zip(e,t0)])
            td=np.asarray([dew_point_from_vapour(float(v)) for v in e])
            result[name]['e'][indexes]=e
            result[name]['RH'][indexes]=rh
            result[name]['Td'][indexes]=td
            if np.any(td>t0+1e-7) or np.any(rh>100+1e-7) or np.any(e>=p0):
                raise AssertionError('CROSS_VARIABLE_PHYSICAL_CLOSURE_FAILURE')
        month_diag.append({'month':mon,'reconstructed_e_mean_hpa':month_targets[mon],
                           'predicted_month_T_C':float(t0.mean()),'predicted_month_P_hpa':float(p0.mean()),
                           'hourly_valid_donors_min':int(min(counts))})
    for name,v in result.items():
        if np.any(v['e']<=0) or np.any(v['RH']<=0) or np.any(~np.isfinite(v['RH'])):
            raise ValueError('INCOMPLETE_ANNUAL_HUMIDITY_FOR_'+name)
    return result,{'monthly':month_diag,'n_hours':len(hours),
                   'donor_hour_availability':dict(counts),'used_donor_ids':sorted(used),
                   'target_meteorology_read_for_prediction':False}


def evaluate(target_obs,by_method,hours,site,year=YEAR):
    """The ONLY function allowed to see observations from the held-out station."""
    indices=[i for i,stamp in enumerate(hours) if stamp in target_obs and all(target_obs[stamp].get(k) is not None for k in ('T','P','e','RH','Td'))]
    if len(indices)<.80*len(hours):raise ValueError('Insufficient qualified target hours for a meaningful annual audit')
    rows=[];bysite=[]
    for method,pred in by_method.items():
        for variable,unit in [('T','C'),('P','hPa'),('e','hPa'),('RH','pp'),('Td','C')]:
            reference=np.asarray([target_obs[hours[i]][variable] for i in indices]);estimate=pred[variable][indices]
            s=score(estimate,reference)
            rows.append({'site':site,'method':method,'variable':variable,'unit':unit,**s})
        for month in MONTHS:
            ix=[i for i in indices if hours[i].month==month]
            if len(ix)<.7*calendar.monthrange(year,month)[1]*24:continue
            e_p=pred['e'][ix];rh_p=pred['RH'][ix];e_o=np.array([target_obs[hours[i]]['e'] for i in ix]);rh_o=np.array([target_obs[hours[i]]['RH'] for i in ix])
            bysite.append({'site':site,'method':method,'month':month,'n_hours':len(ix),
                           'MAE_e_hpa':float(np.mean(np.abs(e_p-e_o))),
                           'MAE_RH_pp':float(np.mean(np.abs(rh_p-rh_o))),
                           'bias_e_hpa':float((e_p-e_o).mean()),
                           'observed_RH_ge90_fraction':float(np.mean(rh_o>=90)),
                           'predicted_RH_ge90_fraction':float(np.mean(rh_p>=90)),
                           'observed_RH_lt30_fraction':float(np.mean(rh_o<30)),
                           'predicted_RH_lt30_fraction':float(np.mean(rh_p<30))})
    return rows,bysite,len(indices)


def epw_humidity_patch(headers,records,year,hourly,expected_site,actual_year=True):
    """Only patch 4 known EPW columns of a REAL SOURCE BASELINE; never invent other fields.
    No actual Swiss EPW baseline is supplied in P8.2D. This is tested with synthetic
    structural fixtures but invoked on real data only when upstream EPW is provided.
    """
    if len(headers)!=8 or len(records)!=8760 or any(len(r)!=35 for r in records):raise ValueError('Missing complete 35-field EPW')
    if headers[0][0]!='LOCATION' or headers[7][0]!='DATA PERIODS' or len(headers[0])<10:
        raise ValueError('EPW header identity invalid')
    if (abs(float(headers[0][6])-float(expected_site['lat']))>0.001 or
        abs(float(headers[0][7])-float(expected_site['lon']))>0.001 or
        abs(float(headers[0][9])-float(expected_site['hoehe_m']))>5):
        raise ValueError('EPW site latitude longitude altitude mismatch')
    if not actual_year or calendar.isleap(year):raise ValueError('Unverified annual EPW year')
    dates=annual_hours(year)
    new=[]
    for i,(r,stamp) in enumerate(zip(records,dates)):
        if [int(x) for x in r[:5]]!=[year,stamp.month,stamp.day,stamp.hour+1,60]:
            raise ValueError('EPW_CALENDAR_MISMATCH')
        v=r.copy()
        for idx,field in ((6,'T'),(7,'Td'),(8,'RH'),(9,'P')):
            v[idx]=f'{hourly[field][i]:.5f}' if idx!=9 else f'{hourly[field][i]*100:.2f}'
        if any(v[j]!=r[j] for j in range(35) if j not in (6,7,8,9)):
            raise AssertionError('EPW non-humidity meteorology changed')
        new.append(v)
    return new


def save_csv(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf8') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)




def epw_hour_map(utc_hours,year,timezone_hours=1):
    """SwissMetNet h timestamp=end-of-hour UTC; EPW hour 1..24=end-of-hour LOCAL STANDARD.

    Standard CET is UTC+1, invariant in summer. 2020 Feb 29 is deleted only
    from an optional 8760-hour TMY representation, not from physical scoring.
    Local-standard midnight is EPW previous date hour 24.
    """
    if timezone_hours!=1:raise ValueError('Swiss EPW mapping requires fixed CET UTC+1')
    if utc_hours!=annual_hours(year):raise ValueError('Incomplete/duplicate UTC source hour sequence')
    mapping=[]
    for i,utc in enumerate(utc_hours):
        local_end=utc+dt.timedelta(hours=timezone_hours)
        if local_end.hour==0:
            stamp_date=(local_end-dt.timedelta(days=1)).date()
            hour=24
        else:stamp_date=local_end.date();hour=local_end.hour
        if stamp_date.year!=year:raise ValueError('EPW boundary mismatch')
        if stamp_date.month==2 and stamp_date.day==29:continue
        mapping.append({'native_utc_index':i,'year':year,'month':stamp_date.month,
                        'day':stamp_date.day,'epw_hour':hour,'minute':60})
    if len(mapping)!=8760:raise AssertionError('EPW needs 8760 data hours')
    if len({(r['month'],r['day'],r['epw_hour']) for r in mapping})!=8760:
        raise AssertionError('EPW repeated/missing local standard hour')
    return mapping



def epw_humidity_payload(utc_hours,year,pred):
    """Ordered EPW humidity-only values; refuses incomplete/invalid physical state.

    These are NOT stand-alone weather EPW files: other 31 weather columns need
    independent measured or validated model sources and identity/time auditing.
    """
    mapped=epw_hour_map(utc_hours,year)
    fields=('T','Td','RH','P')
    n=len(utc_hours)
    if not all(k in pred and len(pred[k])==n for k in fields):
        raise ValueError('Incomplete annual humidity EPW payload')
    output=[]
    for r in mapped:
        i=r['native_utc_index']
        t,td,rh,p=(float(pred[k][i]) for k in fields)
        if not all(map(math.isfinite,(t,td,rh,p))) or not -80<t<70 or not -90<td<=t+1e-7 or not 0<rh<=100.000001 or not 300<p<1150:
            raise ValueError('Invalid hourly humidity EPW physical state')
        output.append({**r,'drybulb_C':t,'dewpoint_C':td,'RH_percent':rh,'station_pressure_Pa':p*100.})
    return output


def patch_epw_with_verified_base(headers,records,year,epw_payload,lat,lon,altitude_m,timezone_hours=1):
    """No synthesized solar, wind, precipitation or other placeholder EPW data.

    EPW base must have verified site identity, 35 fields, 8760 fixed-standard
    hours; all fields except drybulb/Td/RH/P are byte-for-byte preserved.
    """
    if timezone_hours!=1:raise ValueError('Expected fixed Swiss standard CET UTC+1')
    if len(headers)!=8 or len(records)!=8760 or len(epw_payload)!=8760 or any(len(r)!=35 for r in records):
        raise ValueError('Complete verified 8760-hour 35-column baseline required')
    h=headers[0]
    if h[0]!='LOCATION' or len(h)<10 or headers[7][0]!='DATA PERIODS':
        raise ValueError('EPW header invalid')
    if abs(float(h[6])-lat)>.001 or abs(float(h[7])-lon)>.001 or abs(float(h[8])-timezone_hours)>1e-6 or abs(float(h[9])-altitude_m)>5:
        raise ValueError('EPW baseline location/timezone/altitude mismatch')
    out=[]
    for source,v in zip(records,epw_payload):
        if [int(a) for a in source[:5]]!=[year,v['month'],v['day'],v['epw_hour'],60]:
            raise ValueError('EPW hourly local standard calendar mismatch')
        row=source.copy()
        row[6]=f"{v['drybulb_C']:.4f}";row[7]=f"{v['dewpoint_C']:.4f}"
        row[8]=f"{v['RH_percent']:.3f}";row[9]=f"{v['station_pressure_Pa']:.1f}"
        if any(source[k]!=row[k] for k in range(35) if k not in (6,7,8,9)):
            raise AssertionError('EPW unrelated weather content changed')
        out.append(row)
    return out

def spell_metrics(timestamps,values,threshold,high,min_len=6):
    """Missing hours break spells; never bridge gaps in observed coverage."""
    if len(timestamps)!=len(values):raise ValueError('Event axis mismatch')
    if len(timestamps)!=len(set(timestamps)):raise ValueError('Duplicate scored hours')
    spells=[];current=0;previous=None;hits=0
    for hour,value in zip(timestamps,values):
        is_event=(float(value)>=threshold if high else float(value)<threshold)
        if previous is not None and hour-previous!=dt.timedelta(hours=1):
            if current:spells.append(current)
            current=0
        if is_event:current+=1;hits+=1
        else:
            if current:spells.append(current)
            current=0
        previous=hour
    if current:spells.append(current)
    return {'fraction':hits/len(values) if values is not None and len(values) else None,
            'n_event_hours':hits,'n_spells':len(spells),
            'n_spells_ge6h':sum(n>=min_len for n in spells),
            'n_spells_ge12h':sum(n>=12 for n in spells),
            'longest_spell_h':max(spells,default=0),
            'spell_length_p90_h':float(np.quantile(spells,.9)) if spells else 0.}


def extreme_skill(target_obs,pred,hours,site,year,method):
    """Same target-qualified hours and method predictions, no tuning on extremes."""
    stamps=[h for h in hours if h in target_obs and target_obs[h].get('RH') is not None]
    if len(stamps)<.8*len(hours):raise ValueError('Not enough humidity-event reference hours')
    oi=np.array([target_obs[h]['RH'] for h in stamps]);idx={h:i for i,h in enumerate(hours)}
    pi=np.array([pred['RH'][idx[h]] for h in stamps]);rows=[]
    for regime,threshold,high in (('wet_rh_ge90',90.,True),('dry_rh_lt30',30.,False)):
        obs_event=oi>=threshold if high else oi<threshold
        pred_event=pi>=threshold if high else pi<threshold
        tp=int((obs_event&pred_event).sum());fp=int((~obs_event&pred_event).sum());fn=int((obs_event&~pred_event).sum())
        obs=spell_metrics(stamps,oi,threshold,high);predict=spell_metrics(stamps,pi,threshold,high)
        rows.append({'site':site,'year':year,'method':method,'regime':regime,'n_hours':len(stamps),
           'observed_rate':obs['fraction'],'predicted_rate':predict['fraction'],
           'frequency_bias_pp':100*(predict['fraction']-obs['fraction']),
           'TP':tp,'FP':fp,'FN':fn,
           'precision':tp/(tp+fp) if tp+fp else None,
           'recall':tp/(tp+fn) if tp+fn else None,
           'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
           'csi':tp/(tp+fp+fn) if tp+fp+fn else None,
           'observed_spells_ge6h':obs['n_spells_ge6h'],
           'predicted_spells_ge6h':predict['n_spells_ge6h'],
           'observed_spells_ge12h':obs['n_spells_ge12h'],
           'predicted_spells_ge12h':predict['n_spells_ge12h'],
           'observed_longest_spell_h':obs['longest_spell_h'],
           'predicted_longest_spell_h':predict['longest_spell_h']})
    return rows


def run_year(out,normals,year,targets=TARGETS,calibration=None):
    """Re-evaluate FROZEN P8.2D architecture on new years; target data for scoring only."""
    if year not in (2018,2020):raise ValueError('P8.2E holdout years pre-registered as 2018/2020')
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    rawmeta,metasha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    meta,_=parse_meta(rawmeta)
    if not set(targets).issubset(meta):raise ValueError('Missing evaluation site')
    selected={sid:meta[sid] for sid in POOL if sid in meta}
    hours=annual_hours(year);mapped=epw_hour_map(hours,year)
    w={};monthly={};hashes=[];fail=[]
    dec='2020-2029' if year>=2020 else '2010-2019'
    for sid in selected:
        try:
            raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_{dec}.csv',max_bytes=37000000)
            w[sid],qc=parse_swiss_year(raw,sid,year)
            hashes.append({'station':sid,'type':'hourly','sha256':sha,'n_hours':len(w[sid]),'qc':qc})
            b,digest=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid]=swiss_monthly(b,sid)[0]
            hashes.append({'station':sid,'type':'monthly','sha256':digest,'bytes':len(b)})
        except Exception as e:fail.append({'site':sid,'kind':type(e).__name__,'reason':str(e)[:210]})
    loge,tslopes,cal=(calibration if calibration is not None else train_austria_humidity(normals))
    aggregates=[];monthrows=[];eventrows=[];coverage=[]
    for target in targets:
        if target not in w:raise RuntimeError('Missing target scoring data '+target)
        safe_weather={k:v for k,v in w.items() if k!=target}
        safe_month={k:v for k,v in monthly.items() if k!=target}
        try:
            donors=donor_set(meta[target],selected,safe_weather,safe_month,year=year)
            pred,diag=annual_predict(meta[target],donors,hours,safe_weather,safe_month,loge,tslopes,year=year)
            stationrows,months,n=evaluate(w[target],pred,hours,target,year=year)
            for method,series in pred.items():
                eventrows.extend(extreme_skill(w[target],series,hours,target,year,method))
        except (ValueError,AssertionError) as e:
            fail.append({'site':target,'kind':type(e).__name__,'reason':str(e)[:350]})
            continue
        aggregates.extend([{**r,'year':year} for r in stationrows]);monthrows.extend([{**r,'year':year} for r in months])
        coverage.append({'site':target,'year':year,'n_source_utc_hours':len(hours),'n_predicted_hours':diag['n_hours'],
           'n_scored_hours':n,'donors':[s['station_id'] for d,s in donors],
           'monthly_targets':diag['monthly'],'donor_hour_availability':diag['donor_hour_availability']})
    if len(coverage)!=len(targets):raise RuntimeError('NOT_ALL_FROZEN_TARGETS_QUALIFIED '+str(fail))
    for name,items in [('annual_site_skill.csv',aggregates),('monthly_skill.csv',monthrows),('event_extremes.csv',eventrows)]:
        save_csv(dest/name,items)
    rollup=[]
    for method in METHODS:
        for var in ('T','P','e','RH','Td'):
            ar=[x for x in aggregates if x['method']==method and x['variable']==var]
            n=sum(x['n'] for x in ar)
            rollup.append({'year':year,'method':method,'variable':var,'n_hours':n,
              'MAE':sum(x['MAE']*x['n'] for x in ar)/n,
              'RMSE':math.sqrt(sum(x['RMSE']**2*x['n'] for x in ar)/n),
              'bias':sum(x['bias']*x['n'] for x in ar)/n})
    save_csv(dest/'annual_aggregate.csv',rollup)
    report={'stage':'P8.2E','year':year,'scientific_status':'SCIENTIFIC_VALIDATION_NOT_PRODUCTION',
      'source':'Original MeteoSwiss SwissMetNet UTC hourly end-of-interval data',
      'n_native_utc_hours':len(hours),'n_epw_mappable_hours_after_2020_leap_filter':len(mapped),
      'epw_time_rule':'MeteoSwiss hourly timestamp is END of measurement interval UTC, +1h fixed CET (no DST), EPW 1..24 is local END hour; Feb29 removed for synthetic 8760 only',
      'epw_start_map':mapped[0],'epw_end_map':mapped[-1],
      'source_digest':hashes,'station_metadata_sha256':metasha,'original_source_failures':fail,
      'pretrained_Austria_1991_2010':cal,'coverage':coverage,'aggregate':rollup,
      'no_target_data_used_in_training_or_prediction':True,
      'scoring_targets_only_for_evaluation':True,
      'weather_donors_are_contemporaneous':True,
      'leap_2020_observations_scored_all_8784_hours':year==2020,
      'no_weather_epw_written_without_source_complete_epw':True,
      'raw_observed_hourly_not_published':True,
      'caveats':['2018 MeteoSwiss hourly averages follow current post-2018 aggregation; earlier years can differ',
        'EPW 8760 leap-day omission is only for synthetic typical-year payload, not actual-year EnergyPlus EPW',
        'All wet/dry event metrics are evaluated on identical valid target-observation hours',
        'Three Swiss stations/two years, not worldwide cross-regime validation',
        'No solar/wind/precipitation independently supplied; no complete EPW published',
        'Comparisons to 2019 are post hoc research generalization; no model hyperparameter selection allowed']}
    (dest/'crossyear_provenance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('IGE_P8_2E_YEAR_RESULT',json.dumps({'year':year,'coverage':[{k:v for k,v in row.items() if k!='monthly_targets'} for row in coverage],
        'summary':rollup,'events':eventrows,'failures':fail},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    p.add_argument('--austria-station-normals',required=True);p.add_argument('--year',type=int,required=True)
    args=p.parse_args();run_year(args.out,args.austria_station_normals,args.year)