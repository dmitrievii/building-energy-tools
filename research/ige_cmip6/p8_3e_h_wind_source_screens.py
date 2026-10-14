#!/usr/bin/env python3
"""IGE P8.3E-H: independent source-verified wind research screens, not production.
Original MeteoSwiss data used at runtime only. Export aggregate JSON, never original
hourly series, commercial Meteonorm files, or original DEM raster tiles.
"""
from __future__ import annotations
import argparse,collections,csv,datetime as dt,hashlib,json,math,random,statistics
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import numpy as np
from p8_1e_swiss_external import fetch,parse_meta
from p8_2e_crossyear import ROOT
from p8_3a_wind_spatial import parse_wind_year,usable_wind,CALM_MPS,circular_error_deg

PHASES=('E','F','G','H')
SEED=20261015

def save(out,phase,record):
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/f'p8_3{phase.lower()}_aggregate_provenance.json').write_text(
        json.dumps(record,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('IGE_P8_3'+phase+'_SCREEN',json.dumps({
        'status':record['status'],'sites':len(record.get('sites',[]))},ensure_ascii=False),flush=True)

def metadata():
    data,sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    sites,cols=parse_meta(data)
    return sites,sha,list(cols)

def observed(sid,years):
    raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv',
                  max_bytes=37000000)
    return {y:parse_wind_year(raw,sid,y) for y in years},sha

def log_profile(v,z_src,z_dst,z0):
    vals=(v,z_src,z_dst,z0)
    if any(x is None or not math.isfinite(x) for x in vals):
        raise ValueError('UNVERIFIED_LOG_PROFILE_PARAMETER')
    if v<0 or z0<=0 or min(z_src,z_dst)<=z0:
        raise ValueError('INVALID_NEUTRAL_LOG_PROFILE_DOMAIN')
    return v*math.log(z_dst/z0)/math.log(z_src/z0)

def decode_wind_parameter_metadata(raw):
    """MeteoSwiss OGD station metadata may use legacy Windows-1252.

    Decode strictly and record the actual successful codec. Never replace
    invalid bytes or silently label undecodable provenance as verified.
    """
    try:
        source = raw.decode('utf-8-sig', errors='strict')
        codec = 'utf-8-sig'
    except UnicodeDecodeError:
        source = raw.decode('cp1252', errors='strict')
        codec = 'cp1252'
    rows = list(csv.DictReader(source.splitlines(), delimiter=';'))
    if not rows or not any('fkl010h0' in str(v).lower() for r in rows for v in r.values()):
        raise ValueError('WIND_PARAMETER_METADATA_FIELDS_NOT_FOUND')
    matched = [r for r in rows if any(
        ('fkl010h0' in str(v).lower() or 'dkl010h0' in str(v).lower())
        for v in r.values())]
    return matched, codec


def stage_e(out):
    stations,sh,cols=metadata()
    raw,ph=fetch(ROOT+'/ogd-smn_meta_parameters.csv',max_bytes=3000000)
    wind_parameters, parameter_encoding = decode_wind_parameter_metadata(raw)
    targets=('BAS','CHD','GRA','MUB','STG','VIS')
    result={'phase':'P8.3E','status':'METADATA_PASS__INSTRUMENT_HEIGHT_AND_ROUGHNESS_NOT_VERIFIED',
      'station_metadata_sha256':sh,'parameter_metadata_sha256':ph,
      'parameter_metadata_decode_encoding':parameter_encoding,
      'station_columns':cols,'hourly_wind_parameter_definitions':wind_parameters,
      'sites':[{'id':sid,'ground_elevation_masl':stations[sid]['hoehe_m'],
                'anemometer_height_m_agl':None,'roughness_length_z0_m':None,
                'height_normalization_authorized':False} for sid in targets],
      'original_wind_normalized':False,
      'scientific_limit':'Absolute station elevation is not anemometer instrument height. No real-log-profile corrections without documented z_AGL and z0.'}
    save(out,'E',result)

def era5_decode(j):
    hourly=j.get('hourly',{})
    names=('time','wind_speed_10m','wind_direction_10m')
    if any(k not in hourly for k in names):raise ValueError('ERA5_API_SCHEMA')
    arrays=[hourly[n] for n in names]
    if any(len(x)!=744 for x in arrays):raise ValueError('ERA5_2024_JANUARY_HOUR_COUNT')
    if j.get('hourly_units',{}).get('wind_speed_10m')!='m/s':
        raise ValueError('ERA5_SPEED_UNIT_MISMATCH')
    result={}
    for when,speed,direction in zip(*arrays):
        if speed is None or direction is None:continue
        if not (math.isfinite(speed) and math.isfinite(direction) and speed>=0 and 0<=direction<=360):continue
        stamp=dt.datetime.fromisoformat(when)
        if stamp in result:raise ValueError('ERA5_DUPLICATE_HOUR')
        result[stamp]={'speed':speed,'direction':direction%360}
    if len(result)<705:raise ValueError('ERA5_LESS_THAN_95_PERCENT')
    return result

def stage_f(out):
    stations,sh,_=metadata();sites=[];source={}
    for sid in ('BAS','GRA','MUB'):
        x=stations[sid]
        query={'latitude':x['lat'],'longitude':x['lon'],
          'start_date':'2024-01-01','end_date':'2024-01-31',
          'hourly':'wind_speed_10m,wind_direction_10m',
          'models':'era5','wind_speed_unit':'ms','timezone':'GMT'}
        url='https://archive-api.open-meteo.com/v1/archive?'+urlencode(query)
        with urlopen(Request(url,headers={'User-Agent':'IGE-P8.3F-research-source-check'}),timeout=120) as r:
            body=r.read(8000000)
        grid=era5_decode(json.loads(body))
        wx,station_sha=observed(sid,(2024,))
        src={t:v for t,v in wx[2024].items() if t.month==1 and usable_wind(v)}
        byclock={}
        for shift,label in ((0,'same_nominal_hour'),(-1,'grid_one_hour_prior')):
            pairs=[];directions=[]
            for t,row in src.items():
                g=grid.get(t+dt.timedelta(hours=shift))
                if g is None:continue
                pairs.append(g['speed']-row['speed'])
                if row['speed']>=CALM_MPS and g['speed']>=CALM_MPS:
                    directions.append(circular_error_deg(g['direction'],row['direction']))
            if len(pairs)<500:raise ValueError('ERA5_STATION_INSUFFICIENT_OVERLAP')
            byclock[label]={'n':len(pairs),'speed_mae_mps':statistics.mean(map(abs,pairs)),
              'speed_bias_mps':statistics.mean(pairs),
              'n_direction':len(directions),
              'direction_mae_deg':statistics.mean(directions) if directions else None}
        source[sid]={'era5_gateway_sha256':hashlib.sha256(body).hexdigest(),'station_source_sha256':station_sha}
        sites.append({'id':sid,'time_alignment_hypotheses':byclock})
    save(out,'F',{'phase':'P8.3F','status':'ERA5_JANUARY_SOURCE_AND_UNCORRECTED_BACKGROUND_CHECK',
      'sites':sites,'source_sha':source,'meta_sha256':sh,
      'reanalysis':'Open-Meteo historical archive explicitly models=era5, not provider Best Match',
      'station_residual_interpolation_completed':False,'full_year_validated':False,
      'scientific_limit':'Pilot for source/unit/clock; no ERA5+station-residual trained model or independent seasonal validation.'})

def axial_difference(a,b):
    return abs((a-b+90)%180-90)

def axial_wind(rows):
    angles=[math.radians(2*v['direction']) for v in rows.values() if usable_wind(v) and v['speed']>=CALM_MPS]
    if len(angles)<6000:raise ValueError('INSUFFICIENT_NONCALM_WIND')
    c=statistics.mean(math.cos(a) for a in angles)
    s=statistics.mean(math.sin(a) for a in angles)
    axis=(math.degrees(math.atan2(s,c))/2)%180
    if abs(axis-180)<1e-8:axis=0.
    return axis,math.hypot(c,s),len(angles)

def lowest_opposing_axis(ring):
    if len(ring)!=12 or any(not math.isfinite(x) for x in ring):
        raise ValueError('INVALID_12_SECTOR_DEM_RING')
    pairs=[.5*(ring[i]+ring[i+6]) for i in range(6)]
    i=min(range(6),key=lambda i:(pairs[i],i))
    return i*30.,max(pairs)-min(pairs)

def stage_g(out):
    from p8_1c_dem import TileCache,radial,tile_point
    stations,sh,_=metadata()
    site_ids=('CHD','SIO','VIS','GRA')
    coordinates={sid:[radial(stations[sid]['lat'],stations[sid]['lon'],1500,b)
                        for b in range(0,360,30)] for sid in site_ids}
    cache=TileCache(str(Path(out)/'private_original_dem'),zoom=11)
    cache.prefetch({tile_point(lat,lon,11)[0] for cc in coordinates.values()
                    for lat,lon in cc},workers=12)
    sites=[];sha={}
    for sid in site_ids:
        axis,contrast=lowest_opposing_axis([cache.point(lat,lon) for lat,lon in coordinates[sid]])
        wx,digest=observed(sid,(2024,));sha[sid]=digest
        observed_axis,r,n=axial_wind(wx[2024])
        sites.append({'id':sid,'dem_low_axis_deg_mod180':axis,'station_wind_axial_mean_deg':observed_axis,
          'absolute_axial_difference_deg':axial_difference(axis,observed_axis),
          'wind_axis_resultant':r,'n_direction_hours':n,
          'opposing_radial_terrain_contrast_m':contrast})
    save(out,'G',{'phase':'P8.3G','status':'DEM_WIND_ORIENTATION_DIAGNOSTIC_ONLY',
        'sites':sites,'meta_sha256':sh,'original_wind_sha256':sha,
        'dem_original_tile_sha256':cache.sha,
        'predicted_wind_azimuth_corrected':False,
        'scientific_limit':'Lowest opposing 1500m DEM elevation pair is a crude axis, not an aerodynamic corridor model, no station-height or flow skill claim.'})

def complete_days(rows):
    days=collections.defaultdict(dict)
    for t,v in rows.items():
        if usable_wind(v):days[t.date()][t.hour]=v
    return {day:r for day,r in days.items() if len(r)==24}

def block_bootstrap(days,year,seed):
    months=collections.defaultdict(list)
    for d,hours in days.items():months[d.month].append(hours)
    rng=random.Random(seed);out={}
    day=dt.date(year,1,1)
    while day<dt.date(year+1,1,1):
        if not months[day.month]:raise ValueError('NO_COMPLETE_TRAINING_DAYS_IN_MONTH')
        pick=months[day.month][rng.randrange(len(months[day.month]))]
        for h in range(24):out[dt.datetime.combine(day,dt.time(h))]=pick[h]
        day+=dt.timedelta(days=1)
    return out

def wind_summary(rows):
    good={t:r for t,r in rows.items() if usable_wind(r)}
    if len(good)<6000:raise ValueError('INSUFFICIENT_SAMPLED_WIND')
    monthly={m:statistics.mean(r['speed'] for t,r in good.items() if t.month==m) for m in range(1,13)}
    rose=[0]*16
    for row in good.values():
        if row['speed']>=CALM_MPS:
            rose[int(((row['direction']+11.25)%360)//22.5)%16]+=1
    rose=[x/sum(rose) for x in rose]
    return {'n':len(good),'monthly_mean':monthly,'rose':rose,
            'calm_pct':100*sum(r['speed']<CALM_MPS for r in good.values())/len(good),
            'mean_speed_mps':statistics.mean(r['speed'] for r in good.values())}

def stage_h(out):
    sites=[];source={}
    for sid in ('BAS','PAY','VIS'):
        data,sha=observed(sid,(2021,2022,2023,2025));source[sid]=sha
        train={}
        for y in (2021,2022,2023):train.update(complete_days(data[y]))
        synthetic=block_bootstrap(train,2025,SEED)
        p=wind_summary(synthetic);obs=wind_summary(data[2025])
        sites.append({'id':sid,'training_complete_days':len(train),'reference_hours':obs['n'],
          'generated_hours':p['n'],
          'monthly_speed_mean_mae_mps':statistics.mean(abs(p['monthly_mean'][m]-obs['monthly_mean'][m]) for m in range(1,13)),
          'annual_mean_speed_error_mps':p['mean_speed_mps']-obs['mean_speed_mps'],
          'calm_fraction_difference_pp':p['calm_pct']-obs['calm_pct'],
          'sixteen_sector_total_variation':sum(abs(a-b) for a,b in zip(p['rose'],obs['rose']))/2})
    save(out,'H',{'phase':'P8.3H','status':'ONE_SEED_BLOCK_BOOTSTRAP_2025_TEMPORAL_SCREEN',
        'sites':sites,'sha_original_swiss_wind':source,'seed':SEED,
        'training_years':[2021,2022,2023],'unseen_validation_year':2025,
        'model':'Calendar-month-conditioned complete-day empirical resampling',
        'not_hourly_calendar_forecast':True,
        'production_epw_ready':False,
        'scientific_limit':'One stochastic realization; no multi-day persistence or multivariate/future SSP coherent synthetic wind; compare only climate statistics, never calendar-hour MAE.'})

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',required=True,choices=PHASES)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    {'E':stage_e,'F':stage_f,'G':stage_g,'H':stage_h}[args.phase](args.out)
