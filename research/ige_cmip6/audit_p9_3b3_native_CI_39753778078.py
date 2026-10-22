"""Reproduce source, coverage and independent hydrostatic checks of one frozen CI.

Raw station errors are not independently replayed: private station truth is
absent from public artifacts. No production pressure helper is imported.
"""
from pathlib import Path
import argparse,collections,datetime,hashlib,json,math,re,subprocess
ap=argparse.ArgumentParser(description='Independent, network-free audit of the frozen native pilot CI 39753778078.')
ap.add_argument('--evidence-dir',type=Path,required=True,help='artifact/, artifact.zip, contracts.log and pilot.log obtained from this CI')
ap.add_argument('--out',type=Path,required=True)
args=ap.parse_args()
if args.out.exists():raise ValueError('AUDIT_OUTPUT_EXISTS_NO_OVERWRITE')
R=args.evidence_dir;A=R/'artifact';REPO=Path(__file__).resolve().parents[2];HEAD='cca2c8e3255ef34b2498ff5d2581b59e973e510b'
def sha(b):return hashlib.sha256(b).hexdigest()
def read(n):return json.loads((A/(n+'.json')).read_text())
m=read('run_manifest');s=read('revealed_pressure_scores');pred=read('sealed_pressure_predictions');p=pred['hourly'];h=read('historical_sensor_references');lineage=read('native_source_lineage');deep=read('deep_column_diagnostic')
protocol_bytes=subprocess.check_output(['git','show',HEAD+':research/ige_cmip6/p9_3b3_native_protocol.json']);protocol=json.loads(protocol_bytes)
assert m['git_head']==HEAD and sha(protocol_bytes)==m['protocol_sha256']==pred['protocol_sha256']
for name,digest in m['code_sha256'].items():assert sha(subprocess.check_output(['git','show',HEAD+':research/ige_cmip6/'+name]))==digest,name
for name,digest in protocol['protected_control_sha256'].items():
 assert sha(subprocess.check_output(['git','show',HEAD+':'+name]))==digest,name
 assert sha((REPO/name).read_bytes())==digest,name
seal=sha((A/'sealed_pressure_predictions.json').read_bytes());assert seal==m['sealed_prediction_sha256']==s['sealed_prediction_sha256']==read('prediction_seal')['sha256']
assert not read('prediction_seal')['station_observations_opened'] and pred['no_observation_residual_conditioning']
assert len(p)==50 and len(s['cells'])==s['expected_score_cells']==24
failed=[b['timestamp_UTC'] for b in m['source_blockers'] if b.get('scope')=='PRIMARY_PROFILE'];assert len(failed)==11
assert failed==['2021-08-01T'+str(i).zfill(2)+':00' for i in range(13,24)]
assert all(v['valid_hours']==v['expected_hours']==48 and v['status']=='SOURCE_READ' for v in s['observation_provenance'].values())
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
assert all(x['status']=='ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT' and x['coefficient_count']==410240 for x in lineage['original_GRIB_controls'])
assert len(lineage['original_GRIB_controls'])==4
sources=m['source_objects'];assert len(sources)==m['unique_source_objects']==1425
assert sum(x['bytes'] for x in sources)==m['network_downloaded_bytes']==1877424095
size=collections.defaultdict(list)
for x in sources:
 if '/t/' in x['url']:size['t'].append(x['bytes'])
 if '/q/' in x['url']:size['q'].append(x['bytes'])
