"""Offline contracts for seven-model P6.1 daily source/solar regression."""
import json
import unittest
from p6_seven_daily import MODELS, WINDOWS, REFERENCE, check_reference, model_variables, SOURCE_EXCEPTIONS
from p6_daily_multivariable import SPECS, strict_join
from p6_access_full_period import summarize_daily
from test_p6_daily_multivariable import fixture

class SevenModelContract(unittest.TestCase):
    def test_seven_unique_models(self):
        self.assertEqual(len(MODELS),7)
        self.assertEqual(len(set(MODELS)),7)
        self.assertNotIn('ACCESS-CM2',MODELS)

    def test_nine_nasa_variables(self):
        self.assertEqual(len(SPECS),9)
        self.assertIn('rsds',SPECS)
        self.assertIn('huss',SPECS)

    def test_expected_700_model_years(self):
        self.assertEqual(len(WINDOWS),5)
        self.assertEqual(sum(b-a+1 for a,b in
            ((w[1],w[2]) for w in WINDOWS.values()))*len(MODELS),700)

    def test_all_frozen_p5_reference_months(self):
        src=json.loads(REFERENCE.read_text(encoding='utf8'))
        self.assertEqual(src['scale'],100000)
        self.assertEqual(src['order'],list(WINDOWS))
        self.assertEqual(set(src['models']),set(MODELS))
        count=0
        for model in MODELS:
            for i,window in enumerate(WINDOWS):
                numbers=src['models'][model][i]
                self.assertEqual(len(numbers),12)
                self.assertTrue(all(n>0 for n in numbers))
                climo=[{'ghi_mean_kwh_m2':n/100000} for n in numbers]
                self.assertEqual(check_reference(model,window,climo)['status'],'PASS')
                count+=12
        self.assertEqual(count,420)

    def test_mismatched_p5_value_rejected(self):
        src=json.loads(REFERENCE.read_text(encoding='utf8'))
        values=src['models'][MODELS[0]][0]
        climo=[{'ghi_mean_kwh_m2':v/100000} for v in values]
        climo[7]['ghi_mean_kwh_m2']+=.002
        with self.assertRaisesRegex(ValueError,'GHI mismatch'):
            check_reference(MODELS[0],list(WINDOWS)[0],climo)

    def test_documented_variable_exception_is_unique(self):
        self.assertEqual(SOURCE_EXCEPTIONS, {'IPSL-CM6A-LR': ('huss',)})
        self.assertEqual(len(model_variables('IPSL-CM6A-LR')),8)
        for model in MODELS:
            if model!='IPSL-CM6A-LR':
                self.assertEqual(len(model_variables(model)),9)

    def test_ipsl_huss_null_not_fabricated(self):
        payload=fixture(2014)
        del payload['huss']
        joined,qa=strict_join(payload,'historical',2014,allowed_missing=('huss',))
        self.assertEqual(len(joined),365)
        self.assertEqual(qa['missing_variables'],['huss'])
        self.assertTrue(all(row['huss']=='' for row in joined))
        self.assertEqual(len(qa['available_variables']),8)

    def test_ipsl_monthly_huss_aggregate_stays_blank(self):
        payload=fixture(2014)
        del payload['huss']
        joined,_=strict_join(payload,'historical',2014,allowed_missing=('huss',))
        mm,yr,clim=summarize_daily(joined,'historical-1995-2014','historical',(2014,))
        self.assertEqual(len(mm),12)
        self.assertTrue(all(r['huss_mean_kg_kg']=='' for r in mm))
        self.assertEqual(len(yr),1)
        self.assertGreater(clim[0]['ghi_mean_kwh_m2'],0)

    def test_unsupported_missing_source_is_rejected(self):
        p=fixture(2014)
        del p['rsds']
        with self.assertRaisesRegex(ValueError,'Nine variables required'):
            strict_join(p,'historical',2014,allowed_missing=('huss',))

    def test_365_day_join(self):
        f=fixture(2014)
        for v in f:f[v]['calendar']='365_day'
        daily,qa=strict_join(f,'historical',2014)
        self.assertEqual(qa['calendar'],'noleap')
        self.assertEqual(len(daily),365)

if __name__=='__main__': unittest.main()
