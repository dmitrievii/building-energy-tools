"""Offline independent audit of the completed native pressure pilot.

The optional private observation directory contains the six official pressure
products named by their CI SHA256 plus .bin. Raw observations never enter the
public audit output. A score replay is not a new independent holdout.
"""
from pathlib import Path
import argparse,collections,csv,datetime,hashlib,io,json,math,re,subprocess,urllib.parse,zipfile

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--evidence-dir',type=Path,required=True)
ap.add_argument('--previous-evidence-dir',type=Path,required=True)
ap.add_argument('--private-observation-dir',type=Path)
ap.add_argument('--out',type=Path,required=True)
args=ap.parse_args()
if args.out.exists():raise ValueError('AUDIT_OUTPUT_EXISTS_NO_OVERWRITE')
R=args.evidence_dir;A=R/'artifact';OLD=args.previous_evidence_dir;OA=OLD/'artifact'
REPO=Path(__file__).resolve().parents[2]
HEAD='aebdc005505d2789940fe3f5f7eb14e5d31b788e';OLD_HEAD='cca2c8e3255ef34b2498ff5d2581b59e973e510b'
def sha(b):return hashlib.sha256(b).hexdigest()
def read(n):return json.loads((A/(n+'.json')).read_text())
def oldread(n):return json.loads((OA/(n+'.json')).read_text())
def blob(head,path):return subprocess.check_output(['git','show',head+':'+path],cwd=REPO)
def archive(root,expected):
 raw=(root/'artifact.zip').read_bytes();assert sha(raw)==expected
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  assert set(z.namelist())=={p.name for p in (root/'artifact').glob('*.json')}
  for n in z.namelist():assert z.read(n)==(root/'artifact'/n).read_bytes(),n
archive(R,'2545012a7ace42d851ee2b418f50e2c3c30452202097fde4d9b2d6ae4bed3027')
archive(OLD,'8d6ecd929913e0a0601fd3112a0e1d1d738523d57ac2c604edcfb06e22c7ff10')
api=json.loads((R/'api_evidence.json').read_text());run=api['run']
assert run['id']==39757573033 and run['head_sha']==HEAD and run['status']=='completed' and run['conclusion']=='success'
assert len(api['jobs'])==2 and all(j['conclusion']=='success' for j in api['jobs'])
assert len(api['artifacts'])==1 and api['artifacts'][0]['id']==12416732051
assert api['artifacts'][0]['digest']=='sha256:'+sha((R/'artifact.zip').read_bytes())
m=read('run_manifest');s=read('revealed_pressure_scores');pred=read('sealed_pressure_predictions');p=pred['hourly']
h=read('historical_sensor_references');lineage=read('native_source_lineage');deep=read('deep_column_diagnostic')
oldm=oldread('run_manifest');olds=oldread('revealed_pressure_scores');oldp=oldread('sealed_pressure_predictions')['hourly'];oldh=oldread('historical_sensor_references')
protocol_bytes=blob(HEAD,'research/ige_cmip6/p9_3b3_native_completion_protocol.json');protocol=json.loads(protocol_bytes)
frozen_bytes=blob(OLD_HEAD,'research/ige_cmip6/p9_3b3_native_protocol.json');frozen=json.loads(frozen_bytes)
assert m['git_head']==HEAD and sha(protocol_bytes)==m['protocol_sha256']==pred['protocol_sha256']
assert sha(frozen_bytes)=='5c0f3ec123db35e9329f6d511a7bf1154a140581fa6e0181d337983d0806a27c'
assert set(protocol)==set(frozen)|{'resource_completion'}
assert [k for k in frozen if frozen[k]!=protocol[k]]==['phase','max_download_bytes']
for name,digest in m['code_sha256'].items():assert sha(blob(HEAD,'research/ige_cmip6/'+name))==digest,name
for name in ('p9_3b3_native_columns.py','p9_3b3_native_heights.py','p9_3b3_native_validation.py'):
 assert blob(HEAD,'research/ige_cmip6/'+name)==blob(OLD_HEAD,'research/ige_cmip6/'+name)
for name,digest in protocol['protected_control_sha256'].items():
 assert sha(blob(HEAD,name))==sha(blob(OLD_HEAD,name))==sha((REPO/name).read_bytes())==digest,name
