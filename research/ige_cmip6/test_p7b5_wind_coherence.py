"""P7B.5 independent research contracts; no fake success from non-QC sources."""
from __future__ import annotations
import csv,math,tempfile,unittest
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from p7b5_wind_coherence import (
  BASE,STATION,QC,TRAIN,SELECT,VALIDATE,INPUT_SHA,
  metadata,decode,local_times,complete_days,choose,wind_day,donor_direction,
  angular_delta,bins,turn_persistence,read_epw,epw_days,audit_epw,validation_metrics,
)


def stations():return [{'id':STATION,'name':'Graz'}]



class WindContracts(unittest.TestCase):
 def test_original_station_is_not_gcm_synthetic_date(self):
  self.assertEqual(STATION,30);self.assertEqual(TRAIN,(2007,2008))
  self.assertEqual(SELECT,(2009,));self.assertEqual(VALIDATE,(2012,2013,2014))
  self.assertFalse(set(TRAIN)&set(VALIDATE))
 def test_epw_missing_wind_direction_marker_contract(self):
  self.assertEqual(INPUT_SHA,'2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012')
 def test_metadata_missing_flag_rejected(self):
  with self.assertRaisesRegex(ValueError,'hourly QC field'):
   metadata({'parameters':[{'name':'dd','unit':'°'}],'stations':stations()})
 def test_metadata_null_quality_key_skipped_but_required_codes(self):
  fields=('dd','ff','tl','rf','rr');unit=('°','m/s','°C','%','mm')
  meta={'parameters':[e for x,u in zip(fields,unit) for e in ({'name':x,'unit':u},{'name':x+'_flag'})],
        'code_lists':{'q21':[{'key':None,'value':'header'}]+[{'key':x,'value':('ungeprüft' if x==0 else 'approved')} for x in sorted(set(QC)|{0})]},
        'stations':stations()}
  self.assertEqual(metadata(meta)['station']['id'],30)
  meta['code_lists']['q21'][1]['value']='unchecked different'
  with self.assertRaisesRegex(ValueError,'code 0 semantics'):
   metadata(meta)
 def test_calendar_utc_cet_shift_is_explicit(self):
  key=datetime(2012,1,1,tzinfo=timezone.utc)
  payload={key:{'dd':90.,'ff':3.,'tl':4.,'rf':90.,'rr':0.}}
  self.assertIn(datetime(2012,1,1,1),local_times(payload,'record_start'))
  self.assertIn(datetime(2012,1,1,0),local_times(payload,'record_end'))
 def test_incomplete_wind_direction_rejected(self):
  start=datetime(2008,6,1)
  obs={start+timedelta(hours=h):{'ff':2.,'dd':90. if h!=3 else None,'tl':10.,'rf':70.,'rr':0.} for h in range(24)}
  self.assertFalse(complete_days(obs,(2008,)))
 def test_calm_wind_does_not_require_direction(self):
  start=datetime(2008,6,1)
  obs={start+timedelta(hours=h):{'ff':0.2 if h==3 else 2.,'dd':None if h==3 else 90.,
       'tl':10.,'rf':70.,'rr':0.} for h in range(24)}
  out=complete_days(obs,(2008,))
  self.assertEqual(len(out),1)
  self.assertIsNone(out[start.date()]['directions'][3])
 def test_donor_verified_fallback_only(self):
  d={'directions':tuple(210. if x==5 else None for x in range(24))}
  angle,fb=donor_direction(d,4)
  self.assertEqual((angle,fb),(210.,1))
  with self.assertRaisesRegex(ValueError,'no qualified'):
   donor_direction({'directions':(None,)*24},4)
 def test_calm_generated_direction_zero(self):
  day=date(2013,7,1)
  lib={date(2007,7,1)+timedelta(days=i):{'day':date(2007,7,1)+timedelta(days=i),
        'directions':tuple([135.]*24),'speed_mean':2.,'temp_mean':20.,'rh_mean':70.,'wet':False} for i in range(40)}
  # dates span JJA, every donor in July/August
  target={'speed':[0.]*4+[3.]*20,'speed_mean':2.5,'temp_mean':20.,'rh_mean':70.,'wet':False}
  a,_=wind_day(day,target,lib,0)
  self.assertEqual(a[:4],[0.]*4)
  self.assertEqual(a[4:],[135.]*20)
 def test_seed_reproducibility_no_event_date_weather_coupling(self):
  lib={date(2007,6,1)+timedelta(days=i):{'day':date(2007,6,1)+timedelta(days=i),
        'directions':tuple([(i*10)%360]*24),'speed_mean':2.,'temp_mean':20.,'rh_mean':50.,'wet':False} for i in range(40)}
  target={'speed':[3.]*24,'speed_mean':3.,'temp_mean':20.,'rh_mean':50.,'wet':False}
  self.assertEqual(wind_day(date(2013,6,15),target,lib,7),wind_day(date(2013,6,15),target,lib,7))
 def test_circular_angle_wrap(self):
  self.assertEqual(angular_delta(359,1),2)
  self.assertEqual(angular_delta(0,180),180)
 def test_sector_histogram_normalizes(self):
  p=bins([0,90,180,270,None],[1,2,1,1,2]);self.assertAlmostEqual(sum(p),1.)
  self.assertEqual([p[x] for x in (0,2,4,6)],[.25]*4)
 def test_turn_persistence_calm_break(self):
  self.assertEqual(turn_persistence([350.,0.,10.],[3.,3.,3.]),10.)
  self.assertIsNone(turn_persistence([350.,0.],[.2,3.]))
 def test_wind_rose_tv_identity(self):
  target={date(2012,1,1):{'dirs':[90.]*24,'speed':[3.]*24}}
  obs={date(2012,1,1):{'directions':tuple([90.]*24),'speed':tuple([3.]*24)}}
  v=validation_metrics(target,obs)
  self.assertTrue(v['eligible']);self.assertAlmostEqual(v['sector_total_variation'],0.)
 def test_read_epw_sha_guard(self):
  with tempfile.TemporaryDirectory() as p:
   f=Path(p)/'bad.epw';f.write_text('empty')
   with self.assertRaisesRegex(ValueError,'SHA mismatch'):read_epw(f)
 def test_physics_gate_rejects_obvious_unphysical_state(self):
  r=['0']*35;r[6]='15';r[7]='16';r[8]='55';r[9]='90000';r[20]='999';r[21]='2';r[13]='300';r[14]='100';r[15]='200'
  with self.assertRaisesRegex(ValueError,'thermodynamic'):audit_epw([r])

if __name__=='__main__':unittest.main()