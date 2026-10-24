"""Artificial end-to-end IV1 controls; no held-out station/model values.

The real AT gate remains blocked. Happy-path readers and admission are mocked
only in this test module; the CLI has no bypass or synthetic qualification mode.
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

import numpy as np

import p9_1a_global_historical_backbone as era
import p9_3b3_iv1_integration as pipeline
import p9_3b3_iv1_integration_sources as sources
import p9_3b3_iv1_integration_observations as observations
from p9_3b3_compare_vertical_frame import fingerprint, G0, SourceBlocked
from p9_3b3_iv1_admission import admission_report
from p9_3b3_iv1_integration_common import (OBSERVATION_BUDGET, execution_plan,
    integration_guard, member_path, require_time_admission, sha)
from p9_3b3_iv1_integration_statistics import score_arrays
from p9_3b3_iv1_methods import METHODS
from p9_3b3_reference_column import hybrid_column


def synthetic_admission():
    audit = admission_report()
    audit['unit_test_artificial_time_admission'] = True
    for country in audit['time_admission']['countries'].values():
        for row in country.values():
            row.update(status='ADMITTED', operator='CURRENT_VALUE_AT_EXACT_UTC_NODE')
    audit['time_admission']['all_parameter_time_operators_admitted'] = True
    return audit


def artificial_gate():
    stack = ExitStack()
    for name in ('p9_3b3_iv1_integration.require_time_admission',
                 'p9_3b3_iv1_integration_sources.require_time_admission',
                 'p9_3b3_iv1_integration_observations.require_time_admission'):
        stack.enter_context(patch(name, side_effect=synthetic_admission))
    return stack


class ArtificialNativeColumns:
    def __init__(self, cache, config, sensors, contract):
        self.config, self.sensors, self.contract = config, sensors, contract
        self.A = [0.]*138
        self.B = (np.arange(138)/137).tolist()
        pv = self.A+self.B
        self.manifest = {'unit_test_artificial_source_not_station_evidence': True,
            'sources': {k: {'url': config['source_base']+'/'+config[k], 'metadata_sha256': 'a'*64}
                        for k in ('surface', 'temperature', 'moisture', 'grid_reference')},
            'GRIB_pv_sha256': fingerprint(pv), 'original_GRIB_controls': [],
            'paired_surface_lineage_status': 'ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'}
        self.field_attributes = {name: {'units': units, 'GRIB_paramId': param, 'GRIB_gridType': grid,
            'GRIB_stepType': 'instant', 'GRIB_typeOfLevel': 'hybrid', 'GRIB_pv': pv,
            **({'GRIB_J': 639, 'GRIB_K': 639, 'GRIB_M': 639} if grid == 'sh' else {'GRIB_N': 320})}
            for name, units, param, grid in (('z', 'm**2 s**-2', 129, 'sh'), ('lnsp', '~', 152, 'sh'),
                ('t', 'K', 130, 'sh'), ('q', 'kg kg**-1', 133, 'reduced_gg'))}

    def controls(self):
        for stamp in self.config['source_control_hours']:
            for field, param in (('z', 129), ('lnsp', 152)):
                path = self.config['original_surface_GRIB'].format(month=stamp[:7].replace('-', ''),
                    variable='zs' if field == 'z' else 'lnsp')
                self.manifest['original_GRIB_controls'].append({'timestamp_UTC': stamp, 'variable': field,
                    'status': 'ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT', 'hybrid_pv_sha256': fingerprint(self.A+self.B),
                    'url': self.config['source_base']+'/'+path, 'sha256': 'b'*64, 'dataDate': int(stamp[:10].replace('-', '')),
                    'dataTime': 0, 'paramId': param, 'gridType': 'sh', 'J': 639, 'K': 639, 'M': 639,
                    'level': 1, 'typeOfLevel': 'hybrid', 'step': 0, 'dataType': 'an', 'coefficient_count': 410240})
        return self.manifest

    def raw_hour(self, stamp):
        rows = {}
        heights = {'AT': 339.8640826446401, 'DE': 37.294058132779845, 'CH': 1206.8191589456485}
        Tv = 285.*(1+(461.5/287.05-1)*.003)
        for country, (index, lat, lon) in self.contract['fixed_grid_points'].items():
            H = heights[country]
            target = self.sensors[country]['temperature']['height_MSL_m']
            lnsp = math.log(95000.)+G0*(target-H)/(287.05*Tv)
            raw = {'stamp': stamp, 'latitude': lat, 'longitude': lon, 'first_level': 124,
                'z': G0*H, 'lnsp': lnsp, 'T': [285.]*14, 'q': [.003]*14,
                'source_manifest': self.manifest['sources'], 'hybrid_pv': fingerprint(self.A+self.B)}
            column = hybrid_column(lnsp, G0*H, raw['T'], raw['q'], self.A, self.B, first_level=124,
                timestamp_UTC=stamp, latitude=lat, longitude=lon,
                source='ERA5_ORIGINAL_SH_CO_TO_NATIVE_N320_HYBRID_COLUMN', source_sha256=fingerprint(raw))
            rows[str(index)] = {'preimage': raw, 'column_fingerprint': column.fingerprint}
        return rows


def artificial_reference(url, private_cache):
    import datetime as dt
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    start, end = query['start_date'][0], query['end_date'][0]
    times = [(dt.datetime.fromisoformat(start)+dt.timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M') for h in range(336)]
    values = {key: [0.]*336 for key in era.HOURLY}
    values.update(temperature_2m=[11.85]*336, dew_point_2m=[4.85]*336, relative_humidity_2m=[60.]*336,
                  surface_pressure=[950.]*336)
    obj = {'unit_test_artificial_reference': True, 'latitude': round(float(query['latitude'][0])*4)/4,
        'longitude': round(float(query['longitude'][0])*4)/4, 'utc_offset_seconds': 0, 'timezone': 'GMT',
        'hourly': {'time': times, **values}, 'hourly_units': era.EXPECTED_UNITS}
    return json.dumps(obj).encode(), {'from_cache': True, 'bytes_downloaded': 0, 'requests': 0}


def artificial_observations(cases, barometer):
    out = {co: {'values': {'T_K': {}, 'RH_pp': {}, 'p_barometer_Pa': dict(barometer[co])}}
           for co in ('AT', 'DE', 'CH')}
    for case in cases:
        row = case['results'][2]
        for h in range(24):
            stamp = case['date']+f'T{h:02d}:00'
            out[case['country']]['values']['T_K'][stamp] = row['T_K'][h]
            out[case['country']]['values']['RH_pp'][stamp] = row['validation']['diagnostics']['RH_water_pct'][h]
    return out


class RealScientificGuards(unittest.TestCase):
    def test_real_AT_gate_stops_all_IO_stages_before_network_or_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('urllib.request.urlopen', side_effect=AssertionError('NO_HTTP')), \
                 patch('p9_3b3_iv1_integration_sources.IV1Columns', side_effect=AssertionError('NO_READER')):
                for call in (lambda: sources.collect_sources(root/'source', root/'private'),
                             lambda: pipeline.generate_predictions(root/'absent', root/'predictions'),
                             lambda: pipeline.score_predictions(root/'absent', '0'*64, root/'scores/result.json', root/'obs'),
                             lambda: observations.open_observations(integration_guard()[0], root/'obs', root/'absent', '0'*64)):
                    with self.assertRaisesRegex(SourceBlocked, 'TIME_OPERATORS'):
                        call()
            self.assertEqual(list(root.iterdir()), [])

    def test_control_amendment_is_explicit_and_retains_exact_cohort(self):
        p, c = integration_guard()
        plan = execution_plan(p, c)
        self.assertEqual(plan['source_control_hours'], ['2022-02-01T00:00', '2022-08-01T00:00'])
        self.assertEqual(len(set(plan['native_source_hours'])), 676)
        self.assertEqual(plan['target_days'], 84)
        self.assertEqual(plan['method_records_expected'], 420)
        self.assertFalse(plan['control_amendment']['old_preparation_snapshot_rewritten'])
        config = sources.native_config(p, plan)
        self.assertEqual(config['max_download_bytes']+18*era.LIMIT_BYTES+OBSERVATION_BUDGET, p['compute_estimate']['max_network_bytes'])
        self.assertEqual(config['max_requests']+23, p['compute_estimate']['max_requests'])

    def test_model_cache_cannot_access_observation_hosts(self):
        p, c = integration_guard()
        with tempfile.TemporaryDirectory() as folder:
            cache = sources.ModelCache(folder, sources.native_config(p, execution_plan(p, c)))
            with self.assertRaisesRegex(ValueError, 'MODEL_HOST_ONLY'):
                cache.fetch('https://opendata.dwd.de/anything')

    def test_seal_member_paths_refuse_traversal(self):
        for name in ('../observations.json', '/tmp/value', 'x/../../v', 'x\\v'):
            with self.assertRaises(ValueError): member_path('/tmp/sealed', name)

    def test_barometer_validation_does_not_depend_on_daily_donor_availability(self):
        protocol, _ = integration_guard()
        def valid_native_day(data, columns, country, date):
            return None, {date+f'T{h:02d}:00': 95000. for h in range(24)}
        with patch.object(pipeline, 'native_day', side_effect=valid_native_day):
            prepared, pressure = pipeline.prepare_inputs({'reference_requests': []}, {}, {}, protocol)
        self.assertTrue(all('shared_blocker' in row for row in prepared))
        self.assertEqual(sum(len(v) for v in pressure.values()), 2016)


class ArtificialEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source, cls.pred = cls.root/'source', cls.root/'predictions'
        cls.prior_checks = []
        original = pipeline.compare_five
        def observe_order(*args):
            prepared = json.loads((cls.pred/'common_inputs_before_methods.json').read_text())
            if len(prepared) != 84:
                raise AssertionError('ALL_PRIORS_MUST_EXIST_BEFORE_FIRST_METHOD')
            cls.prior_checks.append(sha(cls.pred/'common_inputs_before_methods.json'))
            return original(*args)
        with artificial_gate(), patch.object(sources, 'IV1Columns', ArtificialNativeColumns), \
             patch.object(sources, 'fetch_reference', artificial_reference), patch('builtins.print'):
            cls.collection = sources.collect_sources(cls.source, cls.root/'private')
            with patch.object(pipeline, 'compare_five', side_effect=observe_order):
                cls.generation = pipeline.generate_predictions(cls.source, cls.pred)
            cls.digest = cls.generation['prediction_seal_sha256']
            cls.cases, cls.barometer, cls.protocol = pipeline.verify_predictions(cls.pred, cls.digest)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_complete_artificial_sources_priors_predictions_and_full_seal(self):
        self.assertTrue(self.collection['complete'])
        self.assertEqual(self.generation['case_count'], 84)
        self.assertEqual(self.generation['method_records'], 420)
        self.assertEqual(self.generation['algorithm_errors'], [])
        self.assertEqual(len(self.prior_checks), 84)
        self.assertEqual(len(set(self.prior_checks)), 1)
        self.assertTrue(all('inputs' in c and len(c['results']) == 5 for c in self.cases))
        self.assertEqual(sum(len(v) for v in self.barometer.values()), 2016)

    def test_current_value_scoring_and_registered_statistical_cells(self):
        observed = artificial_observations(self.cases, self.barometer)
        result = score_arrays(self.cases, self.barometer, observed, self.protocol)
        self.assertEqual(len(result['primary_comparisons']), 12)
        self.assertEqual(len(result['individual_cells']), 60)
        self.assertEqual(len(result['pressure_cells']), 6)
        self.assertTrue(all(r['matched_hours'] == 336 for r in result['primary_comparisons']))
        self.assertTrue(result['IV1_research_criteria_pass'])
        self.assertFalse(result['production_epw_ready'])
        self.assertFalse(result['P2_superiority_established'])

    def test_observation_callback_is_after_full_verification_and_rechecked(self):
        events = []
        original = pipeline.verify_predictions
        def verify(*args):
            events.append('VERIFY'); return original(*args)
        def open_values(*args):
            self.assertEqual(events[-1], 'VERIFY')
            events.append('OBSERVATIONS')
            return artificial_observations(self.cases, self.barometer), {'unit_test_artificial_only': True}
        with artificial_gate(), patch.object(pipeline, 'verify_predictions', side_effect=verify), \
             patch.object(observations, 'open_observations', side_effect=open_values):
            result = pipeline.score_predictions(self.pred, self.digest, self.root/'results'/'scores.json', self.root/'obs-private')
        self.assertEqual(events, ['VERIFY', 'OBSERVATIONS', 'VERIFY'])
        self.assertTrue(result['IV1_research_criteria_pass'])

    def test_missing_full_seal_cannot_be_replaced_by_component_seal(self):
        with artificial_gate(), patch.object(observations, 'StationCache', side_effect=AssertionError('NO_OBSERVATION_IO')):
            with self.assertRaises((ValueError, FileNotFoundError)):
                pipeline.score_predictions(self.pred/'components', self.digest, self.root/'missing.json', self.root/'obs2')

    def test_external_digest_and_source_tampering_are_rejected_before_observations(self):
        with artificial_gate(), patch.object(observations, 'open_observations', side_effect=AssertionError('NO_OBSERVATION_IO')):
            with self.assertRaisesRegex(ValueError, 'EXTERNALLY_PINNED'):
                pipeline.score_predictions(self.pred, '0'*64, self.root/'wrong.json', self.root/'obs3')
            dest = self.root/'tampered'
            shutil.copytree(self.pred, dest)
            p = dest/'pressure_barometer_predictions.json'
            p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'SEALED_MEMBER_CHANGED'):
                pipeline.score_predictions(dest, self.digest, self.root/'changed.json', self.root/'obs4')

    def test_rehashed_source_still_requires_native_physical_replay(self):
        dest = self.root/'changed-source'
        shutil.copytree(self.source, dest)
        path = dest/'source_data.json'
        data = json.loads(path.read_text())
        stamp = data['plan']['native_source_hours'][0]
        data['native_hours'][stamp]['73689']['preimage']['q'][0] = -.01
        path.write_text(json.dumps(data))
        seal_path = dest/'source_seal.json'
        seal = json.loads(seal_path.read_text()); seal['members_sha256']['source_data.json'] = sha(path)
        seal_path.write_text(json.dumps(seal))
        with self.assertRaisesRegex(ValueError, 'INPUT_DOMAIN'):
            sources.verify_sources(dest)

    def test_incomplete_native_hour_is_retained_and_cannot_authorize_observations(self):
        dest = self.root/'incomplete-source'
        shutil.copytree(self.source, dest)
        path = dest/'source_data.json'
        data = json.loads(path.read_text())
        stamp = '2022-02-15T00:00'
        data['native_hours'][stamp] = {'status': 'SOURCE_BLOCKED', 'reason': 'ARTIFICIAL_MISSING_PROFILE'}
        data['source_failures'] = [{'scope': 'NATIVE_PROFILE', 'timestamp_UTC': stamp, 'reason': 'ARTIFICIAL_MISSING_PROFILE'}]
        data['complete'] = False
        path.write_text(json.dumps(data))
        seal_path = dest/'source_seal.json'
        seal = json.loads(seal_path.read_text()); seal['members_sha256']['source_data.json'] = sha(path)
        seal_path.write_text(json.dumps(seal))
        replay, columns, _ = sources.verify_sources(dest)
        self.assertFalse(replay['complete'])
        self.assertEqual(len(columns), 675)
        out = self.root/'incomplete-prediction'
        with artificial_gate(), patch('builtins.print'):
            generated = pipeline.generate_predictions(dest, out)
            self.assertEqual(generated['method_records'], 420)
            self.assertFalse(generated['ready_for_scoring_admission'])
            with patch.object(observations, 'open_observations', side_effect=AssertionError('NO_OBSERVATION_IO')):
                with self.assertRaisesRegex(SourceBlocked, 'INCOMPLETE_SOURCES'):
                    pipeline.score_predictions(out, generated['prediction_seal_sha256'], self.root/'no-incomplete-scores.json', self.root/'obs5')

    def test_solver_failure_stays_in_census_and_blocks_unblinding(self):
        out = self.root/'algorithm-failure'
        def fail(*args): raise RuntimeError('ARTIFICIAL_SOLVER_FAILURE')
        # One failed target is enough to test disposition; keep the remaining
        # actual numerical results cached by exact registered case identity.
        by_id = {c['case_id']: deepcopy(c) for c in self.cases}
        first = self.cases[0]['case_id']
        def injected(country, target, pressure, donor):
            identity = 'IV1|'+country+'|'+target.date+'|P2_NATIVE_THERMO'
            if identity == first: return fail()
            return by_id[identity]
        with artificial_gate(), patch.object(pipeline, 'compare_five', side_effect=injected), patch('builtins.print'):
            result = pipeline.generate_predictions(self.source, out)
            self.assertEqual(result['method_records'], 420)
            self.assertEqual(len(result['algorithm_errors']), 1)
            with self.assertRaisesRegex(ValueError, 'ALGORITHM_ERROR'):
                pipeline.verify_predictions(out, result['prediction_seal_sha256'])


if __name__ == '__main__':
    unittest.main()
