"""IGE P8.2E scientific contracts: cross-year, hourly extremes, strict UTC-end to EPW fixed CET."""
import unittest,datetime as dt,math,calendar
import numpy as np
from p8_2e_crossyear import annual_hours,epw_hour_map,spell_metrics,extreme_skill,donor_set,annual_predict
from p8_2a_humidity import esat_water_hpa

class CrossYearContracts(unittest.TestCase):
    def test_native_utc_years_are_complete(self):
        self.assertEqual(len(annual_hours(2018)),8760)
        self.assertEqual(len(annual_hours(2020)),8784)
        self.assertEqual(annual_hours(2020)[-1],dt.datetime(2020,12,31,23))

    def test_epw_utc_end_of_hour_to_fixed_cet(self):
        m=epw_hour_map(annual_hours(2018),2018)
        self.assertEqual((m[0]['native_utc_index'],m[0]['month'],m[0]['day'],m[0]['epw_hour']),(0,1,1,1))
        self.assertEqual((m[-1]['month'],m[-1]['day'],m[-1]['epw_hour']),(12,31,24))
        self.assertEqual(len(m),8760)

    def test_epw_no_dst_duplicate_or_missing_hours(self):
        hs=annual_hours(2018);m=epw_hour_map(hs,2018)
        for target in [dt.datetime(2018,3,25,1),dt.datetime(2018,10,28,1),dt.datetime(2018,7,1,12)]:
            i=hs.index(target)
            self.assertEqual(m[i]['epw_hour'],target.hour+1)
            self.assertEqual((m[i]['month'],m[i]['day']),(target.month,target.day))
        self.assertEqual(sum(r['month']==3 and r['day']==25 for r in m),24)
        self.assertEqual(sum(r['month']==10 and r['day']==28 for r in m),24)

    def test_2020_leap_scored_8784_epw_filtered_8760(self):
        hs=annual_hours(2020);m=epw_hour_map(hs,2020)
        self.assertEqual(len(hs),8784);self.assertEqual(len(m),8760)
        self.assertEqual(sum(h.month==2 and h.day==29 for h in hs),24)
        self.assertFalse(any(r['month']==2 and r['day']==29 for r in m))
        self.assertEqual(sum(r['month']==2 for r in m),28*24)
        self.assertEqual((m[-1]['month'],m[-1]['day'],m[-1]['epw_hour']),(12,31,24))

    def test_invalid_hour_alignment_rejected(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            epw_hour_map(annual_hours(2020)[:-1],2020)
        with self.assertRaisesRegex(ValueError,'fixed CET'):
            epw_hour_map(annual_hours(2018),2018,timezone_hours=2)

    def test_spells_account_for_gaps(self):
        h=[dt.datetime(2018,1,1)+dt.timedelta(hours=i) for i in (0,1,2,4,5)]
        v=np.array([92,94,95,96,97])
        r=spell_metrics(h,v,90,True)
        self.assertEqual(r['longest_spell_h'],3)
        self.assertEqual(r['n_spells'],2)
        self.assertEqual(r['n_spells_ge6h'],0)

    def test_spells_boundary_thresholds(self):
        h=[dt.datetime(2018,1,1)+dt.timedelta(hours=i) for i in range(6)]
        self.assertEqual(spell_metrics(h,np.array([90,89.9,90,90,91,90]),90,True)['n_event_hours'],5)
        self.assertEqual(spell_metrics(h,np.array([30.,29.9,30,20,29,35]),30,False)['n_event_hours'],3)

    def test_event_skill_perfect_prediction(self):
        h=[dt.datetime(2018,1,1)+dt.timedelta(hours=i) for i in range(48)]
        v=np.array([95. if i<24 else 25. for i in range(48)])
        target={t:{'RH':float(x)} for t,x in zip(h,v)}
        out=extreme_skill(target,{'RH':v},h,'T',2018,'full_multidonor_shape')
        self.assertEqual(len(out),2)
        self.assertTrue(all(row['f1']==1 and row['frequency_bias_pp']==0 for row in out))
        self.assertEqual(out[0]['observed_longest_spell_h'],24)

    def test_target_not_allowed_in_new_year_model(self):
        h=annual_hours(2020)
        target={'station_id':'X','lat':47,'lon':8,'hoehe_m':800}
        with self.assertRaisesRegex(AssertionError,'TARGET OBSERVATIONS'):
            annual_predict(target,[(1,{'station_id':'D1'}),(2,{'station_id':'D2'})],h,{'X':{}},{},[0]*12,[0]*12,year=2020)

    def test_year_specific_donor_eligibility(self):
        h=annual_hours(2020)
        target={'station_id':'X','lat':47,'lon':8,'hoehe_m':800}
        stations={'D1':{'station_id':'D1','lat':47.1,'lon':8,'hoehe_m':800},'D2':{'station_id':'D2','lat':47.2,'lon':8,'hoehe_m':900}}
        weather={k:{x:{} for x in h} for k in stations}
        monthly={k:{f'2020-{m:02d}':{'e':7} for m in range(1,13)} for k in stations}
        selected=donor_set(target,stations,weather,monthly,year=2020)
        self.assertEqual(len(selected),2)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):donor_set(target,stations,weather,monthly,year=2018)

    def test_full_frozen_predictor_with_leap_year(self):
        year=2020; hours=annual_hours(year)
        target={'station_id':'X','lat':47,'lon':8,'hoehe_m':800}
        donor=[(10.,{'station_id':'D1','hoehe_m':400}),(20.,{'station_id':'D2','hoehe_m':500})]
        months={s['station_id']:{f'{year}-{m:02d}':{'e':6} for m in range(1,13)} for _,s in donor}
        w={}
        for i,(_,s) in enumerate(donor):
            w[s['station_id']]={h:{'T':8.+8*math.sin(2*math.pi*h.timetuple().tm_yday/366),
                                    'P':950.,'e':6.*(1+.1*math.sin(2*math.pi*h.hour/24+i))} for h in hours}
        pred,diag=annual_predict(target,donor,hours,w,months,[-.00045]*12,[-.0065]*12,year=2020)
        self.assertEqual(diag['n_hours'],8784)
        for a in pred.values():
            self.assertTrue(np.all(a['RH']<=100.00001))
            self.assertTrue(np.all(a['Td']<=a['T']+1.e-7))
            self.assertEqual(len(a['e']),8784)
            for m in range(1,13):
                ii=[i for i,x in enumerate(hours) if x.month==m]
                self.assertAlmostEqual(float(a['e'][ii].mean()),diag['monthly'][m-1]['reconstructed_e_mean_hpa'],places=7)

