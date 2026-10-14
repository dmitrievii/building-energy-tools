#!/usr/bin/env python3
"""IGE P8.2C: conditional hourly vapour synthesis and pointwise physical closure.

Target published monthly vapour pressure, target hourly T and P are GIVEN
boundary conditions. Target hourly vapour, RH and Td must never enter synthesis.
Hourly donor vapour patterns are spatially transferred without fitting on the
heldout station. This is conditional downscaling, NOT end-to-end EPW weather
forecasting. Original MeteoSwiss observations are read transiently, not exported.
"""
from __future__ import annotations
import argparse,calendar,collections,csv,datetime as dt,hashlib,io,json,math
from pathlib import Path
import numpy as np
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2b_humidity import swiss_monthly,safe_number
from p8_2a_humidity import esat_water_hpa
from p8_2b_hourly import dew_point_from_vapour

ROOT='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn'
SITES=('ABO','BER','PAY')
MONTHS=((2019,1),(2019,7),(2020,1),(2020,7))
METH=('constant_e','donor_shape_half','donor_shape_full')
MIN_COMPLETENESS=.85
MAX_PRESSURE_FRACTION=.98
EPS=1.e-6

def parse_hourly(raw,site,year,months):
    rd=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter=';')
    expected={'station_abbr','reference_timestamp','tre200h0','prestah0','pva200h0','ure200h0','tde200h0'}
    if not expected.issubset(set(rd.fieldnames or [])):raise ValueError('MeteoSwiss required hourly schema changed')
    out=collections.defaultdict(dict);qc=collections.Counter()
    for row in rd:
        if row['station_abbr'].strip().upper()!=site:continue
        stamp=row['reference_timestamp']
        try:date=dt.datetime.strptime(stamp,'%d.%m.%Y %H:%M')
        except ValueError:qc['invalid_date']+=1;continue
        if date.year!=year or (date.year,date.month) not in months:continue
        key=(date.year,date.month)
        if date in out[key]:raise ValueError('Duplicate target/donor hourly timestamp')
        out[key][date]={'T':safe_number(row['tre200h0'],-75,65),
                        'P':safe_number(row['prestah0'],450,1150),
                        'e':safe_number(row['pva200h0'],EPS,80),
                        'RH':safe_number(row['ure200h0'],0,105),
                        'Td':safe_number(row['tde200h0'],-90,65)}
    return out,dict(qc)

def capacity(T,P):
    t=np.asarray(T,float);p=np.asarray(P,float)
    if t.shape!=p.shape or t.ndim!=1 or not len(t) or not np.isfinite(t).all() or not np.isfinite(p).all() or np.any(p<=200):raise ValueError('Invalid hourly T/P boundary')
    return np.minimum(np.array([esat_water_hpa(v) for v in t]),MAX_PRESSURE_FRACTION*p)

def reconcile_monthly(target_mean,relative_shape,T,P,atol=1e-8):
    """Monotone scalar water-filling: mean(min(scale *shape, e_sat(T), 0.98P)) = mean_e.

    Each predicted e is physically valid. If target mean cannot be attained due to
    saturated-hour capacity or an invalid shape, fail closed, do not clip silently.
    """
    shape=np.asarray(relative_shape,float); cap=capacity(T,P)
    if shape.shape!=cap.shape or np.any(~np.isfinite(shape)) or np.any(shape<=0):raise ValueError('Nonpositive/infinite donor moisture shape')
    goal=float(target_mean)
    if not math.isfinite(goal) or goal<=EPS:raise ValueError('Unphysical monthly vapour pressure')
    if goal>float(cap.mean())+atol:raise ValueError('INFEASIBLE_MONTHLY_MEAN_UNDER_HOURLY_SATURATION')
    # Avoid huge scaling / nonterminating loops if near saturation; exact feasibility
    # is enforced after the root search.
    lo,hi=0.,max(2*goal/float(np.mean(shape)),EPS)
    for _ in range(90):
        if np.minimum(hi*shape,cap).mean()>=goal-atol:break
        hi*=2
    else:raise ValueError('MONTHLY_MASS_ROOT_NOT_BRACKETED')
    for _ in range(90):
        mid=(lo+hi)/2.
        if np.minimum(mid*shape,cap).mean()<goal:lo=mid
        else:hi=mid
    e=np.minimum(((lo+hi)/2.)*shape,cap)
    if np.any(e<=0) or abs(float(e.mean())-goal)>atol:raise ValueError('MONTHLY_MASS_CONSERVATION_FAILED')
    return e