assert len(protocol['protected_control_sha256'])==m['protected_control_count']==58 and m['protected_changed_count']==0
previous_reports=['research/ige_cmip6/p9_3b3_native_protocol.json','research/ige_cmip6/p9_3b3_native_local_results_20261022.json',
 'research/ige_cmip6/p9_3b3_native_verified_CI_39753778078.json','research/ige_cmip6/p9_3b3_native_completion_local_results_20261022.json',
 'docs/IGE_P9_3B3_NATIVE_LINEAGE_SENSOR_HEIGHTS_RU_20261022.md','docs/IGE_P9_3B3_NATIVE_CI_AUDIT_AND_NEXT_RU_20261022.md']
assert all((REPO/n).read_bytes()==blob(HEAD,n) for n in previous_reports)
seal=sha((A/'sealed_pressure_predictions.json').read_bytes())
assert seal==m['sealed_prediction_sha256']==s['sealed_prediction_sha256']==read('prediction_seal')['sha256']
assert read('prediction_seal')['station_observations_opened'] is False and pred['no_observation_residual_conditioning'] is True
assert m['engineering_execution_status']=='COMPLETE_SOURCE_EXECUTION' and m['source_blockers']==[]
assert m['profile_hours_attempted']==m['source_profile_hours_expected']==m['source_profile_hours_complete']==len(p)==50
assert m['source_profile_hours_missing_or_failed']==0 and len(s['cells'])==s['expected_score_cells']==24
assert set(p)=={day+'T'+str(k).zfill(2)+':00' for day in protocol['development_days'] for k in range(24)}|{'2021-01-31T23:00','2021-07-31T23:00'}
assert all(v['valid_hours']==v['expected_hours']==48 and v['status']=='SOURCE_READ' for v in s['observation_provenance'].values())
assert s['observation_provenance']==olds['observation_provenance']
assert s['observation_provenance']['DE']['field']=='P0_ST_10' and s['observation_provenance']['DE']['native_qc']=={'3':48}
for stamp,cs in p.items():
 assert set(cs)=={'AT','DE','CH'}
 for co,c in cs.items():
  assert len(c['geometry'])==4
  for v in c['methods'].values():
   if co=='AT':assert v.get('reason')=='NO_NATIVE_NEIGHBOR_AIR_DOMAIN_COVERS_BAROMETER_NO_UNDERGROUND_EXTRAPOLATION' and 'pressure_Pa' not in v
   else:assert math.isfinite(v['pressure_Pa']) and 30000<v['pressure_Pa']<115000
  if co!='AT':
   for method in ('P2_NATIVE_SINGLE_COLUMN','P2_NATIVE_UP_TO_FOUR_COLUMNS'):
    active=c['methods'][method]['active_columns'];assert abs(sum(x['weight'] for x in active)-1)<1e-13
    assert len(active)==(4 if co=='DE' and method=='P2_NATIVE_UP_TO_FOUR_COLUMNS' else 1)