if __name__=='__main__':unittest.main()

class EPWPayloadContracts(unittest.TestCase):
    def test_epw_payload_mapped_year2020_not_true_leap_weather_file(self):
        from p8_2e_crossyear import epw_humidity_payload
        hours=annual_hours(2020)
        fake={'T':np.full(8784,12.),'Td':np.full(8784,7.),'RH':np.full(8784,60.),'P':np.full(8784,960.)}
        payload=epw_humidity_payload(hours,2020,fake)
        self.assertEqual(len(payload),8760)
        self.assertEqual(payload[0]['epw_hour'],1)
        self.assertEqual(payload[-1]['epw_hour'],24)
        self.assertEqual(payload[-1]['station_pressure_Pa'],96000.)
    def test_epw_payload_rejects_dewpoint_above_drybulb(self):
        from p8_2e_crossyear import epw_humidity_payload
        hours=annual_hours(2018)
        fake={'T':np.full(8760,12.),'Td':np.full(8760,13.),'RH':np.full(8760,70.),'P':np.full(8760,960.)}
        with self.assertRaisesRegex(ValueError,'physical state'):epw_humidity_payload(hours,2018,fake)
    def test_patch_base_preserves_unrelated_weather(self):
        from p8_2e_crossyear import epw_humidity_payload,patch_epw_with_verified_base
        hours=annual_hours(2018);fake={'T':np.full(8760,12.),'Td':np.full(8760,7.),'RH':np.full(8760,60.),'P':np.full(8760,960.)}
        payload=epw_humidity_payload(hours,2018,fake)
        header=[['LOCATION','TEST','CH','CHE','IGE','9999','47','8','1','800'],['DESIGN CONDITIONS','0'],['TYPICAL/EXTREME PERIODS','0'],['GROUND TEMPERATURES','0'],['HOLIDAYS/DAYLIGHT SAVINGS','No','0','0','0'],['COMMENTS 1','synthetic fixture'],['COMMENTS 2','synthetic fixture'],['DATA PERIODS','1','1','Data','Tuesday','1/1','12/31']]
        rows=[]
        for r in payload:
            a=['999']*35;a[:5]=[str(r['year']),str(r['month']),str(r['day']),str(r['epw_hour']),'60'];a[20]='270';a[14]='100'
            rows.append(a)
        out=patch_epw_with_verified_base(header,rows,2018,payload,47,8,800)
        self.assertEqual(len(out),8760)
        self.assertEqual(out[0][9],'96000.0')
        self.assertTrue(all(a[i]==b[i] for a,b in zip(out,rows) for i in range(35) if i not in (6,7,8,9)))
        with self.assertRaisesRegex(ValueError,'fixed Swiss standard'):
            patch_epw_with_verified_base(header,rows,2018,payload,47,8,800,timezone_hours=2)