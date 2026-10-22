"""Independent pressure comparison, immutable seals and full denominators."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from p9_3b3_native_columns import NativeColumns
from p9_3b3_native_validation import predicted_pressure,score_pressure,score_sealed,sealed_read
from p9_3b3_native_run import PROTOCOL,evaluate_hour,protocol_guard
from p9_3b3_compare_vertical_frame import SourceBlocked
from test_p9_3b3_reference_column import TIME,column


METHODS=['P1_ISOTHERMAL_SAME_SINGLE_ANCHOR','P1_FIXED_LAPSE_0.0065_SAME_SINGLE_ANCHOR','P2_NATIVE_SINGLE_COLUMN','P2_NATIVE_UP_TO_FOUR_COLUMNS']


def protocol():return {'countries':['AT','DE','CH'],'methods':METHODS,'development_days':['2021-02-01','2021-08-01'],
    'minimum_cell_coverage':.9,'pressure_MAE_gate_hPa':2.}


def dummy_columns(ground=0):
    reader=NativeColumns.__new__(NativeColumns);reader.protocol=protocol()
    reader.heights={co:{'sensors':{'pressure':{'height_MSL_m':500.,'latitude':47.,'longitude':15.5,'source_sha256':'b'*64}}}
        for co in reader.protocol['countries']}
    reader.by_country={co:[0,1] for co in reader.protocol['countries']}
    return reader,{0:column(ground=ground,lat=47),1:column(ground=ground,lat=47.25)}


class NativePressureOracles(unittest.TestCase):
    def test_declared_model_and_resources_cannot_silently_diverge_from_execution(self):
        p=json.loads(PROTOCOL.read_text());protocol_guard(p)
        for key,value in (('weights','ERROR_FITTED_WEIGHTS'),('methods',['DIFFERENT_MODEL']),
                ('max_download_bytes',2147483649),('B4_qualified',True)):
            with self.assertRaises(ValueError):protocol_guard({**p,key:value})
    def test_optional_deep_source_failure_cannot_erase_completed_primary_prediction(self):
        p={**protocol(),'source_control_hours':[TIME],'primary_first_model_level':130,'deep_diagnostic_first_model_level':109}
        class Reader:
            def read(self,stamp,first):
                if first==109:raise SourceBlocked('DEEP_SOURCE_UNAVAILABLE')
                return {}
            def predict(self,columns,stamp):return {'PRIMARY':'PRESERVED'}
        value,deep,blocks=evaluate_hour(Reader(),TIME,p)
        self.assertEqual(value,{'PRIMARY':'PRESERVED'})
        self.assertEqual(deep['status'],'SOURCE_BLOCKED')
        self.assertEqual(blocks[0]['scope'],'DEEP_DIAGNOSTIC_ONLY')
    def test_same_anchor_p1_isothermal_matches_p2_in_analytic_isotherm(self):
        reader,columns=dummy_columns();r=reader.predict(columns,TIME)
        for c in reader.protocol['countries']:
            methods=r[c]['methods']
            self.assertAlmostEqual(methods[METHODS[0]]['pressure_Pa'],methods[METHODS[2]]['pressure_Pa'],delta=2e-8)
            self.assertEqual(methods[METHODS[2]]['independent_accuracy'],'NOT_QUALIFIED')

    def test_no_air_column_keeps_all_three_countries_and_all_four_methods(self):
        reader,columns=dummy_columns(ground=600);r=reader.predict(columns,TIME)
        self.assertEqual(set(r),{'AT','DE','CH'})
        self.assertEqual(sum(v['status']=='SOURCE_BLOCKED' for c in r.values() for v in c['methods'].values()),12)

    def test_ch_hour_mean_has_explicit_boundary_and_no_silent_fill(self):
        p={TIME:{'CH':{'methods':{'m':{'pressure_Pa':82000}}}}}
        self.assertIsNone(predicted_pressure(p,'CH','m',TIME))
        p['2021-01-31T23:00']={'CH':{'methods':{'m':{'pressure_Pa':81800}}}}
        self.assertEqual(predicted_pressure(p,'CH','m',TIME),81900)
        self.assertIsNone(predicted_pressure(p,'DE','m',TIME))

    def test_country_and_method_denominators_survive_all_missing_predictions(self):
        r=score_pressure({}, {},protocol())
        self.assertEqual(len(r['cells']),24)
        self.assertTrue(all(c['expected_hours']==24 and c['matched_hours']==0 and c['accuracy_gate']=='INCONCLUSIVE_COVERAGE' for c in r['cells']))
        self.assertFalse(r['all_AT_DE_CH_qualified'])

    def test_scalar_bias_mae_and_paired_errors_use_identical_hours(self):
        p=protocol();pred={};truth={'DE':{}}
        for day in p['development_days']:
            for h in range(24):
                stamp=day+'T'+str(h).zfill(2)+':00';truth['DE'][stamp]=100000.
                pred[stamp]={'DE':{'methods':{name:{'pressure_Pa':100000.+(-1 if h%2 else 1)*(100 if name==METHODS[2] else 200)} for name in METHODS}}}
        r=score_pressure(pred,truth,p)
        rows=[x for x in r['cells'] if x['country']=='DE']
        self.assertEqual(len(rows),8)
        for x in rows:
            self.assertEqual(x['matched_hours'],24);self.assertEqual(x['bias_hPa'],0.)
            self.assertEqual(x['MAE_hPa'],1. if x['method']==METHODS[2] else 2.)
            self.assertFalse(x['independently_qualified'])
        paired=[x for x in r['paired_comparisons'] if x['method']==METHODS[0]]
        self.assertTrue(all(x['delta_MAE_hPa']==1 and x['paired_hours']==24 for x in paired))

    def test_changed_seal_rejected_before_any_observation_source_opens(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'predictions.json';path.write_text('{"hourly":{}}');sha=hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_text('{"hourly":{"tampered":true}}')
            with patch('p9_3b3_native_validation.observation_pressure',side_effect=AssertionError('observations opened too early')):
                with self.assertRaisesRegex(ValueError,'SEALED_PREDICTIONS_CHANGED'):score_sealed(path,sha,None,protocol())


if __name__=='__main__':unittest.main()
