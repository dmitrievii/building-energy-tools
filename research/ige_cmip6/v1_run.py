"""Frozen V1 B0/R1 predictions, then strictly separate held-out scoring."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io,json,math
from pathlib import Path
import numpy as np
import pandas as pd
import zipfile
from v1_prepare import (ROOT,R,REG,ADMISSION,INPUTS,CONTROLS,PREDICTIONS,LEDGER,SEAL,RESULTS,
    WINDOWS,PRODUCT,registered,code_hashes)
from v1_acquire import read_packet,publication_gate
from v1_time_admission import selected_swiss,selected_dwd,bind,decode_at
from epw_climate_analyzer.station_reconstruction import (
    StationReference,T,distance_km,model_reference_operator,reconstruct_temperature,decode_geosphere_hourly)
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.engine.station_year import reconstruct_nodes
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
PROFILES='v1_CH_inverse_profiles_20261026.csv'
PAIRS='v1_paired_temperatures_20261026.csv'


def sources(name,phase):
    bodies,m,storage=read_packet(R,name,phase=phase);plan=registered()
    expected={s['id']:s for s in plan[phase]}
    if m['registration_sha256']!=sha256((R/REG).read_bytes()).hexdigest() or len(m['sources'])!=len(expected) or {r['id'] for r in m['sources']}!=set(expected):
        raise ValueError('V1_SOURCE_REGISTRATION_OR_CENSUS')
    if set(bodies)!={s['member'] for s in m['sources'] if s['status']=='ORIGINAL_BODY_RECEIVED'}:
        raise ValueError('V1_SOURCE_UNREGISTERED_BODY')
    for row in m['sources']:
        spec=expected[row['id']]
        if any(row[k]!=spec[k] for k in ('id','station_key','kind','role','url','member')):
            raise ValueError('V1_SOURCE_CONTRACT_CHANGED')
        if row['status']=='ORIGINAL_BODY_RECEIVED':
            raw=bodies[row['member']]
            if len(raw)!=row['bytes'] or sha256(raw).hexdigest()!=row['sha256']:raise ValueError('V1_SOURCE_RECEIPT_HASH')
    if m['control_bodies_opened_this_phase']!=(phase=='controls'):raise ValueError('V1_SOURCE_PHASE_LEAKAGE')
    return bodies,m,storage


def model_temperature(raw,spec):
    obj=json.loads(raw)
    if obj.get('utc_offset_seconds')!=0 or obj.get('hourly_units',{}).get('temperature_2m')!='°C':
        raise ValueError('V1_MODEL_UTC_OR_UNIT')
    h=obj['hourly'];index=pd.to_datetime(h['time'],utc=True)
    if not index.equals(pd.date_range('2018-01-01',periods=8760,freq='h',tz='UTC')):raise ValueError('V1_MODEL_CALENDAR_CHANGED')
    values=h['temperature_2m']
    if len(values)!=len(index) or any(v is not None and (isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v)) for v in values):
        raise ValueError('V1_MODEL_VALUE_AXIS_OR_TYPE')
    c=spec['station_key'].split(':')[0];params=spec['parameters']
    req=StationReference(c,'request','request',float(params['latitude']),float(params['longitude']),0.,'0'*64)
    grid=StationReference(c,'grid','grid',float(obj['latitude']),float(obj['longitude']),0.,'0'*64)
    distance=distance_km(req,grid)
    if distance>50:raise ValueError('V1_MODEL_GRID_OVER_50KM')
    s=pd.Series(np.asarray(values,dtype=float),index=index,name=T);s=s.where(s.between(-80,65));s.attrs['unit']='°C'
    return s,{'requested_xy':[req.latitude,req.longitude],'returned_xy':[grid.latitude,grid.longitude],
        'grid_separation_km':distance,'provider_elevation_unverified':obj.get('elevation'),
        'model':'era5','elevation_request':'nan','native_orography_and_vertical_transfer_qualified':False,
        'missing_or_out_of_domain_hours':int(s.isna().sum())}


def dwd_product(raw,sid):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if Path(n).name==n and n.startswith('produkt_zehn_min_tu_') and n.endswith('_'+sid+'.txt')]
        if len(names)!=1:raise ValueError('V1_DE_ORIGINAL_OBSERVATION_MEMBER_NOT_UNIQUE')
        name=names[0]
        if z.getinfo(name).file_size>150_000_000:raise ValueError('V1_DE_UNCOMPRESSED_MEMBER_BUDGET')
        return z.read(name),name


def station_values(raw,key,record,first,last,*,field=None,all_ten=False):
    c,sid=key.split(':');ref=admitted_reference(record)
    if c=='CH':
        return selected_swiss(raw,sid,first,last,field=field or 'tre200h0',hour_nodes_only=not all_ten)
    if c=='DE':
        product,_=dwd_product(raw,sid)
        result=bind(selected_dwd(product,ref,first,last),record,provider_field='TT_10')
    else:
        batch=decode_at(raw,ref)
        # Whole original AT request is a single dated station. Select support
        # after schema/native-QC decoding, never alter timestamps or QC flags.
        result=bind(batch,record,provider_field='tl')
    if result is None:
        clock=pd.DatetimeIndex([],tz='UTC');return pd.Series([],index=clock,dtype=float),pd.Series([],index=clock,dtype=bool)
    values,mask=result
    values=values.loc[first:last].copy();mask=mask.reindex(values.index).copy()
    values.attrs.update(unit='°C',reference_operator=record['time_contract']['operator'])
    return values,mask


def make_predictions():
    plan=registered();admission=json.loads((R/ADMISSION).read_text());bodies,m,storage=sources(INPUTS,'inputs')
    model={};obs={};diagnostics={}
    for spec in plan['inputs']:
        row=next(x for x in m['sources'] if x['id']==spec['id']);key=spec['station_key']
        if row['status']!='ORIGINAL_BODY_RECEIVED':diagnostics[spec['id']]={'status':'SOURCE_BLOCKED','reason':'ORIGINAL_BODY_NOT_RECEIVED'};continue
        try:
            if spec['kind']=='model_background':model[key],diagnostics[spec['id']]=model_temperature(bodies[spec['member']],spec)
            else:
                if key in plan['target_keys']:raise ValueError('V1_TARGET_OBSERVATION_IN_PREDICTOR')
                obs[key]=bodies[spec['member']]
        except (ValueError,KeyError,TypeError) as exc:
            diagnostics[spec['id']]={'status':'SOURCE_BLOCKED','reason':type(exc).__name__+':'+str(exc)[:180]}
    frames=[];cases=[];profiles=[]
    for group in admission['groups']:
        key=group['target_key'];country=key[:2];record=admission['records'][key]
        op=record['time_contract']['operator']
        for window in WINDOWS:
            first,last=pd.Timestamp(window['start_UTC']),pd.Timestamp(window['end_UTC']);clock=pd.date_range(first,last,freq='h')
            work_clock=pd.date_range(first-pd.Timedelta(hours=72),last,freq='h') if country=='CH' else clock
            frame=pd.DataFrame({'target_key':key,'country':country,'season':window['season'],
                'reference_time_UTC':clock.strftime('%Y-%m-%dT%H:%M:%SZ'),'B0_C':np.nan,'R1_C':np.nan,
                'R1_predicted':False,'accepted_donor_count':0,'B0_endpoint_C':np.nan,'R1_endpoint_C':np.nan,
                'endpoint_eligible':False,'status':'SOURCE_BLOCKED'})
            reasons=[]
            for slot,d in enumerate(group['donors'],1):frame['donor_'+str(slot)]=d;frame['weight_'+str(slot)]=0.
            if not group['metadata_ready']:reasons.append('SOURCE_TIME_GEOMETRY_NOT_ADMITTED')
            elif key not in model:reasons.append('TARGET_BACKGROUND_NOT_RECEIVED_OR_ADMITTED')
            else:
                baseline=model_reference_operator(model[key],work_clock,op)
                frame['B0_C']=baseline.reindex(clock).to_numpy();frame['B0_endpoint_C']=model[key].reindex(clock).to_numpy()
                references=[];values={};background={};quality={}
                for d in group['donors']:
                    r=admission['records'][d];references.append(admitted_reference(r))
                    try:
                        if d not in obs or d not in model:raise ValueError('DONOR_OR_BACKGROUND_SOURCE_NOT_RECEIVED')
                        v,q=station_values(obs[d],d,r,work_clock[0],work_clock[-1]);values[d]=v;quality[d]=q
                        background[d]=model_reference_operator(model[d],work_clock,op)
                    except (ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
                        reasons.append(d+':'+type(exc).__name__+':'+str(exc)[:180])
                        values[d]=pd.Series(np.nan,index=work_clock);quality[d]=pd.Series(False,index=work_clock)
                        background[d]=pd.Series(np.nan,index=work_clock)
                    values[d].attrs.update(unit='°C',reference_operator=op)
                    background[d].attrs.update(unit='°C',reference_operator=op)
                estimated,ledger=reconstruct_temperature(admitted_reference(record),baseline,references,values,background,quality)
                part=ledger.reindex(clock);frame['R1_C']=estimated.reindex(clock).to_numpy()
                frame['R1_predicted']=part.candidate_admitted.to_numpy();frame['accepted_donor_count']=part.accepted_donor_count.to_numpy()
                frame['status']=np.where(frame.R1_predicted,'PREDICTED','INPUT_QC_OR_COVERAGE_BLOCKED')
                for slot,d in enumerate(group['donors'],1):frame['weight_'+str(slot)]=part['weight__'+d].to_numpy()
                if country=='CH':
                    nodes_clock=work_clock.insert(0,work_clock[0]-pd.Timedelta(hours=1))
                    if model[key].reindex(nodes_clock).notna().all():
                        nodes,inverse=reconstruct_nodes(model[key].reindex(nodes_clock),estimated)
                        eligible=estimated.notna().rolling(73,min_periods=73).sum().eq(73)
                        frame['R1_endpoint_C']=nodes.reindex(clock).to_numpy();frame['endpoint_eligible']=eligible.reindex(clock).to_numpy()
                        inv=inverse.reset_index(names='reference_time_UTC');inv.insert(0,'season',window['season']);inv.insert(0,'target_key',key)
                        inv['endpoint_accuracy_eligible']=eligible.to_numpy();profiles.append(inv)
                    else:reasons.append('CH_ENDPOINT_BACKGROUND_MISSING; NO_SILENT_BOUNDARY_FILL')
            cases.append({'target_key':key,'country':country,'season':window['season'],
                'metadata_ready':group['metadata_ready'],'requested_hours':168,'frozen_donors':group['donors'],
                'B0_reference_hours':int(frame.B0_C.notna().sum()),'R1_predicted_hours':int(frame.R1_predicted.sum()),
                'endpoint_eligible_hours':int(frame.endpoint_eligible.sum()),'source_block_reasons':reasons,
                'control_values_read':False})
            frames.append(frame)
    f=pd.concat(frames,ignore_index=True)
    if len(f)!=4032 or f.duplicated(['target_key','reference_time_UTC']).any():raise ValueError('V1_PREDICTION_CENSUS_CHANGED')
    raw=f.to_csv(index=False,float_format='%.10f',na_rep='',lineterminator='\n').encode()
    p=pd.concat(profiles,ignore_index=True) if profiles else pd.DataFrame()
    profile_raw=p.to_csv(index=False,float_format='%.10f',na_rep='',lineterminator='\n').encode()
    ledger={'schema':'IGE_V1_PRECONTROL_PREDICTION_LEDGER_v1','cases':cases,'source_diagnostics':diagnostics,
        'requested_reference_hours':4032,'predicted_primary_hours':int(f.R1_predicted.sum()),
        'endpoint_eligible_hours':int(f.endpoint_eligible.sum()),'all24_cases_retained':True,
        'control_observation_input':False,'input_original_packet_sha256':storage['sha256']}
    return raw,profile_raw,ledger


def predict(output,registration_commit):
    gate=publication_gate('registration',registration_commit);raw,profiles,ledger=make_predictions()
    output.mkdir(parents=True,exist_ok=False)
    write_exclusive(output/PREDICTIONS,raw);write_exclusive(output/PROFILES,profiles);write_exclusive(output/LEDGER,json_bytes(ledger))
    info=json.loads((R/(INPUTS+'.storage.json')).read_text())
    files={n:sha256(b).hexdigest() for n,b in [(PREDICTIONS,raw),(PROFILES,profiles),(LEDGER,json_bytes(ledger))]}
    for name in [INPUTS+'.storage.json',*[p['name'] for p in info['parts']]]:files[name]=sha256((R/name).read_bytes()).hexdigest()
    seal={'schema':'IGE_V1_ACTUAL_PRECONTROL_PREDICTION_SEAL_v1','created_UTC':datetime.now(timezone.utc).isoformat(),
        'registration_publication_gate':gate,'code_sha256':code_hashes(),'frozen_files_sha256':files,
        'input_original_packet_sha256':info['sha256'],'control_bodies_opened':False,
        'all24_cases_retained':True,'requested_reference_hours':4032,
        'R1_predicted_reference_hours':ledger['predicted_primary_hours'],
        'CH_endpoint_eligible_hours':ledger['endpoint_eligible_hours'],'no_target_observation_input':True}
    write_exclusive(output/SEAL,json_bytes(seal));print(json.dumps({'predicted_hours':ledger['predicted_primary_hours'],
        'CH_endpoint_eligible_hours':ledger['endpoint_eligible_hours'],'seal_sha256':sha256(json_bytes(seal)).hexdigest()}),flush=True)


def load_predictions(raw):
    f=pd.read_csv(io.BytesIO(raw));f['reference_time_UTC']=pd.to_datetime(f.reference_time_UTC,utc=True)
    for c in ('R1_predicted','endpoint_eligible'):
        if f[c].dtype!=bool:raise ValueError('V1_PREDICTION_BOOLEAN_SCHEMA')
    if len(f)!=4032 or f.duplicated(['target_key','reference_time_UTC']).any():raise ValueError('V1_PREDICTION_CENSUS')
    return f


def metrics(error):
    x=np.asarray(error,dtype=float)
    if not np.isfinite(x).all():raise ValueError('V1_NONFINITE_SCORED_ERROR')
    return {'n':len(x),'MAE_K':float(np.abs(x).mean()) if len(x) else None,
        'RMSE_K':float(np.sqrt(np.mean(x*x))) if len(x) else None,'bias_K':float(x.mean()) if len(x) else None,
        'centred_RMSE_K':float(np.sqrt(np.mean((x-x.mean())**2))) if len(x) else None}


def summarize_blocks(blocks):
    """Synchronous season blocks keep within-country same-weather sites together."""
    nonempty=[(np.concatenate([a for a,b in pairs]),np.concatenate([b for a,b in pairs]))
        for _,pairs in sorted(blocks.items()) if pairs and sum(len(a) for a,b in pairs)]
    if not nonempty:return {'B0':metrics([]),'R1':metrics([]),'delta_MAE_K':None,'season_blocks':0,'resampling_95pct_descriptive':None}
    e0=np.concatenate([a for a,b in nonempty]);e1=np.concatenate([b for a,b in nonempty])
    r={'B0':metrics(e0),'R1':metrics(e1),'delta_MAE_K':float(np.abs(e1).mean()-np.abs(e0).mean()),
        'season_blocks':len(nonempty),'resampling_95pct_descriptive':None}
    if len(nonempty)>=2:
        sizes=np.array([len(a) for a,b in nonempty]);sums=np.array([np.abs(b).sum()-np.abs(a).sum() for a,b in nonempty])
        rng=np.random.Generator(np.random.PCG64(20261026));draws=rng.integers(0,len(nonempty),size=(10000,len(nonempty)))
        delta=sums[draws].sum(axis=1)/sizes[draws].sum(axis=1);lo,hi=np.quantile(delta,[.025,.975],method='linear')
        r['resampling_95pct_descriptive']={'lower_K':float(lo),'upper_K':float(hi),'draws':10000,'seed':20261026,
            'unit':'synchronous season-week across both country stations','population_confidence_guarantee':False}
    return r


def observed_six_mean(values,clock):
    samples=np.column_stack([values.reindex(clock-pd.Timedelta(minutes=m)).to_numpy(dtype=float) for m in (50,40,30,20,10,0)])
    complete=np.isfinite(samples).all(axis=1)
    return np.where(complete,np.mean(samples,axis=1),np.nan)


def score_predictions(prediction_raw,ledger):
    plan=registered();admission=json.loads((R/ADMISSION).read_text());bodies,m,info=sources(CONTROLS,'controls')
    predicted=load_predictions(prediction_raw)
    expected={(k,w['season']) for k in plan['target_keys'] for w in WINDOWS}
    if len(ledger['cases'])!=24 or {(c['target_key'],c['season']) for c in ledger['cases']}!=expected:
        raise ValueError('V1_ALL_REGISTERED_CASES_MUST_BE_RETAINED')
    if set(predicted.target_key)!=set(plan['target_keys']):raise ValueError('V1_REGISTERED_PREDICTION_TARGETS_CHANGED')
    control={};receipts={x['id']:x for x in m['sources']}
    for spec in plan['controls']:
        if receipts[spec['id']]['status']=='ORIGINAL_BODY_RECEIVED':control[(spec['station_key'],spec['kind'])]=bodies[spec['member']]
    cases=[];pairs=[];secondary=[];country_blocks={c:{} for c in ('AT','DE','CH')};target_blocks={k:{} for k in plan['target_keys']}
    for case in ledger['cases']:
        key,season,country=case['target_key'],case['season'],case['country'];w=next(w for w in WINDOWS if w['season']==season)
        first,last=pd.Timestamp(w['start_UTC']),pd.Timestamp(w['end_UTC']);clock=pd.date_range(first,last,freq='h')
        p=predicted[(predicted.target_key==key)&(predicted.season==season)].reset_index(drop=True)
        if len(p)!=168 or not pd.DatetimeIndex(p.reference_time_UTC).equals(clock):raise ValueError('V1_PREDICTION_CASE_CLOCK_CHANGED')
        result={'target_key':key,'country':country,'season':season,'requested_hours':168,
            'prediction_hours':case['R1_predicted_hours'],'control_primary_QC_hours':0,'paired_hours':0,
            'status':'SOURCE_BLOCKED','source_block_reasons':list(case['source_block_reasons']),
            'B0_all_reference':metrics([]),'B0_paired':metrics([]),'R1_paired':metrics([]),'delta_MAE_K':None,
            'admitted_for_country_block_estimate':False}
        observed=None;primary=None
        try:
            raw=control[(key,'station_temperature')]
            observed,primary=station_values(raw,key,admission['records'][key],first,last)
            observed=observed.reindex(clock).to_numpy(dtype=float);ok=primary.reindex(clock).eq(True).to_numpy(dtype=bool)&np.isfinite(observed)
            b0=p.B0_C.to_numpy(dtype=float);r1=p.R1_C.to_numpy(dtype=float)
            common=ok&np.isfinite(b0)&np.isfinite(r1)&p.R1_predicted.to_numpy()
            all0=ok&np.isfinite(b0);e0=b0[common]-observed[common];e1=r1[common]-observed[common];n=int(common.sum())
            result.update(control_primary_QC_hours=int(ok.sum()),paired_hours=n,
                status='ADMITTED_HOURLY_ERROR_HOLDOUT' if n>=160 else 'PARTIAL_DESCRIPTIVE_ONLY',
                B0_all_reference=metrics(b0[all0]-observed[all0]),B0_paired=metrics(e0),R1_paired=metrics(e1),
                delta_MAE_K=float(np.abs(e1).mean()-np.abs(e0).mean()) if n else None,
                admitted_for_country_block_estimate=n>=160)
            if country=='AT':
                batch=decode_at(raw,admitted_reference(admission['records'][key]))
                part=batch.data.reindex(clock);result['control_native_quality_counts']={str(k):int(v) for k,v in part['quality_flag__'+T].value_counts(dropna=False).items()}
                result['automatic_original_12_secondary_hours']=int(part['secondary_quality__'+T].eq(True).sum())
            if n>=160:
                country_blocks[country].setdefault(season,[]).append((e0,e1));target_blocks[key].setdefault(season,[]).append((e0,e1))
            for i in np.flatnonzero(common):pairs.append({'target_key':key,'country':country,'season':season,
                'operator':admission['records'][key]['time_contract']['operator'],'reference_time_UTC':clock[i].isoformat(),
                'observed_C':float(observed[i]),'B0_C':float(b0[i]),'R1_C':float(r1[i])})
        except (KeyError,ValueError,TypeError,zipfile.BadZipFile) as exc:
            result['source_block_reasons'].append('CONTROL:'+type(exc).__name__+':'+str(exc)[:180])
        cases.append(result)
        if country!='CH':continue
        sec={'target_key':key,'season':season,'status':'SOURCE_BLOCKED','B0_endpoint':metrics([]),'R1_endpoint':metrics([]),
            'endpoint_paired_hours':0,'same_instrument_h_t_not_independent_replicates':True,'reason':None}
        try:
            t_raw=control[(key,'station_endpoint_temperature')]
            ten,ten_ok=station_values(t_raw,key,admission['records'][key],first-pd.Timedelta(minutes=50),last,field='tre200s0',all_ten=True)
            ten=ten.where(ten_ok);obs=ten.reindex(clock).to_numpy(dtype=float)
            e0=p.B0_endpoint_C.to_numpy(dtype=float);e1=p.R1_endpoint_C.to_numpy(dtype=float)
            common=np.isfinite(obs)&np.isfinite(e0)&np.isfinite(e1)&p.endpoint_eligible.to_numpy()
            six=observed_six_mean(ten,clock)
            hmask=np.isfinite(six)&np.isfinite(observed)&primary.reindex(clock).eq(True).to_numpy(dtype=bool) if observed is not None and primary is not None else np.zeros(168,dtype=bool)
            steps0=np.abs(np.diff(e0));steps1=np.abs(np.diff(e1));finite1=steps1[np.isfinite(steps1)]
            sec.update(status='SCORED_SECONDARY_ENDPOINT_HOLDOUT',B0_endpoint=metrics(e0[common]-obs[common]),
                R1_endpoint=metrics(e1[common]-obs[common]),endpoint_paired_hours=int(common.sum()),
                h_minus_t_six_nominal_node_mean=metrics(observed[hmask]-six[hmask]) if observed is not None else metrics([]),
                endpoint_step_diagnostics={'B0_max_K':float(np.max(steps0)) if np.isfinite(steps0).all() else None,
                    'R1_max_K':float(np.max(finite1)) if len(finite1) else None,
                    'R1_p99_K':float(np.quantile(finite1,.99,method='linear')) if len(finite1) else None,
                    'step_pairs':len(finite1),'step_diagnostics_are_not_an_accuracy_test':True})
        except (KeyError,ValueError,TypeError) as exc:sec['reason']=type(exc).__name__+':'+str(exc)[:180]
        secondary.append(sec)
    countries={c:summarize_blocks(b) for c,b in country_blocks.items()}
    for c,r in countries.items():
        admitted=sum(x['country']==c and x['admitted_for_country_block_estimate'] for x in cases)
        upper=r['resampling_95pct_descriptive']
        r.update(admitted_cases=admitted,registered_cases=8,
            benefit_demonstrated_in_registered_cohort=bool(admitted==8 and r['delta_MAE_K'] is not None and r['delta_MAE_K']<0 and upper and upper['upper_K']<0),
            independent_regional_or_global_accuracy_qualified=False)
    return {'schema':'IGE_V1_PREREGISTERED_HOURLY_ERROR_VALIDATION_RESULTS_v1',
        'status':'LIMITED_NEW_HOURLY_ERROR_HOLDOUT_WITH_EXPOSURE_DISCLOSURE',
        'cases':cases,'per_country':countries,'per_target':{k:summarize_blocks(b) for k,b in target_blocks.items()},
        'secondary_CH_endpoint_cases':secondary,'counts':{'registered_cases':24,
            'admitted_primary_cases':sum(c['admitted_for_country_block_estimate'] for c in cases),
            'source_blocked_cases':sum(c['status']=='SOURCE_BLOCKED' for c in cases),
            'partial_cases':sum(c['status']=='PARTIAL_DESCRIPTIVE_ONLY' for c in cases),
            'paired_primary_hours':len(pairs),'requested_primary_hours':4032},
        'source_costs':{'control_HTTP_attempts':m['HTTP_attempts_this_phase'],
            'cumulative_decoded_body_bytes':m['decoded_body_bytes_read_all_attempts'],'original_control_packet_sha256':info['sha256']},
        'target_values_read_only_after_published_actual_prediction_seal':True,
        'strict_global_raw_byte_blindness_certified':False,'independence_from_ERA5_station_assimilation_certified':False,
        'four_axes':{'execution_correctness':'requires offline replay and CI, reported separately',
            'physical_admissibility':'T range/operator/dated2m only; existing full-weather conditional closure unchanged',
            'independent_accuracy':'new hourly-error cohort assessment only; prior coarse products and bounded audit disclosed; no regional full-weather qualification',
            'operational_readiness':'research only; EnergyPlus, general coordinates, future local multiyear reference and production remain open'},
        'pressure_RH_q_or_future_NASA_accuracy_qualified':False,'production_ready':False,
        'UI_EPW_defaults_changed':False,'IV1_2022_observations_opened':False},pairs


def quantize(obj):
    if isinstance(obj,dict):return {k:quantize(v) for k,v in obj.items()}
    if isinstance(obj,list):return [quantize(v) for v in obj]
    if isinstance(obj,(float,np.floating)):
        if not math.isfinite(float(obj)):raise ValueError('V1_NONFINITE_SERIALIZATION')
        value=round(float(obj),8);return 0. if value==0 else value
    if isinstance(obj,np.integer):return int(obj)
    return obj


def score(output,seal_commit):
    publication_gate('predictions',seal_commit)
    result,pairs=score_predictions((R/PREDICTIONS).read_bytes(),json.loads((R/LEDGER).read_text()))
    output.mkdir(parents=True,exist_ok=False)
    write_exclusive(output/RESULTS,json_bytes(quantize(result)))
    write_exclusive(output/PAIRS,pd.DataFrame(pairs).to_csv(index=False,float_format='%.10f',lineterminator='\n').encode())
    print(json.dumps(quantize({'counts':result['counts'],'per_country':result['per_country']})),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('predict','score'),required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--published-commit',required=True);a=p.parse_args()
    if a.phase=='predict':predict(a.out,a.published_commit)
    else:score(a.out,a.published_commit)