def synthesize(T,P,monthly_e,donor_e=None,donor_timestamps=None,target_timestamps=None):
    """All output variables derive ONLY from synthesized e and given hourly T/P.

    Inputs intentionally do not include target hourly e/RH/Td; donor_e optional.
    Caller must align donor and target hours by exact timestamp before passing.
    """
    t=np.asarray(T,float);p=np.asarray(P,float)
    variants={'constant_e':np.ones(len(t))}
    if donor_e is not None:
        other=np.asarray(donor_e,float)
        if len(other)!=len(t) or np.any(~np.isfinite(other)) or np.any(other<=0):raise ValueError('Nonpositive/incomplete donor e')
        if (donor_timestamps is not None or target_timestamps is not None) and list(donor_timestamps or [])!=list(target_timestamps or []):raise ValueError('Donor-target timestamps unaligned')
        ratio=other/float(other.mean())
        variants['donor_shape_half']=np.sqrt(ratio)
        variants['donor_shape_full']=ratio
    outputs={}
    for name,shape in variants.items():
        e=reconcile_monthly(monthly_e,shape,t,p)
        rh=100*e/np.array([esat_water_hpa(v) for v in t])
        dew=np.array([dew_point_from_vapour(float(v)) for v in e])
        w=.621945*e/(p-e)
        rho=216.7*e/(t+273.15)
        # No individual variable is independently interpolated or clipped.
        outputs[name]={'e':e,'RH':rh,'Td':dew,'w':w,'rho_v':rho}
    return outputs

def score(pred,obs):
    a=np.asarray(pred,float);b=np.asarray(obs,float)
    if a.shape!=b.shape or not len(a):raise ValueError('Unpaired score inputs')
    d=a-b
    return {'n':int(len(d)),'MAE':float(np.mean(np.abs(d))),
            'RMSE':float(np.sqrt(np.mean(d*d))),'bias':float(d.mean())}

def metric_rows(site,target,year,month,matched,methods,T,P,e_target_month):
    obs_e=np.array([target[t]['e'] for t in matched]);obs_rh=np.array([target[t]['RH'] for t in matched]);obs_td=np.array([target[t]['Td'] for t in matched]);
    records=[];closures=[]
    for method,output in methods.items():
        for variable,reference in [('e',obs_e),('RH',obs_rh),('Td',obs_td)]:
            records.append({'site':site,'year':year,'month':month,'method':method,'variable':variable,
                            'MAE':score(output[variable],reference)['MAE'],
                            'RMSE':score(output[variable],reference)['RMSE'],
                            'bias':score(output[variable],reference)['bias'],
                            'n_hours':len(matched)})
        es=np.array([esat_water_hpa(x) for x in T]);rh_calc=100*output['e']/es
        e_from_td=np.array([esat_water_hpa(x) for x in output['Td']])
        closures.append({'site':site,'year':year,'month':month,'method':method,
                         'hourly_mean_e_input':e_target_month,'hourly_mean_e_generated':float(output['e'].mean()),
                         'max_e_mass_residual_hpa':abs(float(output['e'].mean())-e_target_month),
                         'max_rh_closure_pp':float(np.max(np.abs(rh_calc-output['RH']))),
                         'max_e_dewpoint_closure_hpa':float(np.max(np.abs(e_from_td-output['e']))),
                         'saturation_violations':int(np.count_nonzero(output['e']>es+1e-10)),
                         'pressure_violations':int(np.count_nonzero(output['e']>=P)),
                         'dewpoint_above_drybulb':int(np.count_nonzero(output['Td']>T+1e-8)),
                         'negative_w':int(np.count_nonzero(output['w']<0)),
                         'n_hours':len(matched)})
    return records,closures

