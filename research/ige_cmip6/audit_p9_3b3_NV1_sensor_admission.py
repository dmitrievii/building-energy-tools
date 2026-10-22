"""Independent scalar NV1 geometry checks and sensor-specific admission bounds.

Reads frozen CI evidence only. Does not load station pressure observations or
produce a new T/q/p model. Radius totals are CI results, not independently
recounted from the incomplete point catalogue exported by NV1.
"""
from pathlib import Path
import argparse,hashlib,io,json,math,re,subprocess,zipfile
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--nv1-evidence-dir',type=Path,required=True)
ap.add_argument('--work-verified-audit',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True)
a=ap.parse_args()
if a.out.exists():raise ValueError('AUDIT_OUTPUT_EXISTS_NO_OVERWRITE')
ROOT=Path(__file__).resolve().parents[2];R=a.nv1_evidence_dir
SHA='bd6f200d13a7e8888791323c28e6b73a9fefc2b7';RELEASE='a8f9c35878c58394a54910cd6db969bb313b6bfb';PREREG='27a47ca17603bd0e6969ba8f9706f922591cff31'
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(commit,path):return subprocess.check_output(['git','show',commit+':'+path],cwd=ROOT)
raw=(R/'artifact.zip').read_bytes();assert sha(raw)=='0bc868fc1beaf5b54ac787689898d6a90d736bde1904686922279883bdcebc09'
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 assert len(z.namelist())==1;name=z.namelist()[0];body=z.read(name);assert (R/'artifact'/name).read_bytes()==body
v=json.loads(body);api=json.loads((R/'api_evidence.json').read_text());log=(R/'job.log').read_bytes()
assert api['run']['id']==39765492318 and api['run']['head_sha']==SHA and api['run']['conclusion']=='success'
assert len(api['jobs'])==1 and api['jobs'][0]['conclusion']=='success' and re.findall(r'Ran (\d+) tests',log.decode())==['6']
assert api['artifacts'][0]['id']==12419308583 and api['artifacts'][0]['digest']=='sha256:'+sha(raw)
paths=['research/ige_cmip6/p9_3b3_native_at_valley_source_only.py','research/ige_cmip6/test_p9_3b3_native_at_valley_source_only.py']
for path in paths:assert blob(SHA,path)==blob(RELEASE,path)==(ROOT/path).read_bytes(),path
prereg='docs/IGE_P9_3B3_NATIVE_AT_VALLEY_SOURCE_ONLY_GEOMETRY_PREREG_20261022_RU.md'
assert blob(PREREG,prereg)==blob(SHA,prereg)==blob(RELEASE,prereg)==(ROOT/prereg).read_bytes()
protocol=ROOT/'research/ige_cmip6/p9_3b3_native_completion_protocol.json';assert sha(protocol.read_bytes())==v['frozen_source_protocol_SHA256']
work_audit=json.loads(a.work_verified_audit.read_text())
assert work_audit['run_id']==39757573033 and work_audit['tested_head_sha']=='aebdc005505d2789940fe3f5f7eb14e5d31b788e'
assert work_audit['artifact_zip_sha256']=='2545012a7ace42d851ee2b418f50e2c3c30452202097fde4d9b2d6ae4bed3027'
heights=work_audit['historical_sensor_references']['AT']['sensors']
work_lineage=work_audit['native_source_lineage'];baro=heights['pressure'];thermo=heights['temperature']
assert thermo['height_MSL_m']==heights['RH_water']['height_MSL_m']==368.7 and baro['height_MSL_m']==378.8
assert v['historically_dated_WMDR_barometer']['sensor_height_MSL_m']==baro['height_MSL_m']
assert v['historically_dated_WMDR_barometer']['original_WMDR_SHA256']==baro['source_sha256']
assert v['max_same_surface_geopotential_height_difference_m']==0.
for c in v['original_control_hours']:
 original=c['original_GRIB_z'];check=c['source_cast_GRIB_CO_z_control']
 reference=[x for x in work_lineage['original_GRIB_controls'] if x['timestamp_UTC']==c['timestamp_UTC'] and x['variable']=='z'];assert len(reference)==1
 assert original['sha256']==reference[0]['sha256'] and original['hybrid_pv_sha256']==reference[0]['hybrid_pv_sha256']
 assert check['status']=='ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT' and check['coefficient_count']==410240
assert v['original_control_hours'][0]['original_source_z_checksum_at_native_points']==v['original_control_hours'][1]['original_source_z_checksum_at_native_points']
rows=v['radii'];assert [(r['radius_km'],r['n_source_native_N320_columns_inside_radius'],r['n_air_domain_reaches_barometer_height_nominal']) for r in rows]==[(25.,2,0),(50.,8,2),(75.,19,5),(100.,32,9)]
# Scalar great-circle oracle on NV1's declared R=6371 km sphere.
def distance(lat,lon):
 lat0=math.radians(baro['latitude']);lon0=math.radians(baro['longitude']);x=math.radians(lat);y=math.radians(lon)
 b=math.sin((x-lat0)/2)**2+math.cos(lat0)*math.cos(x)*math.sin((y-lon0)/2)**2
 return 12742*math.asin(math.sqrt(b))
points={}
for r in rows:
 for p in r['nearest_five_air_columns_that_reach_barometer']:
  key=(p['latitude'],p['longitude']);points[key]=p
  assert abs(distance(*key)-p['distance_km'])<1e-9
  assert p['distance_km']<=r['radius_km'] and p['native_model_surface_geopotential_height_m']<=378.8
  assert abs(p['barometer_minus_surface_height_m']-(378.8-p['native_model_surface_geopotential_height_m']))<1e-10
