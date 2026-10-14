"""P8.3B locked synthetic vector/direction/QC contracts, without network."""
import datetime as dt, math, unittest
from p8_3b_wind_direction_qc import (
    csv_source_qc_profile, circular_unit_prediction, bin_label, RESULTANT_BINS,
    evaluate_target, summarize_angles, UNIT_RESULTANT_THRESHOLD)

class P83BContracts(unittest.TestCase):
    def test_source_with_no_explicit_qc_flag_is_not_qc_verified(self):
        raw=b'station_abbr;reference_timestamp;fkl010h0;dkl010h0\nABO;01.01.2022 01:00;3.0;180\n'
        x=csv_source_qc_profile(raw,'ABO',2022)
        self.assertFalse(x['individual_qc_available']);self.assertFalse(x['individual_qc_codes_verified'])
    def test_source_with_unknown_qc_codes_cannot_be_certified(self):
        raw=b'station_abbr;reference_timestamp;fkl010h0;dkl010h0;dkl010h0_qc\nABO;01.01.2022 01:00;3.0;180;99\n'
        x=csv_source_qc_profile(raw,'ABO',2022)
        self.assertTrue(x['individual_qc_available']);self.assertFalse(x['individual_qc_codes_verified'])
    def test_source_schema_rejects_missing_wind(self):
        with self.assertRaises(ValueError):csv_source_qc_profile(b'station_abbr;reference_timestamp;fkl010h0\n','ABO',2022)
    def test_359_plus_1_is_north(self):
        a=[(10,{'station_id':'A'}),(10,{'station_id':'B'})]
        w={'A':{0:{'speed':4,'direction':359}},'B':{0:{'speed':4,'direction':1}}}
        x=circular_unit_prediction(a,w,0)
        self.assertLess(min(abs(x['unit_direction']),abs(x['unit_direction']-360)),1e-9)
    def test_unit_direction_independent_of_wind_speed(self):
        a=[(1,{'station_id':'A'}),(1,{'station_id':'B'})]
        w={'A':{0:{'speed':1,'direction':0}},'B':{0:{'speed':10,'direction':90}}}
        x=circular_unit_prediction(a,w,0)
        self.assertAlmostEqual(x['unit_direction'],45,places=7)
    def test_unit_opposition_is_missing(self):
        a=[(10,{'station_id':'A'}),(10,{'station_id':'B'})]
        w={'A':{0:{'speed':6,'direction':0}},'B':{0:{'speed':6,'direction':180}}}
        x=circular_unit_prediction(a,w,0)
        self.assertIsNone(x['unit_direction']);self.assertLess(x['unit_resultant'],1e-8)
    def test_calm_donor_does_not_introduce_north(self):
        a=[(1,{'station_id':'A'}),(1,{'station_id':'B'}),(1,{'station_id':'C'})]
        w={'A':{0:{'speed':0.1,'direction':None}},'B':{0:{'speed':2,'direction':90}},'C':{0:{'speed':3,'direction':90}}}
        x=circular_unit_prediction(a,w,0)
        self.assertEqual(x['unit_direction'],90.)
    def test_single_direction_donor_never_becomes_full_ensemble(self):
        a=[(1,{'station_id':'A'}),(1,{'station_id':'B'})]
        w={'A':{0:{'speed':0.1,'direction':None}},'B':{0:{'speed':3,'direction':100}}}
        self.assertIsNone(circular_unit_prediction(a,w,0)['unit_direction'])
    def test_threshold_is_fixed(self):self.assertEqual(UNIT_RESULTANT_THRESHOLD,0.2)
    def test_reliability_bins_boundaries(self):
        self.assertEqual(bin_label(.2999,RESULTANT_BINS),'0-<0.3')
        self.assertEqual(bin_label(.3,RESULTANT_BINS),'0.3-<0.6')
        self.assertEqual(bin_label(1.,RESULTANT_BINS),'0.85-1')
    def test_all_three_paired_excludes_missing(self):
        row={'observed_direction':5,'observed_speed':2,'vector_direction':5,'unit_direction':None,'nearest_direction':5,'scalar_speed':2,'unit_resultant':0.1,'vector_ratio':0.1}
        s=summarize_angles([row],'X',2022,'site','all')
        self.assertEqual(s['matched_all_three_hours'],0);self.assertEqual(s['vector_resolved_hours'],1)
    def test_paired_error_wrap(self):
        r={'observed_direction':1,'observed_speed':3,'vector_direction':359,'unit_direction':359,'nearest_direction':355,'scalar_speed':3,'unit_resultant':1,'vector_ratio':1}
        s=summarize_angles([r],'X',2022,'site','all')
        self.assertEqual(s['matched_all_three_hours'],1);self.assertAlmostEqual(s['unit_strict_matched_MAE_deg'],2)
    def test_target_leak_protected(self):
        a=[(2,{'station_id':'T'})]
        with self.assertRaises(AssertionError):evaluate_target(2022,'T',[],a,{}, {})
    def test_insufficient_hours_is_fatal(self):
        hrs=[dt.datetime(2022,1,1)+dt.timedelta(hours=i) for i in range(24)]
        a=[(1,{'station_id':'A'}),(2,{'station_id':'B'})]
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_TARGET_COVERAGE'):
            evaluate_target(2022,'T',hrs,a,{'A':{},'B':{}},{})
    def test_circular_diff_never_above_180(self):
        from p8_3a_wind_spatial import circular_error_deg
        for a in range(0,360,13):
            for b in range(0,360,17):self.assertLessEqual(circular_error_deg(a,b),180)
    def test_scalar_speed_unchanged_when_new_unit_dir_evaluated(self):
        from p8_3a_wind_spatial import interpolate
        d=[(2,{'station_id':'A'}),(2,{'station_id':'B'})]
        w={'A':{0:{'speed':3.,'direction':0.}},'B':{0:{'speed':5.,'direction':90.}}}
        before=interpolate(d,w,0)['scalar_speed']
        circular_unit_prediction(d,w,0)
        self.assertEqual(before,interpolate(d,w,0)['scalar_speed'])
if __name__=='__main__':unittest.main()