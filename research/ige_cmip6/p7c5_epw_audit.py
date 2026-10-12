#!/usr/bin/env python3
"""Independent P7C.5 EPW qualification. Does not assert EnergyPlus execution."""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from pathlib import Path
from collections import Counter
import numpy as np

BASE_FIELDS={0,1,2,3,4,5,9,10,11,16,17,18,19,20,22,23,24,25,26,27,28,29,30,31,32,34}
MUTABLE={6,7,8,12,13,14,15,21,33}
NAMES={6:'dry_bulb_C',7:'dewpoint_C',8:'RH_pct',9:'pressure_Pa',12:'horizontal_IR_W_m2',13:'GHI_Wh_m2',14:'DNI_Wh_m2',15:'DHI_Wh_m2',16:'global_illuminance_lux',17:'direct_illuminance_lux',18:'diffuse_illuminance_lux',20:'wind_direction_deg',21:'wind_speed_m_s',22:'total_sky_cover_tenths',23:'opaque_sky_cover_tenths',24:'visibility_km',28:'precipitable_water_mm',32:'albedo',33:'precipitation_mm'}

def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(2**20),b''):h.update(chunk)
 return h.hexdigest()

def epw(path):
 with open(path,encoding='utf-8-sig',newline='') as f:
  it=csv.reader(f);head=[next(it) for _ in range(8)];rows=list(it)
 if len(rows)!=8760 or any(len(r)!=35 for r in rows):raise ValueError('EPW structure 8760×35 violated: '+str(path))
 x=np.array([[float(r[j]) for j in range(35) if j!=5 and j!=27] for r in rows],dtype=np.float64)
 c=[j for j in range(35) if j!=5 and j!=27]; d={j:x[:,k] for k,j in enumerate(c)}
 return head,rows,d

def sat_vp(tc):
 # Buck 1981 approximation liquid water, within -30..50 C diagnostic region
 return 611.21*np.exp((18.678-tc/234.5)*tc/(257.14+tc))

