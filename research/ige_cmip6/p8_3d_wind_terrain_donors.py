#!/usr/bin/env python3
"""IGE P8.3D: pre-registered wind-donor suitability from physical metadata+DEM.

Frozen original P8.3A scalar IDW and vector direction, original P8.3B unit
circle are called without modification; only which four donors are selected
changes. No target measurements influence selection. Original SwissMetNet
hourly records and DEM tiles stay in temporary CI runner, not public exports.
"""
from __future__ import annotations
import argparse, collections, csv, datetime as dt, hashlib, json, math
from pathlib import Path
import numpy as np
from p8_3a_wind_spatial import (CALM_MPS, parse_wind_year, usable_wind, wind_coverage,
    interpolate, circular_error_deg)
from p8_3b_wind_direction_qc import circular_unit_prediction, csv_source_qc_profile
from p8_3c_wind_hybrid_holdout import sector16

# Pre-registered *before* accessing 2024 target errors. New targets relative to
# P8.3A-C; Swiss sites may have served as donors previously (NOT region-blind).
YEAR=2024
TARGETS=('BAS','CHD','GRA','MUB','STG','VIS')
SEARCH_NEAREST=20
DONORS=4
MIN_WIND_YEAR=.90
MIN_TARGET=.80
METHODS=('distance_idw4','altitude_idw4','terrain_idw4')
# Explicit heuristic *distance-equivalent* scales, NOT a physical law or fit.
# Differences in station height / local DEM TPI / DEM ruggedness (m) are
# expressed as equivalent horizontal separation (km). Holdout 2024 never
# changes these parameters. Apply original physical-distance 1/d^2 IDW weights
# AFTER station ranking; do not reweight the wind observations using score.
ALT_KM_PER_M=.04
TPI_KM_PER_M=.03
RUGGED_KM_PER_M=.02
DEM_RING_M=1500.
DEM_BEARINGS=tuple(range(0,360,45))
DEM_ZOOM=11


def eligible_station(coverage,expected):
    if expected<=0:raise ValueError('INVALID_EXPECTED_HOURS')
    return coverage['usable_wind_hours'] >= math.ceil(MIN_WIND_YEAR*expected)


def landform_features(station,cache):
    """Topographic position index and ring ruggedness; not wind exposure or instrument height."""
    from p8_1c_dem import radial
    p=[(station['lat'],station['lon'])]
    p.extend(radial(station['lat'],station['lon'],DEM_RING_M,az) for az in DEM_BEARINGS)
    values=np.array([cache.point(lat,lon) for lat,lon in p],dtype=float)
    if not np.all(np.isfinite(values)):raise ValueError('UNVERIFIED_DEM_VALUE')
    center=float(values[0]);ring=values[1:]
    return {'station_id':station['station_id'],'station_elevation_m':float(station['hoehe_m']),
       'dem_center_m':center,'tpi_1500_m':float(center-ring.mean()),
       'rugged_1500_m':float(ring.std()),'dem_station_delta_m':float(center-station['hoehe_m']),
       'dem_disagreement_gt200m':bool(abs(center-station['hoehe_m'])>200)}


def metadata_dem_features(stations,cache):
    from p8_1c_dem import tile_point,radial
    if not stations:raise ValueError('NO_STATIONS_TO_SAMPLE')
    needed=set()
    for s in stations.values():
        points=[(s['lat'],s['lon'])]+[radial(s['lat'],s['lon'],DEM_RING_M,a) for a in DEM_BEARINGS]
        needed.update(tile_point(a,b,cache.zoom)[0] for a,b in points)
    cache.prefetch(needed,workers=12)
    return {s:landform_features(v,cache) for s,v in sorted(stations.items())}


