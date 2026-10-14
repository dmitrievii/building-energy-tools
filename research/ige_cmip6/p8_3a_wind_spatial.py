#!/usr/bin/env python3
"""P8.3A research pilot: contemporaneous donor wind hindcast, never future weather.

SwissMetNet original hourly scalar wind fkl010h0 [m/s] and meteorological
wind-FROM azimuth dkl010h0 [degrees]. Site withheld from all donor features.
Only metrics, provenance and source SHA are exported; no original hourly data.
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, json, math
from pathlib import Path
import numpy as np

SPEED='fkl010h0'
DIRECTION='dkl010h0'
CALM_MPS=0.5
YEAR=2021
TARGETS=('ABO','BER','PAY')
MIN_QUALIFIED_DONOR_FRACTION=0.90
MIN_SCORED_TARGET_FRACTION=0.80


def number(value, minimum, maximum):
    try:
        x=float(value)
        if math.isfinite(x) and minimum<=x<=maximum:return x
    except (ValueError, TypeError):pass
    return None


def parse_wind_year(raw, site, year=YEAR):
    data=raw.decode('utf-8-sig','strict')
    reader=csv.DictReader(data.splitlines(),delimiter=';')
    required={'station_abbr','reference_timestamp',SPEED,DIRECTION}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('SWISSMETNET_HOURLY_WIND_SCHEMA_CHANGED')
    out={}
    for r in reader:
        if r['station_abbr'].strip().upper()!=site:continue
        try:t=dt.datetime.strptime(r['reference_timestamp'],'%d.%m.%Y %H:%M')
        except ValueError:continue
        if t.year!=year:continue
        if t in out:raise ValueError('DUPLICATE_WIND_TIMESTAMP '+site+' '+str(t))
        speed=number(r[SPEED],0.,90.)
        direction=number(r[DIRECTION],0.,360.)
        if direction is not None:direction%=360.
        out[t]={'speed':speed,'direction':direction}
    return out


def usable_wind(row):
    """Calm speed is real evidence without a physically meaningful azimuth."""
    return row is not None and row.get('speed') is not None and (
        row['speed']<CALM_MPS or row.get('direction') is not None)


def wind_coverage(rows, hours):
    has_speed=sum(rows.get(t,{}).get('speed') is not None for t in hours)
    usable=sum(usable_wind(rows.get(t)) for t in hours)
    measured_noncalm=sum(rows.get(t,{}).get('speed') is not None and rows[t]['speed']>=CALM_MPS for t in hours)
    directional=sum(rows.get(t,{}).get('speed') is not None and rows[t]['speed']>=CALM_MPS and rows[t]['direction'] is not None for t in hours)
    return {'recorded_rows':len(rows),'speed_hours':has_speed,'usable_wind_hours':usable,
            'noncalm_speed_hours':measured_noncalm,'noncalm_direction_hours':directional,
            'eligible':usable>=math.ceil(MIN_QUALIFIED_DONOR_FRACTION*len(hours))}


def wind_from_to_uv(speed,direction):
    """Meteorological 0=N, 90=E FROM -> east/north TO components [m/s]."""
    if not math.isfinite(speed) or speed<0:raise ValueError('invalid speed')
    if speed<CALM_MPS:return 0.,0.
    if direction is None or not math.isfinite(direction):raise ValueError('direction missing')
    theta=math.radians(direction)
    return -speed*math.sin(theta),-speed*math.cos(theta)


def uv_to_wind_from(u,v):
    if not(math.isfinite(u) and math.isfinite(v)):raise ValueError('invalid wind vector')
    speed=math.hypot(u,v)
    direction=(math.degrees(math.atan2(-u,-v))%360.) if speed>=CALM_MPS else None
    return speed,direction


def circular_error_deg(a,b):
    if a is None or b is None:return None
    return abs(((float(a)-float(b)+180.)%360.)-180.)


def idw_weights(distances):
    d=np.asarray(distances,dtype=float)
    if len(d)==0 or np.any(~np.isfinite(d)) or np.any(d<0):raise ValueError('invalid IDW')
    w=1/np.maximum(d,.25)**2
    return w/w.sum()


def interpolate(donors, donor_observations, stamp):
    """Only station observations whose identities are not the target enter here."""
    active=[]
    for distance,station in donors:
        row=donor_observations.get(station['station_id'],{}).get(stamp)
        if usable_wind(row):active.append((distance,station['station_id'],row))
    if len(active)<2:return None
    weights=idw_weights([d for d,_,_ in active]);vel=np.array([r['speed'] for _,_,r in active],float)
    vectors=np.array([wind_from_to_uv(r['speed'],r['direction']) for _,_,r in active])
    east,north=weights@vectors
    vector_speed,vector_dir=uv_to_wind_from(east,north)
    scalar_speed=float(weights@vel)
    if vector_speed>scalar_speed+1e-8:raise AssertionError('VECTOR_TRIANGLE_INEQUALITY')
    closest=active[0][2]
    return {'vector_speed':vector_speed,'vector_direction':vector_dir,
            'scalar_speed':scalar_speed,'nearest_speed':closest['speed'],
            'nearest_direction':closest['direction'] if closest['speed']>=CALM_MPS else None,
            'resultant_ratio':vector_speed/scalar_speed if scalar_speed>1e-12 else 0.,
            'n_used':len(active)}


def score_target(target,year,hours,donors,source,predictions):
    """Target wind observations used solely here for independent scoring."""
    paired=[];direction_count=collections.Counter();direction_error=collections.defaultdict(list)
    for stamp in hours:
        ref=source.get(stamp);p=predictions.get(stamp)
        if p is None or not usable_wind(ref):continue
        s=float(ref['speed'])
        row={'observed_speed':s,'p':p}
        if s>=CALM_MPS and ref['direction'] is not None:
            direction_count['observed_noncalm']+=1
            for method,k in [('vector','vector_direction'),('nearest','nearest_direction')]:
                if p[k] is not None:
                    direction_error[method].append(circular_error_deg(p[k],ref['direction']))
                    direction_count[method+'_resolved']+=1
            if p['vector_direction'] is not None and p['nearest_direction'] is not None:
                direction_error['paired_vector'].append(circular_error_deg(p['vector_direction'],ref['direction']))
                direction_error['paired_nearest'].append(circular_error_deg(p['nearest_direction'],ref['direction']))
        paired.append(row)
    if len(paired)<math.ceil(MIN_SCORED_TARGET_FRACTION*len(hours)):
        raise ValueError(f'INSUFFICIENT_SCORED_WIND_{target}: {len(paired)}/{len(hours)}')
    observed=np.array([r['observed_speed'] for r in paired])
    outputs={'year':year,'site':target,'n_hours':len(paired),
             'direction_reference_noncalm_hours':direction_count['observed_noncalm'],
             'weighted_resultant_ratio_mean':float(np.mean([r['p']['resultant_ratio'] for r in paired])),
             'vector_unresolved_noncalm_reference_hours':direction_count['observed_noncalm']-direction_count['vector_resolved'],
             'wind_vector_opposition_fraction':float(np.mean([r['p']['resultant_ratio']<.3 for r in paired]))}
    for kind,key in [('scalar_idw','scalar_speed'),('vector_idw','vector_speed'),('nearest','nearest_speed')]:
        estimate=np.array([r['p'][key] for r in paired]);err=estimate-observed
        outputs[kind+'_speed_MAE_mps']=float(np.abs(err).mean())
        outputs[kind+'_speed_bias_mps']=float(err.mean())
        outputs[kind+'_speed_RMSE_mps']=float(np.sqrt(np.mean(err**2)))
    for kind in ('vector','nearest','paired_vector','paired_nearest'):
        values=direction_error[kind]
        outputs[kind+'_direction_n']=len(values)
        outputs[kind+'_direction_MAE_deg']=float(np.mean(values)) if values else None
    return outputs


def run(out,year=YEAR):
    if year!=YEAR:raise ValueError('P8.3A only pre-registered initial 2021 pilot')
    from p8_2e_crossyear import ROOT,POOL,annual_hours
    from p8_1e_swiss_external import fetch,parse_meta,haversine
    from p8_2f_station_selection import metadata_candidates
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    hours=annual_hours(year)
    raw,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(raw)
    nearest,candidates=metadata_candidates(metadata,TARGETS,POOL,nearest_count=20)
    weather={};sources=[];coverage=[]
    for sid in candidates:
        try:
            raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv',max_bytes=37000000)
            rows=parse_wind_year(raw,sid,year)
            wind_stats=wind_coverage(rows,hours)
            if wind_stats['eligible'] or sid in TARGETS:weather[sid]=rows
            sources.append({'site':sid,'sha256':sha,'fetch_success':True})
        except Exception as ex:
            wind_stats={'recorded_rows':0,'speed_hours':0,'usable_wind_hours':0,
              'noncalm_speed_hours':0,'noncalm_direction_hours':0,'eligible':False}
            sources.append({'site':sid,'fetch_success':False,'error_type':type(ex).__name__,'message':str(ex)[:100]})
        coverage.append({'site':sid,**wind_stats})
    qualified={x['site'] for x in coverage if x['eligible']}
    results=[];selected=[]
    for target in TARGETS:
        if target not in weather:raise ValueError('TARGET_WIND_UNAVAILABLE '+target)
        avail=sorted(((float(haversine(metadata[target]['lat'],metadata[target]['lon'],metadata[sid]['lat'],metadata[sid]['lon'])),metadata[sid])
                      for sid in qualified if sid!=target),key=lambda z:(z[0],z[1]['station_id']))
        if len(avail)<4:raise ValueError('INSUFFICIENT_WIND_DONORS '+target)
        donors=avail[:4]
        donor_weather={sid:v for sid,v in weather.items() if sid!=target}
        if target in donor_weather or any(s['station_id']==target for _,s in donors):raise AssertionError('TARGET_LEAK')
        predicted={h:p for h in hours if (p:=interpolate(donors,donor_weather,h)) is not None}
        result=score_target(target,year,hours,donors,weather[target],predicted)
        results.append(result)
        selected.append({'year':year,'target':target,'donors':';'.join(s['station_id'] for _,s in donors),
                         'distances_km':';'.join(f'{d:.3f}' for d,_ in donors),
                         'donor_heights_m':';'.join(f'{s["hoehe_m"]:.1f}' for _,s in donors),
                         'prediction_uses_target':False})
    def export(name,rows):
        with (dest/name).open('w',encoding='utf8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    export('wind_station_coverage.csv',coverage)
    export('wind_selected_donors.csv',selected)
    export('wind_station_skill.csv',results)
    report={'stage':'IGE_P8_3A_FIRST_WIND_SPATIAL_HINDCAST','year':year,
      'status':'RESEARCH_ONLY_NOT_A_FUTURE_WIND_GENERATOR',
      'source':'MeteoSwiss SwissMetNet original 2021 hourly observations',
      'wind_speed_field':'fkl010h0 [m/s]', 'wind_direction_field':'dkl010h0 [degrees FROM]',
      'source_clock':'original nominal UTC end-of-hour',
      'donor_protocol':'nearest four with >=90% measured hourly wind usability among nearest 20 plus original 12',
      'target_meteorology_used_as_donor':False,'source_metadata_sha256':meta_sha,
      'source_audit':sources,'site_scores':results,'site_selection':selected,
      'source_qc_limit':'MeteoSwiss numeric validity and coverage screening only; no original q-flag validation in this first pilot',
      'original_hourly_series_published':False,
      'limits':['Vector cancellation is physical and generally reduces estimated scalar wind speed.',
                'Directional MAE conditional on valid emitted noncalm azimuth; direction coverage always reported separately.',
                'Wind near surface affected by terrain, obstruction and sensor exposure.',
                'Station wind hindcast using SAME real-year simultaneous donors is NOT future GCM wind generation.',
                'No measured future wind or complete 35-field EPW represented.',
                'Only first 2021 three-site pilot; validation not production grade.']}
    (dest/'wind_spatial_provenance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('IGE_P8_3A_WIND',json.dumps({'year':year,'sites':results,'donors':selected,'qualified_sources':len(qualified)},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,default=YEAR);ap.add_argument('--out',required=True)
    a=ap.parse_args();run(a.out,a.year)