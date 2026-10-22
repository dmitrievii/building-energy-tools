#!/usr/bin/env python3
"""Original native reduced Gaussian N320 surface-only Graz valley census.

This reads *only native model z (param129)*, source geometry lat/lon,
original source GRIB for source z identity, and PREVIOUSLY DOCUMENTED dated
WMO barometer instrument geolocation. NO pressure observations, no T/q,
no weather-model pressure predictions; no station-error fitting.
"""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
from p9_3b3_native_sources import (
    NativeCache,NativeSource,GaussianGrid,original_surface_grib,
    synthesize,verify_grib_copy)
from p9_3b3_compare_vertical_frame import G0,SourceBlocked

VERSION="IGE_P93B3_NATIVE_GRAZ_VALLEY_SOURCE_ONLY_CENSUS_V1"
PROTOCOL_FILE="research/ige_cmip6/p9_3b3_native_completion_protocol.json"
# Fixed original 2021 Graz Universität WMO OSMAR dated instrument, not station DEM.
BAROMETER={"station":"Graz Universität",
 "wsi":"0-20000-0-11290","lat":47.0777777778,"lon":15.4488888889,
 "sensor_height_MSL_m":378.8,
 "original_WMDR_SHA256":"d58aa5a6c37fb030d9b8a3bcd8c7c3c1cf0964a2609acf43c1408cba9f13b788",
 "datum_verification":"APPROXIMATE_GEOID_MSL_TO_PHI_OVER_CONSTANT_G0_NOT_CERTIFIED"}
TIMES=("2021-02-01T00:00","2021-08-01T00:00")
RADII_KM=(25.,50.,75.,100.)
NEAREST_LIMIT=5
MAX_POINT_COUNT=300
MAX_STATIC_DIFF_M=.25

def vector_distance_km(latitudes,longitudes,station):
 """Great-circle lengths on WGS-like sphere, geographic not observed pressure."""
 la1=np.deg2rad(np.asarray(latitudes,float))
 lo1=np.deg2rad(np.asarray(longitudes,float))
 la2=math.radians(station['lat']);lo2=math.radians(station['lon'])
 dlat=la1-la2;dlon=lo1-lo2
 a=np.sin(dlat/2)**2+np.cos(la1)*np.cos(la2)*np.sin(dlon/2)**2
 return 12742*np.arcsin(np.sqrt(np.clip(a,0.,1.)))