def ranking_score(target,donor,d_km,features,method):
    """Only immutable geographic metadata/DEM influence ranking."""
    if method not in METHODS:raise ValueError('UNSUPPORTED_WIND_SELECTOR '+method)
    if not math.isfinite(d_km) or d_km<0:raise ValueError('INVALID_DISTANCE')
    if target['station_id']==donor['station_id']:raise AssertionError('TARGET_IS_DONOR')
    z=float(target['hoehe_m'])-float(donor['hoehe_m'])
    if method=='distance_idw4':return d_km
    alt=ALT_KM_PER_M*z
    if method=='altitude_idw4':return math.hypot(d_km,alt)
    t=features[target['station_id']];s=features[donor['station_id']]
    dtpi=TPI_KM_PER_M*(t['tpi_1500_m']-s['tpi_1500_m'])
    dr=RUGGED_KM_PER_M*(t['rugged_1500_m']-s['rugged_1500_m'])
    return math.sqrt(d_km*d_km+alt*alt+dtpi*dtpi+dr*dr)


def choose_donors(target,metadata,qualified,features,method,n=DONORS):
    from p8_1e_swiss_external import haversine
    if target['station_id'] not in metadata:raise ValueError('TARGET_METADATA_MISSING')
    ranked=[]
    for sid in sorted(qualified):
        if sid==target['station_id']:continue
        if sid not in metadata:raise ValueError('QUALIFIED_STATION_NOT_IN_METADATA')
        station=metadata[sid]
        distance=float(haversine(target['lat'],target['lon'],station['lat'],station['lon']))
        score=ranking_score(target,station,distance,features,method)
        ranked.append((score,distance,sid,station))
    ranked.sort(key=lambda r:(r[0],r[1],r[2]))
    if len(ranked)<n:raise ValueError('INSUFFICIENT_ELIGIBLE_WIND_DONORS')
    # Crucial: return true geographic distance for the unchanged P8.3A weights.
    return [(dist,station) for score,dist,sid,station in ranked[:n]]


def score_site(target,hours,donors,observations):
    """All selection methods scored on identical actual timestamps per site."""
    if any(s['station_id']==target for _,s in donors):raise AssertionError('TARGET_LEAK')
    source=observations.get(target)
    if source is None:raise ValueError('TARGET_SOURCE_UNAVAILABLE')
    donor_only={s:observations[s] for _,sta in donors for s in [sta['station_id']] if s!=target}
    if len(donor_only)!=DONORS:raise ValueError('DONOR_SOURCE_UNAVAILABLE')
    out={}
    for stamp in hours:
        ref=source.get(stamp)
        if not usable_wind(ref):continue
        p=interpolate(donors,donor_only,stamp)
        unit=circular_unit_prediction(donors,donor_only,stamp)
        if p is None:continue
        direction=float(ref['direction']) if ref['speed']>=CALM_MPS else None
        out[stamp]={'reference_speed':ref['speed'],'reference_direction':direction,
          'scalar':p['scalar_speed'],'vector_direction':p['vector_direction'],
          'unit_direction':unit['unit_direction'],'nearest_direction':p['nearest_direction'],
          'unit_resultant':unit['unit_resultant']}
    return out


def summarize(stamp_data,site,method,strict_common=None):
    """Keep common-hour and own-hour denominators explicit."""
    if strict_common is None:strict_common=set(stamp_data)
    rows=[stamp_data[t] for t in sorted(strict_common) if t in stamp_data]
    if not rows:raise ValueError('EMPTY_COMMON_HOURS')
    abs_speed=[abs(r['scalar']-r['reference_speed']) for r in rows]
    bias_speed=[r['scalar']-r['reference_speed'] for r in rows]
    nc=[r for r in rows if r['reference_direction'] is not None]
    result={'target':site,'method':method,'n_common_score_hours':len(rows),'n_common_noncalm':len(nc),
      'scalar_speed_MAE_mps':sum(abs_speed)/len(abs_speed),'scalar_speed_bias_mps':sum(bias_speed)/len(bias_speed)}
    for k in ('vector_direction','unit_direction','nearest_direction'):
        v=[r for r in nc if r[k] is not None]
        result[k+'_n_resolved']=len(v)
        result[k+'_coverage_pct']=100*len(v)/len(nc) if nc else None
        result[k+'_emitted_MAE_deg']=sum(circular_error_deg(r[k],r['reference_direction']) for r in v)/len(v) if v else None
        result[k+'_fixed90_deg']=sum(circular_error_deg(r[k],r['reference_direction']) if r[k] is not None else 90. for r in nc)/len(nc) if nc else None
        result[k+'_sum_abs_error_deg']=sum(circular_error_deg(r[k],r['reference_direction']) for r in v)
    result['speed_sum_abs_error_mps']=sum(abs_speed)
    return result


