#!/usr/bin/env python3
"""Independent MeteoSwiss hourly psychrometric closure audit, *not* EPW synthesis.

Tests co-temporal T/RH/e/dewpoint/P and checks non-commutation of means;
raw station records are never exported; provider e/Td may be derived variables.
"""
from __future__ import annotations
import argparse,calendar,collections,csv,datetime,hashlib,io,json,math
from pathlib import Path
import numpy as np
from p8_1e_swiss_external import fetch,decode_csv,pick_col
from p8_2a_humidity import esat_water_hpa
from p8_2b_humidity import HOURLY_SITES,HOURLY_MONTHS,swiss_monthly,safe_number

ROOT='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn'

def dew_point_from_vapour(e):
    """Invert Buck (water) with monotone bisection, only meaningful for e>0."""
    if not .01<e<80:raise ValueError('Dewpoint inversion outside calibration range')
    lo,hi=-85.,65.
    for i in range(55):
        m=(lo+hi)/2
        if esat_water_hpa(m)<e:lo=m
        else:hi=m
    return (lo+hi)/2

def hourly_fields(raw,station,year,months):
    """Rows filtered before numerical processing, no leakage from other years."""
    decoded=raw.decode('utf-8-sig',errors='strict')
    reader=csv.DictReader(io.StringIO(decoded),delimiter=';')
    columns=reader.fieldnames or ()
    needed=('reference_timestamp','station_abbr','tre200h0','ure200h0','pva200h0','tde200h0','prestah0')
    if not set(needed).issubset(set(columns)):
        raise ValueError('Swiss hourly humidity schema lacks required fields: '+str(columns))
    out=collections.defaultdict(list);q=collections.Counter();seen=set()
    for row in reader:
        if row['station_abbr'].upper()!=station:continue
        timestamp=row['reference_timestamp']
        try:t=datetime.datetime.strptime(timestamp,'%d.%m.%Y %H:%M')
        except ValueError:q['invalid_datetime']+=1;continue
        if t.year!=year or (t.year,t.month) not in months:continue
        ident=(t.year,t.month,t.day,t.hour)
        if ident in seen:raise ValueError('Duplicate hourly UTC timestamp')
        seen.add(ident)
        vals={'T':safe_number(row['tre200h0'],-70,60),
              'RH':safe_number(row['ure200h0'],0,105),
              'e':safe_number(row['pva200h0'],.01,80),
              'Td':safe_number(row['tde200h0'],-90,60),
              'P':safe_number(row['prestah0'],450,1150)}
        if not all(vals[k] is not None for k in ('T','RH','e','Td','P')):
            q['missing_required_hour']+=1;continue
        if vals['e']>vals['P']:q['vapour_gt_atmospheric_pressure']+=1;continue
        out[(year,t.month)].append(vals)
    return out,dict(q)

def closure(rows):
    if not rows:raise ValueError('No hours to evaluate')
    errors=collections.defaultdict(list);invalid=collections.Counter()
    for r in rows:
        t,rh,e,td,p=(r[k] for k in ('T','RH','e','Td','P'))
        e_trh=esat_water_hpa(t)*rh/100
        e_td=esat_water_hpa(td)
        rh_ep=100*e/esat_water_hpa(t)
        dp_ep=dew_point_from_vapour(e)
        errors['e_from_T_RH_minus_e_hpa'].append(e_trh-e)
        errors['e_from_Td_minus_e_hpa'].append(e_td-e)
        errors['RH_from_e_T_minus_RH_pct'].append(rh_ep-rh)
        errors['Td_from_e_minus_Td_C'].append(dp_ep-td)
        if e>esat_water_hpa(t)*1.005:invalid['supersaturated_by_observed_e_T']+=1
        if rh_ep>100:invalid['derived_RH_above_100']+=1
        if rh_ep<0:invalid['derived_RH_below_0']+=1
    metrics={k:{'MAE':float(np.mean(np.abs(a))),'RMSE':float(np.sqrt(np.mean(np.asarray(a)**2))),
      'bias':float(np.mean(a)),'P95_abs':float(np.quantile(np.abs(a),.95))} for k,a in errors.items()}
    return metrics,dict(invalid)

