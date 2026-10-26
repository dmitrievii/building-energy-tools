"""Metadata-only V1 registration: no station measurement URL is opened here."""
from __future__ import annotations
from dataclasses import asdict, replace
from hashlib import sha256
import io,json,re,subprocess,sys,zipfile,tarfile
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]; R=ROOT/'research/ige_cmip6'
sys.path.insert(0,str(ROOT/'tools/climate_analyzer'))
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.station_reconstruction import StationReference,distance_km,_csv
from epw_climate_analyzer.station_admission import physical_identity,admitted_reference
from a1_prepare import metadata_sources
from a12_prepare_history import wmdr_geometry
from v1_time_admission import operator,dwd_geometry
BASE='040a7473727336d45c9ac1151709ccbaf8b6e245'
META='v1_metadata_sources_20261026.zip'
REG='v1_registration_20261026.json'
ADMISSION='v1_time_geometry_admission_20261026.json'
EXPOSURE='v1_exposure_audit_20261026.json'
INPUTS='v1_input_sources_20261026.zip'
CONTROLS='v1_control_sources_20261026.zip'
PREDICTIONS='v1_predictions_20261026.csv'
LEDGER='v1_prediction_ledger_20261026.json'
SEAL='v1_prediction_seal_20261026.json'
RESULTS='v1_results_20261026.json'
TARGETS=('AT:5609','AT:20123','DE:01270','DE:00232','CH:STG','CH:SCU')
WINDOWS=tuple({'season':s,'start_UTC':f'2018-{m:02d}-10T00:00:00Z',
    'end_UTC':f'2018-{m:02d}-16T23:00:00Z'} for s,m in
    [('winter',1),('spring',4),('summer',7),('autumn',10)])
AT_WSI={'5609':('AT_WMDR_5609.xml','11389'), '20123':('AT_WMDR_20123.xml','11213'),
    '5625':('AT_WMDR_5625.xml','11078'),'3805':('AT_WMDR_3805.xml','11070'),
    '3702':('AT_WMDR_3702_11024.xml','11024'),'3811':('AT_WMDR_3811.xml','11075'),
    '20105':('AT_WMDR_20105.xml','11275'),'20270':('AT_WMDR_20270_11227.xml','11227'),
    '20220':('AT_WMDR_20220_11278.xml','11278')}
DE_PRODUCT='climate-10_minutes-air_temperature'
PRODUCT={'AT':('klima-v2-1h','tl'),'DE':(DE_PRODUCT,'TT_10'),'CH':('ogd-smn-h','tre200h0')}
SMN='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn'
DE_ROOT='https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/'
CODE=['research/ige_cmip6/'+n for n in ('v1_prepare.py','v1_time_admission.py',
    'v1_acquire.py','v1_run.py','v1_verify.py','v1_acquire_metadata.py')]+[
    'tools/climate_analyzer/tests/test_ige_v1.py','.github/workflows/ige-v1-time-admission-20261026.yml']
FROZEN_CORE=['tools/climate_analyzer/epw_climate_analyzer/'+n for n in
    ('station_reconstruction.py','station_admission.py','engine/station_year.py')]


def metadata():
    raw=(R/META).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        m=json.loads(z.read('manifest.json'))
        if m['station_observation_bodies_opened'] is not False:raise ValueError('V1_METADATA_OBSERVATION_LEAKAGE')
        if set(z.namelist())!=set(m['member_sha256'])|{'manifest.json'}:raise ValueError('V1_METADATA_CENSUS')
        bodies={n:z.read(n) for n in m['member_sha256']}
        if any(sha256(bodies[n]).hexdigest()!=h for n,h in m['member_sha256'].items()):raise ValueError('V1_METADATA_MEMBER_HASH')
    return bodies,m


