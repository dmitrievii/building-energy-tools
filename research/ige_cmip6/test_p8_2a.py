"""P8.2A: paired humidity reconstruction, immutable QC and temporal blocks."""
import unittest,math
import numpy as np
from p8_2a_humidity import (esat_water_hpa,loge_lapse,decode_monthly,
    training_stations,moisture_predictions,evaluate,station_bootstrap,TRAIN_YEARS,TEST_YEARS)

class HumidityContracts(unittest.TestCase):
    def test_saturation(self):
        self.assertAlmostEqual(esat_water_hpa(0),6.1121,places=2)
        self.assertAlmostEqual(esat_water_hpa(20),23.38,delta=.2)
        self.assertGreater(esat_water_hpa(30),esat_water_hpa(20))
    def test_monthly_mean_noncommutation(self):
        # Equal-duration high and low T, with RH=50% both: monthly e(mean) != RH*es(T_mean).
        mean_e=(.5*esat_water_hpa(-10)+.5*esat_water_hpa(30))/2
        self.assertGreater(100*mean_e/esat_water_hpa(10),50.)
    def test_log_vapour_vertical_scale(self):
        d=[]
        for i in range(25):
            z=150+i*85
            d.append({'station_id':i,'hoehe_m':z,'lat':46.5+i*.03,'lon':13.5+((i*7)%8)*.10,
                 'loge_train':[math.log(13)-z/2100.]*12})
        lapse=loge_lapse(d,0)
        self.assertAlmostEqual(lapse,-1/2100,delta=.0001)
    def test_absent_month_or_bad_qc_not_filled(self):
        axis=[f'{year:04d}-{m:02d}-01T00:00:00Z' for year in range(1991,2021) for m in range(1,13)]
        data=[10.]*360
        flag=[10]*360;flag[1]=90
        fields={x:{'unit':u[0],'data':data[:]} for x,u in {
           'tl_mittel':('°C',),'dampf_mittel':('hPa',),'rf_mittel':('%',),
           'absf_mittel':('g/m³',),'p':('hPa',)}.items()}
        for key in list(fields):fields[key+'_flag']={'unit':'code','data':flag[:]}
        fields['dampf_mittel']['data'][2]=None
        features=[{'properties':{'station':{'id':12},'parameters':fields}}]
        r,diag=decode_monthly({'timestamps':axis,'features':features},{12})
        self.assertNotIn('1991-02',r[12]['dampf_mittel'])
        self.assertNotIn('1991-03',r[12]['dampf_mittel'])
        self.assertEqual(diag['dampf_mittel_flag_rejected'],1)
        self.assertEqual(diag['dampf_mittel_null'],1)
    def test_wrong_axis_rejected(self):
        with self.assertRaisesRegex(ValueError,'chronology'):
            decode_monthly({'timestamps':['2010-01-01'],'features':[]},set())
    def test_no_flag_cannot_silently_pass(self):
        axis=[f'{y}-{m:02d}' for y in range(1991,2021) for m in range(1,13)]
        record={'properties':{'station':15,'parameters':{'dampf_mittel':{'unit':'hPa','data':[10]*360}}}}
        v,diagnostics=decode_monthly({'timestamps':axis,'features':[record]},{15})
        self.assertEqual(v[15].get('dampf_mittel',{}),{})
        self.assertEqual(diagnostics['dampf_mittel_no_flag_station'],1)
    def test_leakage_station_guard(self):
        t={'station_id':1,'hoehe_m':1000}
        donors=[(10.,{'station_id':1,'hoehe_m':1000})]*8
        with self.assertRaisesRegex(AssertionError,'LEAKAGE'):
            moisture_predictions(t,donors,'2015-01',{},-.0005)
    def test_methods_share_donors_and_fixed_scale(self):
        t={'station_id':55,'hoehe_m':2000}
        donors=[(10+i,{'station_id':i,'hoehe_m':1000}) for i in range(8)]
        series={i:{'dampf_mittel':{'2015-06':10.}} for i in range(8)}
        x=moisture_predictions(t,donors,'2015-06',series,-.0005)
        self.assertEqual(set(x),{'e_linear_idw','e_log_idw','e_log_fixed_scale','e_log_regional'})
        self.assertAlmostEqual(x['e_linear_idw'],10.)
        self.assertAlmostEqual(x['e_log_idw'],10.)
        self.assertAlmostEqual(x['e_log_fixed_scale'],10*math.exp(-.5),places=8)
        self.assertAlmostEqual(x['e_log_regional'],10*math.exp(-.5),places=8)
    def test_train_period_disjoint(self):
        self.assertEqual((min(TRAIN_YEARS),max(TRAIN_YEARS)),(1991,2010))
        self.assertEqual((min(TEST_YEARS),max(TEST_YEARS)),(2011,2020))
        self.assertFalse(set(TRAIN_YEARS)&set(TEST_YEARS))
    def test_historical_training_not_using_test(self):
        meta={1:{'station_id':1,'station':'A','lat':47.,'lon':15.,'hoehe_m':300.}}
        e={f'{y}-{m:02d}':8. for y in range(1991,2011) for m in range(1,13)}
        t={f'{y}-{m:02d}':10. for y in range(1991,2011) for m in range(1,13)}
        s={1:{'dampf_mittel':{**e,'2019-01':1000.},'tl_mittel':{**t,'2019-01':500.}}}
        calib=training_stations(meta,s)
        self.assertAlmostEqual(calib[0]['loge_train'][0],math.log(8))
        self.assertAlmostEqual(calib[0]['tmittel'][0],10.)
    def test_synthetic_fold_changes_from_target_only(self):
        meta={};series={}
        for i in range(20):
            z=200+60*i
            meta[i]={'station_id':i,'station':f'S{i}','lat':46.5+.055*i,'lon':14.+(i%4)*.31,'hoehe_m':z}
            e={f'{y}-{m:02d}':float(math.exp(math.log(12)-z/2200)) for y in range(1991,2021) for m in range(1,13)}
            t={f'{y}-{m:02d}':float(14.-.006*z) for y in range(1991,2021) for m in range(1,13)}
            rh={f'{y}-{m:02d}':50. for y in range(1991,2021) for m in range(1,13)}
            series[i]={'dampf_mittel':e,'tl_mittel':t,'rf_mittel':rh}
        preds,diag,n=evaluate(meta,series,0)
        self.assertTrue(len(preds)>200)
        focus=[x for x in preds if x['station_id']==0 and x['year']==2019 and x['month']==1]
        self.assertEqual(len(focus),6) # synthetic series deliberately has no absf
        prev={x['method']:x['error'] for x in focus}
        series[0]['dampf_mittel']['2019-01']+=2.
        nxt,_,_=evaluate(meta,series,0)
        focus2=[x for x in nxt if x['station_id']==0 and x['year']==2019 and x['month']==1]
        for x in focus2:
            if x['method'] in ('e_linear_idw','e_log_idw','e_log_fixed_scale','e_log_regional'):
                self.assertAlmostEqual(x['error'],prev[x['method']]-2.)
    def test_cluster_bootstrap_sign(self):
        rows=[]
        for site in range(12):
            for m in range(1,13):
                for name,err in [('e_linear_idw',2.),('e_log_regional',1.)]:
                    rows.append({'station_id':site,'year':2019,'month':m,'buffer_km':0,'variable':'vapour_pressure_hpa','method':name,'abs_error':err})
        d=station_bootstrap(rows,0,'e_linear_idw','e_log_regional','vapour_pressure_hpa',100)
        self.assertAlmostEqual(d['mean_station_MAE_gain'],1.)
        self.assertGreater(d['CI95'][0],.99)

if __name__=='__main__':unittest.main()