projected=m['network_downloaded_bytes']+sum((730-len(v))*sum(v)/len(v) for v in size.values())
logs={n:(R/(n+'.log')).read_bytes() for n in ('contracts','pilot')}
log_lines=[v for v in logs['contracts'].decode().splitlines() if re.search(r'Ran \d+ tests|SEMANTICS_CONTRACTS_PASS|Protected files: 58 changed: 0',v)]
counts=[int(v) for v in re.findall(r'Ran (\d+) tests',logs['contracts'].decode())];assert counts==[205,14,50,8]
audit={
 'phase':'P9.3B3_NATIVE_CI_VERIFIED_WITH_INCOMPLETE_RESOURCE_COVERAGE',
 'run_id':39753778078,'html_url':'https://github.com/dmitrievii/building-energy-tools/actions/runs/39753778078',
 'tested_head_sha':HEAD,'conclusion':'success','jobs_successful':2,'tests_passed':sum(counts),'log_statements':log_lines,
 'job_log_sha256':{n:sha(v) for n,v in logs.items()},'artifact_id':12414524493,
 'artifact_zip_sha256':sha((R/'artifact.zip').read_bytes()),'artifact_file_sha256':{f.name:sha(f.read_bytes()) for f in sorted(A.glob('*.json'))},
 'actual_implementation_hashes_match_tested_commit':True,'tested_code_sha256':m['code_sha256'],
 'tested_protocol_sha256':m['protocol_sha256'],'protected_controls_verified':58,'protected_changed_count':0,
 'sealed_prediction_sha256':seal,'seal_matches_manifest_scores_and_seal_file':True,
 'historical_sensor_references':h,'native_source_lineage':lineage,
 'engineering_assessment':'INCOMPLETE_SOURCE_EXECUTION_DESPITE_GREEN_JOB',
 'profile_hours_attempted':50,'profile_hours_complete':39,'profile_hours_failed':11,'primary_profile_failure_hours':failed,
 'score_cell_count':24,'expected_unique_station_hours':144,'matched_unique_station_hours':74,
 'cells':s['cells'],'paired_comparisons':s['paired_comparisons'],'observation_provenance':s['observation_provenance'],
 'independent_audit_checks':{'prediction_side_time_coverage_recomputed':True,'score_gate_logic_recomputed':True,
   'paired_aggregate_deltas_recomputed':True,'exported_deep_layer_equations_checked':layer_checks,
   'max_hydrostatic_layer_equation_residual_m2s2':hydro_max,
   'independent_bottom_up_pressure_results_checked':pressure_checks,'max_pressure_discrepancy_Pa':pressure_max,
   'raw_station_score_recomputation':'NOT_PERFORMED_RAW_STATION_VALUES_NOT_EXPORTED; aggregate arithmetic and source parser semantics audited, not a new independent truth replay'},
 'deep_vs_primary_max_pressure_delta_hPa':depth,
 'resource_observation':{k:m[k] for k in ('network_downloaded_bytes','network_requests','unique_source_objects','wall_seconds','peak_RSS_KiB')},
 'resource_completion_basis':{'old_cap_bytes':2147483648,'proposed_new_cap_bytes':3221225472,
   'compressed_t_chunks_read':len(size['t']),'compressed_q_chunks_read':len(size['q']),'expected_each':730,
   'estimated_complete_bytes':round(projected),'estimated_complete_GiB':projected/2**30,
   'projection_is_estimate_not_a_measured_complete_run':True,
   'false_early_rejection_cause':'80 MB object-ceiling reservations before Content-Length; six simultaneous reservations can reject bodies that fit',
   'true_capacity_issue':'Projected complete body bytes also exceed the previous 2 GiB cap'},
 'science_assessment':{'code_contracts':'PASS_277_TESTS_AT_TESTED_COMMIT',
   'physical_scope':'CONDITIONAL_HYDROSTATIC_NATIVE_AIR_COLUMNS_ONLY; no condensate, water-saturation or surface-layer qualification',
   'independent_accuracy':'NOT_QUALIFIED_PREVIOUSLY_REVEALED_TWO_DAY_PILOT',
   'P2_dominates_P1':False,'all_AT_DE_CH_qualified':False,'B4_qualified':False,'operational_ready':False,'production_epw_ready':False,
   'height_datum':'Dated instrument MSL references confirmed; national MSL to ERA5 geopotential transformation remains approximate',
   'old_2013_2014_results_rewritten':False,'main_modified':False,'merge_performed':False},
 'next_steps':['Complete the same frozen source-only pilot with corrected byte reservations and a logged 3 GiB resource amendment; require all 50 source profiles for engineering CI success',
   'Audit the completed summer cells before selecting any model; retain all negative or tied P1/P2 comparisons',
   'Prepare a separately frozen valley/surface-layer identifiability experiment for AT; do not fabricate underground ERA5 air or fit current station residuals',
   'Only after spatial and temporal operators are fixed, define new AT/DE/CH holdout blocks and later return to NASA daily T-p-q-RH closure']}
assert audit['artifact_zip_sha256']=='8d6ecd929913e0a0601fd3112a0e1d1d738523d57ac2c604edcfb06e22c7ff10'
args.out.write_text(json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'tests':sum(counts),'profiles_complete':39,'matched_unique_station_hours':74,'protected_controls':58,'layer_checks':layer_checks,'independent_pressure_checks':pressure_checks,'max_hydrostatic_residual':hydro_max,'max_pressure_difference_Pa':pressure_max,'estimated_complete_bytes':round(projected)}))
