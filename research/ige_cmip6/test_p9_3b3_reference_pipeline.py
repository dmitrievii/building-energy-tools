"""Scientific admission and bounded I/O contracts, without network access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_reference_run import PROTOCOL,protected_controls,reference_alignment,run,site_diagnostic
from p9_3b3_reference_sources import BoundedCache
from test_p9_3b3_reference_column import TIME,column


class AdmissionContracts(unittest.TestCase):
    def test_cross_product_level_below_supplied_surface_fails_without_empirical_repair(self):
        c=column(ground=2000.,gas='ECMWF_PUBLISHED_APPROXIMATION');before=c.fingerprint
        r=reference_alignment(c,c.domain[0]-10.)
        self.assertEqual(r['necessary_bottom_level_above_surface'],'VIOLATED_FOR_THIS_CROSS_PRODUCT_COLUMN')
        self.assertFalse(r['matching_surface_and_lnsp_processing_pipeline_qualified'])
        self.assertFalse(r['empirical_surface_shift_or_pressure_fit_applied'])
        self.assertEqual(c.fingerprint,before)
        r=reference_alignment(c,c.full_geopotential_ECMWF_alpha_m2s2[-1])
        self.assertEqual(r['necessary_bottom_level_above_surface'],'PASS_NECESSARY_ONLY')
        self.assertEqual(r['level_137_ECMWF_reference_residual_m'],0.)
        self.assertFalse(r['matching_surface_and_lnsp_processing_pipeline_qualified'])

    def test_current_barometer_and_ground_never_qualify_2021_station_accuracy(self):
        site={'station_id':'DAV','latitude':47.,'longitude':15.5,'source':'SOURCE',
            'source_sha256':'a'*64,'barometer_height_m':502.,'general_station_height_m':500.}
        r=site_diagnostic(site,[column()],TIME)
        self.assertFalse(r['height_valid_for_2021_sensor_validation'])
        self.assertIn('SOURCE_BLOCKED',r['station_sensor_qualification'])
        self.assertEqual(len(r['cases']),2)
        for case in r['cases'].values():
            self.assertFalse(case['pressure_model_qualified'])
            self.assertFalse(case['sensor_height_history_qualified'])
        self.assertEqual(r['P1_P2_comparison_at_current_snapshot']['comparison_scope'],
            'SOURCE_ONLY_SAME_ANCHOR_SENSITIVITY_NOT_ACCURACY')

    def test_source_geometry_blocker_retained_without_dropping_site(self):
        site={'station_id':'DAV','latitude':47.,'longitude':15.5,'source':'SOURCE',
            'source_sha256':'a'*64,'barometer_height_m':502.,'general_station_height_m':500.}
        r=site_diagnostic(site,[column(ground=600.)],TIME)
        self.assertEqual(r['station_id'],'DAV')
        self.assertTrue(all(case['status']=='SOURCE_BLOCKED' for case in r['cases'].values()))
        self.assertEqual(r['P1_P2_comparison_at_current_snapshot']['status'],'SOURCE_BLOCKED')

    def test_protected_controls_include_c2_and_dwd_and_reject_modified_bytes(self):
        p=json.loads(PROTOCOL.read_text());result=protected_controls(p)
        self.assertGreaterEqual(result['verified_count'],49)
        self.assertIn('research/ige_cmip6/p9_3b3_c2_projection.py',p['protected_control_sha256'])
        self.assertIn('research/ige_cmip6/p9_3b2d_canonical_pressure_fields.py',p['protected_control_sha256'])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'control.py';path.write_bytes(b'new')
            with self.assertRaisesRegex(ValueError,'FROZEN_CONTROLS_CHANGED'):
                protected_controls({'protected_control_sha256':{'control.py':hashlib.sha256(b'old').hexdigest()}},Path(td))

    def test_existing_report_never_overwritten_and_cache_inside_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'existing').mkdir()
            with self.assertRaisesRegex(ValueError,'NO_OVERWRITE'):run(p/'existing',p/'cache')
            with self.assertRaisesRegex(ValueError,'OUTSIDE_PUBLIC_OUTPUT'):run(p/'new',p/'new'/'cache')
            self.assertFalse((p/'new').exists())


class BoundedNetworkContracts(unittest.TestCase):
    def protocol(self):
        return {'max_requests':1,'max_download_bytes':10,'max_object_bytes':8,'source_timeout_seconds':1}

    def test_wrong_host_rejected_before_any_request(self):
        with tempfile.TemporaryDirectory() as td:
            c=BoundedCache(td,self.protocol())
            with self.assertRaisesRegex(ValueError,'HOST_NOT_ALLOWED'):c.fetch('https://unapproved.invalid/x')
            self.assertEqual(c.requests,0)

    def test_content_length_budget_checked_before_body_download_and_no_partial_cache(self):
        class Response:
            headers={'Content-Length':'999999999'}
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):raise AssertionError('oversized body must not be read')
        with tempfile.TemporaryDirectory() as td:
            c=BoundedCache(td,self.protocol())
            with patch('urllib.request.urlopen',return_value=Response()):
                with self.assertRaisesRegex(SourceBlocked,'BUDGET'):c.fetch('https://storage.googleapis.com/test')
            self.assertEqual(list(Path(td).iterdir()),[])
            self.assertEqual(c.downloaded,0)
            path=Path(td)/(hashlib.sha256(b'https://storage.googleapis.com/cached').hexdigest()+'.bin')
            path.write_bytes(b'oversized-cache')
            with patch.object(Path,'read_bytes',side_effect=AssertionError('cache bound checked before allocation')):
                with self.assertRaisesRegex(SourceBlocked,'CACHED_OBJECT_BUDGET'):c.fetch('https://storage.googleapis.com/cached')

    def test_unknown_length_download_bounded_and_counted_and_never_cached_on_overflow(self):
        class Response:
            headers={}
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):
                if n!=8:raise AssertionError('strict bounded object read without sentinel download')
                return b'01234567'
        with tempfile.TemporaryDirectory() as td:
            c=BoundedCache(td,self.protocol())
            with patch('urllib.request.urlopen',return_value=Response()):
                with self.assertRaisesRegex(SourceBlocked,'BUDGET'):c.fetch('https://storage.googleapis.com/test')
            self.assertEqual(c.downloaded,8);self.assertFalse(list(Path(td).iterdir()))
            with self.assertRaisesRegex(SourceBlocked,'REQUEST_BUDGET'):c.fetch('https://storage.googleapis.com/next')


if __name__=='__main__':unittest.main()
