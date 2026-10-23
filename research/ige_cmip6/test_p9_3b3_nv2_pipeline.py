"""Sealed I/O, exact cell accounting, metadata-only access and CLI failures."""
import contextlib
import copy
import dataclasses
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from p9_3b3_native_run import write_json
from p9_3b3_native_validation import predicted_pressure
from p9_3b3_nv2_run import (ROOT, execution_summary, main, protocol_guard,
                            refresh_sensor_references, run, source_hours)
from p9_3b3_nv2_columns import NV2Columns
from p9_3b3_nv2_validation import score_after_seal, score_nv2
from p9_3b3_reference_run import protected_controls
from test_p9_3b3_nv2_geometry import protocol
from test_p9_3b3_nv2_columns import graz_columns
from test_p9_3b3_reference_column import column


def full_predictions(p):
    return {t: {co: {'methods': {m: {'pressure_Pa': 100000.} for m in p['methods_by_country'][co]},
                     'G0': {'methods': {m: {'pressure_Pa': 100000.} for m in p['G0_regression_methods']}}}
                for co in p['countries']} for t in source_hours(p)}


def sealed_fixture(out):
    p = protocol()
    data = {'sealed_pressure_predictions.json': {'hourly': full_predictions(p)},
            'source_geometry_and_fixed_donors.json': {'D1': 1},
            'native_primary_profiles.json': {'profiles': 'SEALED_SOURCE_ONLY'}}
    seals = {}
    for name, value in data.items():
        write_json(out/name, value)
        seals[name] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    return seals


class FrozenContracts(unittest.TestCase):
    def test_all_eighty_earlier_files_match_frozen_hashes(self):
        p = protocol_guard(protocol())
        self.assertEqual(protected_controls(p)['verified_count'], 80)

    def test_protocol_rejects_geometry_method_resource_and_qualification_drift(self):
        p = protocol()
        for key, value in (('radius_km', 75), ('P1_lapse_K_per_m', .007), ('max_download_bytes', 4*1024**3),
                           ('expected_pressure_score_cells', 24), ('B4_qualified', True)):
            with self.assertRaisesRegex(ValueError, 'DESIGN_DRIFT'):
                protocol_guard({**p, key: value})
        changed = copy.deepcopy(p)
        changed['methods_by_country']['AT'].pop()
        with self.assertRaises(ValueError):
            protocol_guard(changed)

    def test_all_fifty_source_hours_include_two_real_CH_boundaries(self):
        p = protocol()
        hours = source_hours(p)
        self.assertEqual(len(hours), 50)
        self.assertIn('2021-01-31T23:00', hours)
        self.assertIn('2021-07-31T23:00', hours)

    def test_reference_refresh_fetches_WMDR_only_and_keeps_metadata_identity(self):
        p = protocol()
        base = json.loads((ROOT/p['source_protocol_file']).read_text())
        fixed = json.loads((ROOT/p['dated_sensor_reference_file']).read_text())['countries']
        code_to_key = {216: 'pressure', 224: 'temperature', 12249: 'RH_water'}
        wsi_to_country = {v: k for k, v in base['station_WSI'].items()}
        class Cache:
            def fetch(self, url, limit):
                assert url.startswith('https://oscar.wmo.int/surface/rest/api/wmd/download/')
                return url.rsplit('/', 1)[-1].encode()
        def parser(raw, wsi, code, stamps, role):
            self.assertEqual(raw.decode(), wsi)
            self.assertEqual(len(stamps), 50)
            result = copy.deepcopy(fixed[wsi_to_country[wsi]]['sensors'][code_to_key[code]])
            result['source_sha256'] = 'b'*64
            return result
        with patch('p9_3b3_nv2_run.sensor_records', side_effect=parser):
            actual = refresh_sensor_references(Cache(), p, base)
        self.assertTrue(all(v['reference_refresh'] == 'WMDR_SEMANTIC_IDENTITY_CONFIRMED' for v in actual.values()))
        self.assertEqual(actual['DE']['sensors']['pressure']['height_MSL_m'], 82.5)
        def changed(*args):
            r = parser(*args)
            r['height_MSL_m'] += 1
            return r
        with patch('p9_3b3_nv2_run.sensor_records', side_effect=changed):
            actual = refresh_sensor_references(Cache(), p, base)
        self.assertTrue(all(v['status'] == 'SOURCE_BLOCKED' for v in actual.values()))


