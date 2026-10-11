"""P7B.3D cross-year/cross-site source, physics, independence contracts."""
import unittest
from datetime import datetime,timedelta,timezone,date
from p7b3d_crosssite_generalization import (
  DONORS,GRAZ,EVAL_YEARS,TRAIN_YEARS,SELECT_YEAR,ALPHA,QUALITY,
  full_days,aggregate_6of6,build_daily_models,geometry,solar_cos,
  metadata_station_check,project_energy,solar_cloud_persistence,pct
)

class CrossSiteScienceContracts(unittest.TestCase):
    def test_preset_site_independence_and_fixed_holdouts(self):
        self.assertEqual(set(DONORS),{53,94,200})
        self.assertEqual(GRAZ[0],30)
        self.assertFalse(set(EVAL_YEARS)&set(TRAIN_YEARS))
        self.assertNotIn(SELECT_YEAR,EVAL_YEARS)
        self.assertNotIn(SELECT_YEAR,TRAIN_YEARS)
        self.assertEqual(ALPHA,.75)
    def test_original_qc_rejects_zero(self):
        self.assertNotIn(0,QUALITY)
        self.assertIn(21,QUALITY)
    def test_utc_to_cet_exact_hour_no_dst(self):
        d=datetime(2013,7,1,12,tzinfo=timezone.utc)
        row=[(d+timedelta(minutes=10*i),200.,True) for i in range(6)]
        r,n=aggregate_6of6(row,'record_start',2013)
        self.assertEqual(len(r),1)
        self.assertAlmostEqual(r[datetime(2013,7,1,13)],.2)
    def test_record_end_uses_own_hour(self):
        d=datetime(2013,7,1,12,tzinfo=timezone.utc)
        row=[(d+timedelta(minutes=10*i),200.,True) for i in range(6)]
        r,n=aggregate_6of6(row,'record_end',2013)
        self.assertEqual(len(r),0)
    def test_missing_or_unchecked_ten_minute_invalidates_hour(self):
        d=datetime(2013,7,1,12,tzinfo=timezone.utc)
        row=[(d+timedelta(minutes=10*i),200.,i!=3) for i in range(6)]
        r,n=aggregate_6of6(row,'record_start',2013)
        self.assertEqual(r,{})
    def test_exactly_six_samples(self):
        d=datetime(2013,7,1,12,tzinfo=timezone.utc)
        row=[(d+timedelta(minutes=10*i),200.,True) for i in range(5)]
        r,_=aggregate_6of6(row,'record_start',2013)
        self.assertEqual(r,{})
    def test_complete_original_24_hour_days_only(self):
        d=datetime(2013,7,1)
        a={d+timedelta(hours=i):.2 for i in range(23)}
        self.assertEqual(full_days(a),{})
        a[d+timedelta(hours=23)]=.2
        self.assertEqual(len(full_days(a)),1)
    def test_sun_geometry_day_night(self):
        self.assertGreater(solar_cos(datetime(2013,6,21,12),47.08,15.45),.7)
        self.assertEqual(solar_cos(datetime(2013,6,21,0),47.08,15.45),0)
    def test_subhour_geometry_nonnegative(self):
        a=geometry(date(2013,6,21),47.08,15.45)
        self.assertEqual(len(a),24)
        self.assertTrue(all(toa>=0 and clear>=0 for _,toa,clear in a))
        self.assertGreater(sum(v[1] for v in a),7.)
    def test_daily_known_energy_exact(self):
        sample={date(2013,6,21):[.0]*6+[.08,.22,.35,.42,.50,.55,.56,.55,.43,.34,.2,.06]+[0.]*6}
        values,obs,flags=build_daily_models(sample,47.08,15.45)
        self.assertFalse(flags)
        a=list(values.values())[0]
        self.assertAlmostEqual(sum(x[1] for x in a),sum(sample[date(2013,6,21)]),places=9)
        self.assertEqual(len(obs),24)
        self.assertTrue(all(x[1]>=0 and x[1]<=x[2]+1e-10 for x in a))
    def test_exclude_unreachable_daily_energy_not_modify_truth(self):
        sample={date(2013,6,21):[1.]*24}
        model,obs,flags=build_daily_models(sample,47.08,15.45)
        self.assertEqual(len(model),0)
        self.assertEqual(len(obs),0)
        self.assertEqual(flags[0]['reason'],'DAILY_OBS_GHI_EXCEEDS_REGISTERED_CAP')
    def test_original_metadata_location_and_alias_contract(self):
        params=[{'name':'cglo','unit':'W/m²'},{'name':'cglo_flag'}]
        legend=[{'key':str(x),'value':'v'} for x in QUALITY|{0}]
        stations=[{'id':i,'has_global_radiation':True,'lat':lat,'lon':lon,'group_id':None}
                  for i,(_,lat,lon) in DONORS.items()]
        meta={'stations':stations,'parameters':params,'code_lists':{'q21':legend}}
        self.assertEqual(len(metadata_station_check(meta)),3)
        stations[0]['group_id']=30
        with self.assertRaisesRegex(ValueError,'alias'):
            metadata_station_check(meta)
    def test_clear_not_identical_to_toa(self):
        a=geometry(date(2013,6,21),47.08,15.45)
        self.assertTrue(any(0<c<toa for _,toa,c in a))
    def test_cloud_run_persistence_no_night_counts(self):
        day=date(2013,6,21)
        rows={datetime(2013,6,21,h):0 for h in range(24)}
        out=solar_cloud_persistence(rows,47.08,15.45)
        self.assertGreater(out['cloud_run_count'],0)
        self.assertLess(out['p95_cloud_run_hours'],24)
    def test_percentile_endpoints(self):
        self.assertEqual(pct([1,2,3],0),1)
        self.assertEqual(pct([1,2,3],1),3)
    def test_fail_closed_physical_projection(self):
        with self.assertRaises(ValueError):
            project_energy([1.,1.],3.,[1.,1.])

if __name__=='__main__':unittest.main()