import unittest,datetime
from p8_1d_hourly_pilot import unpack,summarize_pairs,PAIRS
class Tests(unittest.TestCase):
 def test_real_utc_index_and_strict_qc(self):
  times=[(datetime.datetime(2018,1,1,tzinfo=datetime.timezone.utc)+datetime.timedelta(hours=i)).isoformat() for i in range(3)]
  payload={'timestamps':times,'features':[{'properties':{'station':119,'parameters':{
    'tl':{'unit':'°C','data':[-4,-3,-2]},'tl_flag':{'data':[10,99,20]}}}}]}
  r=unpack(payload,{119},3,'tl_flag')
  self.assertEqual(len(r[119]),2)
  with self.assertRaisesRegex(ValueError,'Incomplete timestamp'):
   unpack(payload,{119},4,'tl_flag')
 def test_warm_alpine_over_valley_is_indicator_not_profile(self):
  lower,upper,name=PAIRS[0]
  dates=[datetime.datetime(2015,1,5,h,tzinfo=datetime.timezone.utc) for h in (22,23)]
  rows=summarize_pairs({lower:{d:0. for d in dates},upper:{d:2. for d in dates}},
      {lower:{'altitude':1200},upper:{'altitude':2000}},2015,1,{})
  a=[r for r in rows if r['time_of_day']=='night'][0]
  self.assertAlmostEqual(a['fraction_upper_warmer'],1.0)
  self.assertEqual(a['qualified_upper_warmer_hours'],2)
if __name__=='__main__':unittest.main()