def save_csv(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def run(out,sites=SITES,months=MONTHS):
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw_meta,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    meta,_=parse_meta(raw_meta)
    if any(x not in meta for x in sites):raise RuntimeError('Unknown Swiss station in frozen pilot selection')
    months=set(months);allhour={};allmonthly={};hashes=[];failures=[];quality=collections.Counter()
    for site in sites:
        raw,sha=fetch(f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_m.csv',max_bytes=20000000)
        allmonthly[site],qc=swiss_monthly(raw,site)
        hashes.append({'site':site,'type':'monthly','sha256':sha,'bytes':len(raw)})
        allhour[site]={}
        for year in sorted({y for y,m in months}):
            dec='2010-2019' if year<2020 else '2020-2029'
            url=f'{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_{dec}.csv'
            blob,digest=fetch(url,max_bytes=35000000)
            data,qc=parse_hourly(blob,site,year,months)
            hashes.append({'site':site,'type':'hourly','decade':dec,'sha256':digest,'bytes':len(blob)})
            quality.update(qc)
            allhour[site].update(data)
    rows=[];clos=[];used=[]
    for site in sites:
        near=sorted([s for s in sites if s!=site],key=lambda s:(float(haversine(meta[s]['lat'],meta[s]['lon'],meta[site]['lat'],meta[site]['lon'])),s))
        donor=near[0]
        for year,month in sorted(months):
            key=(year,month);ym=f'{year}-{month:02d}'
            month_obs=allmonthly[site].get(ym)
            if not month_obs or month_obs.get('e') is None:failures.append({'site':site,'ym':ym,'reason':'missing_measured_monthly_e'});continue
            target=allhour[site].get(key,{});donor_hours=allhour[donor].get(key,{})
            # Fixed intersection for ALL methods ensures genuine paired comparison.
            common=sorted(k for k in target if k in donor_hours and
                    all(target[k][x] is not None for x in ('T','P','e','RH','Td')) and donor_hours[k]['e'] is not None)
            expected=calendar.monthrange(year,month)[1]*24
            if len(common)<MIN_COMPLETENESS*expected:
                failures.append({'site':site,'ym':ym,'reason':'insufficient_matched_hours','matched':len(common),'expected':expected,'donor':donor});continue
            t=np.array([target[k]['T'] for k in common]);p=np.array([target[k]['P'] for k in common]);e_d=np.array([donor_hours[k]['e'] for k in common]);
            try:pred=synthesize(t,p,month_obs['e'],e_d,common,common)
            except ValueError as err:
                failures.append({'site':site,'ym':ym,'reason':str(err),'matched':len(common),'donor':donor});continue
            metrics,closure=metric_rows(site,target,year,month,common,pred,t,p,month_obs['e']);rows+=metrics;clos+=closure
            used.append({'site':site,'ym':ym,'donor':donor,'n_hours':len(common),'expected_hours':expected,
                         'completeness':len(common)/expected,'monthly_input_e_hpa':month_obs['e'],
                         'observed_mean_e_on_matched_hours_hpa':float(np.mean([target[k]['e'] for k in common]))})
    if len(used)<8 or len({x['site'] for x in used})<2:raise RuntimeError('INSUFFICIENT_INDEPENDENT_SITES_MONTHS_FOR_HOURLY_SYNTHESIS '+str(used)+' '+str(failures))
    if any(c['max_e_mass_residual_hpa']>1e-8 or c['saturation_violations'] or c['pressure_violations'] or c['dewpoint_above_drybulb'] or c['negative_w'] for c in clos):raise AssertionError('PHYSICAL_CLOSURE_FAILURE')
    save_csv(dest/'synthesis_method_month_metrics.csv',rows)
    save_csv(dest/'synthesis_physical_closure.csv',clos)
    save_csv(dest/'synthesis_month_coverage.csv',used)
    ag=[]
    for name in METH:
        for var in ('e','RH','Td'):
            items=[z for z in rows if z['method']==name and z['variable']==var]
            if not items:continue
            weight=sum(z['n_hours'] for z in items)
            ag.append({'method':name,'variable':var,'n_hours':weight,'n_site_months':len(items),
                       'MAE':sum(z['n_hours']*z['MAE'] for z in items)/weight,
                       'RMSE':math.sqrt(sum(z['n_hours']*z['RMSE']**2 for z in items)/weight),
                       'bias':sum(z['n_hours']*z['bias'] for z in items)/weight})
    save_csv(dest/'synthesis_aggregate_metrics.csv',ag)
    provenance={'phase':'P8.2C_CONDITIONAL_HOURLY_MOISTURE_SYNTHESIS','scientific_status':'RESEARCH_HOLDOUT_NOT_PRODUCTION',
                'source':'Original MeteoSwiss SwissMetNet monthly e and hourly T/P/e/RH/Td',
                'sites':list(sites),'months':[f'{y}-{m:02d}' for y,m in sorted(months)],
                'n_scored_site_months':len(used),'n_scored_paired_hours':sum(z['n_hours'] for z in used),
                'conditioning':'TARGET measured monthly e, hourly drybulb T and P are supplied as input; target hourly e, RH and Td only used for scoring.',
                'not_independent_monthly_moisture_forecast':True,
                'donor_hourly_e_same_month':True,
                'donor_choice':'Single geographically nearest available station selected from metadata before outcome analysis',
                'physical_closure':{'relative_humidity_from_e_and_T':True,'dewpoint_from_e':True,'mixing_ratio_from_e_and_P':True,'vapour_density_from_e_and_T':True,'monthly_e_exactly_conserved_over_qualified_hours':True,'no_silent_rh_clipping':True},
                'assumptions':['Buck liquid-water saturation used at all temperatures','Published Swiss station hours treated as same nominal time, including DST-neutral numeric timestamps','Subset-qualified hourly mean matched to provided monthly mean; incompleteness documented','Constrained saturation projection can distort copied donor humidity temporal shape','Given target T and P: no independent temperature or pressure synthesis'],
                'coverage':used,'exclusions':failures,'quality':dict(quality),'metrics':ag,'source_sha256':hashes,'source_station_metadata_sha256':meta_sha,
                'original_observations_published':False}
    (dest/'synthesis_provenance.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False)+'\n')
    print('IGE_P8_2C_HOURLY_SYNTHESIS',json.dumps({'n_months':len(used),'paired_hours':provenance['n_scored_paired_hours'],'metrics':ag,'excluded':failures}),flush=True)
    return provenance

if __name__=='__main__':
    pa=argparse.ArgumentParser();pa.add_argument('--out',required=True)
    a=pa.parse_args();run(a.out)