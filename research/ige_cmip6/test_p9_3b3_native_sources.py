"""Independent harmonic oracles and exact source-support contracts."""
import math
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.special import sph_harm_y

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_native_sources import GaussianGrid,NativeCache,NativeSource,cf_seconds,real_coefficients,synthesize,verify_grib_copy
from test_p9_3b3_reference_sources import source_fixture,TIME


def packed(n,entries):
    result=[]
    for m in range(n+1):
        for ell in range(m,n+1):
            x=entries.get((ell,m),0j);result.extend([complex(x).real,complex(x).imag])
    return np.array(result)


def independent_harmonic(entries,latitude,longitude):
    value=0.
    for (ell,m),x in entries.items():
        y=math.sqrt(4*math.pi)*(-1)**m*sph_harm_y(ell,m,math.radians(90-latitude),math.radians(longitude))
        value+=(1 if m==0 else 2)*(complex(x)*y).real
    return value


class HarmonicOracles(unittest.TestCase):
    def test_constant_and_cartesian_dipole_with_imaginary_sign(self):
        entries={(0,0):11.,(1,0):2.,(1,1):3+4j}
        for lat,lon in ((0,0),(0,90),(47,15),(90,0),(-90,270)):
            expected=11+2*math.sqrt(3)*math.sin(math.radians(lat))
            expected+=2*math.sqrt(1.5)*math.cos(math.radians(lat))*(3*math.cos(math.radians(lon))-4*math.sin(math.radians(lon)))
            self.assertAlmostEqual(synthesize(packed(1,entries),[(lat,lon)],1)[0],expected,places=12)

    def test_random_complex_waves_against_independent_scipy_complex_basis(self):
        rng=np.random.default_rng(20261022)
        entries={(ell,m):complex(rng.normal(),0 if m==0 else rng.normal())
                 for m in range(13) for ell in range(m,13)}
        points=[(float(a),float(b)) for a,b in zip(rng.uniform(-80,80,17),rng.uniform(0,360,17))]
        got=synthesize(packed(12,entries),points,12)
        np.testing.assert_allclose(got,[independent_harmonic(entries,*p) for p in points],atol=2e-12,rtol=2e-13)

    def test_sparse_high_degree_639_and_polar_stability(self):
        entries={(0,0):270.,(639,0):.2,(639,37):.1-.3j,(638,638):.01+.03j}
        points=[(47.072580762649004,15.6),(0,90),(89,0),(-89,270)]
        np.testing.assert_allclose(synthesize(packed(639,entries),points),
            [independent_harmonic(entries,*p) for p in points],atol=2e-10,rtol=1e-12)

    def test_wrong_coefficient_count_nonreal_zonal_or_untyped_truncation_rejected(self):
        for values,n in (([1,0,2],1),([1,1],0),([1,0],639.0),([math.nan,0],0)):
            with self.assertRaises(ValueError):real_coefficients(values,n)

    def test_original_grib_copy_requires_float32_identity_not_loose_tolerance(self):
        original=np.array([11.495611045,.000123456789,0.]);copy=original.astype('<f4')
        self.assertEqual(verify_grib_copy(original,copy)['status'],'ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT')
        changed=copy.copy();changed[1]=np.nextafter(changed[1],np.float32(math.inf))
        with self.assertRaises(SourceBlocked):verify_grib_copy(original,changed)


