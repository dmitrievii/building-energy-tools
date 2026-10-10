"""P6.2A expanded research contracts; no live NASA/GeoSphere calls in tests."""
from __future__ import annotations
import datetime as dt
import unittest

from p6_2a_eight_model_ensemble import MODELS, EXPECTED_WINDOWS, summary_from_audits
from p6_2a_hourly_station_probe import CORE, parse_provider

def make_period(model,window,index):
    historic=window=='historical-1995-2014'
    return {
        'model':model,'member':'r1i1p1f1',
        'scenario':'historical' if historic else 'ssp585',
        'annual_mean_tas_c':10+index,
        'annual_mean_pr_mm':800+20*index,
        'annual_mean_ghi_kwh_m2':1500+10*index,
        'seasons':{season:{
            'tas_mean_c':20+index,
            'tasmax_p95_c':32+index,
            'wet_day_fraction_ge1mm':.4+.001*index,
            'pearson_daily_within_season':{
                'tas_c__rsds_kwh_m2_day':.2+.01*index,
                'pr_mm_day__rsds_kwh_m2_day':-.4+.01*index,
            }} for season in ('DJF','MAM','JJA','SON')}
    }

def make_hourly():
    days=[(dt.datetime(2020,7,1,tzinfo=dt.timezone.utc)+dt.timedelta(hours=i)).isoformat() for i in range(168)]
    units={'tl':'°C','rf':'%','rr':'mm','cglo':'W/m²','ff':'m/s','p':'hPa'}
    para=[{'name':k,'unit':unit} for k,unit in units.items()]
    para.extend({'name':k+'_flag','unit':'code'} for k in units)
    columns={k:{'unit':unit,'data':[12.]*168} for k,unit in units.items()}
    columns.update({k+'_flag':{'unit':'code','data':[0]*168} for k in units})
    return ({'stations':[{'id':30,'name':'Graz'}],'parameters':para},
            {'timestamps':days,'features':[{'properties':{'station':30,'parameters':columns}}]})

class EnsembleScienceContract(unittest.TestCase):
    def test_all_eight_models_from_closed_p5(self):
        self.assertEqual(len(MODELS),8)
        self.assertEqual(len(set(MODELS)),8)
        self.assertEqual(len(EXPECTED_WINDOWS),5)

    def test_32_paired_changes_and_descriptive_model_spread(self):
        audits={model:{w:make_period(model,w,j) for j,w in enumerate(EXPECTED_WINDOWS)}
                for model in MODELS}
        comparisons,spread=summary_from_audits(audits)
        self.assertEqual(len(comparisons),32)
        self.assertEqual(len(spread),4*8)
        self.assertTrue(all(r['models_with_metric']==8 for r in spread))
        self.assertTrue(all(r['interpretation']=='descriptive_8_GCM_spread_not_probability' for r in spread))
        self.assertAlmostEqual(comparisons[0]['tas_annual_mean_change_c'],1.)

    def test_model_missing_is_rejected(self):
        audits={model:{w:make_period(model,w,j) for j,w in enumerate(EXPECTED_WINDOWS)}
                for model in MODELS[:-1]}
        with self.assertRaisesRegex(ValueError,'Exactly eight'):
            summary_from_audits(audits)

    def test_window_missing_is_rejected(self):
        audits={model:{w:make_period(model,w,j) for j,w in enumerate(EXPECTED_WINDOWS)}
                for model in MODELS}
        del audits[MODELS[3]]['ssp585-2080-2099']
        with self.assertRaisesRegex(ValueError,'Incomplete five-window'):
            summary_from_audits(audits)

    def test_hourly_one_week_raw_units_and_flags(self):
        metadata,raw=make_hourly()
        qa=parse_provider(metadata,raw)
        self.assertEqual(qa['timestamps_count'],168)
        self.assertEqual(set(qa['fields']),set(CORE))
        self.assertEqual(len(qa['quality_flags']),6)
        self.assertEqual(qa['provider_timestamp_timezone'],'UTC')

    def test_hourly_missingness_is_reported(self):
        metadata,raw=make_hourly()
        field=raw['features'][0]['properties']['parameters']['cglo']['data']
        field[:40]=[None]*40
        qa=parse_provider(metadata,raw)
        self.assertEqual(qa['fields']['cglo']['missing'],40)
        self.assertEqual(qa['fields']['cglo']['available'],128)

    def test_wrong_station_or_units_blocks(self):
        metadata,raw=make_hourly()
        raw['features'][0]['properties']['station']=42
        with self.assertRaisesRegex(ValueError,'Wrong GeoSphere station'):
            parse_provider(metadata,raw)
        metadata,raw=make_hourly()
        metadata['parameters'][0]['unit']='K'
        with self.assertRaisesRegex(ValueError,'Unrecognized GeoSphere parameter unit'):
            parse_provider(metadata,raw)

    def test_without_explicit_utc_hourly_rejected(self):
        metadata,raw=make_hourly()
        raw['timestamps'][0]='2020-07-01T00:00:00'
        with self.assertRaisesRegex(ValueError,'not explicitly UTC'):
            parse_provider(metadata,raw)

if __name__=='__main__':
    unittest.main()