# Recompute prediction-side temporal support and score-cell coverage without
# importing the implementation under audit. Raw station truth is not exported.
def pressure(t,co,method):return p.get(t,{}).get(co,{}).get('methods',{}).get(method,{}).get('pressure_Pa')
def support(day,co,method):
 hours=[]
 for k in range(24):
  stamp=day+'T'+str(k).zfill(2)+':00';value=pressure(stamp,co,method)
  if value is None:continue
  if co=='CH':
   before=(datetime.datetime.fromisoformat(stamp)-datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
   value0=pressure(before,co,method)
   if value0 is None:continue
  hours.append(stamp)
 return hours
cells={}
for c in s['cells']:
 key=c['country'],c['day'],c['method'];assert key not in cells;cells[key]=c
 count=len(support(c['day'],c['country'],c['method']));assert c['matched_hours']==count and c['coverage']==count/24
 if count:
  assert -1e-12<=abs(c['bias_hPa'])<=c['MAE_hPa']+1e-12<=c['RMSE_hPa']+2e-12<=c['max_abs_error_hPa']+3e-12
  expected='PASS_THIS_REVEALED_CELL' if c['MAE_hPa']<=2 else 'FAIL_THIS_REVEALED_CELL'
 else:expected='INCONCLUSIVE_COVERAGE'
 if count<24*.9:expected='INCONCLUSIVE_COVERAGE'
 assert c['accuracy_gate']==expected and c['independently_qualified'] is False
for c in s['paired_comparisons']:
 a=cells[c['country'],c['day'],c['method']];b=cells[c['country'],c['day'],c['baseline']]
 assert a['matched_hours']==b['matched_hours']==c['paired_hours']
 assert abs(c['delta_MAE_hPa']-(a['MAE_hPa']-b['MAE_hPa']))<1e-12
 assert abs(c['delta_RMSE_hPa']-(a['RMSE_hPa']-b['RMSE_hPa']))<1e-12
# Independent bottom-up hydrostatics on exported 29-layer source columns.
# No production hydrostatic or transfer helper is imported here.
RD=287.05;C=461.5/RD-1;G0=9.80665
hydro_max=0.;pressure_max=0.;pressure_checks=0;layer_checks=0;depth={}
def state(col,phi):
 z=col['half_geopotential_m2s2']
 for j in range(len(z)-1):
  if z[j]>=phi>=z[j+1]:return col['temperature_K'][j],col['specific_humidity_kgkg'][j]
 raise AssertionError('outside air domain')
def logp(col,phi):
 z=col['half_geopotential_m2s2'];v=math.log(col['half_pressure_Pa'][-1])
 for j,(t,q) in enumerate(zip(col['temperature_K'],col['specific_humidity_kgkg'])):
  dz=max(0.,min(phi,z[j])-z[j+1]);v-=dz/(RD*t*(1+C*q))
 return v
def distance(sensor,col):
 lat,lon=map(math.radians,(sensor['latitude'],sensor['longitude']));a,b=map(math.radians,(col['latitude'],col['longitude']))
 k=math.sin((a-lat)/2)**2+math.cos(lat)*math.cos(a)*math.sin((b-lon)/2)**2
 return 2*6371.0088*math.asin(math.sqrt(k))
for stamp,d in deep.items():
 cols=d['columns']
 for col in cols:
  z=col['half_geopotential_m2s2'];pr=col['half_pressure_Pa']
  assert all(x>0 for x in pr) and all(x>0 for x in col['temperature_K']) and all(0<=x<.1 for x in col['specific_humidity_kgkg'])
  for j,(t,q) in enumerate(zip(col['temperature_K'],col['specific_humidity_kgkg'])):
   residual=z[j]-z[j+1]-RD*t*(1+C*q)*math.log(pr[j+1]/pr[j]);hydro_max=max(hydro_max,abs(residual));layer_checks+=1
 for co,result in d['predictions'].items():
  sensor=h[co]['sensors']['pressure'];phi=G0*sensor['height_MSL_m']
  # Re-select columns using only source-only geometry published in predictions.
  coordinates={(a['latitude'],a['longitude']) for a in result.get('geometry',[])}
  eligible=[c for c in cols if (c['latitude'],c['longitude']) in coordinates and c['half_geopotential_m2s2'][-1]<=phi<=c['half_geopotential_m2s2'][0]]
  if not eligible:
   assert co=='AT' and all(v['status']=='SOURCE_BLOCKED' for v in result['methods'].values());continue
  closest=min(eligible,key=lambda col:(distance(sensor,col),col['latitude'],col['longitude']))
  for method,value in result['methods'].items():
   if 'pressure_Pa' not in value:continue
   if method=='P2_NATIVE_SINGLE_COLUMN':estimate=math.exp(logp(closest,phi))
   elif method=='P2_NATIVE_UP_TO_FOUR_COLUMNS':
    dist=[distance(sensor,c) for c in eligible];w=[1/(v*v) for v in dist];total=sum(w);w=[v/total for v in w]
    top=min(c['half_geopotential_m2s2'][0] for c in eligible);anchor=sum(ww*logp(c,top) for ww,c in zip(w,eligible))
    boundaries=sorted({phi,top,*[v for c in eligible for v in c['half_geopotential_m2s2'] if phi<v<top]});integ=0.
    for low,high in zip(boundaries,boundaries[1:]):
     tq=[state(c,(low+high)/2) for c in eligible];t=sum(ww*a[0] for ww,a in zip(w,tq));q=sum(ww*a[1] for ww,a in zip(w,tq));integ+=(high-low)/(RD*t*(1+C*q))
    estimate=math.exp(anchor+integ)
   else:
    t,q=state(closest,phi);factor=1+C*q;dz=(phi-closest['half_geopotential_m2s2'][-1])/G0
    gamma=(.0065 if 'LAPSE' in method else 0)*factor;tv=t*factor
    ratio=-G0*dz/(RD*tv) if gamma==0 else -G0/(RD*gamma)*math.log1p(gamma*dz/tv)
    estimate=closest['half_pressure_Pa'][-1]*math.exp(ratio)
   pressure_max=max(pressure_max,abs(estimate-value['pressure_Pa']));pressure_checks+=1
   main=pressure(stamp,co,method);k=co+'|'+method;depth[k]=max(depth.get(k,0),abs(main-value['pressure_Pa'])/100)
assert hydro_max<1e-8 and pressure_max<1e-7 and layer_checks==696 and pressure_checks==16
assert len(lineage['original_GRIB_controls'])==4
assert all(c['status']=='ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT' and c['coefficient_count']==410240 for c in lineage['original_GRIB_controls'])
assert (A/'native_source_lineage.json').read_bytes()==(OA/'native_source_lineage.json').read_bytes()
assert all(deep[t]['columns']==oldread('deep_column_diagnostic')[t]['columns'] for t in deep)
def without_source_hashes(x):
 if isinstance(x,dict):return {k:without_source_hashes(v) for k,v in x.items() if k not in ('source_sha256','source_WMDR_sha256')}
 if isinstance(x,list):return [without_source_hashes(v) for v in x]
 return x
assert without_source_hashes(h)==without_source_hashes(oldh)
oldobjects={x['url']+'|'+str(x['range']):x for x in oldm['source_objects']}
objects={x['url']+'|'+str(x['range']):x for x in m['source_objects']}
assert set(oldobjects)<=set(objects)
changes=[{'url':v['url'],'old_sha256':v['sha256'],'new_sha256':objects[k]['sha256']} for k,v in oldobjects.items() if v['sha256']!=objects[k]['sha256']]
assert {x['url'] for x in changes}=={'https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-11290','https://oscar.wmo.int/surface/rest/api/wmd/download/0-276-6-399'}
assert len(oldobjects)==1425 and len(objects)==m['unique_source_objects']==m['network_requests']==1661
assert sum(x['bytes'] for x in objects.values())==m['network_downloaded_bytes']==2194174739
assert m['network_downloaded_bytes']<protocol['max_download_bytes']==3221225472 and m['network_requests']<protocol['max_requests']==2000
chunks={name:[v['bytes'] for v in objects.values() if '/'+name+'/' in v['url']] for name in ('t','q')}
assert len(chunks['t'])==len(chunks['q'])==730
common_hours=0;common_pressures=0;max_difference=0.;nonbitexact=0
for stamp,cs in oldp.items():
 valid=any('pressure_Pa' in v for c in cs.values() for v in c['methods'].values())
 if not valid:continue
 common_hours+=1
 for co,c in cs.items():
  for method,v in c['methods'].items():
   if 'pressure_Pa' not in v:continue
   delta=abs(v['pressure_Pa']-p[stamp][co]['methods'][method]['pressure_Pa']);max_difference=max(max_difference,delta);common_pressures+=1;nonbitexact+=int(delta>0)
assert common_hours==39 and common_pressures==312 and max_difference<1e-7
logs={name:(R/(name+'.log')).read_bytes() for name in ('contracts','pilot')}
counts=[int(v) for v in re.findall(r'Ran (\d+) tests',logs['contracts'].decode())];assert counts==[213,14,50,8]
assert 'P93B2D_ORIGINAL_PRESSURE_FIELD_SEMANTICS_CONTRACTS_PASS' in logs['contracts'].decode()
assert 'Protected files: 58 changed: 0' in logs['contracts'].decode()
assert 'PREDICTIONS_SEALED_OPEN_REVEALED_PRESSURE_OBSERVATIONS' in logs['pilot'].decode()
# Independent raw pressure parsing and scoring. Only six pressure products are
# required; AT GeoJSON embeds the hPa unit, so the live metadata endpoint is not
# an input to this replay. No production observation/scoring helper is used.
replay={'status':'NOT_RUN_PRIVATE_SOURCE_BYTES_NOT_SUPPLIED','new_independent_holdout':False}
if args.private_observation_dir:
 products=[];observed={'AT':{},'DE':{},'CH':{}};wanted={day+'T'+str(k).zfill(2)+':00' for day in protocol['development_days'] for k in range(24)}
 def source(record):
  b=(args.private_observation_dir/(record['sha256']+'.bin')).read_bytes();assert sha(b)==record['sha256']
  products.append({**record,'bytes':len(b)});return b
 series={}
 for record in s['observation_provenance']['AT']['sources']:
  query=urllib.parse.parse_qs(urllib.parse.urlsplit(record['url']).query)
  if 'station_ids' not in query:continue
  station=int(query['station_ids'][0]);day=query['start'][0][:10];obj=json.loads(source(record));assert len(obj['features'])==1
  fields=obj['features'][0]['properties']['parameters'];assert fields['p']['unit']=='hPa'
  times=[datetime.datetime.fromisoformat(t.replace('Z','+00:00')).astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M') for t in obj['timestamps']]
  assert times==[day+'T'+str(k).zfill(2)+':00' for k in range(24)]
  series[day,station]=(times,fields['p']['data'],fields['p_flag']['data'])
 for day in protocol['development_days']:
  assert series[day,30]==series[day,16412]
  times,values,flags=series[day,30]
  for t,v,f in zip(times,values,flags):
   assert f in (10,11,12,20,21,22) and 450<float(v)<1100;observed['AT'][t]=float(v)*100
 records=s['observation_provenance']['DE']['sources'];assert len(records)==1
 with zipfile.ZipFile(io.BytesIO(source(records[0]))) as z:
  names=[n for n in z.namelist() if n.startswith('produkt') and n.endswith('.txt')];assert len(names)==1
  for raw in csv.DictReader(io.StringIO(z.read(names[0]).decode('latin1')),delimiter=';'):
   row={k.strip():v.strip() for k,v in raw.items() if k is not None};date=row['MESS_DATUM']
   if len(date)!=12 or not date.endswith('00'):continue
   t=datetime.datetime.strptime(date,'%Y%m%d%H%M').strftime('%Y-%m-%dT%H:%M')
   if t not in wanted:continue
   assert int(row['STATIONS_ID'])==399 and row['QN']=='3' and t not in observed['DE']
   v=float(row['P0_ST_10']);assert 450<v<1100;observed['DE'][t]=v*100
 records=s['observation_provenance']['CH']['sources'];assert len(records)==1
 for row in csv.DictReader(io.StringIO(source(records[0]).decode('utf-8-sig')),delimiter=';'):
  t=datetime.datetime.strptime(row['reference_timestamp'],'%d.%m.%Y %H:%M').strftime('%Y-%m-%dT%H:%M')
  if t not in wanted:continue
  assert row['station_abbr'].strip().upper()=='DAV' and t not in observed['CH']
  v=float(row['prestah0']);assert 450<v<1100;observed['CH'][t]=v*100
 assert len(products)==6 and all(set(v)==wanted for v in observed.values())
 max_metric_delta=0.;replayed=0;replayed_matched=0
 for c in s['cells']:
  errors=[]
  for t in support(c['day'],c['country'],c['method']):
   v=pressure(t,c['country'],c['method'])
   if c['country']=='CH':
    prev=(datetime.datetime.fromisoformat(t)-datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M');v=(v+pressure(prev,'CH',c['method']))/2
   errors.append((v-observed[c['country']][t])/100)
  assert len(errors)==c['matched_hours'];replayed+=1
  if errors:
   metrics={'MAE_hPa':math.fsum(abs(v) for v in errors)/len(errors),'bias_hPa':math.fsum(errors)/len(errors),
    'RMSE_hPa':math.sqrt(math.fsum(v*v for v in errors)/len(errors)),'max_abs_error_hPa':max(abs(v) for v in errors)}
   for key,value in metrics.items():max_metric_delta=max(max_metric_delta,abs(value-c[key]))
   replayed_matched+=1
 assert replayed==24 and replayed_matched==16 and max_metric_delta<1e-10
 replay={'status':'EXACT_SIX_PRESSURE_PRODUCT_HASHES_AND_INDEPENDENT_RAW_SCORE_REPLAY_PASS','products':products,
  'valid_hours_by_country':{co:len(v) for co,v in observed.items()},'cells_replayed':24,'matched_cells_replayed':16,
  'max_aggregate_metric_difference_hPa':max_metric_delta,'raw_values_in_public_output':False,
  'live_AT_metadata_endpoint_used':False,'AT_pressure_unit_verified_in_each_exact_GeoJSON_product':True,
  'new_independent_holdout':False}
matched_unique=sum(c['matched_hours'] for c in s['cells'] if c['method']=='P2_NATIVE_SINGLE_COLUMN')
assert matched_unique==96 and sum(c['accuracy_gate']=='PASS_THIS_REVEALED_CELL' for c in s['cells'])==16
assert all(c['independently_qualified'] is False for c in s['cells'])
audit={
 'phase':'P9.3B3_NATIVE_COMPLETION_CI_VERIFIED','run_id':39757573033,'html_url':run['html_url'],
 'tested_head_sha':HEAD,'conclusion':run['conclusion'],'jobs':api['jobs'],'tests_passed':sum(counts),
 'log_statements':[v for v in logs['contracts'].decode().splitlines() if re.search(r'Ran \d+ tests|SEMANTICS_CONTRACTS_PASS|Protected files: 58 changed: 0',v)],
 'job_log_sha256':{k:sha(v) for k,v in logs.items()},'artifact_id':12416732051,
 'artifact_zip_sha256':sha((R/'artifact.zip').read_bytes()),'artifact_file_sha256':{f.name:sha(f.read_bytes()) for f in sorted(A.glob('*.json'))},
 'actual_implementation_hashes_match_tested_commit':True,'tested_code_sha256':m['code_sha256'],'tested_protocol_sha256':m['protocol_sha256'],
 'protected_controls_verified':58,'protected_changed_count':0,'original_protocol_and_previous_results_unchanged':True,
 'sealed_prediction_sha256':seal,'seal_matches_manifest_scores_and_seal_file':True,
 'engineering_assessment':'COMPLETE_SOURCE_EXECUTION','source_profile_hours_expected':50,'source_profile_hours_complete':50,'source_blockers':[],
 'score_cell_count':24,'matched_cells':16,'geometrically_blocked_AT_cells':8,
 'expected_unique_station_hours':144,'matched_unique_station_hours':matched_unique,
 'cells':s['cells'],'paired_comparisons':s['paired_comparisons'],'observation_provenance':s['observation_provenance'],
 'historical_sensor_references':h,'native_source_lineage':lineage,
 'independent_audit_checks':{'prediction_side_time_coverage_recomputed':True,'CH_boundary_nodes_present':True,
  'score_gate_logic_recomputed':True,'paired_aggregate_deltas_recomputed':True,'exported_deep_layer_equations_checked':layer_checks,
  'max_hydrostatic_layer_equation_residual_m2s2':hydro_max,'independent_bottom_up_pressure_results_checked':pressure_checks,
  'max_pressure_discrepancy_Pa':pressure_max,'raw_station_score_replay':replay},
 'comparison_with_CI_39753778078':{'common_complete_source_hours':common_hours,'common_pressure_values':common_pressures,
  'max_abs_pressure_delta_Pa':max_difference,'nonbitexact_pressure_values':nonbitexact,
  'common_source_objects':len(oldobjects),'bit_identical_common_source_objects':len(oldobjects)-len(changes),
  'changed_source_objects':changes,'dated_sensor_fields_identical_after_excluding_provenance_hashes':True,
  'deep_native_column_values_identical':True,'station_observation_product_provenance_identical':True,
  'WMDR_byte_change_reason':'NOT_IDENTIFIED_RAW_XML_NOT_EXPORTED; do not infer a formatting or timestamp cause',
  'whole_prediction_file_bitwise_identical':False},
 'deep_vs_primary_max_pressure_delta_hPa':depth,
 'resource_observation':{k:m[k] for k in ('network_downloaded_bytes','network_requests','unique_source_objects','wall_seconds','peak_RSS_KiB')},
 'complete_download_GiB':m['network_downloaded_bytes']/2**30,'T_chunks':730,'q_chunks':730,
 'science_assessment':{'code_contracts':'PASS_285_TESTS_AT_TESTED_COMMIT',
  'physical_scope':'CONDITIONAL_HYDROSTATIC_NATIVE_AIR_COLUMNS_ONLY; no water-saturation, condensate, datum or surface-layer qualification',
  'independent_accuracy':'NOT_QUALIFIED_PREVIOUSLY_REVEALED_TWO_DAY_PILOT','P2_dominates_P1':False,
  'all_AT_DE_CH_qualified':False,'B4_qualified':False,'operational_ready':False,'production_epw_ready':False,
  'native_future_CanESM5_pressure_recovered':False,'main_modified':False,'merge_performed':False},
 'next_step':'Freeze G1 geometry-only air-column admission and barometer/thermohygrometer transfer study for AT/DE/CH; preserve current four-column blocker as G0. Do not fit this revealed pressure cohort.'}
args.out.write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'tests':sum(counts),'profiles':50,'matched_unique_station_hours':matched_unique,'score_cells':24,
 'common_pressure_max_delta_Pa':max_difference,'independent_raw_score_replay':replay['status'],
 'metric_difference_hPa':replay.get('max_aggregate_metric_difference_hPa'),'hydrostatic_max_residual':hydro_max,'pressure_max_difference_Pa':pressure_max}))