class NativeSupportContracts(unittest.TestCase):
    def test_cf_origin_without_midnight_and_exact_requested_hour(self):
        cache,old,meta=source_fixture();source=NativeSource('https://fixture',cache)
        source.m['time/.zattrs']['units']='hours since 1900-01-01'
        import datetime as dt
        from numcodecs import Blosc
        hour=int((dt.datetime(2021,2,1)-dt.datetime(1900,1,1)).total_seconds()/3600)
        cache.data['https://fixture/time/0']=Blosc(cname='lz4',clevel=5,shuffle=1).encode(np.array([hour],dtype='<i8'))
        self.assertEqual(source.time_index(TIME),0)
        with self.assertRaisesRegex(SourceBlocked,'ABSENT'):source.time_index('2021-02-01T01:00')
        with self.assertRaisesRegex(ValueError,'UTC_HOUR'):source.time_index(TIME+'+01:00')

    def test_gaussian_bracketing_uses_two_sides_of_each_ring_not_two_nearest(self):
        lat=np.array([-1,-1,-1,-1,1,1,1]);lon=np.array([0,90,180,270,0,120,240])
        g=GaussianGrid(lat,lon)
        self.assertEqual(g.neighbors(0,100),[1,2,4,5])
        self.assertEqual(g.neighbors(0,359),[3,0,6,4])
        with self.assertRaises(SourceBlocked):g.neighbors(2,15)

    def test_original_month_range_ignored_is_blocked_before_body_read(self):
        class Response:
            status=200;headers={'Content-Length':'10000000000'}
            def geturl(self):return 'https://storage.googleapis.com/month.grb2'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):raise AssertionError('entire month must not be downloaded')
        p={'max_requests':2,'max_download_bytes':200,'max_object_bytes':100,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p)
            with patch('urllib.request.urlopen',return_value=Response()):
                with self.assertRaisesRegex(SourceBlocked,'RANGE_IGNORED'):
                    c.fetch('https://storage.googleapis.com/month.grb2',byte_range=(0,15))
            self.assertEqual(c.downloaded,0)
            self.assertEqual(c._reserved,0)

    def test_offline_and_invalid_range_fail_before_http_or_budget_reservation(self):
        p={'max_requests':4,'max_download_bytes':100,'max_object_bytes':100,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p,cache_only=True)
            with patch('urllib.request.urlopen',side_effect=AssertionError('offline or invalid range cannot open HTTP')):
                with self.assertRaisesRegex(SourceBlocked,'CACHE_ONLY'):c.fetch('https://storage.googleapis.com/missing')
                with self.assertRaisesRegex(SourceBlocked,'RANGE_BUDGET'):c.fetch('https://storage.googleapis.com/invalid',byte_range=(0,1000))
            self.assertEqual((c.requests,c.downloaded,c._reserved),(0,0,0))

    def test_concurrent_downloads_share_one_strict_byte_budget_and_release_reservations(self):
        from concurrent.futures import ThreadPoolExecutor
        import io
        class Response:
            status=200;headers={'Content-Length':'16'}
            def __init__(self):self.body=io.BytesIO(b'x'*16)
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return self.body.read(n)
        p={'max_requests':20,'max_download_bytes':64,'max_object_bytes':32,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p)
            def fetch(i):
                try:return len(c.fetch('https://storage.googleapis.com/test'+str(i)))
                except SourceBlocked:return 0
            with patch('urllib.request.urlopen',side_effect=lambda *a,**k:Response()):
                with ThreadPoolExecutor(max_workers=6) as pool:sizes=list(pool.map(fetch,range(12)))
            self.assertEqual(c.downloaded,sum(sizes));self.assertLessEqual(c.downloaded,64)
            self.assertEqual(c._reserved,0);self.assertLessEqual(c.requests,20)

    def test_all_declared_bodies_fit_even_when_simultaneous_object_ceilings_do_not(self):
        from concurrent.futures import ThreadPoolExecutor
        import io
        import threading
        ready=threading.Barrier(6,timeout=5)
        class Response:
            status=200;headers={'Content-Length':'4'}
            def __init__(self):self.body=io.BytesIO(b'abcd')
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return self.body.read(n)
        def opened(*a,**k):ready.wait();return Response()
        p={'max_requests':6,'max_download_bytes':24,'max_object_bytes':80,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p)
            with patch('urllib.request.urlopen',side_effect=opened):
                with ThreadPoolExecutor(max_workers=6) as pool:
                    bodies=list(pool.map(lambda i:c.fetch('https://storage.googleapis.com/test'+str(i)),range(6)))
            self.assertEqual(bodies,[b'abcd']*6)
            self.assertEqual((c.downloaded,c.requests,c._reserved),(24,6,0))

    def test_declared_body_over_remaining_budget_is_rejected_before_read(self):
        class Response:
            status=200;headers={'Content-Length':'4'}
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):raise AssertionError('body must not exceed remaining byte budget')
        p={'max_requests':6,'max_download_bytes':3,'max_object_bytes':80,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p)
            with patch('urllib.request.urlopen',return_value=Response()):
                with self.assertRaisesRegex(SourceBlocked,'DOWNLOAD_BUDGET'):c.fetch('https://storage.googleapis.com/test')
            self.assertEqual((c.downloaded,c.requests,c._reserved),(0,1,0))

    def test_truncated_body_counts_received_bytes_and_releases_unused_reservation(self):
        import io
        class Response:
            status=200;headers={'Content-Length':'5'}
            def __init__(self):self.body=io.BytesIO(b'abc')
            def geturl(self):return 'https://storage.googleapis.com/test'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return self.body.read(n)
        p={'max_requests':6,'max_download_bytes':10,'max_object_bytes':80,'source_timeout_seconds':1}
        with tempfile.TemporaryDirectory() as td:
            c=NativeCache(td,p)
            with patch('urllib.request.urlopen',return_value=Response()):
                with self.assertRaisesRegex(SourceBlocked,'TRUNCATED_BODY'):c.fetch('https://storage.googleapis.com/test')
            self.assertEqual((c.downloaded,c.requests,c._reserved),(3,1,0))
            self.assertEqual(c.records,[])


if __name__=='__main__':unittest.main()
