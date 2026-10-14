import unittest
from p8_2f_expanded_2019 import prioritized_candidates
class ExpandedStationPilotContracts(unittest.TestCase):
 def test_original_pool_remains_available(self):
  m={'AAA':{'station_id':'AAA','lat':47.0,'lon':8.0,'hoehe_m':100},
     'BBB':{'station_id':'BBB','lat':47.001,'lon':8.0,'hoehe_m':100},
     'CCC':{'station_id':'CCC','lat':48.0,'lon':8.0,'hoehe_m':100}}
  near,pool=prioritized_candidates(m,targets=['AAA'],original_pool=['CCC'],limit=1)
  self.assertEqual(near['AAA'],['BBB'])
  self.assertEqual(pool,['BBB','CCC'])
 def test_target_never_in_nearest_list(self):
  m={'AAA':{'station_id':'AAA','lat':47.0,'lon':8.0,'hoehe_m':100},
     'BBB':{'station_id':'BBB','lat':47.001,'lon':8.0,'hoehe_m':100}}
  near,pool=prioritized_candidates(m,targets=['AAA'],original_pool=[],limit=1)
  self.assertNotIn('AAA',near['AAA'])
if __name__=='__main__':unittest.main()