class ScoreAccounting(unittest.TestCase):
    def test_blocked_cells_and_all_pairwise_comparisons_stay_in_denominator(self):
        r = score_nv2({}, {}, protocol())
        self.assertEqual(len(r['cells']), 26)
        self.assertEqual(len(r['paired_comparisons']), 54)
        self.assertTrue(all(c['expected_hours'] == 24 and c['matched_hours'] == 0 for c in r['cells']))
        self.assertTrue(all(p['paired_hours'] == 0 for p in r['paired_comparisons']))

    def test_pairwise_metrics_recomputed_on_intersection_not_full_cell_MAE(self):
        p = protocol()
        pred = full_predictions(p)
        truth = {co: {t: 100000. for t in source_hours(p)} for co in p['countries']}
        # Method A has 24 hours but only 12 overlap B. Excluded A errors=100 hPa.
        for h in range(24):
            t = '2021-02-01T'+str(h).zfill(2)+':00'
            pred[t]['DE']['methods']['P1_ISOTHERMAL_D1']['pressure_Pa'] += 100 if h < 12 else 10000
            pred[t]['DE']['methods']['P2_NATIVE_D1'] = ({'pressure_Pa': 100200} if h < 12 else {'status': 'SOURCE_BLOCKED'})
        r = score_nv2(pred, truth, p)
        pair = next(r for r in r['paired_comparisons'] if r['country'] == 'DE' and r['day'] == '2021-02-01'
                    and r['method'] == 'P1_ISOTHERMAL_D1' and r['baseline'] == 'P2_NATIVE_D1')
        self.assertEqual(pair['paired_hours'], 12)
        self.assertEqual(pair['delta_MAE_hPa'], -1.)
        self.assertEqual(pair['comparison_scope'], 'SAME_DONOR_SAME_SURFACE_ANCHOR')

    def test_CH_boundary_missing_is_not_filled(self):
        p = protocol()
        pred = full_predictions(p)
        pred.pop('2021-01-31T23:00')
        self.assertIsNone(predicted_pressure(pred, 'CH', 'P2_NATIVE_D1', '2021-02-01T00:00'))
        truth = {co: {t: 100000. for t in source_hours(p)} for co in p['countries']}
        r = score_nv2(pred, truth, p)
        rows = [c for c in r['cells'] if c['country'] == 'CH' and c['day'] == '2021-02-01']
        self.assertTrue(all(c['matched_hours'] == 23 for c in rows))

    def test_technical_success_does_not_assert_all_targets_physically_admissible_or_skill(self):
        p = protocol()
        heights = {co: {'reference_refresh': 'WMDR_SEMANTIC_IDENTITY_CONFIRMED'} for co in p['countries']}
        source = {'paired_surface_lineage_status': 'ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'}
        score = {**score_nv2({}, {}, p), 'observation_provenance': {co: {'status': 'SOURCE_READ'} for co in p['countries']}}
        r = execution_summary(p, {t: {} for t in source_hours(p)}, source, heights, score, stations=True)
        self.assertEqual(r['engineering_execution_status'], 'COMPLETE_SOURCE_EXECUTION')
        self.assertIn('NOT_QUALIFIED', r['independent_accuracy'])
        self.assertEqual(r['operational_readiness'], 'NOT_QUALIFIED')
        self.assertFalse(r['B4_qualified'])