def catalogs(bodies):
    old,_,_=metadata_sources();pool=[]
    first,last=pd.Timestamp('2018-01-01',tz='UTC'),pd.Timestamp('2018-12-31T23:00Z')
    for row in json.loads(old['AT_hourly_v2_metadata.json'])['stations']:
        if row['type']!='INDIVIDUAL' or not pd.Timestamp(row['valid_from'])<=first<=last<=pd.Timestamp(row['valid_to']):continue
        sid=str(row['id']);pool.append(StationReference('AT',sid,row['name'],row['lat'],row['lon'],row['altitude'],
            sha256(old['AT_hourly_v2_metadata.json']).hexdigest(),physical_identity('AT',sid,group_id=row['group_id'])))
    raw=bodies['DE_10min_stations.txt']
    for line in raw.decode('cp1252').splitlines():
        m=re.match(r'^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s{2,}',line)
        if not m:continue
        sid,a,b,h,lat,lon,name=m.groups()
        if a<='20180101' and b>='20181231':pool.append(StationReference('DE',sid,name.strip(),float(lat),float(lon),float(h),sha256(raw).hexdigest(),physical_identity('DE',sid)))
    inventory,_=_csv(old['CH_inventory.csv']);available=set()
    for r in inventory:
        if r['parameter_shortname']!='tre200h0':continue
        a=pd.to_datetime(r['data_since'],format='%d.%m.%Y %H:%M',utc=True)
        b=pd.to_datetime(r['data_till'],format='%d.%m.%Y %H:%M',utc=True) if r['data_till'].strip() else pd.Timestamp('2100-01-01',tz='UTC')
        if a<=first<=last<=b:available.add(r['station_abbr'])
    rows,_=_csv(old['CH_stations.csv'])
    for r in rows:
        sid=r['station_abbr']
        if sid not in available:continue
        pool.append(StationReference('CH',sid,r['station_name'],float(r['station_coordinates_wgs84_lat']),float(r['station_coordinates_wgs84_lon']),float(r['station_height_masl']),sha256(old['CH_stations.csv']).hexdigest(),physical_identity('CH',sid,wsi=r['station_wigos_id'])))
    if len({s.key for s in pool})!=len(pool):raise ValueError('V1_CATALOG_DUPLICATE_IDENTITY')
    return pool


def record(station,first,last,bodies):
    country,sid=station.country,station.station_id
    product,field=PRODUCT[country];op=operator(country,product,field,first,last)
    row={'station_key':station.key,'frozen_station':asdict(station),
        'resolved_identity_group':station.identity_group,'reference_first_UTC':first.isoformat(),
        'reference_last_UTC':last.isoformat(),'time_contract':{'operator':op.published_operator,
        'definition':asdict(op),'true_sensor_filter_known':False},
        'geometry_status':'SOURCE_BLOCKED','geometry':None,'strict_2m_compatible':False,
        'temperature_source_eligible':False,'source_block_reasons':[],'source_evidence_sha256':{}}
    support_first=first-pd.Timedelta(minutes=50) if country=='CH' else first
    try:
        if country=='DE':
            n='DE_10min_meta_'+sid+'.zip';g,e=dwd_geometry(bodies[n],sid,support_first,last)
            e[n]=sha256(bodies[n]).hexdigest()
        else:
            if country=='AT':n,w=AT_WSI[sid];wsi='0-20000-0-'+w
            else:n='CH_WMDR_'+sid+'.xml';wsi=station.identity_group.removeprefix('CH_WIGOS:')
            g=wmdr_geometry(bodies[n],wsi,country,support_first,last);e={n:sha256(bodies[n]).hexdigest()}
        point=replace(station,latitude=g['latitude'],longitude=g['longitude'])
        if distance_km(station,point)>.5:raise ValueError('V1_DATED_SOURCE_IDENTITY_SEPARATION_OVER_500M')
        row.update(geometry=g,geometry_status='DATED_TEMPERATURE_SENSOR_CONFIRMED',source_evidence_sha256=e)
        row['strict_2m_compatible']=g['AGL_m']==2. and g['local_reference_surface'] in ('localGround','naturalGround')
        if not row['strict_2m_compatible']:raise ValueError('V1_STRICT_DATED_2M_REQUIRED')
        row['temperature_source_eligible']=True
        admitted_reference(row)
    except (ValueError,KeyError) as exc:
        row['temperature_source_eligible']=False
        row['source_block_reasons'].append(type(exc).__name__+':'+str(exc))
    return row