for p in v['original_FOUR_IMMEDIATE_NATIVE_GRID_SURFACE']:assert abs(distance(p['latitude'],p['longitude'])-p['distance_km'])<1e-9
candidates=rows[1]['nearest_five_air_columns_that_reach_barometer'];assert len(candidates)==2
admission=[]
for p in candidates:
 H=p['native_model_surface_geopotential_height_m'];bm=baro['height_MSL_m']-H;tm=thermo['height_MSL_m']-H
 admission.append({'latitude':p['latitude'],'longitude':p['longitude'],'distance_km':p['distance_km'],'native_surface_H_m':H,
  'barometer_lower_boundary_margin_m':bm,'thermohygrometer_lower_boundary_margin_m':tm,
  'barometer_nominal_lower_boundary_pass':bm>=0,'thermohygrometer_nominal_lower_boundary_pass':tm>=0,
  'barometer_2m_buffer_pass':bm>=2,'thermohygrometer_2m_buffer_pass':tm>=2,
  'full_hourly_column_admission':'NOT_TESTED_NV1_HAS_NO_T_Q_P_PROFILES'})
assert all(p['barometer_2m_buffer_pass'] for p in admission)
assert [p['thermohygrometer_nominal_lower_boundary_pass'] for p in admission]==[False,True]
# An exported point omitted from the Work stencil is closer than its furthest
# included point. Thus that stencil is not the four globally nearest cells.
furthest=max(v['original_FOUR_IMMEDIATE_NATIVE_GRID_SURFACE'],key=lambda p:p['distance_km'])
assert candidates[0]['distance_km']<furthest['distance_km']
assert (candidates[0]['latitude'],candidates[0]['longitude']) not in {(p['latitude'],p['longitude']) for p in v['original_FOUR_IMMEDIATE_NATIVE_GRID_SURFACE']}
# Both donors east of the site give a separating half-plane: no nonnegative
# weights summing to one can reproduce the station longitude/first moment.
assert all(p['longitude']>baro['longitude'] and p['latitude']<baro['latitude'] for p in candidates)
inv=[1/p['distance_km']**2 for p in candidates];weights=[x/sum(inv) for x in inv]
first=[0.,0.]
for p,w in zip(candidates,weights):
 east=6371*math.cos(math.radians(baro['latitude']))*math.radians(p['longitude']-baro['longitude'])
 north=6371*math.radians(p['latitude']-baro['latitude']);first[0]+=w*east;first[1]+=w*north
result={
 'phase':'P9.3B3_NV1_INDEPENDENT_SENSOR_ADMISSION_AND_SPATIAL_SUPPORT_CROSSCHECK',
 'source_run_id':39765492318,'source_tested_commit':SHA,'source_release_commit':RELEASE,'source_preregistration_commit':PREREG,
 'tests_in_source_CI':6,'artifact_id':12419308583,'artifact_zip_sha256':sha(raw),'artifact_json_sha256':sha(body),'job_log_sha256':sha(log),
 'source_implementation_sha256':{p:sha(blob(SHA,p)) for p in paths},'source_protocol_sha256':v['frozen_source_protocol_SHA256'],
 'verified_Work_audit_sha256':sha(a.work_verified_audit.read_bytes()),
 'source_geometry_report':v,'geometry_check_scope':'Scalar distances, published candidates, barometer/T/RH lower-bound admission and spatial support recomputed; full 32-point census not independently recounted because full candidate catalogue is absent from the source artifact',
 'barometer_height_MSL_m':378.8,'thermohygrometer_height_MSL_m':368.7,'candidate_admission':admission,
 'count_barometer_lower_boundary_pass_within_50km':2,'count_thermohygrometer_lower_boundary_pass_among_the_two_barometer_candidates':1,
 'old_Work_stencil':'FOUR_BRACKETING_GRID_CELLS_TWO_LATITUDE_RINGS_AND_TWO_LONGITUDE_SIDES; NOT_FOUR_NEAREST_BY_DISTANCE',
 'nearest_admissible_omitted_distance_km':candidates[0]['distance_km'],'furthest_included_stencil_distance_km':furthest['distance_km'],
 'horizontal_support':{'all_two_donors_east_of_target':True,'all_two_donors_south_of_target':True,
  'target_inside_nonnegative_weight_convex_hull':False,'inverse_square_distance_weights_for_geometry_diagnostic_only':weights,
  'first_moment_east_north_km_local_tangent_approximation':first,'first_moment_norm_km':math.hypot(*first),
  'two_donor_linear_pressure_design_rank':2,'unknowns_for_unconstrained_two_dimensional_affine_field':3,
  'full_2D_horizontal_gradient_identified_by_two_donors':False,
  'diagnostic_is_new_model_prediction_or_pressure_skill':False},
 'scientific_limits':['Only the surface lower boundary has been tested; hourly T/q/p and full air-domain coverage remain uncomputed',
  'H_MSL mapped to Phi/g0 remains a conditional datum approximation; 2m buffer is a design sensitivity, not a certified uncertainty bound',
  'Barometer and thermohygrometer must use their own coordinates, heights, admitted columns and observation operators',
  'Regional donor transfer requires an explicit horizontal-field assumption or uncertainty interval; geometry alone gives no pressure accuracy'],
 'new_pressure_scores_produced':False,'new_independent_holdout':False,'B4_qualified':False,'production_epw_ready':False,
 'source_reports_or_scientific_code_rewritten':False}
a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'barometer_candidates':2,'thermohygrometer_candidates_among_them':1,'candidate_margins':[(p['barometer_lower_boundary_margin_m'],p['thermohygrometer_lower_boundary_margin_m']) for p in admission],
 'weights':weights,'first_moment_east_north_km':first,'first_moment_norm_km':math.hypot(*first),'site_outside_donor_convex_hull':True}))
