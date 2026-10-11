"""P7B.3A original station / time / model independence and statistics tests."""
import csv
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from p7b3_observed_hourly_solar import (
    consecutive_deltas, full_days, lag1_daily, moments, paired_metrics,
    percentile, select_observations, synthetic, season)

FIELDS=['station_id','year','month','timestamp_utc','window','variable',
 'original_10min_count','qc_accepted_10min_count','ground_hour_qc_approved',
 'ground_kwh_m2_hour','nasa_location','power_kwh_m2_hour','power_minus_ground']

class P7B3AScienceContracts(unittest.TestCase):
 def test_percentile_linear(self):
  self.assertEqual(percentile([0,10],.9),9)
  self.assertIsNone(percentile([],.95))
  self.assertEqual(moments([0,1,2])['p50'],1)
 def test_no_calendar_date_pairing(self):
  rows,a,b=paired_metrics({(6,12):[.4,.8]}, {(6,12):[.5]})
  self.assertEqual(a['cells'],1)
  self.assertAlmostEqual(a['bias_kwh_m2_hour'],-.1)
  self.assertEqual(b['cells'],1)
 def test_daylight_threshold_excludes_night(self):
  _,a,b=paired_metrics({(1,0):[0.],(1,12):[.05]},
                       {(1,0):[0.],(1,12):[.04]})
  self.assertEqual(a['cells'],2)
  self.assertEqual(b['cells'],1)
 def test_do_not_bridge_missing_hour_for_delta(self):
  data=[(datetime(2013,6,1,10),.1),(datetime(2013,6,1,11),.2),
        (datetime(2013,6,1,13),.9)]
  self.assertEqual(consecutive_deltas(data),[.1])
 def test_require_full_calendar_day(self):
  t=datetime(2013,6,1)
  data={t+timedelta(hours=h):1 for h in range(23)}
  self.assertEqual(full_days(data),{})
  data[t+timedelta(hours=23)]=1
  self.assertEqual(list(full_days(data).values()),[24])
 def test_seasons(self):
  self.assertEqual(season(12),'DJF')
  self.assertEqual(season(5),'MAM')
 def fixture(self,rows):
  td=tempfile.TemporaryDirectory()
  path=Path(td.name)/'obs.csv'
  with path.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=FIELDS)
   w.writeheader()
   w.writerows(rows)
  return td,path
 def row(self,**changes):
  base={'station_id':'30','year':'2013','month':'6',
       'timestamp_utc':'2013-06-01T10:00:00+00:00',
       'window':'record_start','variable':'cglo','original_10min_count':'6',
       'qc_accepted_10min_count':'6','ground_hour_qc_approved':'True',
       'ground_kwh_m2_hour':'0.4','nasa_location':'graz_station30',
       'power_kwh_m2_hour':'0.3','power_minus_ground':'-0.1'}
  return {**base,**changes}
 def test_strict_original_qc_no_station_duplicate_or_nasa(self):
  rows=[self.row(),self.row(station_id='16412'),
        self.row(window='record_end'),self.row(variable='chim'),
        self.row(nasa_location='nasa_gcm_cell'),
        self.row(timestamp_utc='2013-06-01T11:00:00+00:00',
                 qc_accepted_10min_count='0',ground_hour_qc_approved='False'),
        self.row(timestamp_utc='2013-06-01T12:00:00+00:00',
                 original_10min_count='5',qc_accepted_10min_count='5'),
        self.row(timestamp_utc='2013-06-01T13:00:00+00:00',
                 ground_kwh_m2_hour='')]
  td,p=self.fixture(rows)
  try:
   data,qc=select_observations(p,'record_start')
   self.assertEqual(data,{datetime(2013,6,1,11):.4})
   self.assertEqual(qc['qc_accepted_years'],{2013:1})
   self.assertEqual(qc['rejection_counts']['no_complete_source_qc_hour'],2)
  finally:td.cleanup()
 def test_record_end_does_not_leak_into_start(self):
  td,p=self.fixture([self.row(window='record_end')])
  try:
   self.assertFalse(select_observations(p,'record_start')[0])
   self.assertEqual(len(select_observations(p,'record_end')[0]),1)
  finally:td.cleanup()
 def test_duplicate_original_time_rejected(self):
  td,p=self.fixture([self.row(),self.row()])
  try:
   with self.assertRaisesRegex(ValueError,'Duplicate'):
    select_observations(p,'record_start')
  finally:td.cleanup()
 def test_synthetic_source_exact_8760_required(self):
  td=tempfile.TemporaryDirectory()
  p=Path(td.name)/'x.csv'
  p.write_text('local_hour,ghi_Wh\n2013-01-01T00:00:00+01:00,10\n')
  try:
   with self.assertRaisesRegex(ValueError,'8760'):
    synthetic(p,'ghi_Wh')
  finally:td.cleanup()
 def test_lag1_must_not_bridge_missing_days(self):
  start=datetime(2013,6,1)
  data={start+timedelta(hours=h):float(h) for h in range(24)}
  data.update({start+timedelta(days=2,hours=h):float(h) for h in range(24)})
  self.assertEqual(lag1_daily(data)['JJA']['n_pairs'],0)

if __name__=='__main__':unittest.main()
