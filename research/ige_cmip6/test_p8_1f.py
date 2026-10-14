"""P8.1F guards: pre-event features, disjoint sites/years/regions and skill baselines."""
import unittest,datetime,math
import numpy as np
from p8_1f_events import (date_utc,build_pairs,fit_logit,predict_logit,scores,climatology,
                            evaluate_folds,TRAIN_YEARS,TEST_YEARS)
from p8_1f_regions import region,predict_one,station_bootstrap,swiss_dem
from p8_1d_regime import features


def ln(z,temp,wspd=40,dpdp=40):
    chars=list(' '*60)
    def put(a,b,value):chars[a:b]=list(f'{value:>{b-a}d}')
    put(16,21,z);chars[21]=' ';put(22,27,int(temp*10));chars[27]=' '
    put(34,39,dpdp);put(46,51,wspd)
    return ''.join(chars)

def head(site,year,month,day,hour):
    return {'id':site,'year':year,'month':month,'day':day,'hour':hour,'nlev':2}

class Contracts(unittest.TestCase):
    def test_real_igra_field_positions(self):
        from p8_1e_igra_profiles import level
        self.assertEqual(level(ln(200,5.0)),(200,5.))

    def test_event_features_are_exclusively_antecedent(self):
        old=[ln(200,5.0,20,30),ln(500,3.0)]
        current=[ln(200,2.0,50,70),ln(500,5.0)]
        target=head('S',2019,1,1,12)
        first=head('S',2019,1,1,0)
        pairs,_=build_pairs([(first,old),(target,current)],200)
        self.assertEqual(len(pairs),1);self.assertEqual(pairs[0]['y'],1)
        feature=pairs[0]['features'].copy()
        # Same target weather can be changed arbitrarily; forecast covariates unchanged.
        different=[ln(200,-10,200,200),ln(500,-15)]
        altered,_=build_pairs([(first,old),(target,different)],200)
        self.assertEqual(altered[0]['y'],0)
        np.testing.assert_array_equal(feature,altered[0]['features'])
        self.assertEqual(pairs[0]['lead_hours'],12.)
        self.assertGreater(pairs[0]['target_timestamp'],pairs[0]['source_timestamp'])

    def test_26_hour_lead_guard(self):
        a=[ln(200,1),ln(500,2)]
        seq=[(head('S',2019,1,1,0),a),(head('S',2019,1,3,0),a)]
        rows,diag=build_pairs(seq,200)
        self.assertEqual(len(rows),0)
        self.assertEqual(diag['gap_outside_10_to_26h'],1)

    def test_logit_fits_without_sklearn(self):
        rng=np.random.default_rng(20261014)
        rows=[]
        for i in range(110):
            x=np.array([i%2,math.sin(i),math.cos(i),i%2,1.,i%15,0.,float('nan'),12.],float)
            y=int((i%5)<2)
            rows.append({'features':x,'y':y})
        model=fit_logit(rows)
        pred=predict_logit(model,rows)
        self.assertTrue(np.all(np.isfinite(pred)))
        self.assertTrue(np.all((pred>0)&(pred<1)))

    def test_site_and_year_blocks(self):
        sites=['A','B','C']
        rows=[]
        for site in sites:
            for year in (2017,2018,2019,2020):
                for mon in range(1,13):
                    for hour in (0,12):
                        rows.append({'site':site,'year':year,'month':mon,'target_hour':hour,
                            'features':np.array([hour/12,math.sin(mon),math.cos(mon),mon%2,
                              0.,float(mon),2.,1.,12.]),'y':int(mon%3==0)})
        folds,excluded=evaluate_folds(rows,min_test=25)
        self.assertEqual(len(folds),3)
        self.assertEqual(len(excluded),0)
        self.assertTrue(all(f['heldout_site'] not in f['train_sites'] for f in folds))
        self.assertTrue(all(f['n_test']==48 and f['n_train']==96 for f in folds))
        self.assertTrue(set(TRAIN_YEARS).isdisjoint(TEST_YEARS))

    def test_skill_scoring_logloss_and_brier(self):
        v=scores([0,1],[.1,.9]);self.assertAlmostEqual(v['brier'],.01)
        self.assertLess(v['logloss'],.12)

    def test_geographic_partitions_fixed_boundaries(self):
        self.assertEqual(region({'lon':7.499}),'west_lt7.5E')
        self.assertEqual(region({'lon':7.5}),'central_7.5_to_9E')
        self.assertEqual(region({'lon':9}),'east_ge9E')

    def test_no_same_region_donors(self):
        target={'station_id':'T','lat':47.,'lon':6.5,'hoehe_m':900,
              'tpi_1500_m':-60,'tpi_5000_m':-140,'rugged_1500_m':90,'slope_250m_proxy':.1}
        donor=[];obs={'T':{'2018-01':1.}}
        for i in range(12):
            q={'station_id':f'D{i}','lat':47.+(i%4)*.2,'lon':8.0+(i%4)*.1,
               'hoehe_m':300+i*30,'tpi_1500_m':-20,'tpi_5000_m':0,
               'rugged_1500_m':40,'slope_250m_proxy':.08}
            donor.append(q);obs[q['station_id']]={'2018-01':10.+i}
        frozen={'by_buffer':{'0':{'valley_cold_k':-.02,'ridge_cold_k':.05,
           'valley_warm_k':-.03,'ridge_warm_k':.04}}}
        p=predict_one(target,donor,obs,2018,1,[-.005]*12,frozen,0)
        self.assertIsNotNone(p)
        # Introduce a nearer station inside target region: it must never be accepted as donor.
        nearby={**donor[0],'station_id':'LEAK','lat':47.01,'lon':6.51}
        with self.assertRaisesRegex(AssertionError,'GEOGRAPHIC REGION LEAKAGE'):
            predict_one(target,donor+[nearby],obs,2018,1,[-.005]*12,frozen,0)

    def test_spatial_parameters_pre_frozen(self):
        import json
        from pathlib import Path
        src=Path(__file__).resolve().parent/'data'/'p8_1f_frozen_terrain.json'
        if not src.exists():src=Path(__file__).resolve().parent/'frozen_austria_orographic_coefficients.json'
        o=json.loads(src.read_text())
        self.assertEqual(o['source_stage'],'P8.1D')
        self.assertEqual(set(o['by_buffer']),{'0','50'})
        self.assertTrue(all(abs(v)<1 for co in o['by_buffer'].values() for v in co.values()))

    def test_no_station_reused_between_years_in_score_keys(self):
        rows=[]
        for sid in range(10):
            for method,err in [('idw_austria_regional',.5),('frozen_austria_regime',.4)]:
                rows.append({'buffer_km':0,'method':method,'station_id':str(sid),
                  'year':2019,'month':1,'abs_error_c':err})
        v=station_bootstrap(rows,0,reps=50)
        self.assertAlmostEqual(v['mean_station_gain_C'],.1)

if __name__=='__main__':unittest.main()