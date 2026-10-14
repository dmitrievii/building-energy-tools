import unittest,datetime as dt
from p8_2f_station_selection import (metadata_candidates,coverage,closest_eligible_donors,physical_donor_distance_report)

class DonorSelectionContracts(unittest.TestCase):
    def meta(self):
        return {'TAR':dict(station_id='TAR',lat=47.0,lon=8.0,hoehe_m=500),
                'AAA':dict(station_id='AAA',lat=47.02,lon=8.0,hoehe_m=520),
                'BBB':dict(station_id='BBB',lat=47.03,lon=8.0,hoehe_m=530),
                'CCC':dict(station_id='CCC',lat=47.04,lon=8.0,hoehe_m=540),
                'DDD':dict(station_id='DDD',lat=47.05,lon=8.0,hoehe_m=550),
                'EEE':dict(station_id='EEE',lat=47.06,lon=8.0,hoehe_m=560)}
    def month(self,year):return {f'{year}-{i:02d}':{'e':9.1} for i in range(1,13)}
    def hourly(self,year):
        n=8784 if year==2020 else 8760
        return {dt.datetime(year,1,1)+dt.timedelta(hours=i):{'T':10,'P':990,'e':9.1,'RH':70} for i in range(n)}
    def test_metadata_only_does_not_read_weather(self):
        near,union=metadata_candidates(self.meta(),['TAR'],['EEE'],nearest_count=4)
        self.assertEqual(near['TAR'],['AAA','BBB','CCC','DDD'])
        self.assertIn('EEE',union);self.assertIn('TAR',union)
    def test_donor_selection_excludes_target(self):
        m=self.meta();sel=closest_eligible_donors(m['TAR'],m,set(m),'TAR',4)
        self.assertEqual([s['station_id'] for _,s in sel],['AAA','BBB','CCC','DDD'])
        self.assertTrue(all(d>0 for d,s in sel))
    def test_reject_target_mismatch(self):
        with self.assertRaises(AssertionError):closest_eligible_donors(self.meta()['TAR'],self.meta(),{'AAA'},'EEE')
    def test_reject_timestamps_without_weather(self):
        w=self.hourly(2019)
        for v in w.values():v['RH']=None
        self.assertFalse(coverage(w,self.month(2019),2019)['eligible_complete'])
    def test_reject_one_missing_temperature(self):
        w=self.hourly(2019);w[next(iter(w))]['T']=None
        self.assertEqual(coverage(w,self.month(2019),2019)['n_hour_complete_TPeRH'],8759)
        self.assertFalse(coverage(w,self.month(2019),2019)['eligible_complete'])
    def test_nonleap_complete(self):
        self.assertTrue(coverage(self.hourly(2018),self.month(2018),2018)['eligible_complete'])
    def test_leapyear_complete(self):
        self.assertTrue(coverage(self.hourly(2020),self.month(2020),2020)['eligible_complete'])
    def test_leapyear_8760_rejected(self):
        self.assertFalse(coverage(self.hourly(2018),self.month(2020),2020)['eligible_complete'])
    def test_missing_month_rejected(self):
        m=self.month(2019);del m['2019-04']
        self.assertFalse(coverage(self.hourly(2019),m,2019)['eligible_complete'])
    def test_donor_metadata_no_raw(self):
        donor=closest_eligible_donors(self.meta()['TAR'],self.meta(),set(self.meta()),'TAR')
        d=physical_donor_distance_report(self.meta()['TAR'],donor)
        self.assertEqual(len(d),4);self.assertEqual(d[0]['height_difference_m'],20)
    def test_insufficient_candidates_fails_closed(self):
        with self.assertRaises(ValueError):closest_eligible_donors(self.meta()['TAR'],self.meta(),{'AAA','BBB'},'TAR')
    def test_small_search_window_rejected(self):
        with self.assertRaises(ValueError):metadata_candidates(self.meta(),['TAR'],[],nearest_count=2)
if __name__=='__main__':unittest.main()