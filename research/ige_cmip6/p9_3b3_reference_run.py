"""P1/P2 source-only reference probe: bounded, auditable, never station scoring."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import time

import numcodecs
import numpy as np

from p9_3b3_compare_pressure import hydrostatic_pressure
from p9_3b3_compare_vertical_frame import G0,PressureSeries,SourceBlocked,VerticalCoordinate,fingerprint
from p9_3b3_reference_column import hybrid_column,transfer_pressure
from p9_3b3_reference_sources import ArcoSource,BoundedCache,four_corners,station_metadata


ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=Path(__file__).with_name('p9_3b3_reference_protocol.json')
CODE_NAMES=('p9_3b3_reference_column.py','p9_3b3_reference_sources.py','p9_3b3_reference_run.py')


def protected_controls(protocol,root=ROOT):
    actual={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in protocol['protected_control_sha256']}
    changed=[name for name,value in actual.items() if value!=protocol['protected_control_sha256'][name]]
    if changed:raise ValueError('P93REF_FROZEN_CONTROLS_CHANGED:'+','.join(changed))
    return {'verified_count':len(actual),'changed_count':0,'actual_sha256':actual}


def distance_km(a,b,c,d):
    """Spherical distance, fixed geometry for weights; no pressure residuals."""
    x,y=math.radians(c-a),math.radians(d-b)
    v=math.sin(x/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(y/2)**2
    return 6371.0088*2*math.asin(math.sqrt(min(1.,v)))


def diagnostic_target(height,role,evidence):
    # verified refers ONLY to a read metadata value. Its historical epoch and
    # datum equivalence remain unqualified in every returned site result.
    return VerticalCoordinate(height,'GEOMETRIC_M','MSL_GEOID',role,evidence,True)


def reference_alignment(column,source_full_137_phi):
    """Necessary geometry check, not an empirically fitted tolerance or repair.

    With positive Tv and increasing half-level pressure, ECMWF's alpha puts
    full level 137 strictly above its own surface. Mixing two source products
    can violate this before any station observations are opened.
    """
    surface=column.half_geopotential_m2s2[-1]
    above=float(source_full_137_phi)-surface
    return {'level_137_ECMWF_reference_residual_m':
                (column.full_geopotential_ECMWF_alpha_m2s2[-1]-source_full_137_phi)/G0,
        'source_level_137_minus_supplied_surface_m':above/G0,
        'necessary_bottom_level_above_surface':'PASS_NECESSARY_ONLY' if above>0 else 'VIOLATED_FOR_THIS_CROSS_PRODUCT_COLUMN',
        'matching_surface_and_lnsp_processing_pipeline_qualified':False,
        'source_reference_qualification':'NOT_ESTABLISHED_CROSS_PRODUCT_GEOMETRY',
        'empirical_surface_shift_or_pressure_fit_applied':False}


def p1_comparison(columns,distances,site,stamp):
    h=site['barometer_height_m'];phi=G0*h
    valid=[(c,d) for c,d in zip(columns,distances) if c.domain[0]<=phi<=c.domain[1]]
    if not valid:raise SourceBlocked('P93REF_NO_P1_AIR_COLUMN_AT_SNAPSHOT_BAROMETER')
    c,d=min(valid,key=lambda pair:(pair[1],pair[0].latitude,pair[0].longitude))
    # H = supplied national MASL is a declared conditional approximation,
    # not a claim of datum transformation or historical sensor qualification.
    anchor=VerticalCoordinate(c.domain[0]/G0,'GEOPOTENTIAL_HEIGHT_M','MSL_GEOID',
        'GRID_SURFACE','ARCO_SOURCE_PHI_DIV_G0',True)
    target=VerticalCoordinate(h,'GEOPOTENTIAL_HEIGHT_M','MSL_GEOID','BAROMETER',
        'CURRENT_SNAPSHOT_MASL_ASSUMED_H_NOT_2021_QUALIFIED',True)
    p=PressureSeries((c.half_pressure_Pa[-1],),anchor,stamp[:10],c.source,
        'INSTANTANEOUS_HOUR_NODE_UTC:'+stamp,source_sha256=c.source_sha256)
    t,q=c.state(phi);result={}
    for lapse in (0.,.0065):
        candidate=hydrostatic_pressure(p,target,[t],[q],proxy_source=c.source+'|'+stamp,
            proxy_date=stamp[:10],lapse_K_per_m=lapse)
        result[str(lapse)]={'pressure_Pa':candidate.pressure.values_Pa[0],**candidate.metadata()}
    result['P2_same_single_column']=transfer_pressure([c],[d],
        diagnostic_target(h,'BAROMETER',target.evidence),timestamp_UTC=stamp,allow_constant_g_geometric=True)
    result['comparison_scope']='SOURCE_ONLY_SAME_ANCHOR_SENSITIVITY_NOT_ACCURACY'
    return result


def site_diagnostic(site,columns,stamp):
    distances=[distance_km(site['latitude'],site['longitude'],c.latitude,c.longitude) for c in columns]
    result={'station_id':site['station_id'],'height_valid_for_2021_sensor_validation':False,
        'station_sensor_qualification':'SOURCE_BLOCKED_HISTORICAL_SENSOR_HEIGHT_AND_DATUM',
        'declared_height_approximation':'NATIONAL_MASL_ASSUMED_GEOPOTENTIAL_HEIGHT_H_WITH_CONSTANT_G0',
        'column_geometry':[{'latitude':c.latitude,'longitude':c.longitude,'distance_km':d,
            'surface_H_m':c.domain[0]/G0,'top_H_m':c.domain[1]/G0,'fingerprint':c.fingerprint}
            for c,d in zip(columns,distances)],'cases':{}}
    cases=[('general_station_height_SENSITIVITY_ONLY',site['general_station_height_m'],'STATION_GROUND')]
    if site['barometer_height_m'] is not None:
        cases.append(('current_snapshot_barometer_NOT_2021_QUALIFIED',site['barometer_height_m'],'BAROMETER'))
    for name,height,role in cases:
        target=diagnostic_target(height,role,site['source']+'#'+site['source_sha256'])
        try:
            value=transfer_pressure(columns,distances,target,timestamp_UTC=stamp,
                allow_ground_diagnostic=True,allow_constant_g_geometric=True)
            result['cases'][name]={'status':'CONDITIONAL_SOURCE_ONLY_HYDROSTATIC_RESULT',**value}
        except SourceBlocked as exc:
            result['cases'][name]={'status':'SOURCE_BLOCKED','reason':str(exc),'target':asdict(target)}
    if site['barometer_height_m'] is not None:
        try:result['P1_P2_comparison_at_current_snapshot']=p1_comparison(columns,distances,site,stamp)
        except SourceBlocked as exc:result['P1_P2_comparison_at_current_snapshot']={'status':'SOURCE_BLOCKED','reason':str(exc)}
    return result


def source_profiles(protocol,cache,sites):
    admitted={country:s for country,s in sites.items() if s.get('status')!='SOURCE_BLOCKED'}
    if not admitted:raise SourceBlocked('P93REF_NO_STATION_METADATA_GEOMETRY')
    ml=ArcoSource(protocol['ML_source'],cache);surface=ArcoSource(protocol['surface_source'],cache)
    A,B=ml.pv_coefficients()
    for source,name,units in ((ml,'geopotential','m**2 s**-2'),
            (surface,'surface_pressure','Pa'),(surface,'geopotential_at_surface','m**2 s**-2')):
        if source.array(name)[1].get('units')!=units:raise ValueError('P93REF_SOURCE_UNITS:'+name)
    levels=list(range(protocol['lowest_model_level'],protocol['highest_model_level']+1))
    by_site={country:four_corners(s['latitude'],s['longitude']) for country,s in admitted.items()}
    points=sorted({p for ps in by_site.values() for p in ps})
    metadata={'ML_sha256':ml.metadata_sha,'surface_sha256':surface.metadata_sha,
        'hybrid_A_Pa':A,'hybrid_B':B,'hybrid_coefficients_source':'MATCHED_T_Q_GRIB_pv',
        'surface_lnsp':'EXPLICIT_LOG_OF_ARCO_SURFACE_PRESSURE_NOT_ORIGINAL_LNSP_GRIB',
        'horizontal_grid':'ARCO_0.25_DEG_REMAPPED_NOT_NATIVE_SPECTRAL_OR_CDS_GRIB',
        'vertical_grid':'ORIGINAL_137_HYBRID_A_B_COORDINATES_BOTTOM_109_TO_137',
        'profiles':[]}
    for stamp in protocol['source_only_profile_times']:
        print('SOURCE_ONLY_PROFILE_START '+stamp,flush=True)
        start=time.perf_counter();before=cache.downloaded
        record={'timestamp_UTC':stamp,'status':'SOURCE_BLOCKED','sites':{}}
        try:
            values={}
            for name in ('temperature','specific_humidity'):
                print('READ_MODEL_LEVEL_CHUNKS '+name+' '+stamp,flush=True)
                values[name]=ml.point_values(name,stamp,points,levels)
            ps=surface.point_values('surface_pressure',stamp,points)
            phi=surface.point_values('geopotential_at_surface',stamp,points)
            z137=ml.point_values('geopotential',stamp,points,[137])[:,0]
            columns={};diagnostics=[]
            for i,(lat,lon) in enumerate(points):
                inputs={'timestamp_UTC':stamp,'latitude':lat,'longitude':lon,'surface_pressure_Pa':float(ps[i]),
                    'surface_geopotential_m2s2':float(phi[i]),'T_K':values['temperature'][i].tolist(),
                    'q_kgkg':values['specific_humidity'][i].tolist(),'hybrid_coefficients_sha256':fingerprint([A,B]),
                    'source_metadata_sha256':[ml.metadata_sha,surface.metadata_sha]}
                kwargs=dict(first_level=levels[0],timestamp_UTC=stamp,latitude=lat,longitude=lon,
                    source='ERA5_ARCO_HYBRID_VERTICAL_REMAPPED_HORIZONTAL',source_sha256=fingerprint(inputs))
                c=hybrid_column(math.log(ps[i]),phi[i],values['temperature'][i],values['specific_humidity'][i],A,B,**kwargs)
                ref=hybrid_column(math.log(ps[i]),phi[i],values['temperature'][i],values['specific_humidity'][i],A,B,
                    gas='ECMWF_PUBLISHED_APPROXIMATION',**kwargs)
                columns[(lat,lon)]=c
                diagnostics.append({**inputs,'B3_column_fingerprint':c.fingerprint,
                    'source_full_level_137_geopotential_m2s2':float(z137[i]),
                    'ECMWF_gas_reconstructed_level_137_geopotential_m2s2':ref.full_geopotential_ECMWF_alpha_m2s2[-1],
                    **reference_alignment(ref,float(z137[i])),
                    'B3_minus_ECMWF_reconstruction_top_m':(c.domain[1]-ref.domain[1])/G0,
                    'reference_scope':'REGRID_NONCOMMUTATION_DIAGNOSTIC_NOT_STATION_ACCURACY_OR_NATIVE_GRIB_IDENTITY'})
            record.update(status='BOUNDED_SOURCE_ONLY_PROFILES_RECONSTRUCTED',columns=diagnostics,
                sites={country:site_diagnostic(admitted[country],[columns[p] for p in points_at_site],stamp)
                    for country,points_at_site in by_site.items()})
        except (SourceBlocked,OSError) as exc:
            record['reason']=type(exc).__name__+':'+str(exc)
            record['sites']={country:{'status':'SOURCE_BLOCKED','reason':record['reason'],
                'height_valid_for_2021_sensor_validation':False} for country in protocol['countries']}
        for country in protocol['countries']:
            record['sites'].setdefault(country,{'status':'SOURCE_BLOCKED','reason':'STATION_METADATA_NOT_AVAILABLE',
                'height_valid_for_2021_sensor_validation':False})
        record['wall_seconds']=time.perf_counter()-start;record['new_download_bytes']=cache.downloaded-before
        metadata['profiles'].append(record)
        print('SOURCE_ONLY_PROFILE_END '+stamp+' '+record['status'],flush=True)
    return metadata


def source_cost(cache,profiles):
    unique={r['url']:r for r in cache.records}
    chunks={u:r for u,r in unique.items() if '/temperature/' in u or '/specific_humidity/' in u or
        '/geopotential/' in u or '/surface_pressure/' in u or '/geopotential_at_surface/' in u}
    n=sum(p['status']=='BOUNDED_SOURCE_ONLY_PROFILES_RECONSTRUCTED' for p in profiles)
    size=sum(r['bytes'] for r in chunks.values())
    return {'network_downloaded_bytes_this_process':cache.downloaded,'network_requests_this_process':cache.requests,
        'unique_source_objects_accessed':len(unique),'unique_source_object_bytes_including_cache_hits':sum(r['bytes'] for r in unique.values()),
        'complete_source_hours':n,'global_field_chunk_bytes_for_accessed_profiles':size,
        'estimated_672_hours_field_bytes_if_same_compression':size/n*672 if n else None,
        'estimate_scope':'LINEAR_CHUNK_STORAGE_ESTIMATE_NOT_MEASURED_FULL_COHORT_RUN',
        'objects':list(unique.values())}


def run(out,private_cache,probe_profiles=False):
    start=time.perf_counter();out=Path(out);private_cache=Path(private_cache)
    if out.exists():raise ValueError('P93REF_OUTPUT_EXISTS_NO_OVERWRITE')
    if out.resolve() in (private_cache.resolve(),*private_cache.resolve().parents):
        raise ValueError('P93REF_PRIVATE_CACHE_MUST_BE_OUTSIDE_PUBLIC_OUTPUT')
    protocol=json.loads(PROTOCOL.read_text());controls=protected_controls(protocol)
    # Resolve code before creating output and before any source access.
    provenance={'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'code_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in CODE_NAMES},
        'python':platform.python_version(),'numpy':np.__version__,'numcodecs':numcodecs.__version__,
        'started_UTC':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    out.mkdir(parents=True)
    cache=BoundedCache(private_cache,protocol);sites=station_metadata(cache)
    source={'profiles':[],'status':'METADATA_ONLY_NO_PROFILE_REQUESTED'}
    if probe_profiles:
        try:source=source_profiles(protocol,cache,sites)
        except (SourceBlocked,OSError) as exc:
            source={'status':'SOURCE_BLOCKED','reason':type(exc).__name__+':'+str(exc),
                'profiles':[{'timestamp_UTC':stamp,'status':'SOURCE_BLOCKED','sites':{
                    country:{'status':'SOURCE_BLOCKED','reason':str(exc)} for country in protocol['countries']}}
                    for stamp in protocol['source_only_profile_times']]}
    result={'phase':protocol['phase'],'provenance':provenance,'protected_controls':controls,
        'station_metadata':sites,'source_profiles':source,'cost':source_cost(cache,source['profiles']),
        'code_correctness':'REQUIRES_SEPARATE_CONTRACT_TEST_RESULTS',
        'physical_admissibility':'CONDITIONAL_HYDROSTATIC_AIR_ONLY_SEE_PER_TARGET_BLOCKERS',
        'P2_source_reference_qualification':'NOT_ESTABLISHED_MATCHING_SURFACE_AND_LNSP_PIPELINE_REQUIRED',
        'independent_accuracy':'NOT_TESTED_NO_STATION_SCORES_OR_NEW_HOLDOUT',
        'operational_readiness':'NOT_READY','station_height_qualified_count':0,
        'B4_qualified':False,'production_epw_ready':False,'native_CDS_GRIB_identity':False,
        'native_future_CanESM5_pressure_recovered':False,
        'next_station_validation_gate':['HISTORICAL_SENSOR_HEIGHT_AND_DATUM_AT_DE_CH',
            'MATCHING_MODEL_LEVEL_SURFACE_PHI_AND_LNSP_WITHOUT_EMPIRICAL_SHIFT',
            'BOUNDED_REGIONAL_SOURCE_EXTRACTION_FOR_FULL_HOURLY_COHORT',
            'FROZEN_OUT_OF_SAMPLE_PROTOCOL_BEFORE_ANY_NEW_OBSERVATIONS'],
        'temperature_donor_changed':False,'old_2013_2014_regressions_changed_or_tuned':False,
        'wall_seconds':time.perf_counter()-start}
    (out/'reference_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'report':str(out/'reference_probe.json'),'complete_source_hours':result['cost']['complete_source_hours'],
        'network_bytes':cache.downloaded,'wall_seconds':result['wall_seconds'],'station_height_qualified_count':0}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True);parser.add_argument('--private-cache',required=True)
    parser.add_argument('--probe-profiles',action='store_true')
    args=parser.parse_args();run(args.out,args.private_cache,args.probe_profiles)