class SealAndFailureBehavior(unittest.TestCase):
    def test_full_fifty_hour_runner_with_real_predictor_and_synthetic_sources(self):
        p = protocol()
        base = json.loads((ROOT/p['source_protocol_file']).read_text())
        heights = json.loads((ROOT/p['dated_sensor_reference_file']).read_text())['countries']
        for h in heights.values():
            h['reference_refresh'] = 'WMDR_SEMANTIC_IDENTITY_CONFIRMED'
        reader = NV2Columns.__new__(NV2Columns)
        reader.nv2_protocol, reader.protocol, reader.heights = p, base, heights
        reader.by_country = {'AT': [1, 2], 'DE': [3], 'CH': [4]}
        reader.donors = {'AT': {'D1': 1, 'D2': 2}, 'DE': {'D1': 3}, 'CH': {'D1': 4}}
        reader.catalogue = {}
        reader.controls = lambda: {'paired_surface_lineage_status': 'ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'}
        def read(stamp, first_level):
            cs = {index: dataclasses.replace(c, timestamp_UTC=stamp) for index, c in graz_columns().items()}
            for country, index in (('DE', 3), ('CH', 4)):
                sensor = heights[country]['sensors']['pressure']
                c = column(ground=sensor['height_MSL_m']-100, first=first_level)
                cs[index] = dataclasses.replace(c, timestamp_UTC=stamp, latitude=sensor['latitude'], longitude=sensor['longitude'])
            return cs
        reader.read = read
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)/'out'
            def observations(cache, country, source_protocol):
                seal = json.loads((out/'prediction_seal.json').read_text())
                self.assertFalse(seal['station_pressure_products_opened'])
                self.assertEqual(len(seal['source_products_sha256']), 6)
                return {t: 98000. for t in source_hours(p)}, {'status': 'SOURCE_READ'}
            with patch('p9_3b3_nv2_run.refresh_sensor_references', return_value=heights), \
                    patch('p9_3b3_nv2_run.NV2Columns', return_value=reader), \
                    patch('p9_3b3_native_validation.observation_pressure', side_effect=observations), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = run(out, Path(td)/'private', stations=True)
            self.assertEqual(result['engineering_execution_status'], 'COMPLETE_SOURCE_EXECUTION')
            self.assertEqual(result['source_profile_hours_complete'], 50)
            self.assertEqual(result['score_cells_retained'], 26)
            self.assertEqual(result['G0_score_cells_retained'], 24)
            data = json.loads((out/'sealed_pressure_predictions.json').read_text())
            at = data['hourly']['2021-02-01T00:00']['AT']
            self.assertNotIn('pressure_Pa', at['roles']['temperature']['methods']['P2_NATIVE_D1'])
            self.assertIn('pressure_Pa', at['roles']['temperature']['methods']['P2_NATIVE_D2'])
            self.assertIn('NOT_QUALIFIED', result['independent_accuracy'])

    def test_each_source_product_is_checked_before_any_observation_I_O(self):
        p = protocol()
        base = json.loads((ROOT/p['source_protocol_file']).read_text())
        for name in ('source_geometry_and_fixed_donors.json', 'native_primary_profiles.json', 'sealed_pressure_predictions.json'):
            with tempfile.TemporaryDirectory() as td:
                out = Path(td)
                seals = sealed_fixture(out)
                (out/name).write_text('{}')
                with patch('p9_3b3_native_validation.observation_pressure', side_effect=AssertionError('OPENED_TOO_EARLY')) as obs:
                    with self.assertRaisesRegex(ValueError, 'SEALED_PREDICTIONS_CHANGED'):
                        score_after_seal(out, seals, None, p, base, p['countries'])
                    obs.assert_not_called()

    def test_post_I_O_tampering_is_rejected_and_G0_reuses_same_truth(self):
        p = protocol()
        base = json.loads((ROOT/p['source_protocol_file']).read_text())
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            seals = sealed_fixture(out)
            def observation(cache, country, source_protocol):
                (out/'source_geometry_and_fixed_donors.json').write_text('{}')
                return {}, {'status': 'SOURCE_READ'}
            with patch('p9_3b3_native_validation.observation_pressure', side_effect=observation):
                with self.assertRaisesRegex(ValueError, 'SEALED_PREDICTIONS_CHANGED'):
                    score_after_seal(out, seals, None, p, base, p['countries'])
            seals = sealed_fixture(out)
            with patch('p9_3b3_native_validation.observation_pressure', return_value=({}, {'status': 'SOURCE_READ'})) as obs:
                nv2, g0 = score_after_seal(out, seals, None, p, base, p['countries'])
            self.assertEqual(obs.call_count, 3)
            self.assertEqual(len(nv2['cells']), 26)
            self.assertEqual(len(g0['cells']), 24)
            self.assertEqual(nv2['observation_provenance'], g0['observation_provenance'])

    def test_source_only_empty_cache_saves_full_failure_census_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            out, cache = Path(td)/'out', Path(td)/'private'
            with patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK_FORBIDDEN')) as network:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = main(['--out', str(out), '--private-cache', str(cache), '--stations', '--cache-only'])
                network.assert_not_called()
            self.assertEqual(result, 1)
            r = json.loads((out/'run_manifest.json').read_text())
            scores = json.loads((out/'revealed_pressure_scores_NV2.json').read_text())
            self.assertEqual(r['source_profile_hours_complete'], 0)
            self.assertEqual(r['source_profile_hours_expected'], 50)
            self.assertEqual(len(scores['cells']), 26)
            self.assertFalse(r['production_epw_ready'])

    def test_output_reuse_and_private_cache_inside_artifact_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(ValueError, 'NO_OVERWRITE'):
                run(root, root/'private')
            with self.assertRaisesRegex(ValueError, 'CACHE_INSIDE_OUTPUT'):
                run(root/'new', root/'new'/'private')
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