def frozen_radius_census(grid_points,distances,heights,station=BAROMETER,radii=RADII_KM):
 """Pure source-only audit, no source pressure or observed measurements."""
 ds=np.asarray(distances,float);H=np.asarray(heights,float)
 if ds.ndim!=1 or len(ds)!=len(grid_points) or H.shape!=ds.shape or not np.all(np.isfinite(H)):
  raise ValueError('P93NV_SOURCE_GEOMETRY_DIMENSIONS_OR_FINITE')
 if np.any(ds<0) or not np.all(np.isfinite(ds)) or not all(r>0 for r in radii):
  raise ValueError('P93NV_DISTANCE_RADIUS_INVALID')
 if not (0<station['sensor_height_MSL_m']<5000):
  raise ValueError('P93NV_ORIGINAL_BAROMETER_HEIGHT_UNQUALIFIED')
 # The result does not depend on the supplied point order.
 ordered=sorted(range(len(ds)),key=lambda i:(float(ds[i]),float(grid_points[i][0]),
       float(grid_points[i][1])))
 rows=[];hbar=float(station['sensor_height_MSL_m'])
 for radius in radii:
  inside=[i for i in ordered if ds[i]<=radius+1e-9]
  eligible=[i for i in inside if H[i]<=hbar]
  conservative=[i for i in inside if H[i]<=hbar-2]
  def entry(i):
   return {'latitude':float(grid_points[i][0]),'longitude':float(grid_points[i][1]),
      'distance_km':float(ds[i]),'native_model_surface_geopotential_height_m':float(H[i]),
      'barometer_minus_surface_height_m':hbar-float(H[i])}
  rows.append({'radius_km':float(radius),
    'n_source_native_N320_columns_inside_radius':len(inside),
    'n_air_domain_reaches_barometer_height_nominal':len(eligible),
    'n_air_domain_reaches_2m_below_barometer_sensitivity':len(conservative),
    'min_source_surface_height_m':float(min(H[i] for i in inside)) if inside else None,
    'max_source_surface_height_m':float(max(H[i] for i in inside)) if inside else None,
    'nearest_native_grid_geometric':entry(inside[0]) if inside else None,
    'nearest_air_column_that_reaches_barometer':entry(eligible[0]) if eligible else None,
    'nearest_five_air_columns_that_reach_barometer':[entry(i) for i in eligible[:NEAREST_LIMIT]],
    'original_station_pressure_scores_accessed':False})
 final=rows[-1]
 if not final['n_air_domain_reaches_barometer_height_nominal']:
  status="NO_NATIVE_OROGRAPHY_BELOW_BAROMETER_WITHIN_PREDEFINED_RADIUS"
 else:
  d=final['nearest_air_column_that_reaches_barometer']['distance_km']
  status=("AIR_DOMAIN_EXISTS_BUT_HORIZONTAL_REPRESENTATIVENESS_NOT_QUALIFIED"
          if d>50 else "SOURCE_ONLY_AT_LEAST_ONE_NATIVE_COLUMN_REACHES_BAROMETER_NOT_PRESSURE_QUALIFICATION")
 return {'radii':rows,'status':status,'NO_STATION_PRESSURE_T_RH_VALUES_READ':True}

