"""Offline V1 source admission and, when present, actual held-out source replay."""
from __future__ import annotations
import argparse
from hashlib import sha256
import io,json,subprocess,time,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from v1_prepare import ROOT,R,BASE,REG,ADMISSION,EXPOSURE,META,INPUTS,CONTROLS,PREDICTIONS,LEDGER,SEAL,RESULTS,registered,code_hashes
from v1_run import PROFILES,PAIRS,make_predictions,score_predictions,quantize
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from a15_verify import verify as verify_parent
LIVING={'docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md','research/ige_cmip6/e2e_two_product_roadmap_20261025.json'}


def protection():
    subprocess.run(['git','merge-base','--is-ancestor',BASE,'HEAD'],cwd=ROOT,check=True)
    for line in subprocess.check_output(['git','diff','--name-status',BASE],cwd=ROOT,text=True).splitlines():
        status,name=line.split('\t',1)
        if status!='A' and name not in LIVING:raise ValueError('V1_OLD_CORE_UI_OR_SCIENTIFIC_RESULT_CHANGED:'+name)
    plan=registered()
    for name,digest in plan['protected_core_sha256'].items():
        if sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('V1_FROZEN_ESTIMATOR_OR_MEAN_INVERSE_CHANGED')
    return {'parent_commit':BASE,'existing_engine_UI_and_scientific_results_byte_unchanged':True,
        'only_existing_file_exceptions':sorted(LIVING),'main_or_merge_used':False,
        'station_scope':['AT','DE','CH'],'IV1_2022_values_opened':False}


def numeric_json_equal(a,b,tolerance=1.1e-8):
    if isinstance(a,dict):return isinstance(b,dict) and set(a)==set(b) and all(numeric_json_equal(v,b[k],tolerance) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(numeric_json_equal(x,y,tolerance) for x,y in zip(a,b))
    if isinstance(a,bool) or a is None or isinstance(a,str):return type(a)==type(b) and a==b
    if isinstance(a,int):return isinstance(b,int) and not isinstance(b,bool) and a==b
    if isinstance(a,float):return isinstance(b,(float,int)) and not isinstance(b,bool) and abs(a-b)<=tolerance
    return a==b


def csv_equal(expected,replayed,tolerance=1.1e-10):
    a=pd.read_csv(io.BytesIO(expected));b=pd.read_csv(io.BytesIO(replayed))
    if list(a.columns)!=list(b.columns) or a.shape!=b.shape:raise ValueError('V1_REPLAY_CSV_SCHEMA')
    differences={}
    for c in a:
        if pd.api.types.is_numeric_dtype(a[c]) and not pd.api.types.is_bool_dtype(a[c]):
            if not pd.api.types.is_numeric_dtype(b[c]):raise ValueError('V1_REPLAY_NUMERIC_SCHEMA')
            x,y=a[c].to_numpy(dtype=float),b[c].to_numpy(dtype=float)
            if not np.array_equal(np.isnan(x),np.isnan(y)) or not np.allclose(x,y,rtol=0,atol=tolerance,equal_nan=True):
                raise ValueError('V1_REPLAY_CSV_NUMERICAL_CHANGE:'+c)
            finite=np.isfinite(x)&np.isfinite(y);differences[c]=float(np.max(np.abs(x[finite]-y[finite]))) if finite.any() else 0.
        elif not a[c].equals(b[c]):raise ValueError('V1_REPLAY_NONNUMERIC_CHANGE:'+c)
    return {'byte_identical':expected==replayed,'printed_digit_compatibility':True,'absolute_tolerance':tolerance,'max_difference_by_numeric_column':differences}


def verify(output,stage='registration',*,parent=True):
    output.mkdir(parents=True,exist_ok=False);guard=protection();start=time.monotonic()
    if parent:verify_parent(output/'parent_A1_5')
    suite=unittest.TestLoader().discover(str(ROOT/'tools/climate_analyzer/tests'),pattern='test_ige_v1.py')
    begin=time.monotonic();result=unittest.TextTestRunner(verbosity=1).run(suite)
    tests={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'wall_seconds':time.monotonic()-begin,'status':'PASS' if result.wasSuccessful() else 'FAIL',
        'synthetic_control_values_only':True}
    write_exclusive(output/'v1_tests.json',json_bytes(tests))
    if not result.wasSuccessful():raise RuntimeError('V1_TESTS_FAILED')
    for name in (REG,ADMISSION,EXPOSURE,META):write_exclusive(output/name,(R/name).read_bytes())
    replay={}
    if stage=='results':
        seal=json.loads((R/SEAL).read_text())
        if seal['code_sha256']!=code_hashes() or seal['control_bodies_opened'] is not False:raise ValueError('V1_METHOD_CHANGED_AFTER_TARGETS')
        for name,digest in seal['frozen_files_sha256'].items():
            if sha256((R/name).read_bytes()).hexdigest()!=digest:raise ValueError('V1_ACTUAL_PRECONTROL_SEAL_BYTES_CHANGED')
        raw,profiles,ledger=make_predictions()
        replay['predictions']=csv_equal((R/PREDICTIONS).read_bytes(),raw)
        replay['CH_inverse_profiles']=csv_equal((R/PROFILES).read_bytes(),profiles)
        saved=json.loads((R/LEDGER).read_text())
        if not numeric_json_equal(saved,ledger,tolerance=1e-12):raise ValueError('V1_REPLAY_PREDICTION_LEDGER_CHANGED')
        scored,pairs=score_predictions((R/PREDICTIONS).read_bytes(),saved)
        if not numeric_json_equal(json.loads((R/RESULTS).read_text()),quantize(scored)):
            raise ValueError('V1_ACTUAL_CONTROL_SCORING_REPLAY_CHANGED')
        pair_raw=pd.DataFrame(pairs).to_csv(index=False,float_format='%.10f',lineterminator='\n').encode()
        replay['pairs']=csv_equal((R/PAIRS).read_bytes(),pair_raw)
        replay['scores_within_registered_printed_digits']=True
        for name in (PREDICTIONS,PROFILES,LEDGER,SEAL,RESULTS,PAIRS):write_exclusive(output/name,(R/name).read_bytes())
    elif stage!='registration':raise ValueError('V1_UNKNOWN_VERIFY_STAGE')
    parent_tests=json.loads((output/'parent_A1_5/tests.json').read_text())['tests_run'] if parent else 0
    summary={'schema':'IGE_V1_OFFLINE_VERIFICATION_v1','stage':stage,'tests':tests,
        'parent_A1_5_tests':parent_tests,'total_tests':parent_tests+tests['tests_run'],
        'protection':guard,'registration_metadata_cases_ready':24,'method_code_sha256':code_hashes(),
        'actual_source_replay':replay,'wall_seconds':time.monotonic()-start,
        'accuracy_report_produced':stage=='results','independent_regional_full_weather_accuracy_qualified':False,
        'production_ready':False,'actual_EnergyPlus_run':False,'network_used_by_verifier':False}
    write_exclusive(output/'v1_verification.json',json_bytes(summary))
    print(json.dumps({'V1_stage':stage,'total_tests':summary['total_tests'],'actual_source_replay':replay,'production_ready':False}),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--stage',choices=('registration','results'),default='registration')
    p.add_argument('--without-parent',action='store_true');a=p.parse_args();verify(a.out,a.stage,parent=not a.without_parent)