def prepare_admission():
    bodies,m=metadata();pool=catalogs(bodies);by={s.key:s for s in pool}
    selected=[by[k] for k in TARGETS];first=pd.Timestamp('2018-01-07T00:00Z');last=pd.Timestamp('2018-10-16T23:00Z')
    # The discovery cap is fixed before weather acquisition: first eight AT,
    # first four DE/CH candidates. Admission uses metadata alone, never coverage/errors.
    records={};groups=[];discovery=[]
    for target in selected:
        candidates=sorted((distance_km(target,s),s.key,s) for s in pool if s.country==target.country
            and s.key not in TARGETS and s.identity_group not in {t.identity_group for t in selected}
            and all(distance_km(s,t)>=5 for t in selected if t.country==s.country)
            and 5<=distance_km(target,s)<=150)
        unique=[];seen=set()
        for d,k,s in candidates:
            if s.identity_group in seen:continue
            seen.add(s.identity_group);unique.append((d,k,s))
            if len(unique)==(8 if target.country=='AT' else 4):break
        for s in [target,*[s for _,_,s in unique]]:
            if s.key not in records:records[s.key]=record(s,first,last,bodies)
        good=[]
        for d,k,s in unique:
            r=records[k]
            if r['temperature_source_eligible'] and records[target.key]['temperature_source_eligible']:
                if not 5<=distance_km(admitted_reference(records[target.key]),admitted_reference(r))<=150:
                    raise ValueError('V1_DATED_DONOR_GEOMETRY_CHANGES_RANK_ADMISSION')
                good.append(k)
        slots=good[:3]
        groups.append({'target_key':target.key,'target_name':target.name,'donors':slots,
            'metadata_ready':records[target.key]['temperature_source_eligible'] and len(slots)>=2,
            'donor_selection':'first three metadata-admitted in fixed nominal-distance candidate order; no weather availability selection',
            'candidate_order':[k for _,k,_ in unique]})
        discovery.extend({'target_key':target.key,'candidate_key':k,'nominal_distance_km':d,
            'admitted':records[k]['temperature_source_eligible'],'selected':k in slots,
            'reason':records[k]['source_block_reasons']} for d,k,s in unique)
    return {'schema':'IGE_V1_TIME_AND_DATED_T2M_ADMISSION_v1','parent_commit':BASE,
        'metadata_packet_sha256':sha256((R/META).read_bytes()).hexdigest(),
        'time_support':'four registered weeks plus 72h predictor spinup; h support starts 50min earlier',
        'records':records,'groups':groups,'metadata_candidate_audit':discovery,
        'ready_cases':4*sum(g['metadata_ready'] for g in groups),'all_cases_retained':24,
        'new_station_measurement_or_model_requests':0,'independent_accuracy_qualified':False,
        'old_DWD_TT_TU_operator_admission_changed':False,'production_ready':False}


