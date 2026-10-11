"""P7B.3C: strict temporal independence, energy and empirical resampling tests."""
import csv
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from p7b3c_conditional_solar import (
    ALPHAS, TRAIN_YEARS, SELECT_YEAR, EVAL_YEARS, SEASONS,
    build_library, complete_days, generate, haurwitz, load_original_station,
    month_hour_score, percentile, project_energy, seasonal_p95,
    sun_cos_midpoint,
)

HEADERS=['station_id','year','month','timestamp_utc','window','variable',
         'original_10min_count','qc_accepted_10min_count',
         'ground_hour_qc_approved','ground_kwh_m2_hour',
         'nasa_location','power_kwh_m2_hour','power_minus_ground']

class HourlySolarContracts(unittest.TestCase):
    def test_folds_immutable_disjoint(self):
        self.assertFalse(set(TRAIN_YEARS)&set(SELECT_YEAR))
        self.assertFalse(set(TRAIN_YEARS)&set(EVAL_YEARS))
        self.assertFalse(set(SELECT_YEAR)&set(EVAL_YEARS))
        self.assertEqual(ALPHAS,(0.,.25,.5,.75,1.))
    def test_clear_sky_night_and_noon(self):
        night=sun_cos_midpoint(datetime(2013,6,22,0))
        noon=sun_cos_midpoint(datetime(2013,6,22,12))
        self.assertEqual(night,0)
        self.assertGreater(noon,.8)
        self.assertEqual(haurwitz(0),0)
        self.assertGreater(haurwitz(noon),.8)
    def test_clear_sky_season(self):
        self.assertGreater(sun_cos_midpoint(datetime(2013,6,22,12)),
                           sun_cos_midpoint(datetime(2013,12,22,12)))
    def test_clear_sky_daily_phase(self):
        self.assertGreater(sun_cos_midpoint(datetime(2013,3,22,12)),
                           sun_cos_midpoint(datetime(2013,3,22,6)))
    def test_quantile_linear(self):
        self.assertAlmostEqual(percentile([0.,10.],.95),9.5)
        self.assertIsNone(percentile([],.5))
    def test_complete_day_needs_all_hours(self):
        dt=datetime(2008,1,1)
        data={dt+timedelta(hours=h):.1 for h in range(23)}
        self.assertEqual(complete_days(data),{})
        data[dt+timedelta(hours=23)]=.1
        self.assertEqual(len(complete_days(data)),1)
    def test_projection_exact_daily_energy(self):
        caps=[1.,.4,1.,0.]+[0.]*20
        raw=[.4,.2,.6,0.]+[0.]*20
        val=project_energy(raw,1.8,caps)
        self.assertAlmostEqual(sum(val),1.8,places=9)
        self.assertTrue(all(0<=x<=c for x,c in zip(val,caps)))
    def test_projection_zero_night(self):
        self.assertEqual(project_energy([1.]*24,0,[.4]*24),[0.]*24)
    def test_projection_unreachable_rejected(self):
        with self.assertRaises(ValueError):project_energy([1.]*24,3,[.1]*24)
    def test_project_bad_length(self):
        with self.assertRaises(ValueError):project_energy([1.],[.1][0],[1.])
    def test_library_rejects_incomplete_record(self):
        self.assertRaises(ValueError,build_library,{datetime(2007,1,1):.5})
    def test_original_ground_filter_not_nasa_and_q0(self):
        d=datetime(2009,6,1,10)
        base={'station_id':'30','year':'2009','month':'6','timestamp_utc':d.isoformat()+'+00:00',
              'window':'record_start','variable':'cglo','original_10min_count':'6',
              'qc_accepted_10min_count':'6','ground_hour_qc_approved':'True',
              'ground_kwh_m2_hour':'0.4','nasa_location':'graz_station30',
              'power_kwh_m2_hour':'0.5','power_minus_ground':'0.1'}
        rows=[base,{**base,'station_id':'16412'},
              {**base,'nasa_location':'nasa_gcm_cell'},
              {**base,'window':'record_end'},
              {**base,'variable':'chim'},
              {**base,'timestamp_utc':(d+timedelta(hours=1)).isoformat()+'+00:00',
               'qc_accepted_10min_count':'0','ground_hour_qc_approved':'False'}]
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'obs.csv'
            with file.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=HEADERS);w.writeheader();w.writerows(rows)
            result,qc=load_original_station(file,'record_start',[2009])
        self.assertEqual(result,{datetime(2009,6,1,11):.4})
        self.assertEqual(qc,{2009:1})
    def test_no_model_event_date_correlation(self):
        dt=datetime(2013,6,1,8)
        obs={dt+timedelta(hours=h):.05 for h in range(10)}
        with self.assertRaisesRegex(ValueError,'insufficient'):
            month_hour_score(obs,obs)
    def test_seasonal_deltas_must_have_true_consecutive_hours(self):
        data={datetime(2009,6,1,8):.1,datetime(2009,6,1,10):.3}
        with self.assertRaisesRegex(ValueError,'insufficient'):
            seasonal_p95(data)
    def test_stochastic_reproducible_and_conserving(self):
        library={s:[{'day':f'2007-06-{i:02d}','kt':.4+i*.001,
                     'ratios':[1.+.1*math.sin(j+i) for j in range(24)]}
                    for i in range(1,16)] for s in ('DJF','MAM','JJA','SON')}
        d=datetime(2013,6,1)
        rows=[(d+timedelta(hours=h),.2 if 8<=h<18 else 0.,
               .8 if 8<=h<18 else 0.,
               .5 if 8<=h<18 else 0.) for h in range(24)]
        x,qa=generate({d.date():rows},library,.75,2)
        y,qb=generate({d.date():rows},library,.75,2)
        self.assertEqual(x,y)
        self.assertAlmostEqual(sum(x.values()),2.,places=10)
        self.assertLess(qa['max_daily_energy_residual'],1e-9)
    def test_m0_unchanged_if_alpha_zero(self):
        dt=datetime(2013,6,1)
        rows=[(dt+timedelta(hours=h),.01*h,.7,.4) for h in range(24)]
        x,q=generate({dt.date():rows},{},0,0)
        self.assertEqual([x[t] for t,*_ in rows],[r[1] for r in rows])

if __name__=='__main__':unittest.main()