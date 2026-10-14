"""P8.3C frozen hybrid: synthetic tests only, no provider source data used."""
import unittest, datetime as dt, math
from p8_3c_wind_hybrid_holdout import (
    YEAR, TARGETS, hybrid_direction, bin_speed, sector16, build_scored_hours,
    summarize, interval_failure_spells, METHODS,
)
from p8_3a_wind_spatial import circular_error_deg, interpolate
from p8_3b_wind_direction_qc import circular_unit_prediction, UNIT_RESULTANT_THRESHOLD


def dummy(t,hour,direction, speed=3., scalar=3., vec=.9, unit=.9, nearest=None, fallback=None):
    return {'time':t+dt.timedelta(hours=hour),'site':'GVE','year':2023,
        'obs_direction':direction, 'obs_speed':speed,'scalar_speed':scalar,
        'nearest_direction':nearest,'vector_direction':vec,'unit_direction':unit,
        'hybrid_direction':(fallback if fallback is not None else (vec if vec is not None else unit)),
        'fallback_reason':('vector' if vec is not None else ('unit_fallback' if unit is not None else 'unresolved')),
        'vector_ratio':.5, 'unit_resultant':.8,
        'speed_bin':bin_speed(speed),'season':'DJF'}


class TestHybrid(unittest.TestCase):
    def test_2023_is_frozen(self):self.assertEqual(YEAR,2023)
    def test_independent_targets(self):
        self.assertEqual(len(TARGETS),6)
        self.assertTrue(set(TARGETS).isdisjoint(('ABO','BER','PAY')))
    def test_original_threshold_not_changed(self):self.assertEqual(UNIT_RESULTANT_THRESHOLD,.20)
    def test_legacy_vector_wins_even_if_unit_disagrees(self):
        self.assertEqual(hybrid_direction(90.,270.),(90.,'vector'))
    def test_unit_recovers_only_if_vector_absent(self):
        self.assertEqual(hybrid_direction(None,180.),(180.,'unit_fallback'))
    def test_no_invalid_azimuth_invented(self):
        self.assertEqual(hybrid_direction(None,None),(None,'unresolved'))
    def test_zero_is_valid_north(self):
        self.assertEqual(hybrid_direction(0.,300.),(0.,'vector'))
        self.assertEqual(hybrid_direction(None,0.),(0.,'unit_fallback'))
    def test_circular_wrapping(self):self.assertAlmostEqual(circular_error_deg(359.,1.),2.)
    def test_sector_wrap(self):
        self.assertEqual(sector16(359),0);self.assertEqual(sector16(1),0)
        self.assertEqual(sector16(23),1)
        self.assertEqual(sector16(None),None)
    def test_speed_bins(self):
        self.assertEqual(bin_speed(.49),'calm')
        self.assertEqual(bin_speed(.5),'0.5-<2')
        self.assertEqual(bin_speed(2),'2-<5')
        self.assertEqual(bin_speed(5),'>=5')
    def test_no_target_in_prediction(self):
        h=dt.datetime(2023,1,1)
        d=[(10.,{'station_id':'A'}),(15.,{'station_id':'B'})]
        w={'A':{h:{'speed':4.,'direction':0.}},'B':{h:{'speed':4.,'direction':0.}}}
        t={h:{'speed':4.,'direction':270.}}
        with self.assertRaisesRegex(AssertionError,'TARGET_WIND_LEAKAGE'):
            build_scored_hours('GVE',2023,[h],d,{**w,'GVE':t},t)
    def test_prediction_uses_donors_and_source_only_as_score(self):
        h=dt.datetime(2023,1,1)
        d=[(10.,{'station_id':'A'}),(15.,{'station_id':'B'})]
        w={'A':{h:{'speed':4.,'direction':0.}},'B':{h:{'speed':4.,'direction':0.}}}
        t={h:{'speed':4.,'direction':270.}}
        rows,diag=build_scored_hours('GVE',2023,[h],d,w,t)
        self.assertEqual(len(rows),1)
        self.assertLess(circular_error_deg(rows[0]['hybrid_direction'],0.),1e-10)
        self.assertEqual(diag['n_target_hours'],1)
    def test_frozen_scalar_speed_unchanged(self):
        h=dt.datetime(2023,1,1)
        d=[(10.,{'station_id':'A'}),(15.,{'station_id':'B'})]
        w={'A':{h:{'speed':4.,'direction':30.}},'B':{h:{'speed':6.,'direction':60.}}}
        t={h:{'speed':3.,'direction':20.}}
        scored,_=build_scored_hours('GVE',2023,[h],d,w,t)
        original=interpolate(d,w,h)
        self.assertAlmostEqual(scored[0]['scalar_speed'],original['scalar_speed'])
        self.assertEqual(scored[0]['vector_direction'],original['vector_direction'])
    def test_unit_circle_does_not_reinterpret_calm(self):
        h=dt.datetime(2023,1,1)
        d=[(10.,{'station_id':'A'}),(15.,{'station_id':'B'})]
        w={'A':{h:{'speed':.2,'direction':200.}},'B':{h:{'speed':3.,'direction':10.}}}
        self.assertIsNone(circular_unit_prediction(d,w,h)['unit_direction'])
    def test_both_methods_undefined(self):
        h=dt.datetime(2023,1,1)
        d=[(10.,{'station_id':'A'}),(10.,{'station_id':'B'})]
        w={'A':{h:{'speed':3.,'direction':0.}},'B':{h:{'speed':3.,'direction':180.}}}
        x=circular_unit_prediction(d,w,h)
        self.assertIsNone(x['unit_direction'])
        self.assertIsNone(interpolate(d,w,h)['vector_direction'])
    def test_recovered_hours_reported_separately(self):
        t=dt.datetime(2023,1,1)
        rows=[dummy(t,0,10.,vec=0.,unit=15.,nearest=30.),
              dummy(t,1,30.,vec=None,unit=20.,nearest=70.),
              dummy(t,2,60.,vec=None,unit=None,nearest=90.)]
        x=summarize(rows,'site','GVE')
        self.assertEqual(x['n_observed_noncalm'],3)
        self.assertEqual(x['vector_resolved'],1)
        self.assertEqual(x['hybrid_resolved'],2)
        self.assertEqual(x['n_hybrid_newly_recovered'],1)
        self.assertEqual(x['n_hybrid_unresolved'],1)
        self.assertAlmostEqual(x['recovered_MAE_deg'],10)
        self.assertAlmostEqual(x['recovered_vs_nearest_nearest_MAE_deg'],40)
        self.assertEqual(x['n_matched_all_four'],1)
        self.assertAlmostEqual(x['hybrid_fixeddenom_abs90_mean_deg'],(10+10+90)/3)
    def test_fixed_denominator_180_penalty_is_explicit(self):
        t=dt.datetime(2023,1,1)
        rows=[dummy(t,0,0,vec=None,unit=None,nearest=None),dummy(t,1,0,vec=0,unit=0,nearest=0)]
        x=summarize(rows,'site','GVE')
        self.assertEqual(x['vector_fixeddenom_abs180_mean_deg'],90)
    def test_common_hour_paired_metrics_cannot_inflate_skill(self):
        t=dt.datetime(2023,1,1)
        rows=[dummy(t,0,0,vec=0,unit=80,nearest=20),dummy(t,1,0,vec=None,unit=80,nearest=None)]
        x=summarize(rows,'site','GVE')
        self.assertEqual(x['n_matched_all_four'],1)
        self.assertEqual(x['vector_matched4_MAE_deg'],0)
        self.assertEqual(x['unit_matched4_MAE_deg'],80)
        self.assertEqual(x['hybrid_matched4_MAE_deg'],0)
        self.assertEqual(x['hybrid_emitted_MAE_deg'],40)
    def test_calm_has_no_measured_direction(self):
        t=dt.datetime(2023,1,1)
        x=summarize([dummy(t,0,None,speed=.1,vec=None,unit=None,nearest=None)],'site','GVE')
        self.assertEqual(x['n_observed_noncalm'],0)
        self.assertIsNone(x['hybrid_coverage_pct'])
    def test_unresolved_duration_across_gaps(self):
        t=dt.datetime(2023,1,1)
        rows=[dummy(t,0,0,vec=None,unit=None),dummy(t,1,0,vec=None,unit=None),
              dummy(t,4,0,vec=None,unit=None),dummy(t,5,0,vec=None,unit=None),
              dummy(t,6,0,vec=0,unit=0)]
        x=interval_failure_spells(rows)
        self.assertEqual(x['hybrid_unresolved_spells'],2)
        self.assertEqual(x['unresolved_max_consecutive_hours'],2)
    def test_unresolved_duration_break_on_calm(self):
        t=dt.datetime(2023,1,1)
        rows=[dummy(t,0,0,vec=None,unit=None),dummy(t,1,None,vec=None,unit=None,speed=0.1),dummy(t,2,0,vec=None,unit=None)]
        self.assertEqual(interval_failure_spells(rows)['hybrid_unresolved_spells'],2)
    def test_small_target_coverage_fails(self):
        t=dt.datetime(2023,1,1)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_TARGET_REFERENCE_COVERAGE'):
            build_scored_hours('GVE',2023,[t+dt.timedelta(hours=i) for i in range(10)],[],{}, {t:{'speed':5.,'direction':0.}})

if __name__=='__main__':unittest.main()