def exposure():
    from p8_1e_swiss_external import parse_meta
    from p8_2f_station_selection import metadata_candidates
    from p8_2e_crossyear import POOL,TARGETS as OLD_TARGETS
    old,_,_=metadata_sources();m,_=parse_meta(old['CH_stations.csv'])
    _,old_candidates=metadata_candidates(m,OLD_TARGETS,POOL)
    paths=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'--','research/ige_cmip6','docs','.github/workflows'],cwd=ROOT,text=True).splitlines()
    paths=[p for p in paths if Path(p).suffix in ('.py','.md','.yml','.yaml') and not Path(p).name.startswith('test_')]
    hashes={};mentions={k:[] for k in TARGETS};counts={k:0 for k in TARGETS}
    terms={'AT:5609':['5609','St. Pölten','St.Poelten'],'AT:20123':['20123','Villach'],
        'DE:01270':['01270','Erfurt'],'DE:00232':['00232','Augsburg'],
        'CH:STG':['STG','St. Gallen'],'CH:SCU':['SCU','Scuol']}
    frozen_archive=subprocess.check_output(['git','archive','--format=tar',BASE,'--',*paths],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(frozen_archive)) as archive:
        frozen_bodies={p:archive.extractfile(p).read() for p in paths}
    for p in paths:
        raw=frozen_bodies[p];hashes[p]=sha256(raw).hexdigest()
        for i,line in enumerate(raw.decode('utf-8',errors='replace').splitlines(),1):
            for key,ts in terms.items():
                if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(t)+r'(?![A-Za-z0-9_])',line,re.I) for t in ts):
                    counts[key]+=1
                    if len(mentions[key])<12:mentions[key].append({'path':p,'line':i,'context':line[:200]})
    if set(['STG','SCU']) & set(old_candidates):raise ValueError('V1_PRIOR_2010_2019_CH_HOURLY_POOL_EXPOSURE')
    return {'schema':'IGE_V1_BOUNDED_EXPOSURE_AUDIT_v1','parent_commit':BASE,
        'audited_text_file_sha256':hashes,'text_files':len(hashes),'matches':mentions,'match_counts':counts,
        'old_CH_2010_2019_hourly_candidate_union':old_candidates,
        'old_CH_2020_2029_all_station_wind_container_census_excluded_as_control_year':True,
        'old_2013_2014_and_2025_A1_targets_are_revealed_regressions_only':True,
        'new_2018_hourly_control_values_or_errors_opened':False,
        'known_target_2018_hourly_fit_or_score_use_in_reviewed_scope':False,
        'prior_coarse_temperature_exposure':'AT broad monthly/climatology studies and CH monthly 2011-2020 station studies exist; not certified station-blind',
        'raw_target_2018_hourly_container_prior_use_found_in_reviewed_scope':False,
        'scope_limit':['retained source code/reports/workflows and restored provenance; not every expired Actions body',
            'untracked external archives and unindexed past sessions not certifiable',
            'absence of a text match is not proof of non-use',
            'ERA5 may assimilate station information; this is not independence from the reanalysis assimilation system'],
        'claim_permitted':'new hourly-error holdout relative to frozen R1, with bounded exposure audit and disclosed coarse-product exposure',
        'strict_raw_byte_unseen_global_certification':False,
        'if_new_prior_target_use_found':'retain case in registry, downgrade to revealed; no post-error replacement'}


def source_specs(admission):
    groups=admission['groups'];keys=sorted({g['target_key'] for g in groups if g['metadata_ready']}|{k for g in groups if g['metadata_ready'] for k in g['donors']})
    donors=sorted({k for g in groups if g['metadata_ready'] for k in g['donors']})
    targets=sorted(g['target_key'] for g in groups if g['metadata_ready'])
    bodies,_=metadata();background=[];obs=[];controls=[]
    for key in keys:
        ref=admitted_reference(admission['records'][key])
        params={'latitude':f'{ref.latitude:.6f}','longitude':f'{ref.longitude:.6f}',
            'start_date':'2018-01-01','end_date':'2018-12-31','hourly':'temperature_2m',
            'models':'era5','elevation':'nan','cell_selection':'nearest','timezone':'GMT',
            'timeformat':'iso8601','temperature_unit':'celsius'}
        background.append({'id':'background_'+key.replace(':','_'),'station_key':key,
            'kind':'model_background','role':'background','parameters':params,
            'url':'https://archive-api.open-meteo.com/v1/archive?'+urlencode(params),
            'member':'background_'+key.replace(':','_')+'.json','max_body_bytes':2_000_000})
    for role,these,out in [('donor',donors,obs),('control',targets,controls)]:
        for key in these:
            c,s=key.split(':');suffix='.json' if c=='AT' else '.zip' if c=='DE' else '.csv'
            if c=='AT':
                params={'station_ids':s,'parameters':'tl,tl_flag','output_format':'geojson',
                    'start':'2018-01-07T00:00:00Z','end':'2018-10-16T23:00:00Z'}
                url='https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?'+urlencode(params)
            elif c=='DE':
                matches=sorted(set(re.findall('10minutenwerte_TU_'+s+r'_(\d{8})_(\d{8})_hist.zip',bodies['DE_10min_historical_index.html'].decode())))
                matches=[(a,b) for a,b in matches if a<='20180107' and b>='20181016']
                if len(matches)!=1:raise ValueError('V1_DE_ARCHIVE_DISCOVERY_NOT_UNIQUE:'+key)
                a,b=matches[0];url=DE_ROOT+'historical/'+f'10minutenwerte_TU_{s}_{a}_{b}_hist.zip'
            else:url=f'{SMN}/{s.lower()}/ogd-smn_{s.lower()}_h_historical_2010-2019.csv'
            out.append({'id':role+'_'+key.replace(':','_'),'station_key':key,'kind':'station_temperature',
                'role':role,'url':url,'member':role+'_'+key.replace(':','_')+suffix,
                'max_body_bytes':2_000_000 if c=='AT' else 10_000_000 if c=='DE' else 45_000_000})
    for key in targets:
        c,s=key.split(':')
        if c!='CH':continue
        url=f'{SMN}/{s.lower()}/ogd-smn_{s.lower()}_t_historical_2010-2019.csv'
        stac=json.loads(bodies['CH_STAC_'+s.lower()+'.json'])
        if not any(a['href']==url for a in stac['assets'].values()):raise ValueError('V1_CH_SECONDARY_ASSET_NOT_IN_STAC')
        controls.append({'id':'endpoint_'+key.replace(':','_'),'station_key':key,'kind':'station_endpoint_temperature',
            'role':'control','url':url,'member':'endpoint_'+key.replace(':','_')+'.csv','max_body_bytes':260_000_000})
    return background+obs,controls


