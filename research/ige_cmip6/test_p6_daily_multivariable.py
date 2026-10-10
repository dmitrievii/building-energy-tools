"""P6.1 offline contracts: no missing days, unit mixing, or physical closure drift."""
import datetime as dt
import unittest
from p6_daily_multivariable import SPECS,strict_join,validate_unit,validate_value,leap_year

def fixture(year=2014):
    n=366 if leap_year(year) else 365
    days=[(d.year,d.month,d.day) for d in
          (dt.date(year,1,1)+dt.timedelta(days=i) for i in range(n))]
    vals={'tas':280.,'tasmax':285.,'tasmin':278.,'hurs':78.,'huss':.005,
          'pr':.00005,'rsds':100.,'rlds':300.,'sfcWind':2.}
    return {var:{'days':days[:], 'values':[vals[var]]*n,'unit':SPECS[var][0],
                 'calendar':'proleptic_gregorian','lat':46.875,'lon':15.375}
            for var in SPECS}

class PilotContract(unittest.TestCase):
    def test_nominal_data_and_conversions(self):
        rows,qa=strict_join(fixture(),'historical',2014)
        self.assertEqual(len(rows),365)
        self.assertEqual(qa['days'],365)
        self.assertEqual(rows[0]['date'],'2014-01-01')
        self.assertAlmostEqual(rows[0]['tas_c'],6.85)
        self.assertAlmostEqual(rows[0]['pr_mm_day'],4.32)
        self.assertAlmostEqual(rows[0]['rsds_kwh_m2_day'],2.4)

    def test_leap_year(self):
        rows,_=strict_join(fixture(2052),'ssp245',2052)
        self.assertEqual(len(rows),366)
        self.assertIn('2052-02-29',[r['date'] for r in rows])

    def test_missing_day_one_variable(self):
        p=fixture();p['pr']['days'].pop(50);p['pr']['values'].pop(50)
        with self.assertRaisesRegex(ValueError,'misaligned'):strict_join(p,'historical',2014)

    def test_missing_day_all_variables(self):
        p=fixture()
        for k in p:p[k]['days'].pop(50);p[k]['values'].pop(50)
        with self.assertRaisesRegex(ValueError,'Incomplete'):strict_join(p,'historical',2014)

    def test_no_mixed_grid(self):
        p=fixture();p['rsds']['lon']=15.625
        with self.assertRaisesRegex(ValueError,'Mixed grid'):strict_join(p,'historical',2014)

    def test_no_mixed_calendar(self):
        p=fixture();p['rsds']['calendar']='365_day'
        with self.assertRaisesRegex(ValueError,'Mixed CF calendars'):strict_join(p,'historical',2014)

    def test_unit_guard(self):
        p=fixture();p['rsds']['unit']='kWh/m2'
        with self.assertRaisesRegex(ValueError,'noncanonical'):strict_join(p,'historical',2014)

    def test_temperature_guard(self):
        p=fixture();p['tasmin']['values'][25]=290
        with self.assertRaisesRegex(ValueError,'tas lies outside'):strict_join(p,'historical',2014)

    def test_nan_negative_guard(self):
        for k,v in (('hurs',float('nan')),('rsds',-1.),('pr',float('inf'))):
            p=fixture();p[k]['values'][0]=v
            with self.assertRaisesRegex(ValueError,'invalid daily value'):
                strict_join(p,'historical',2014)

    def test_full_variable_set(self):
        p=fixture();p.pop('rlds')
        with self.assertRaisesRegex(ValueError,'Nine variables required'):strict_join(p,'historical',2014)

    def test_noleap_calendar(self):
        p=fixture()
        for k in p:p[k]['calendar']='365_day'
        rows,_=strict_join(p,'historical',2014)
        self.assertEqual(len(rows),365)
        p=fixture(2052)
        for k in p:p[k]['calendar']='365_day'
        with self.assertRaises(ValueError):strict_join(p,'ssp245',2052)

    def test_unit_normalization(self):
        validate_unit('tas','Kelvin')
        validate_unit('rsds','W m-2')
        with self.assertRaises(ValueError):validate_value('huss',1.0)

if __name__=='__main__':unittest.main()