def compare_selectors(target,hours,selections,observations):
    estimated={key:score_site(target,hours,donors,observations) for key,donors in selections.items()}
    common=set(hours)
    for v in estimated.values():common&=set(v)
    if len(common)<math.ceil(MIN_TARGET*len(hours)):
        raise ValueError(f'INSUFFICIENT_COMMON_WIND_HOURS {target}: {len(common)}/{len(hours)}')
    # Also use identical actually non-calm hours in direction comparisons.
    result=[summarize(estimated[k],target,k,strict_common=common) for k in METHODS]
    nc=[t for t in common if estimated[METHODS[0]][t]['reference_direction'] is not None]
    for method,key in [('vector','vector_direction'),('unit','unit_direction')]:
        paired=[t for t in nc if all(estimated[m][t][key] is not None for m in METHODS)]
        for i,m in enumerate(METHODS):
            vals=[circular_error_deg(estimated[m][t][key],estimated[m][t]['reference_direction']) for t in paired]
            result[i][method+'_strict_three_method_n']=len(vals)
            result[i][method+'_strict_three_method_MAE_deg']=sum(vals)/len(vals) if vals else None
    return result,{'target':target,'n_matched_hours':len(common),
           'n_matched_noncalm':len(nc),'n_2024_hours':len(hours)}


