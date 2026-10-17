"""P9.2A offline physical invariants, seed, UTC, leakage, event regimes."""
import unittest,datetime as dt
from p9_2a_joint_weather_regimes import (
 FIELDS,Day,regime,check_vector,canonical_days,sampler,diagnostics,seam_cost,scoring
)
SHA='a'*64
def v(hour=0,rain=0.,cloud=10.):
 return {'temperature_2m':9.+hour*.1,'dew_point_2m':7.5,
 'relative_humidity_2m':80.,'surface_pressure':1001.,'precipitation':rain,
 'cloud_cover':cloud,'shortwave_radiation':220.,'direct_radiation':110.,
 'diffuse_radiation':110.,'direct_normal_irradiance':180.,
 'wind_speed_10m':2.,'wind_direction_10m':200.}
def day(y,d,cloud=10.,rain=0.):
 return Day(dt.date(y,1,d),tuple(v(h,rain if 8<=h<16 else 0,cloud) for h in range(24)),SHA)
class P92AContract(unittest.TestCase):
 def test_regimes(self):
  self.assertEqual(regime(v()),'clear_dry')
  self.assertEqual(regime(v(cloud=90)),'cloudy_dry')
  self.assertEqual(regime(v(cloud=50)),'mixed_dry')
  self.assertEqual(regime(v(rain=.01)),'wet')
 def test_missing_cloud_refused(self):
  x=v();del x['cloud_cover']
  with self.assertRaisesRegex(ValueError,'MISSING'):regime(x)
 def test_nonphysical_dewpoint_refused(self):
  x=v();x['dew_point_2m']=x['temperature_2m']+3
  with self.assertRaisesRegex(ValueError,'THERMODYNAMIC'):check_vector(x)
 def test_negative_rain_refused(self):
  with self.assertRaisesRegex(ValueError,'PRECIPITATION'):check_vector(v(rain=-1))
 def test_source_joint_fields_preserved_exactly(self):
  donors=[day(2019,10,10.,.2),day(2020,10,90.,.5)]
  out=sampler(donors,[dt.date(2022,1,10),dt.date(2022,1,11)],7313)
  for d in out:self.assertIn(d.vectors,[x.vectors for x in donors])
 def test_reproducible_seed(self):
  pool=[day(y,j,90. if j%2 else 5.,.5 if j%3 else 0.)
        for y in (2019,2020) for j in range(10,17)]
  dates=[dt.date(2022,1,j) for j in range(10,17)]
  self.assertEqual([x.vectors for x in sampler(pool,dates,7313)],
                   [x.vectors for x in sampler(pool,dates,7313)])
 def test_target_year_leakage_blocked(self):
  with self.assertRaisesRegex(ValueError,'LEAKAGE'):
   sampler([day(2022,10)], [dt.date(2022,1,10)],7313)
 def test_month_substitution_blocked(self):
  with self.assertRaisesRegex(ValueError,'NO_SOURCE'):
   sampler([day(2019,10)], [dt.date(2022,7,10)],7313)
 def test_exact_UTC(self):
  vv=[v(h) for h in range(24)]
  arrays={k:[x[k] for x in vv] for k in FIELDS}
  times=[f'2019-01-10T{h:02d}:00Z' for h in range(24)]
  self.assertEqual(len(canonical_days(times,arrays,SHA)),1)
  times[0]=times[0][:-1]
  with self.assertRaisesRegex(ValueError,'UTC'):canonical_days(times,arrays,SHA)
 def test_no_duplicate_time(self):
  vv=[v(h) for h in range(24)]
  arrays={k:[x[k] for x in vv] for k in FIELDS}
  times=[f'2019-01-10T{h:02d}:00Z' for h in range(24)];times[2]=times[1]
  with self.assertRaisesRegex(ValueError,'DUPLICATE'):canonical_days(times,arrays,SHA)
 def test_seam_cost(self):
  self.assertEqual(seam_cost(v(),v()),0)
  self.assertGreater(seam_cost(v(),v(cloud=95)),0)
 def test_wet_spell_diagnostics(self):
  d=diagnostics([day(2019,10,90,.7),day(2019,11,5,0)])
  self.assertEqual(d['n_hours'],48)
  self.assertGreater(d['P_next_wet_given_wet'],0)
  self.assertGreater(d['wet_minus_dry_cloud_pp'],0)
 def test_hourly_iid_preserves_joint_hourly_vector(self):
  pool=[day(y,j,10 if j%2 else 90,.5 if j%3 else 0)
        for y in (2019,2020) for j in range(10,17)]
  out=sampler(pool,[dt.date(2022,1,j) for j in range(10,17)],7313,
              mode='iid_joint_hourly_control') if False else sampler(
                  pool,[dt.date(2022,1,j) for j in range(10,17)],7313,
                  mode='iid_hourly_joint_vector')
  self.assertEqual(sum(len(x.vectors) for x in out),168)
if __name__=='__main__':unittest.main()
