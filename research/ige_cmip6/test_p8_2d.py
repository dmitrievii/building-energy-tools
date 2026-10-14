"""P8.2D scientific non-leakage, annual coverage, humidity feasibility and EPW invariance."""
import unittest,datetime as dt,calendar,math,io
import numpy as np
from p8_2d_annual import (annual_hours,parse_swiss_year,hypsometric_pressure,
  weights,donor_set,annual_predict,evaluate,epw_humidity_patch)
from p8_2a_humidity import esat_water_hpa

class StrictContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hours=annual_hours()
        cls.target={'station_id':'T','lat':47.,'lon':8.,'hoehe_m':800.}
        cls.sources=[{'station_id':'D1','lat':46.5,'lon':8.,'hoehe_m':450.},
                     {'station_id':'D2','lat':47.5,'lon':8.,'hoehe_m':550.}]
        cls.monthly={d['station_id']:{f'2019-{m:02d}':{'e':4.3} for m in range(1,13)} for d in cls.sources}
        cls.weather={}
        for i,d in enumerate(cls.sources):
            cls.weather[d['station_id']]={}
            for h in cls.hours:
                t=12+6*math.sin(2*math.pi*(h.timetuple().tm_yday-90)/365)+2*math.sin(2*math.pi*h.hour/24)+i
                cls.weather[d['station_id']][h]={'T':t,'P':960-i*12,'e':4.3*(1+.2*math.sin(2*math.pi*h.hour/24+i)), 'RH':55.,'Td':-4.}
        cls.donors=[(12.,cls.sources[0]),(18.,cls.sources[1])]
        cls.loge=[-.00045]*12;cls.tslopes=[-.0065]*12

    def test_annual_calendar_strict(self):
        self.assertEqual(len(self.hours),8760)
        self.assertEqual(self.hours[-1],dt.datetime(2019,12,31,23))
        with self.assertRaisesRegex(ValueError,'nonleap'):annual_hours(2020)

    def test_raw_swiss_hourly_duplicate_rejected(self):
        h='station_abbr;reference_timestamp;tre200h0;prestah0;pva200h0;ure200h0;tde200h0\n'
        a='D1;01.01.2019 00:00;10;960;4;50;-5\n'
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):parse_swiss_year((h+a+a).encode(),'D1')

    def test_no_target_weather_allowed(self):
        obs={**self.weather,'T':self.weather['D1']}
        with self.assertRaisesRegex(AssertionError,'TARGET OBSERVATIONS'):
            annual_predict(self.target,self.donors,self.hours,obs,self.monthly,self.loge,self.tslopes)

    def test_no_target_monthly_weather_allowed(self):
        obs={**self.monthly,'T':self.monthly['D1']}
        with self.assertRaisesRegex(AssertionError,'TARGET OBSERVATIONS'):
            annual_predict(self.target,self.donors,self.hours,self.weather,obs,self.loge,self.tslopes)

    def test_no_target_station_as_donor(self):
        with self.assertRaisesRegex(AssertionError,'TARGET IN DONOR SET'):
            annual_predict(self.target,[(10,self.target),*self.donors],self.hours,self.weather,self.monthly,self.loge,self.tslopes)

    def test_pressure_hypsometric(self):
        self.assertLess(hypsometric_pressure(980,10,1000),980)
        self.assertGreater(hypsometric_pressure(980,10,-1000),980)
        self.assertAlmostEqual(hypsometric_pressure(980,10,0),980)

    def test_distance_weights(self):
        v=weights([2,4]);self.assertAlmostEqual(v.sum(),1)
        self.assertGreater(v[0],v[1])

    def test_donor_selection_geographic_only(self):
        d=donor_set(self.target,{s['station_id']:s for s in self.sources},self.weather,self.monthly)
        self.assertEqual(len(d),2)
        self.assertNotIn('T',[s['station_id'] for _,s in d])

    def test_full_annual_hourly_physically_closed_and_monthly_e_conserved(self):
        predictions,diag=annual_predict(self.target,self.donors,self.hours,self.weather,self.monthly,self.loge,self.tslopes)
        self.assertEqual(diag['n_hours'],8760)
        self.assertEqual(len(predictions),4)
        for method,a in predictions.items():
            self.assertEqual(len(a['e']),8760)
            self.assertTrue(np.all(a['RH']>0))
            self.assertTrue(np.all(a['RH']<=100+1e-8))
            self.assertTrue(np.all(a['Td']<=a['T']+1e-7))
            self.assertTrue(np.all(a['e']<a['P']))
            np.testing.assert_allclose(a['RH'],100*a['e']/np.array([esat_water_hpa(x) for x in a['T']]),rtol=1e-12)
            for m in range(1,13):
                ix=[i for i,h in enumerate(self.hours) if h.month==m]
                self.assertAlmostEqual(float(a['e'][ix].mean()),diag['monthly'][m-1]['reconstructed_e_mean_hpa'],places=8)

    def test_annual_missing_donor_hours_fail_closed(self):
        w={k:v.copy() for k,v in self.weather.items()}
        for a in w.values():a.pop(self.hours[10])
        with self.assertRaisesRegex(ValueError,'NO_INDEPENDENT_HOURLY_DONOR_COVERAGE'):
            annual_predict(self.target,self.donors,self.hours,w,self.monthly,self.loge,self.tslopes)

    def test_true_target_only_in_evaluation(self):
        predicted,diag=annual_predict(self.target,self.donors,self.hours,self.weather,self.monthly,self.loge,self.tslopes)
        raw={h:{'T':2,'P':900,'e':5,'RH':60,'Td':-2} for h in self.hours}
        scores,months,n=evaluate(raw,predicted,self.hours,'T')
        self.assertEqual(n,8760);self.assertTrue(scores);self.assertTrue(months)

    def test_epw_patch_location_and_weather_preservation(self):
        h=[['LOCATION','T','State','CHE','IGE','0000','47','8','1','800'],
           ['DESIGN CONDITIONS','0'],['TYPICAL/EXTREME PERIODS','0'],
           ['GROUND TEMPERATURES','0'],['HOLIDAYS/DAYLIGHT SAVINGS','No','0','0','0'],
           ['COMMENTS 1','synthetic structural test'],['COMMENTS 2','synthetic structural test'],
           ['DATA PERIODS','1','1','Data','Tuesday','1/1','12/31']]
        r=[]
        for t in self.hours:
            row=['0']*35
            row[:5]=[str(t.year),str(t.month),str(t.day),str(t.hour+1),'60']
            row[13]='123';row[20]='999';row[21]='3'
            r.append(row)
        d={k:np.ones(8760)*v for k,v in [('T',12),('Td',7),('RH',66),('P',960)]}
        adjusted=epw_humidity_patch(h,r,2019,d,self.target)
        self.assertEqual(len(adjusted),8760)
        self.assertEqual(adjusted[0][9],'96000.00')
        self.assertTrue(all(a[j]==b[j] for a,b in zip(r,adjusted) for j in range(35) if j not in (6,7,8,9)))
        with self.assertRaisesRegex(ValueError,'site latitude'):
            epw_humidity_patch(h,r,2019,d,{**self.target,'lat':46})
        r[10][3]='99'
        with self.assertRaisesRegex(ValueError,'CALENDAR'):
            epw_humidity_patch(h,r,2019,d,self.target)

if __name__=='__main__':unittest.main()