def one_month(rows,monthly):
    x={k:float(np.mean([r[k] for r in rows])) for k in ('T','RH','e','Td','P')}
    hourly_rh_proxy=np.mean([100*r['e']/esat_water_hpa(r['T']) for r in rows])
    monthly_rh_proxy=100*x['e']/esat_water_hpa(x['T'])
    return {'hours_used':len(rows),'hourly_mean_e_hpa':x['e'],
       'hourly_mean_T_C':x['T'],'hourly_mean_RH_pct':x['RH'],
       'RH_from_monthly_mean_e_and_T_pct':monthly_rh_proxy,
       'mean_of_hourly_RH_from_e_and_T_pct':float(hourly_rh_proxy),
       'Jensen_gap_RH_pct':monthly_rh_proxy-float(hourly_rh_proxy),
       'provider_monthly_e_hpa':monthly.get('e') if monthly else None,
       'provider_monthly_RH_pct':monthly.get('RH') if monthly else None,
       'monthly_e_minus_mean_hourly_e_hpa':(monthly['e']-x['e']) if monthly and monthly['e'] is not None else None,
       'monthly_RH_minus_mean_hourly_RH_pct':(monthly['RH']-x['RH']) if monthly and monthly['RH'] is not None else None}

def run(out,sites=HOURLY_SITES,months=HOURLY_MONTHS):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=[];file_hashes=[];fail=[];quality=collections.Counter()
    for site in sites:
        raw,sha=fetch(f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_m.csv',max_bytes=20000000)
        monthly,monthly_qc=swiss_monthly(raw,site)
        file_hashes.append({'site':site,'type':'monthly','sha256':sha})
        for year in sorted({y for y,m in months}):
            decade='2010-2019' if year<=2019 else '2020-2029'
            url=f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_{decade}.csv'
            original,dig=fetch(url,max_bytes=30000000)
            file_hashes.append({'site':site,'type':'hourly','decade':decade,'sha256':dig,'bytes':len(original)})
            samples,qc=hourly_fields(original,site,year,months)
            quality.update(qc)
            for (y,mon),values in samples.items():
                expected=calendar.monthrange(y,mon)[1]*24
                fraction=len(values)/expected
                if fraction<.85:
                    fail.append({'site':site,'year':y,'month':mon,'reason':'less_than_85pct_complete_hours','n_hours':len(values),'expected':expected})
                    continue
                metric,invalid=closure(values)
                quality.update(invalid)
                summary=one_month(values,monthly.get(f'{y}-{mon:02d}'))
                rows.append({'site':site,'year':y,'month':mon,'valid_hours':len(values),'expected_hours':expected,
                             'completeness':fraction,'metrics':metric,'diagnostics':invalid,**summary})
    if len(rows)<4:raise RuntimeError('Insufficient real co-temporal psychrometric validation months '+str(len(rows)))
    # Publish aggregates, not timestamped or raw observed hourly values.
    aggregate={}
    for key in next(iter(rows))['metrics']:
        agg=[(r['valid_hours'],r['metrics'][key]) for r in rows]
        aggregate[key]={'weighted_MAE':sum(n*z['MAE'] for n,z in agg)/sum(n for n,z in agg),
                        'weighted_RMSE':math.sqrt(sum(n*z['RMSE']**2 for n,z in agg)/sum(n for n,z in agg)),
                        'weighted_bias':sum(n*z['bias'] for n,z in agg)/sum(n for n,z in agg)}
    outrows=[{k:v for k,v in r.items() if k not in ('metrics','diagnostics')} for r in rows]
    from p8_1b_temporal_holdout import save_csv
    save_csv(out/'psychrometric_months.csv',outrows)
    report={'phase':'P8.2B_HOURLY_PSYCHROMETRIC_CLOSURE','provider':'MeteoSwiss independent hourly T/RH/e/Td/P',
            'evaluated_months':len(rows),'n_valid_hourly_tuples':sum(r['valid_hours'] for r in rows),
            'hourly_aggregate':aggregate,'monthly_details':rows,'qc':dict(quality),
            'incomplete_months':fail,'source_hashes':file_hashes,
            'saturation_reference':'Buck 1981 liquid-water saturation for all T, intentional reference hypothesis',
            'reference_e_field':'pva200h0','reference_Td_field':'tde200h0',
            'provider_may_derive_e_or_Td_from_T_and_RH':True,
            'no_hourly_raw_observations_published':True,
            'no_forced_monthly_physical_closure':True,
            'limitations':['Hour T/RH/e/Td may not be sensor-independent; algebraic identity check, not full independent accuracy',
             'Differences between means from hourly data and published monthly means can reflect averaging conventions, coverage and QC',
             'No T/RH/e values from this hourly dataset enter spatial model training',
             'Monthly means need not obey instantaneous psychrometric equalities',
             'Only two Swiss stations/four months each; not a general EPW production guarantee']}
    (out/'hourly_closure_provenance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('IGE_P8_2B_HOURLY_CLOSURE',json.dumps({'n_months':len(rows),'n_hourly':report['n_valid_hourly_tuples'],'closure':aggregate,'qc':dict(quality),'monthly_jensen':[{'site':r['site'],'year':r['year'],'month':r['month'],'gap_RH_pct':r['Jensen_gap_RH_pct']} for r in rows]}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    args=p.parse_args();run(args.out)