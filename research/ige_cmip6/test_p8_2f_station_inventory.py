import unittest
from p8_2f_station_inventory import catalog
class TestInventory(unittest.TestCase):
 def test_full_network_outranks_restricted_pool(self):
  meta={
    'ABO':{'station_id':'ABO','station':'Target','lat':47.0,'lon':8.0,'hoehe_m':1000},
    'AAA':{'station_id':'AAA','station':'near','lat':47.01,'lon':8.0,'hoehe_m':1000},
    'BBB':{'station_id':'BBB','station':'far','lat':47.1,'lon':8.0,'hoehe_m':1000}}
  rows=catalog(meta,sites=['ABO'],pool=['BBB'])
  a={x['candidate']:x for x in rows}
  self.assertEqual(a['AAA']['distance_rank_all_metadata'],1)
  self.assertFalse(a['AAA']['in_original_12_site_pool'])
  self.assertEqual(a['AAA']['hourly_and_monthly_data_availability'],'NOT_CHECKED')
 def test_altitude_ranking_differs(self):
  meta={'ABO':{'station_id':'ABO','station':'t','lat':47,'lon':8,'hoehe_m':1000},
        'AAA':{'station_id':'AAA','station':'a','lat':47.001,'lon':8,'hoehe_m':0},
        'BBB':{'station_id':'BBB','station':'b','lat':47.015,'lon':8,'hoehe_m':1000}}
  a={r['candidate']:r for r in catalog(meta,sites=['ABO'],pool=['AAA'])}
  self.assertEqual(a['AAA']['distance_rank_all_metadata'],1)
  self.assertEqual(a['BBB']['altitude_rank_all_metadata'],1)
if __name__=='__main__':unittest.main()