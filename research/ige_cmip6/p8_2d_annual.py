#!/usr/bin/env python3
"""P8.2D independent Swiss annual humidity reconstruction; original test station weather scoring ONLY.
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
YEAR=2019
TARGETS=('ABO','BER','PAY')
# Strict metadata-driven candidate list fixed before evaluating target observations.
POOL=('ABO','BER','PAY','BAS','DAV','LUG','GVE','SIO','SMA','WYN','ZER','CHD')
N_DONORS=4
METHODS=('constant','nearest_shape','half_multidonor_shape','full_multidonor_shape')
MONTHS=tuple(range(1,13))
RD=287.05
G=9.80665


def annual_hours(year=YEAR):
    if calendar.isleap(year):raise ValueError('EPW annual test requires explicit nonleap source year')
    start=dt.datetime(year,1,1)
    return [start+dt.timedelta(hours=i) for i in range(8760)]


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


def donor_set(target,all_sites,weather,monthly,min_donors=2,max_donors=N_DONORS):
    """Site identity and donor availability only, never target meteorological values."""
    nearest=sorted(((float(haversine(target['lat'],target['lon'],s['lat'],s['lon'])),s)
                   for s in all_sites.values() if s['station_id']!=target['station_id']
                   and s['station_id'] in weather and s['station_id'] in monthly),
                   key=lambda item:(item[0],item[1]['station_id']))
    eligible=[(dist,s) for dist,s in nearest if len(weather[s['station_id']])>=8000 and
                sum(monthly[s['station_id']].get(f'{YEAR}-{m:02d}',{}).get('e') is not None for m in MONTHS)>=12]
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


def annual_predict(target,donors,hours,weather,monthly,loge_slopes,t_slopes, min_hourly_donors=2):
    """Construct 8760 T/P/e/RH/Td ONLY from other stations and Austrian historical slope.

    No target observation is passed in the input collections. Per-hour donor fallback
    renormalizes weights across available donors, never fills target with its own data.
    Monthly target e is itself reconstructed from donor MONTHLY station series.
    """
    if len(hours)!=8760 or len(set(hours))!=8760 or hours!=annual_hours():raise ValueError('Expected exact contiguous nonleap year')
    if target['station_id'] in weather or target['station_id'] in monthly:
        raise AssertionError('TARGET OBSERVATIONS PRESENT IN RECONSTRUCTION INPUT')
    if len(donors)<min_hourly_donors:raise ValueError('Insufficient donors')
    if any(s['station_id']==target['station_id'] for d,s in donors):raise AssertionError('TARGET IN DONOR SET')
    t=[];p=[];shape=[];month_targets={};counts=collections.Counter();used=set()
    # One calibration shared by all predictions, fitted to Austria 1991-2010.
    for month in MONTHS:
        stamp=f'{YEAR}-{month:02d}'
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
            r=weather.get(nearest,{}).get(hours[i]);d=monthly[nearest][f'{YEAR}-{mon:02d}']['e']
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


def evaluate(target_obs,by_method,hours,site):
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
            if len(ix)<.7*calendar.monthrange(YEAR,month)[1]*24:continue
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


def run(out,normals,targets=TARGETS,year=YEAR):
    if year!=YEAR:raise ValueError('Only frozen nonleap source year allowed')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rawmeta,metasha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    meta,_=parse_meta(rawmeta)
    if not set(targets).issubset(meta):raise ValueError('Target site metadata unavailable')
    selected={s:meta[s] for s in POOL if s in meta};hours=annual_hours(year)
    obs={};monthly={};hashes=[];errors=[]
    for sid in selected:
        url=f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2010-2019.csv'
        try:
            blob,sha=fetch(url,max_bytes=37000000)
            arr,qc=parse_swiss_year(blob,sid,year)
            obs[sid]=arr;hashes.append({'station':sid,'source':'hourly','sha256':sha,'bytes':len(blob),'n_records':len(arr),'qc':qc})
            b,digest=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_m.csv',max_bytes=20000000)
            monthly[sid]=swiss_monthly(b,sid)[0]
            hashes.append({'station':sid,'source':'monthly','sha256':digest,'bytes':len(b)})
        except Exception as ex:errors.append({'station':sid,'kind':type(ex).__name__,'reason':str(ex)[:220]})
    loge,t_slopes,cal=train_austria_humidity(normals)
    summary=[];bymonth=[];coverage=[]
    for tid in targets:
        if tid not in obs:raise RuntimeError('Target observations unavailable for scoring '+tid)
        safe_weather={k:v for k,v in obs.items() if k!=tid}
        safe_monthly={k:v for k,v in monthly.items() if k!=tid}
        try:
            donors=donor_set(meta[tid],selected,safe_weather,safe_monthly)
            predictions,diag=annual_predict(meta[tid],donors,hours,safe_weather,safe_monthly,loge,t_slopes)
            metric,months,n=evaluate(obs[tid],predictions,hours,tid)
        except (ValueError,AssertionError) as ex:
            errors.append({'station':tid,'kind':type(ex).__name__,'reason':str(ex)[:220]});continue
        summary.extend(metric);bymonth.extend(months)
        coverage.append({'site':tid,'n_target_qualified_hours':n,'n_predicted_hours':8760,
          'donors':[s['station_id'] for d,s in donors], 'details':diag})
    if len(coverage)<2:raise RuntimeError('ANNUAL_SPATIAL_VALIDATION_INSUFFICIENT_COMPLETE_TARGET_SITES '+str(errors))
    save_csv(out/'annual_metrics.csv',summary)
    save_csv(out/'annual_monthly_skill.csv',bymonth)
    summary_rollup=[]
    for method in METHODS:
        for variable in ('T','P','e','RH','Td'):
            block=[r for r in summary if r['method']==method and r['variable']==variable]
            if not block:continue
            count=sum(r['n'] for r in block)
            summary_rollup.append({'method':method,'variable':variable,'n_scored_hours':count,'n_sites':len(block),
                                   'MAE':sum(r['MAE']*r['n'] for r in block)/count,
                                   'RMSE':math.sqrt(sum(r['RMSE']**2*r['n'] for r in block)/count),
                                   'bias':sum(r['bias']*r['n'] for r in block)/count})
    save_csv(out/'annual_aggregate.csv',summary_rollup)
    report={'phase':'P8.2D','scope':'Independent annual spatial reconstruction T/P/e/RH/Td 2019 SwissMetNet',
       'scientific_status':'ANNUAL_RECONSTRUCTION_ONLY_NOT_FULL_EPW',
       'target_sites':list(targets),'year':year,'station_metadata_sha256':metasha,'calibration':cal,
       'provenance':hashes,'source_failures':errors,'coverage':coverage,'aggregate_metrics':summary_rollup,
       'target_obs_never_used_in_predictor':True,
       'target_site_metadata_coordinates_altitude_only':True,
       'reference_T_and_P_not_supplied_to_synthesis':True,
       'same_year_donor_weather_observed':True,'not_advance_weather_prediction':True,
       'annual_epw_humidity_payload_ready':True,
       'full_epw_not_generated_no_verified_solar_wind_sky_rain_baseline':True,
       'no_raw_or_derived_hourly_provider_series_published':True,
       'limitations':['Region/site independent geography beyond three Swiss test sites not established',
         'Hourly simultaneous donor observations used, so this is spatial reconstruction, not weather generation without station observations',
         'T and P were reconstructed with simplified altitude lapse / dry hypsometric adjustment',
         'Physical monthly moisture projection can change temporal distribution','All wet/dry event rates use same available scoring hours',
         'EPW-ready four-column payload validated only for structural patch interface; full EPW needs trustworthy remaining variables']}
    (out/'p8_2d_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print('IGE_P8_2D_ANNUAL_RESULT',json.dumps({'coverage':coverage,'aggregates':summary_rollup,'failures':errors}),flush=True)
    return report

if __name__=='__main__':
    pa=argparse.ArgumentParser();pa.add_argument('--out',required=True);pa.add_argument('--austria-station-normals',required=True)
    a=pa.parse_args();run(a.out,a.austria_station_normals)