def _csv(path,rows):
    if not rows:raise ValueError('EMPTY_EXPORT')
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def run(year,out):
    if year!=YEAR:raise ValueError('PRE_REGISTERED_YEAR_ONLY_2024')
    from p8_2e_crossyear import ROOT, POOL, annual_hours
    from p8_1e_swiss_external import fetch,parse_meta
    from p8_2f_station_selection import metadata_candidates
    from p8_1c_dem import TileCache
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    hours=annual_hours(year)
    meta,meta_sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    metadata,_=parse_meta(meta)
    if not set(TARGETS).issubset(metadata):raise ValueError('PRE_REGISTERED_TARGET_METADATA_MISSING')
    _,candidates=metadata_candidates(metadata,TARGETS,POOL,nearest_count=SEARCH_NEAREST)
    coverage=[];audit=[];weather={};headers=[]
    for sid in candidates:
        try:
            raw,sha=fetch(f'{ROOT}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2020-2029.csv',max_bytes=37000000)
            headers.append(csv_source_qc_profile(raw,sid,year))
            obs=parse_wind_year(raw,sid,year)
            c=wind_coverage(obs,hours)
            if eligible_station(c,len(hours)) or sid in TARGETS:weather[sid]=obs
            audit.append({'site':sid,'download_ok':True,'sha256':sha,'source_error':''})
        except Exception as exc:
            c={'recorded_rows':0,'speed_hours':0,'usable_wind_hours':0,'noncalm_speed_hours':0,'noncalm_direction_hours':0,'eligible':False}
            audit.append({'site':sid,'download_ok':False,'sha256':'','source_error':type(exc).__name__+':'+str(exc)[:110]})
            headers.append({'site':sid,'year':year,'qc_status':'SOURCE_UNAVAILABLE','individual_qc_available':False,'individual_qc_codes_verified':False})
        coverage.append({'site':sid,'year':year,**c})
    qualified={x['site'] for x in coverage if eligible_station(x,len(hours))}
    if not set(TARGETS).issubset(weather):raise ValueError('PRE_REGISTERED_TARGET_OBSERVATIONS_MISSING')
    feature_sites={s:metadata[s] for s in set(qualified)|set(TARGETS)}
    cache=TileCache(dest/'_private_dem_cache',zoom=DEM_ZOOM)
    features=metadata_dem_features(feature_sites,cache)
    selection=[];scores=[];diag=[]
    for tid in TARGETS:
        target=metadata[tid]
        chosen={m:choose_donors(target,metadata,qualified,features,m) for m in METHODS}
        # Each target's readings excluded from all predictor source mappings.
        rows,info=compare_selectors(tid,hours,chosen,weather)
        scores.extend(rows);diag.append(info)
        for method,donors in chosen.items():
            selection.append({'target':tid,'year':year,'method':method,
               'donors':';'.join(s['station_id'] for _,s in donors),
               'true_distance_km':';'.join(f'{d:.3f}' for d,s in donors),
               'heights_m':';'.join(f'{s["hoehe_m"]:.1f}' for _,s in donors),
               'tpi_1500_m':';'.join(f'{features[s["station_id"]]["tpi_1500_m"]:.1f}' for _,s in donors),
               'rugged_1500_m':';'.join(f'{features[s["station_id"]]["rugged_1500_m"]:.1f}' for _,s in donors),
               'uses_target_meteorology_for_selection':False})
    # Missing original station records remain missing; at least 80% of all
    # physical UTC hours MUST be matched across ranking methods.
    for x in scores:
        if x['n_common_score_hours']<math.ceil(MIN_TARGET*len(hours)):
            raise ValueError('INSUFFICIENT_SCORED_HOURS')
    _csv(dest/'p8_3d_wind_scores.csv',scores)
    _csv(dest/'p8_3d_wind_selected_donors.csv',selection)
    _csv(dest/'p8_3d_source_coverage.csv',coverage)
    _csv(dest/'p8_3d_wind_headers.csv',headers)
    _csv(dest/'p8_3d_dem_features.csv',list(features.values()))
    # Raw DEM PNG tiles must not be uploaded; only SHA hashes and features.
    provenance={'stage':'IGE_P8_3D_WIND_PHYSICAL_DONOR_SELECTION',
      'year':year,'targets':TARGETS,'n_hours_per_target':len(hours),
      'status':'RESEARCH_NOT_PRODUCTION','candidate_count':len(candidates),
      'qualified_donors_count':len(qualified), 'methods':METHODS,
      'pre_registered_effective_distance_scaling_km_per_m':{'altitude':ALT_KM_PER_M,'tpi':TPI_KM_PER_M,'ruggedness':RUGGED_KM_PER_M},
      'ranking_only':'Original P8.3A physical-distance IDW weights and P8.3B circle direction unchanged',
      'dem':{'provider':'Mapzen/Tilezen AWS Terrain Tiles (mosaicked DEM)','zoom':DEM_ZOOM,
             'ring_m':DEM_RING_M,'bearings':DEM_BEARINGS,
             'sha256_tiles':cache.sha,'station_exposure_verified':False,
             'anemometer_height_verified':False},
      'metadata_sha256':meta_sha,'source_sha256_and_errors':audit,'n_sites':len(TARGETS),
      'matched_clock_diagnostics':diag,
      'source_qc_individual_verified':False,
      'no_public_original_hourly_data':True,
      'limitations':['Altitude and DEM topographic similarity are pre-registered proxy heuristics, not mechanistic wind flow equations',
        'No verified anemometer mounting height, exposure class, upstream roughness, snow height or per-record QC',
        'Same-time actual donor observations used; not future wind or SSP EPW',
        '2024 is new temporal test, target sites unused as wind targets before, but historical studies may have included these as donors',
        'Physical ranking uses donors selected from nearest-20 metadata union and original 12; not all 159 full hourly files screened',
        'DEM tiles derive from mosaicked data; station terrain difference can reflect non-ground instrument altitude',
        'Year-wide station eligibility assumes retrospective source coverage and cannot imply real-time missing-data usability']}
    (dest/'p8_3d_provenance.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('IGE_P8_3D_WIND',json.dumps({'year':year,'scores':scores,'selections':selection,'n_qualified':len(qualified)},ensure_ascii=False),flush=True)
    return provenance

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,default=YEAR)
    ap.add_argument('--out',required=True)
    args=ap.parse_args();run(args.year,args.out)