def prepare_registration():
    a=prepare_admission();e=exposure();inputs,controls=source_specs(a)
    return {'schema':'IGE_V1_PREREGISTERED_TEMPERATURE_TIME_FORM_VALIDATION_v1','date':'2026-10-26',
        'parent_commit':BASE,'countries':['AT','DE','CH'],'target_keys':list(TARGETS),'windows':list(WINDOWS),
        'targets':'six fixed new hourly-error targets chosen for geography and exposure, not meteorological error; no post-score replacement',
        'groups':a['groups'],'cases':24,'requested_primary_reference_hours':4032,
        'temperature_scope_only':True,'source_time_geometry_admission_sha256':sha256(json_bytes(a)).hexdigest(),
        'exposure_audit_sha256':sha256(json_bytes(e)).hexdigest(),'metadata_packet_sha256':sha256((R/META).read_bytes()).hexdigest(),
        'operators':{c:asdict(operator(c,*PRODUCT[c],WINDOWS[0]['start_UTC'],WINDOWS[-1]['end_UTC'])) for c in ('AT','DE','CH')},
        'method':{'B0':'ERA5-derived Open-Meteo elevation=nan nearest-cell published hourly T, no vertical correction',
            'R1':'unchanged A1 residual IDW2; first3 metadata-admitted fixed donors; min2 native-primary-QC donors per hour',
            'target_observations_or_target_monthly_weather_used_in_predictor':False,
            'distance_exponent':2,'minimum_distance_km':5,'maximum_distance_km':150,
            'lapse_inversion_or_bias_fit':False,'target_aliases_excluded_from_all_donors':True,
            'primary_missing':'raw R1 NaN with explicit ledger, no B0 fill',
            'CH_hourly_model_operator':'5/12 previous + 7/12 current; linear subhourly surrogate, not true continuous hourly average'},
        'secondary_CH_endpoint_test':{'field':'tre200s0 at HH:00, original t historical product, new controls after seal',
            'method':'unchanged A1.4 reconstruct_nodes; delta_H=(12 b_H-5 delta_Hminus1)/7; initial delta=0',
            'predictor_spinup_hours':72,'maximum_frequency_gain':6,
            'sensitivity_assumption':'20 K initial correction error; bound20*(5/7)^73 at first scored endpoint; not a proved atmospheric bound',
            'eligible_endpoint':'current plus preceding72 raw R1 means all primary-QC admitted; fallback-derived endpoints excluded from paired accuracy',
            'diagnostics':['B0/R1 endpoint MAE RMSE bias centred RMSE','maximum and p99 hour-to-hour T increments',
                'published h minus six original t nominal-node mean; require all six t samples; no claim of identical historical QC'],
            'counts_not_added_to_primary_independent_sample_size':True,'model_filter_equivalence_certified':False},
        'scoring':{'primary':'paired MAE R1 minus B0, same eligible reference hours, per country and per station-season',
            'report':['RMSE','bias','centred RMSE','all-reference B0','missing and rejected QCs','coverage','all24 cases including failures'],
            'case_admission_minimum_paired_hours':160,'requested_hours_per_case':168,
            'partial_cases':'descriptive metrics retained but excluded from admitted-country block estimate; no replacement',
            'resampling':{'draws':10000,'seed':20261026,'unit':'four synchronous season-week blocks per country, both stations together',
                'interval':'2.5/97.5 percentiles, descriptive sensitivity only; four seasonal blocks are not a population-confidence guarantee',
                'station_and_same_weather_dependence_respected':True},
            'benefit_rule':'country paired delta_MAE<0 and descriptive resampling upper<0; report each country, never select a winner by pooled countries',
            'six_sites_one_year_cannot_qualify_regional_or_global_accuracy':True,'automatic_default_or_EPW_promotion':False},
        'QC':{'AT':{'primary':[22],'secondary':[12],'secondary_not_substitute_for_primary':True},
            'DE':{'primary':[3],'product':'TT_10 historical','not_equivalent_to_hourly_QN10':True},
            'CH':{'primary':'PUBLISHED_HISTORICAL_NO_ROW_QC','not_equivalent_to_AT_or_DE_quality':True},
            'temperature_domain_C':[-80,65],'new_field_or_flag_schema':'fail closed',
            'AT_integer_code_encoding':'JSON22 and22.0 represent the same native22; fractional/boolean QC rejected, never rounded'},
        'inputs':inputs,'controls':controls,
        'source_budget':{'max_decoded_body_bytes_all_attempts_inputs_plus_controls':900_000_000,
            'attempts_per_asset':3,'timeout_seconds':45,'parallel_downloads':1,
            'max_assets':len(inputs)+len(controls),'no_source_station_date_model_or_QC_substitution':True,
            'max_uncompressed_DE_observation_member_bytes':150_000_000},
        'seals':{'registration':'publish protocol, metadata, admission, exposure and executable method before predictor acquisition',
            'predictions':'publish actual predictions/ledger/code/input hashes before any control body, including CH t',
            'control_gate':'exact published git commit and remote branch receipt required; no method/QC/time/selection changes after opening controls'},
        'serialization':{'prediction_CSV_decimals':10,'score_JSON_decimals':8,
            'portable_replay':'non-numeric cells exact; numeric CSV within1.1e-10; score floats within1.1e-8; original source and sealed bytes always hash-exact',
            'these_printed_digit_tolerances_are_not_station_accuracy_thresholds':True},
        'exposure_claim':e['claim_permitted'],'strict_raw_byte_unseen_global_certification':False,
        'ERA5_station_assimilation_independence_certified':False,'pressure_RH_q_accuracy_qualified_by_this_test':False,
        'NASA_future_event_accuracy_qualified_by_this_test':False,'EnergyPlus_test_in_this_temperature_stage':False,
        'IV1_2022_values_opened':False,'production_ready':False,
        'protected_core_sha256':{n:sha256((ROOT/n).read_bytes()).hexdigest() for n in FROZEN_CORE}}


def registered():
    plan=prepare_registration()
    if (R/REG).read_bytes()!=json_bytes(plan):raise ValueError('V1_REGISTERED_PROTOCOL_CHANGED')
    if (R/ADMISSION).read_bytes()!=json_bytes(prepare_admission()):raise ValueError('V1_ADMISSION_CHANGED')
    if (R/EXPOSURE).read_bytes()!=json_bytes(exposure()):raise ValueError('V1_EXPOSURE_CHANGED')
    return plan


def code_hashes():
    return {n:sha256((ROOT/n).read_bytes()).hexdigest() for n in [*CODE,*FROZEN_CORE,
        *['research/ige_cmip6/'+s for s in (REG,ADMISSION,EXPOSURE,META)]]}

if __name__=='__main__':
    print(json.dumps(prepare_registration(),ensure_ascii=False,indent=2))