def check(original,member):
 h,b,bs=original;f,rows,cs=member
 if h[0][:4]!=f[0][:4] or h[0][5:]!=f[0][5:]:raise ValueError('Physical Location header changed')
 mismatch=Counter()
 for j in BASE_FIELDS:
  mismatch[j]=sum(a[j]!=c[j] for a,c in zip(b,rows))
 other={str(j):n for j,n in mismatch.items() if n>0}
 if other:raise ValueError('Nonmutable fields changed: '+str(other))
 if any(int(r[1])!=int(q[1]) or int(r[2])!=int(q[2]) or int(r[3])!=int(q[3]) or int(r[4])!=int(q[4]) for r,q in zip(b,rows)):
  raise ValueError('EPW time alignment changed')
 t,td,rh,p=[cs[j] for j in (6,7,8,9)]
 q_humidity=np.maximum(sat_vp(t),1e-9)
 rh_from_dew=100*sat_vp(td)/q_humidity
 counts={
   'not_finite_critical_hours':int(np.sum(~np.isfinite(np.array([cs[j] for j in (6,7,8,9,12,13,14,15,20,21,33)]).T).all(axis=1))),
   'RH_out_of_range_hours':int(np.count_nonzero((rh<0)|(rh>100))),
   'dewpoint_exceeds_T_hours':int(np.count_nonzero(td>t+1e-6)),
   'psychrometric_RH_disagreement_gt_2pp_hours':int(np.count_nonzero(np.abs(rh-rh_from_dew)>2)),
   'RH_at_saturation_hours':int(np.count_nonzero(rh>=99.995)),
   'RH_jump_gt20pp_hours':int(np.count_nonzero(np.abs(np.diff(rh))>20)),
   'daylight_GHI_positive_hours':int(np.count_nonzero(cs[13]>1)),
   'GHI_negative_hours':int(np.count_nonzero(cs[13]<0)),
   'DNI_negative_hours':int(np.count_nonzero(cs[14]<0)),
   'DHI_negative_hours':int(np.count_nonzero(cs[15]<0)),
   'wind_direction_missing_hours':int(np.count_nonzero(cs[20]>=999)),
   'wind_negative_hours':int(np.count_nonzero(cs[21]<0)),
   'rain_negative_hours':int(np.count_nonzero(cs[33]<0)),
   'opaque_cloud_missing_hours':int(np.count_nonzero(cs[23]>=99)),
   'total_cloud_missing_hours':int(np.count_nonzero(cs[22]>=99)),
   'visibility_missing_hours':int(np.count_nonzero(cs[24]>=9999)),
   'precipitable_water_missing_hours':int(np.count_nonzero(cs[28]>=999)),
 }
 # Independent cross-field test: solar radiation has been morphed, illuminance has not.
 changed_radiation= np.abs(cs[13]-bs[13])>0.5
 lux_valid=(bs[16]<999999)&(bs[16]>0)
 counts['changed_GHI_hours_with_original_unchanged_global_lux']=int(np.count_nonzero(changed_radiation&lux_valid&(cs[16]==bs[16])))
 counts['changed_DNI_hours_with_original_unchanged_direct_lux']=int(np.count_nonzero((np.abs(cs[14]-bs[14])>0.5)&(bs[17]<999999)&(bs[17]>0)&(cs[17]==bs[17])))
 counts['changed_DHI_hours_with_original_unchanged_diffuse_lux']=int(np.count_nonzero((np.abs(cs[15]-bs[15])>0.5)&(bs[18]<999999)&(bs[18]>0)&(cs[18]==bs[18])))
 # Additional study limitations unchanged opaque sky and ground temperature etc.
 max_psy=float(np.max(np.abs(rh-rh_from_dew)))
 changed_cols=[j for j in MUTABLE if any(a[j]!=c[j] for a,c in zip(b,rows))]
 numeric={
  'mean_temperature_C':float(np.mean(t)),'annual_GHI_kwh_m2':float(np.sum(cs[13])/1000),
  'mean_RH_pct':float(np.mean(rh)),'maximum_RH_mismatch_pp':max_psy,
  'max_hourly_RH_jump_pp':float(np.max(np.abs(np.diff(rh)))),
  'daily_Tmax_ge30_count':int(np.sum(np.maximum.reduce(t.reshape(365,24),axis=1)>=30)),
  'annual_precipitation_mm':float(np.sum(cs[33])),
 }
 # EPW air humidity must be consistent with dry bulb, dewpoint and RH at reporting precision.
 blocking=any(counts[k] for k in ['not_finite_critical_hours','RH_out_of_range_hours','dewpoint_exceeds_T_hours','psychrometric_RH_disagreement_gt_2pp_hours','GHI_negative_hours','DNI_negative_hours','DHI_negative_hours','wind_direction_missing_hours','wind_negative_hours','rain_negative_hours'])
 warnings={
  'solar_luminous_cross_field_unmorphed':any(counts[k] for k in ['changed_GHI_hours_with_original_unchanged_global_lux','changed_DNI_hours_with_original_unchanged_direct_lux','changed_DHI_hours_with_original_unchanged_diffuse_lux']),
  'cloud_and_other_met_inherited':True,'ground_temperature_header_inherited':True,
  'inherited_wind_direction_is_not_future_wind_forecast':True,
  'humidity_optimizer_strict_convergence_not_demonstrated':True,
 }
 return {'physical_blocking_flag':bool(blocking),'research_warnings':warnings,'changed_epw_field_indices':changed_cols,'counts':counts,'metrics':numeric}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--epw-dir',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
 b=epw(a.baseline);files=sorted(Path(a.epw_dir).glob('*.epw'))
 if len(files)!=28:raise ValueError(f'Expected 28 EPWs, found {len(files)}')
 entries=[]
 for path in files:
  e=check(b,epw(path));e.update({'filename':path.name,'sha256':sha(path)});entries.append(e)
 c=Counter();flags=Counter()
 for e in entries:
  c.update(e['counts']);flags.update({k:int(v) for k,v in e['research_warnings'].items()})
 outcome={'stage':'P7C5_PHYSICAL_AUDIT_NOT_ENERGYPLUS','baseline_file_sha256':sha(a.baseline),'count_epws':len(files),'all_8760_35_pass':True,'EPW_LOCATION_provider_tag_replaced_by_IGE':True,
 'any_blocking_physical_error':any(x['physical_blocking_flag'] for x in entries), 'research_only':True, 'production_epw_ready':False,
 'total_counts':dict(c),'warning_counts_by_member':dict(flags),'members':entries,
 'energyplus_real_simulations_executed':False}
 Path(a.out).mkdir(parents=True,exist_ok=True)
 (Path(a.out)/'p7c5_independent_physical_audit.json').write_text(json.dumps(outcome,indent=2)+'\n')
 with (Path(a.out)/'p7c5_member_physical_summary.csv').open('w',newline='') as f:
  fields=['filename','sha256','physical_blocking_flag','mean_temperature_C','annual_GHI_kwh_m2','daily_Tmax_ge30_count','maximum_RH_mismatch_pp','psychrometric_RH_disagreement_gt_2pp_hours','changed_GHI_hours_with_original_unchanged_global_lux','changed_DNI_hours_with_original_unchanged_direct_lux','changed_DHI_hours_with_original_unchanged_diffuse_lux','opaque_cloud_missing_hours']
  w=csv.DictWriter(f,fields);w.writeheader()
  for x in entries:
   d={**x,**x['counts'],**x['metrics']};w.writerow({k:d.get(k,'') for k in fields})
 print(json.dumps({k:v for k,v in outcome.items() if k not in ('members',)},indent=2))

if __name__=='__main__':main()