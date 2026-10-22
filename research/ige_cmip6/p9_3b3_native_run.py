"""Native source controls -> dated sensors -> sealed P1/P2 -> revealed scoring."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import subprocess
import time

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_native_columns import NativeColumns
from p9_3b3_native_heights import historical_heights
from p9_3b3_native_sources import NativeCache
from p9_3b3_native_validation import score_pressure,score_sealed,target_hours
from p9_3b3_reference_run import protected_controls


ROOT=Path(__file__).resolve().parents[2]
PROTOCOL=Path(__file__).with_name('p9_3b3_native_protocol.json')
METHODS=('P1_ISOTHERMAL_SAME_SINGLE_ANCHOR','P1_FIXED_LAPSE_0.0065_SAME_SINGLE_ANCHOR',
         'P2_NATIVE_SINGLE_COLUMN','P2_NATIVE_UP_TO_FOUR_COLUMNS')


def write_json(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def protocol_guard(p):
    expected={'countries':['AT','DE','CH'],'development_days':['2021-02-01','2021-08-01'],
        'methods':list(METHODS),'maximum_neighbor_columns':4,'weights':'INVERSE_SQUARED_GEOMETRIC_DISTANCE_SOURCE_ONLY',
        'anchor':'SINGLE_WEIGHTED_LOG_P_AT_COMMON_AIR_TOP','underground_policy':'BLOCK_NO_EXTRAPOLATION',
        'gas':'B3_GAS_CONSISTENT','thermo_height_AGL_m':2.0,'minimum_cell_coverage':.9,'pressure_MAE_gate_hPa':2.0,
        'expected_station_hours':144,'highest_model_level':137}
    if any(p.get(k)!=v for k,v in expected.items()):raise ValueError('P93N_PROTOCOL_MODEL_OR_COHORT_DRIFT')
    if not 1<=p['deep_diagnostic_first_model_level']<=p['primary_first_model_level']<=137:
        raise ValueError('P93N_PROTOCOL_LEVEL_RANGE')
    download_cap=2147483648
    if 'resource_completion' in p:
        # The completion experiment may change resources, never the revealed
        # cohort, formulas, geometry, weights, metadata or acceptance gates.
        raw=PROTOCOL.read_bytes();frozen=json.loads(raw);amendment=p['resource_completion']
        allowed={'phase','max_download_bytes','resource_completion'}
        if (hashlib.sha256(raw).hexdigest()!='5c0f3ec123db35e9329f6d511a7bf1154a140581fa6e0181d337983d0806a27c' or
                not isinstance(amendment,dict) or
                set(p)!=set(frozen)|{'resource_completion'} or
                any(p[k]!=v for k,v in frozen.items() if k not in allowed) or
                p['phase']!='P9.3B3_NATIVE_RESOURCE_COMPLETION_AFTER_CI_39753778078' or
                amendment.get('previous_run_id')!=39753778078 or
                amendment.get('reference_protocol_sha256')!=hashlib.sha256(raw).hexdigest() or
                amendment.get('scientific_model_changed') is not False or
                p['max_download_bytes']!=3221225472):
            raise ValueError('P93N_RESOURCE_COMPLETION_CHANGED_FROZEN_SCIENCE')
        download_cap=3221225472
    caps={'max_download_bytes':download_cap,'max_requests':2000,'max_object_bytes':80000000,'max_decompressed_chunk_bytes':80000000}
    if any(type(p.get(k)) is not int or not 0<p[k]<=v for k,v in caps.items()):raise ValueError('P93N_PROTOCOL_RESOURCE_CAP')
    if any(p.get(k) for k in ('B4_qualified','production_epw_ready','native_future_CanESM5_pressure_recovered','merge_main')):
        raise ValueError('P93N_PROTOCOL_UNSUPPORTED_QUALIFICATION')
    return p


def execution_summary(predictions,blockers,source,heights,score,stamps,*,stations):
    """Source execution is separate from terrain coverage and accuracy gates."""
    expected=set(stamps)
    failed={b.get('timestamp_UTC') for b in blockers if b.get('scope')=='PRIMARY_PROFILE'}
    complete=len((expected&set(predictions))-failed)
    lineage=source.get('paired_surface_lineage_status')=='ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'
    heights_complete=set(heights)=={'AT','DE','CH'} and all(h.get('status')==
        'HISTORICAL_SENSOR_HEIGHT_REFERENCES_CONFIRMED_CONDITIONAL_MSL_DATUM' for h in heights.values())
    observations_complete=(not stations or score is not None and
        all(score.get('observation_provenance',{}).get(co,{}).get('status')=='SOURCE_READ' for co in ('AT','DE','CH')))
    cells_complete=not stations or score is not None and len(score.get('cells',[]))==24
    success=lineage and heights_complete and complete==len(expected) and observations_complete and cells_complete
    return {'engineering_execution_status':'COMPLETE_SOURCE_EXECUTION' if success else 'INCOMPLETE_SOURCE_EXECUTION',
        'source_profile_hours_expected':len(expected),'source_profile_hours_complete':complete,
        'source_profile_hours_missing_or_failed':len(expected)-complete,
        'observation_sources_read_without_source_blocker':observations_complete,
        'engineering_success_is_independent_accuracy_qualification':False}


def evaluate_hour(reader,stamp,protocol):
    blockers=[];deep={}
    try:
        cs=reader.read(stamp,protocol['primary_first_model_level']);prediction=reader.predict(cs,stamp)
    except (SourceBlocked,OSError) as exc:
        why=type(exc).__name__+':'+str(exc);blockers.append({'timestamp_UTC':stamp,'scope':'PRIMARY_PROFILE','reason':why})
        prediction={co:{'methods':{m:{'status':'SOURCE_BLOCKED','reason':why} for m in protocol['methods']}} for co in protocol['countries']}
        return prediction,deep,blockers
    if stamp in protocol['source_control_hours']:
        try:
            full=reader.read(stamp,protocol['deep_diagnostic_first_model_level'])
            deep={'predictions':reader.predict(full,stamp),'columns':[asdict(c) for c in full.values()]}
        except (SourceBlocked,OSError) as exc:
            why=type(exc).__name__+':'+str(exc);deep={'status':'SOURCE_BLOCKED','reason':why}
            blockers.append({'timestamp_UTC':stamp,'scope':'DEEP_DIAGNOSTIC_ONLY','reason':why})
    return prediction,deep,blockers


def run(out,private_cache,*,stations=False,cache_only=False,protocol_path=None):
    out=Path(out);cache_path=Path(private_cache)
    if out.exists():raise ValueError('P93N_OUTPUT_EXISTS_NO_OVERWRITE')
    if out.resolve() in (cache_path.resolve(),*cache_path.resolve().parents):raise ValueError('P93N_PRIVATE_CACHE_INSIDE_OUTPUT')
    protocol_path=PROTOCOL if protocol_path is None else Path(protocol_path)
    start=time.perf_counter();protocol_bytes=protocol_path.read_bytes();p=protocol_guard(json.loads(protocol_bytes));controls=protected_controls(p)
    if p['countries']!=['AT','DE','CH'] or p['expected_station_hours']!=len(target_hours(p))*3:
        raise ValueError('P93N_FROZEN_COUNTRY_COHORT_CONTRACT')
    out.mkdir(parents=True);cache=NativeCache(cache_path,p,cache_only=cache_only)
    manifest={'phase':p['phase'],'protocol_sha256':hashlib.sha256(protocol_bytes).hexdigest(),'protocol_file':protocol_path.name,
        'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'code_sha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(Path(__file__).parent.glob('p9_3b3_native_*.py'))},
        'python':platform.python_version(),'packages':{n:importlib.metadata.version(n) for n in ('numpy','scipy','numcodecs','pyshtools','eccodes','eccodeslib')},
        'protected_control_count':controls['verified_count'],'protected_changed_count':0,
        'started_UTC':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'new_independent_holdout':False,'B4_qualified':False,'production_epw_ready':False,'operational_ready':False,
        'cache_only_mode':cache_only,
        'native_future_CanESM5_pressure_recovered':False,'temperature_donor_changed':False,'old_2013_2014_results_rewritten':False}
    heights=historical_heights(cache,p);write_json(out/'historical_sensor_references.json',heights)
    print('HISTORICAL_REFERENCE_COUNTRIES '+str(sum(h['status']!='SOURCE_BLOCKED' for h in heights.values()))+' / 3',flush=True)
    source={};predictions={};deep={};blockers=[];score=None
    stamps=(sorted(set(target_hours(p)+[(dt.datetime.fromisoformat(day)-dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        for day in p['development_days']])) if stations else p['source_control_hours'])
    try:
        columns=NativeColumns(cache,p,heights);source=columns.controls()
        write_json(out/'native_source_lineage.json',source)
        # Profiles are computed before any station pressure observations open.
        for stamp in stamps:
            print('NATIVE_PROFILE '+stamp,flush=True)
            prediction,diagnostic,errors=evaluate_hour(columns,stamp,p);predictions[stamp]=prediction;blockers.extend(errors)
            if diagnostic:deep[stamp]=diagnostic
    except (SourceBlocked,OSError) as exc:
        why=type(exc).__name__+':'+str(exc);source={'status':'SOURCE_BLOCKED','reason':why};blockers.append({'scope':'NATIVE_SOURCE_INITIALIZATION','reason':why})
        write_json(out/'native_source_lineage.json',source)
    write_json(out/'deep_column_diagnostic.json',deep)
    sealed=out/'sealed_pressure_predictions.json'
    write_json(sealed,{'phase':p['phase'],'protocol_sha256':manifest['protocol_sha256'],'hourly':predictions,
        'scope':'SOURCE_ONLY_PREDICTIONS_BEFORE_STATION_OBSERVATION_ACCESS','no_observation_residual_conditioning':True})
    digest=hashlib.sha256(sealed.read_bytes()).hexdigest();manifest['sealed_prediction_sha256']=digest
    write_json(out/'prediction_seal.json',{'sha256':digest,'station_observations_opened':False})
    if stations:
        if source.get('paired_surface_lineage_status','').startswith('ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED'):
            print('PREDICTIONS_SEALED_OPEN_REVEALED_PRESSURE_OBSERVATIONS',flush=True)
            eligible=[co for co,h in heights.items() if h['status']!='SOURCE_BLOCKED']
            score=score_sealed(sealed,digest,cache,p,eligible_countries=eligible)
        else:
            score={**score_pressure(predictions,{},p),'sealed_prediction_sha256':digest,
                'observation_provenance':{'status':'OBSERVATIONS_NOT_OPENED_NATIVE_LINEAGE_BLOCKED'}}
        write_json(out/'revealed_pressure_scores.json',score)
        manifest['score_cell_count']=len(score['cells'])
    manifest.update(execution_summary(predictions,blockers,source,heights,score,stamps,stations=stations))
    objects={r['url']+'|'+str(r['range']):r for r in cache.records}
    manifest.update(historical_sensor_countries_confirmed=sum(h['status']!='SOURCE_BLOCKED' for h in heights.values()),
        source_lineage_status=source.get('paired_surface_lineage_status',source.get('status','UNKNOWN')),
        expected_station_hours=p['expected_station_hours'],profile_hours_attempted=len(predictions),source_blockers=blockers,
        independent_accuracy='NOT_QUALIFIED_PREVIOUSLY_REVEALED_TWO_DAY_PILOT',
        physical_scope='HYDROSTATIC_NATIVE_AIR_COLUMNS_ONLY_NO_CONDENSATE_NO_SURFACE_LAYER_QUALIFICATION',
        height_datum='HISTORY_REFERENCES_CONFIRMED_WHERE_READ_MSL_TO_GEOPOTENTIAL_CONSTANT_G0_APPROXIMATION',
        network_downloaded_bytes=cache.downloaded,network_requests=cache.requests,
        unique_source_objects=len(objects),source_objects=list(objects.values()),
        unique_source_bytes_including_cache=sum(r['bytes'] for r in objects.values()),
        wall_seconds=time.perf_counter()-start,peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write_json(out/'run_manifest.json',manifest)
    print(json.dumps({k:manifest[k] for k in ('source_lineage_status','historical_sensor_countries_confirmed',
        'profile_hours_attempted','source_profile_hours_complete','engineering_execution_status',
        'network_downloaded_bytes','network_requests','wall_seconds')}),flush=True)
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True);ap.add_argument('--private-cache',required=True)
    ap.add_argument('--stations',action='store_true');ap.add_argument('--cache-only',action='store_true')
    ap.add_argument('--protocol',default=str(PROTOCOL));ap.add_argument('--require-complete-sources',action='store_true')
    a=ap.parse_args(argv);r=run(a.out,a.private_cache,stations=a.stations,cache_only=a.cache_only,protocol_path=a.protocol)
    if a.require_complete_sources and r['engineering_execution_status']!='COMPLETE_SOURCE_EXECUTION':
        print('P93N_INCOMPLETE_SOURCE_EXECUTION_RESULTS_SAVED',flush=True);return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