def run(out,private_cache,protocol_path):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 protocol_file=Path(protocol_path)
 raw=protocol_file.read_bytes();protocol=json.loads(raw)
 if (protocol.get('source_control_hours')!=list(TIMES) or
    protocol.get('underground_policy')!='BLOCK_NO_EXTRAPOLATION' or
    protocol.get('primary_first_model_level')!=124 or
    protocol.get('source_base')!='https://storage.googleapis.com/gcp-public-data-arco-era5'):
  raise ValueError('P93NV_WORK_ORIGINAL_SOURCE_PROTOCOL_DRIFT')
 cache=NativeCache(private_cache,protocol)
 surface=NativeSource(protocol['source_base']+'/'+protocol['surface'],cache)
 moisture=NativeSource(protocol['source_base']+'/'+protocol['moisture'],cache)
 lat=moisture._vector('latitude');lon=moisture._vector('longitude')
 grid=GaussianGrid(lat,lon)
 if (len(lat)!=542080 or len(grid.rings)!=640):
  raise ValueError('P93NV_ORIGINAL_NATIVE_REDUCED_N320_COORDINATES_CHANGED')
 distances=vector_distance_km(lat,lon,BAROMETER)
 ids=np.flatnonzero(distances<=max(RADII_KM)+1e-8)
 if not (4<len(ids)<=MAX_POINT_COUNT):
  raise ValueError('P93NV_UNEXPECTED_ORIGINAL_NATIVE_100KM_POINT_COUNT')
 points=grid.points([int(i) for i in ids])
 nearest4=set(grid.neighbors(BAROMETER['lat'],BAROMETER['lon']))
 if not nearest4.issubset(set(map(int,ids))):
  raise ValueError('P93NV_FOUR_NATIVE_IMMEDIATE_NEIGHBORS_MISSING')
 orig=surface.array('z')[1]
 if (orig.get('GRIB_paramId')!=129 or orig.get('units')!='m**2 s**-2' or
    orig.get('GRIB_gridType')!='sh'):
  raise ValueError('P93NV_NATIVE_ORIGINAL_Z_NOT_SURFACE_GEOPOTENTIAL')
 source=[]
 H_time=[]
 for stamp in TIMES:
  uri=(protocol['source_base']+'/'+protocol['original_surface_GRIB'].format(
   month=stamp[:7].replace('-',''),variable='zs'))
  original_grib,identity=original_surface_grib(cache,uri,stamp,129)
  co=surface.field('z',stamp)
  check=verify_grib_copy(original_grib,co)
  H=synthesize(co,points)/G0
  if not np.isfinite(H).all() or np.any((H < -500)|(H>5500)):
   raise SourceBlocked('P93NV_ORIGINAL_MODEL_SURFACE_NONPHYSICAL')
  source.append({'timestamp_UTC':stamp,'original_GRIB_z':identity,
    'source_cast_GRIB_CO_z_control':check,
    'regridding':'SH_T639_SHTOOLS_REAL_4PI_TO_ORIGINAL_N320_PREDICTOR_ONLY',
    'original_source_z_checksum_at_native_points':hashlib.sha256(
      np.asarray(H,dtype='<f8').tobytes()).hexdigest()})
  H_time.append(H)
 if max(abs(H_time[0]-H_time[1]))>MAX_STATIC_DIFF_M:
  raise SourceBlocked('P93NV_ORIGINAL_SURFACE_Z_NOT_STATIONARY_AT_CONTROLS')
 result=frozen_radius_census(points,distances[ids],H_time[0])
 first={str(int(index)):{'latitude':float(lat[index]),'longitude':float(lon[index]),
       'distance_km':float(distances[index]),
       'surface_H_m':float(H_time[0][int(np.where(ids==index)[0][0])])}
       for index in sorted(nearest4)}
 report={'phase':VERSION,'base_WORK_completed_run':39757573033,
  'source_original_commit':'aebdc005505d2789940fe3f5f7eb14e5d31b788e',
  'prior_incomplete_39_of_50_resolved':True,
  'experimental_scope':'SOURCE_ONLY_GRAZ_NATIVE_OROGRAPHY_NO_PREDICTION',
  'preregistered_control':"docs/IGE_P9_3B3_NATIVE_AT_VALLEY_SOURCE_ONLY_GEOMETRY_PREREG_20261022_RU.md",
  'frozen_source_protocol_SHA256':hashlib.sha256(raw).hexdigest(),
  'historically_dated_WMDR_barometer':BAROMETER,
  'native_N320_total_grid_coordinates':len(lat),
  'source_native_columns_considered_within_100km':len(ids),
  'original_FOUR_IMMEDIATE_NATIVE_GRID_SURFACE':list(first.values()),
  'original_control_hours':source,
  'max_same_surface_geopotential_height_difference_m':float(max(abs(H_time[0]-H_time[1]))),
  'new_2021_pressure_scores_produced':False,
  'original_station_pressure_hourly_observations_read':False,
  'observed_pressure_used_to_select_native_column':False,
  'original_temperature_and_specific_humidity_model_columns_not_loaded':True,
  'original_CanESM5_native_pressure_unavailable':True,
  'new_independent_AT_DE_CH_pressure_accuracy_validation_qualified':False,
  'B4_qualified':False,'production_epw_ready':False,
  'source_lineage':{'surface_CO_z':surface.base,
    'native_reduced_gaussian_latlon_source':moisture.base},
  **result}
 path=out/"p93b3_native_Graz_AT_source_only_100km_geopotential_orography_census.json"
 path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 print("P93NV_ORIGINAL_GRAZ_NATIVE_SURFACE_ONLY_GEOMETRY",json.dumps({
   'native_100km_points':len(ids),'radii':[(r['radius_km'],r['n_air_domain_reaches_barometer_height_nominal']) for r in result['radii']],
   'nearest_eligible':result['radii'][-1]['nearest_air_column_that_reaches_barometer'],
   'original_4_surface':list(first.values()),
   'source_status':result['status'],
   'native_air_domain_not_station_skill':True}),flush=True)
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--protocol',default=PROTOCOL_FILE)
 p.add_argument('--private-cache',default='inputs/p93nv-private-cache')
 p.add_argument('--out',default='outputs/p93nv-source-geometry')
 a=p.parse_args();run(a.out,a.private_cache,a.protocol)
