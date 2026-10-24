"""Parser and statistical oracles on invented observations only; no HTTP."""
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import numpy as np

import p9_3b3_iv1_integration_observations as obs
import p9_3b3_iv1_integration_sources as sources
from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_iv1_integration_common import integration_guard
from p9_3b3_iv1_integration_statistics import bootstrap_bounds, metrics, score_arrays
from p9_3b3_iv1_methods import METHODS


def at_payload():
    start = dt.datetime(2022, 2, 15)
    parameters = {}
    for field, unit, value in (('tl', '°C', 10.), ('rf', '%', 60.), ('p', 'hPa', 950.)):
        parameters[field] = {'unit': unit, 'data': [value]*336}
        parameters[field+'_flag'] = {'unit': '', 'data': [10]*336}
    return {'timestamps': [(start+dt.timedelta(hours=h)).isoformat()+'Z' for h in range(336)],
        'features': [{'properties': {'station': '16412', 'parameters': parameters}}]}


def zipped_csv(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('produkt_artificial.txt', text.encode('latin-1'))
    return stream.getvalue()


class StationParserOracles(unittest.TestCase):
    def test_AT_individual_identity_exact_nodes_units_and_variable_flags(self):
        obj = at_payload()
        obj['features'][0]['properties']['parameters']['tl_flag']['data'][:3] = [30, True, '10']
        result = obs.parse_AT(json.dumps(obj).encode(), '2022-02-15', '2022-02-28')
        self.assertEqual(len(result['values']['T_K']), 333)
        self.assertEqual(len(result['values']['RH_pp']), 336)
        self.assertEqual(result['values']['T_K']['2022-02-15T03:00'], 283.15)
        self.assertEqual(result['values']['p_barometer_Pa']['2022-02-15T00:00'], 95000.)
        for mutate, reason in (
            (lambda x: x['features'][0]['properties'].update(station='30'), 'INDIVIDUAL_16412'),
            (lambda x: x['timestamps'].__setitem__(0, '2022-02-15T00:00:00.001Z'), 'EXACT_UTC'),
            (lambda x: x['timestamps'].__setitem__(0, '2022-02-15T00:00:00'), 'EXACT_UTC'),
            (lambda x: x['features'][0]['properties']['parameters']['p'].update(unit='Pa'), 'UNITS_OR_LENGTH')):
            changed = at_payload(); mutate(changed)
            with self.assertRaisesRegex(ValueError, reason):
                obs.parse_AT(json.dumps(changed).encode(), '2022-02-15', '2022-02-28')

    def test_DE_urban_absolute_pressure_never_reduced_QN3_only_HH00(self):
        text = ('STATIONS_ID;MESS_DATUM;QN;P0_ST_10;PP_ST_10\n'
                '399;202202150000;3;950;1020\n399;202202150100;10;951;1021\n'
                '399;202202150200;;952;1022\n399;202202150010;3;999;1099\n')
        wanted = {f'2022-02-15T{h:02d}:00' for h in range(3)}
        result = obs.parse_DE(zipped_csv(text), 'p', wanted)
        self.assertEqual(result['values']['p_barometer_Pa'], {'2022-02-15T00:00': 95000.})
        self.assertEqual(result['QC_counts']['p'], {'3': 1, '10': 1, '': 1})
        reduced_only = 'STATIONS_ID;MESS_DATUM;QN;PP_ST_10\n399;202202150000;3;1020\n'
        with self.assertRaisesRegex(ValueError, 'NO_GENERIC_OR_REDUCED'):
            obs.parse_DE(zipped_csv(reduced_only), 'p', wanted)
        for bad in (text+text.splitlines()[1]+'\n', text.replace('399;', '400;', 1)):
            with self.assertRaisesRegex(ValueError, 'OTHER_STATION_OR_DUPLICATE'):
                obs.parse_DE(zipped_csv(bad), 'p', wanted)

    def test_DE_T_RH_missing_sentinels_not_clipped_or_imputed(self):
        text = ('STATIONS_ID;MESS_DATUM;QN;TT_ST_10;RF_ST_10\n'
                '399;202202150000;3;10;101\n399;202202150100;3;-999;-999\n')
        result = obs.parse_DE(zipped_csv(text), 'T_RH', {'2022-02-15T00:00', '2022-02-15T01:00'})
        self.assertEqual(result['values']['T_K'], {'2022-02-15T00:00': 283.15})
        self.assertEqual(result['values']['RH_pp'], {'2022-02-15T00:00': 101.})

    def test_CH_current_fields_exact_nodes_and_distinct_QC_tier(self):
        header = 'station_abbr;reference_timestamp;tre200s0;ure200s0;prestas0\n'
        raw = (header+'DAV;15.02.2022 00:00;10;60;950\nDAV;15.02.2022 00:10;99;99;999\n').encode()
        wanted = {'2022-02-15T00:00'}
        result = obs.parse_CH(raw, wanted)
        self.assertEqual(result['values']['T_K'], {'2022-02-15T00:00': 283.15})
        self.assertIn('NO_COMPARABLE_PER_SAMPLE_QC', result['quality_tier'])
        means = raw.replace(b'tre200s0', b'tre200h0').replace(b'ure200s0', b'ure200h0').replace(b'prestas0', b'prestah0')
        with self.assertRaisesRegex(ValueError, 'NO_HOURLY_MEAN'):
            obs.parse_CH(means, wanted)
        for stamp in ('2022-02-15T00:00:01Z', '2022-02-15T00:00:00.001Z', '2022-02-15T00:00:00'):
            with self.assertRaises(ValueError):
                obs.parse_CH((header+f'DAV;{stamp};10;60;950\n').encode(), wanted)
        with self.assertRaisesRegex(ValueError, 'OTHER_STATION_OR_DUPLICATE'):
            obs.parse_CH(raw.replace(b'DAV;', b'BER;', 1), wanted)


def response_for(url, raw, etag='"version"', include_length=True):
    response = MagicMock()
    response.__enter__.return_value = response
    response.geturl.return_value = url
    response.headers = {'ETag': etag}
    if include_length:
        response.headers['Content-Length'] = str(len(raw))
    response.read.side_effect = lambda limit: raw[:limit]
    return response


class StationCacheOracles(unittest.TestCase):
    def test_archive_ETag_drift_blocks_before_body(self):
        url = 'https://example.invalid/artificial'
        response = response_for(url, b'not meteorology')
        with tempfile.TemporaryDirectory() as folder, patch.object(obs.era, '_no_redirect_opener') as opener:
            opener.return_value.open.return_value = response
            cache = obs.StationCache(folder, [url])
            with self.assertRaisesRegex(SourceBlocked, 'VERSION_DRIFT_BEFORE_BODY'):
                cache.fetch(url, expected_etag='"other"')
            response.read.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_asset_checksum_cache_replay_and_no_unregistered_URL(self):
        url, raw = 'https://example.invalid/artificial', b'invented fixture'
        with tempfile.TemporaryDirectory() as folder, patch.object(obs.era, '_no_redirect_opener') as opener:
            opener.return_value.open.return_value = response_for(url, raw)
            cache = obs.StationCache(folder, [url])
            with self.assertRaisesRegex(SourceBlocked, 'CHECKSUM_CHANGED'):
                cache.fetch(url, expected_sha='0'*64)
            self.assertEqual(cache.fetch(url, expected_sha=hashlib.sha256(raw).hexdigest()), raw)
            self.assertEqual(cache.downloaded, len(raw))
            self.assertEqual(opener.return_value.open.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'UNREGISTERED'):
                cache.fetch(url+'?unregistered')
            next(Path(folder).glob('*.bin')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'CACHE_VERSION_CHANGED'):
                cache.fetch(url)

    def test_total_budget_and_unknown_length_do_not_read_one_extra_byte(self):
        url = 'https://example.invalid/artificial'
        with tempfile.TemporaryDirectory() as folder, patch.object(obs.era, '_no_redirect_opener') as opener, \
             patch.object(obs, 'OBSERVATION_BUDGET', 5):
            response = response_for(url, b'123456789', include_length=False)
            opener.return_value.open.return_value = response
            cache = obs.StationCache(folder, [url])
            with self.assertRaisesRegex(ValueError, 'SIZE_OR_TRUNCATION'):
                cache.fetch(url)
            response.read.assert_called_once_with(5)
            self.assertEqual(cache.downloaded, 5)
            with self.assertRaisesRegex(ValueError, 'TOTAL_BUDGET'):
                cache.fetch(url)
            self.assertEqual(opener.return_value.open.call_count, 1)


class ModelCacheOracles(unittest.TestCase):
    def cache(self, folder):
        return sources.ModelCache(folder, {'max_object_bytes': 10, 'max_download_bytes': 15,
            'max_requests': 2, 'source_timeout_seconds': 1})

    def test_native_range_requires_206_and_exact_registered_range_before_body(self):
        url = 'https://storage.googleapis.com/gcp-public-data-arco-era5/artificial'
        with tempfile.TemporaryDirectory() as folder, patch.object(sources.era, '_no_redirect_opener') as opener:
            response = response_for(url, b'1234'); response.status = 200
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(SourceBlocked, 'RANGE_IGNORED'):
                self.cache(folder).fetch(url, byte_range=(0, 3))
            response.read.assert_not_called()

    def test_native_cache_replay_requires_digest_and_counts_only_downloads(self):
        url = 'https://storage.googleapis.com/gcp-public-data-arco-era5/artificial'
        with tempfile.TemporaryDirectory() as folder, patch.object(sources.era, '_no_redirect_opener') as opener:
            response = response_for(url, b'1234'); response.status = 206
            response.headers['Content-Range'] = 'bytes 0-3/999999'
            opener.return_value.open.return_value = response
            cache = self.cache(folder)
            self.assertEqual(cache.fetch(url, byte_range=(0, 3)), b'1234')
            self.assertEqual(cache.fetch(url, byte_range=(0, 3)), b'1234')
            self.assertEqual(cache.downloaded, 4)
            self.assertEqual(cache.requests, 1)
            self.assertEqual(cache._reserved, 0)
            next(Path(folder).glob('*.bin')).write_bytes(b'other')
            with self.assertRaisesRegex(SourceBlocked, 'CACHE_DIGEST_OR_BUDGET'):
                cache.fetch(url, byte_range=(0, 3))

    def test_native_redirect_and_unknown_eof_preserve_model_only_boundary(self):
        url = 'https://storage.googleapis.com/gcp-public-data-arco-era5/artificial'
        with tempfile.TemporaryDirectory() as folder, patch.object(sources.era, '_no_redirect_opener') as opener:
            response = response_for('https://opendata.dwd.de/artificial', b'fake')
            opener.return_value.open.return_value = response
            cache = self.cache(folder)
            with self.assertRaisesRegex(SourceBlocked, 'REDIRECT_NOT_REGISTERED'):
                cache.fetch(url)
            response.read.assert_not_called()
            response = response_for(url, b'12345678901', include_length=False)
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(SourceBlocked, 'UNPROVEN_EOF'):
                cache.fetch(url)
            self.assertEqual(cache.downloaded, 10)
            self.assertEqual(cache._reserved, 0)
            with self.assertRaisesRegex(SourceBlocked, 'REQUEST_BUDGET'):
                cache.fetch(url)


class StatisticalOracles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = integration_guard()[0]

    def test_metrics_are_signed_errors_not_mislabeled_bias(self):
        self.assertEqual(metrics([-1., 3.]), {'MAE': 2., 'RMSE': np.sqrt(5), 'bias': 1.})
        self.assertEqual(metrics([]), {'MAE': None, 'RMSE': None, 'bias': None})
        with self.assertRaises(ValueError): metrics([float('nan')])

    def test_bootstrap_pools_hours_and_uses_registered_circular_blocks(self):
        settings = self.protocol['statistics']
        sums = np.arange(14.)*2
        counts = np.arange(14)+1
        result = bootstrap_bounds(sums, counts, settings)
        # Independent scalar oracle for the primary bound, same PCG64 stream.
        rng = np.random.Generator(np.random.PCG64(settings['seed']))
        draws = []
        for _ in range(settings['repetitions']):
            indices = []
            for start in rng.integers(0, 14, size=5):
                indices.extend([(int(start)+i) % 14 for i in range(3)])
            indices = indices[:14]
            draws.append(sum(sums[i] for i in indices)/sum(counts[i] for i in indices))
        expected = np.quantile(draws, settings['one_sided_upper_quantile'])
        self.assertEqual(result[0]['upper_delta_MAE'], expected)
        self.assertEqual([r['block_days'] for r in result], [3, 2, 7])
        constant = bootstrap_bounds(.25*counts, counts, settings)
        self.assertTrue(all(r['upper_delta_MAE'] == .25 for r in constant))

    def test_bootstrap_zero_support_is_inconclusive_without_redraw(self):
        counts = [1]+[0]*13
        result = bootstrap_bounds([0.]*14, counts, self.protocol['statistics'])
        self.assertTrue(all(r['status'] == 'INCONCLUSIVE_ZERO_SUPPORT_REPLICATE' for r in result))
        self.assertTrue(all(r['upper_delta_MAE'] is None and r['zero_support_replicates'] > 0 for r in result))

    def fixture(self):
        cases, barometer = [], {co: {} for co in ('AT', 'DE', 'CH')}
        observed = {co: {'values': {'T_K': {}, 'RH_pp': {}, 'p_barometer_Pa': {}}} for co in barometer}
        for country in barometer:
            for start, _ in self.protocol['windows_UTC']:
                for d in range(14):
                    date = (dt.date.fromisoformat(start)+dt.timedelta(days=d)).isoformat()
                    rows = []
                    for method in METHODS:
                        candidate = method == self.protocol['primary_comparison'][0]
                        rows.append({'IV1_method': method, 'status': 'ARTIFICIAL_STATISTICAL_FIXTURE',
                            'T_K': [285.+.05*candidate]*24, 'q_kgkg': [.004]*24, 'p_Pa': [95000.]*24,
                            'validation': {'diagnostics': {'RH_water_pct': [60.+.2*candidate]*24,
                                                           'RH_source_pct': [1.]*24}}})
                    cases.append({'country': country, 'date': date, 'results': rows})
                    for h in range(24):
                        stamp = date+f'T{h:02d}:00'
                        barometer[country][stamp] = 95000.
                        for key, value in (('T_K', 284.), ('RH_pp', 60.), ('p_barometer_Pa', 95000.)):
                            observed[country]['values'][key][stamp] = value
        return cases, barometer, observed

    def test_primary_masks_remain_paired_and_all_five_mask_is_reported(self):
        cases, barometer, observed = self.fixture()
        cases[0]['results'][0] = {'IV1_method': METHODS[0], 'status': 'CERTIFIED_INFEASIBLE'}
        result = score_arrays(cases, barometer, observed, self.protocol)
        primary = result['primary_comparisons'][0]
        common = result['all_five_common_cells'][0]
        self.assertEqual(primary['matched_hours'], 336)
        self.assertEqual(common['matched_hours'], 312)
        self.assertEqual(result['method_dispositions'][0]['physical_state_hours'], 312)
        self.assertEqual(result['method_dispositions'][0]['status_counts']['CERTIFIED_INFEASIBLE'], 1)
        self.assertEqual(len(primary['paired_days']), 14)
        self.assertTrue(result['IV1_research_criteria_pass'])
        RH = [r for r in result['primary_comparisons'] if r['variable'] == 'RH_pp'][0]
        self.assertAlmostEqual(RH['delta_MAE'], .2)  # water RH, never ice/source RH
        self.assertFalse(result['derived_humidity_proxy_cells'][0]['independent_specific_humidity_measurement'])

    def test_missing_primary_hours_stay_in_denominator_and_prevent_pass(self):
        cases, barometer, observed = self.fixture()
        for case in cases[:2]:
            case['results'][-1] = {'IV1_method': METHODS[-1], 'status': 'UNRESOLVED'}
        result = score_arrays(cases, barometer, observed, self.protocol)
        first = result['primary_comparisons'][0]
        self.assertEqual(first['matched_hours'], 288)
        self.assertEqual(first['expected_hours'], 336)
        self.assertEqual(first['status'], 'INCONCLUSIVE_COVERAGE')
        self.assertFalse(result['IV1_research_criteria_pass'])


if __name__ == '__main__':
    unittest.main()
