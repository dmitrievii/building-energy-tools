"""Artificial archive/I/O controls; actual physics replay remains unchanged."""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import p9_1a_global_historical_backbone as era
import p9_3b3_iv1_missing_source_recovery as recovery
from p9_3b3_iv1_integration_common import integration_guard, execution_plan, sha


class MissingSourceRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'source'; self.source.mkdir()
        self.archive = self.root/'original.zip'; self.archive.write_bytes(b'ARTIFICIAL_UNIT_TEST_ARCHIVE')
        self.protocol, contract = integration_guard()
        plan = execution_plan(self.protocol, contract)
        missing = '2022-02-18T12:00'
        sensor = {'latitude': 46., 'longitude': 9.}
        self.data = {'plan': plan, 'complete': False, 'station_values_opened': False,
            'native_hours': {t: {'artificial_unit_test': t} for t in plan['native_source_hours']},
            'reference_requests': [], 'source_failures': [{'scope': 'ARTIFICIAL_TLS_FAILURE'}],
            'sensors': {co: {'temperature': sensor} for co in ('AT', 'DE', 'CH')},
            'hybrid_pv': [0.]*276, 'field_attributes': {'artificial': True},
            'lineage': {'sources': {'unit_test': True}, 'original_GRIB_controls': []},
            'network_bytes': 50, 'network_bytes_conservative_upper_bound': 100,
            'network_requests': 1, 'network_requests_conservative_upper_bound': 2, 'wall_seconds': 1.}
        self.data['native_hours'][missing] = {'status': 'SOURCE_BLOCKED', 'reason': 'ARTIFICIAL_TLS_FAILURE'}
        for i, r in enumerate(plan['reference_requests']):
            entry = {'request': r, 'url': era.request_url(46., 9., r['start'], r['end'])}
            if i == 15:
                entry.update(status='SOURCE_BLOCKED', reason='ARTIFICIAL_TLS_FAILURE')
            else:
                p = self.source/f'reference_{i:02d}.json'; p.write_bytes(b'ARTIFICIAL_REFERENCE_'+str(i).encode())
                entry.update(status='SOURCE_READ', member=p.name, sha256=sha(p))
            self.data['reference_requests'].append(entry)
        self.request_path = self.root/'request.json'
        self.request = {'stage': 'RESTORE_ONLY_REGISTERED_MISSING_MODEL_INPUTS_BEFORE_OBSERVATIONS',
            'parent_commit': '00476b4496905aefc016cda2b5a98de065662009',
            'heldout_2022_station_values_opened': False, 'original_artifact_sha256': sha(self.archive),
            'missing_native_hours': [missing], 'missing_reference_indices': [15],
            'missing_reference_identity': {'country': 'CH', 'year': 2020, 'start': '2020-08-15', 'end': '2020-08-28'},
            'additional_native_byte_ceiling': 512*1024**2, 'additional_native_request_ceiling': 1000}
        self.profile_calls, self.reference_calls = [], []

    def proofs(self):
        p = self.source/'source_data.json'; p.write_text(json.dumps(self.data))
        members = {p.name: sha(p) for p in self.source.iterdir() if p.name != 'source_seal.json'}
        s = self.source/'source_seal.json'; s.write_text(json.dumps({'members_sha256': members, 'contract_sha256': 'a'*64}))
        self.request.update(original_source_data_sha256=sha(p), original_source_seal_sha256=sha(s))

    def invoke(self, *, wrong_seal=False, changed_lineage=False):
        self.proofs()
        if wrong_seal: self.request['original_source_seal_sha256'] = '0'*64
        self.request_path.write_text(json.dumps(self.request))
        test = self
        class ArtificialCache:
            def __init__(self, *args): self.downloaded, self.requests = 1000, 20
        class ArtificialReader:
            def __init__(self, *args):
                self.A, self.B = [0.]*138, [0.]*138
                self.field_attributes = test.data['field_attributes']
            def controls(self):
                v = deepcopy(test.data['lineage'])
                if changed_lineage: v['sources'] = {'different': True}
                return v
            def raw_hour(self, stamp):
                test.profile_calls.append(stamp)
                return {'artificial_restored_profile': stamp}
        def reference(url, cache):
            self.reference_calls.append(url)
            return b'ARTIFICIAL_RESTORED_REFERENCE', {'bytes_downloaded': 27, 'requests': 1}
        def verify(path):
            if Path(path) == self.source: return deepcopy(self.data), {}, {}
            d = json.loads((Path(path)/'source_data.json').read_text())
            return d, {i: None for i in range(676)}, {i: None for i in range(18)}
        with ExitStack() as stack:
            for name, value in (('REQUEST', self.request_path), ('REQUEST_SHA', sha(self.request_path)),
                                ('ModelCache', ArtificialCache), ('IV1Columns', ArtificialReader)):
                stack.enter_context(patch.object(recovery, name, value))
            stack.enter_context(patch.object(recovery, 'require_committed_recovery'))
            stack.enter_context(patch.object(recovery, 'verify_sources', side_effect=verify))
            stack.enter_context(patch.object(recovery, 'fetch_reference', side_effect=reference))
            stack.enter_context(patch.object(recovery.era, 'parse_source'))
            return recovery.recover_sources(self.source, self.archive, self.root/'completed', self.root/'private')

    def test_exact_two_restorations_preserve_all_existing_inputs_and_failure_history(self):
        result = self.invoke()
        self.assertEqual(self.profile_calls, ['2022-02-18T12:00'])
        self.assertEqual(len(self.reference_calls), 1)
        self.assertEqual(result['native_hours'], 676)
        self.assertEqual(result['reference_requests'], 18)
        self.assertEqual(result['preserved_native_hours'], 675)
        self.assertEqual(result['preserved_reference_bodies'], 17)
        new = json.loads((self.root/'completed/source_data.json').read_text())
        for stamp, row in self.data['native_hours'].items():
            if stamp != self.request['missing_native_hours'][0]: self.assertEqual(new['native_hours'][stamp], row)
        self.assertEqual(new['source_recovery']['original_source_failures'], self.data['source_failures'])
        self.assertEqual(new['source_failures'], [])
        self.assertFalse(result['ready_to_open_observations'])
        self.assertEqual(sha(self.source/'source_data.json'), self.request['original_source_data_sha256'])

    def test_changed_predecessor_seal_and_uncommitted_helper_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'PREDECESSOR_SOURCE_SEAL'):
            self.invoke(wrong_seal=True)
        self.assertEqual(self.profile_calls, [])
        with patch.object(recovery.subprocess, 'run'), patch.object(recovery.subprocess, 'check_output', return_value=b'changed'):
            with self.assertRaisesRegex(ValueError, 'MUST_ALREADY_BE_COMMITTED'):
                recovery.require_committed_recovery(self.request)

    def test_different_missing_native_census_cannot_be_substituted(self):
        other = next(t for t in self.data['native_hours'] if t != '2022-02-18T12:00')
        self.data['native_hours'][other] = {'status': 'SOURCE_BLOCKED'}
        with self.assertRaisesRegex(ValueError, 'EXACT_ORIGINAL_MISSING_INPUTS'):
            self.invoke()
        self.assertEqual(self.profile_calls, [])

    def test_different_reference_country_or_date_cannot_be_substituted(self):
        self.data['reference_requests'][15]['request']['country'] = 'AT'
        with self.assertRaisesRegex(ValueError, 'REFERENCE_IDENTITY_CHANGED'):
            self.invoke()
        self.assertEqual(self.reference_calls, [])

    def test_cumulative_budget_is_checked_before_any_new_profile(self):
        self.data['network_bytes_conservative_upper_bound'] = self.protocol['compute_estimate']['max_network_bytes']
        with self.assertRaisesRegex(ValueError, 'CUMULATIVE_OR_ADDITIONAL_BUDGET'):
            self.invoke()
        self.assertEqual(self.profile_calls, [])

    def test_source_lineage_change_blocks_restoration_before_profile_or_reference_reads(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_METADATA_HYBRID_OR_RAW_GRIB_CHAIN_CHANGED'):
            self.invoke(changed_lineage=True)
        self.assertEqual(self.profile_calls, [])
        self.assertEqual(self.reference_calls, [])
        self.assertFalse((self.root/'completed').exists())


if __name__ == '__main__': unittest.main()
