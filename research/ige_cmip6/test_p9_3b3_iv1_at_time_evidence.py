"""Provider metadata evidence, not station-weather accuracy tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_iv1_admission import admission_report
import p9_3b3_iv1_integration_at_time as evidence
from p9_3b3_iv1_integration_common import require_time_admission
import p9_3b3_iv1_integration as pipeline
import p9_3b3_iv1_integration_observations as observations
from p9_3b3_iv1_preflight import guard


class OriginalProviderTimeEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = guard()
        _, cls.bodies = evidence.load_evidence()

    def alter(self, name, change):
        bodies = dict(self.bodies)
        obj = json.loads(bodies[name]); change(obj)
        bodies[name] = json.dumps(obj).encode()
        return bodies

    def test_all_nine_nominal_published_nodes_are_admitted_without_filter_certificate(self):
        audit = require_time_admission()
        self.assertEqual(audit['time_admission']['admitted_fields'], 9)
        self.assertTrue(audit['ready_for_native_source_collection'])
        self.assertFalse(audit['ready_to_open_observations'])
        rows = audit['time_admission']['countries']['AT']
        self.assertEqual({r['field'] for r in rows.values()}, {'tl', 'rf', 'p'})
        self.assertTrue(all(r['operator'] == 'CURRENT_VALUE_AT_EXACT_UTC_NODE' for r in rows.values()))
        self.assertTrue(all(r['instrument_averaging_window_seconds'] is None
                            and not r['instrument_filter_period_certified']
                            and not r['v1_v2_value_identity_checked'] for r in rows.values()))
        self.assertTrue(all('INFERENCE_FROM_PROVIDER' in r['nominal_operator_v2_basis'] for r in rows.values()))

    def test_historical_six_field_snapshot_and_dated_sensors_are_unchanged(self):
        old, new = admission_report(), evidence.current_admission_report()
        self.assertEqual(old['time_admission']['admitted_fields'], 6)
        self.assertFalse(old['ready_for_native_source_collection'])
        self.assertEqual(fingerprint(old['dated_sensors']), fingerprint(new['dated_sensors']))
        for co in ('DE', 'CH'):
            self.assertEqual(old['time_admission']['countries'][co], new['time_admission']['countries'][co])

    def test_generic_hourly_label_or_hourly_mean_cannot_replace_base_sample_proof(self):
        for name, field, description in (
            ('legacy_hourly_metadata.json', 'TTX', 'Lufttemperatur, Stunden-Messwert'),
            ('legacy_hourly_metadata.json', 'FFX', 'Relative Feuchte, Stundenmittelwert'),
            ('legacy_10min_metadata.json', 'P', 'Luftdruck, 10-Minuten-Mittelwert')):
            bodies = self.alter(name, lambda obj: evidence.parameter(obj, field).update(desc=description))
            with self.assertRaisesRegex(ValueError, 'BASE_SAMPLE_SELECTION_NOT_DOCUMENTED'):
                evidence.parse_evidence(bodies, self.protocol)

    def test_missing_wrong_or_duplicate_provider_mapping_blocks_version_transfer(self):
        for name, old, new in (('hourly_parameter_mapping.csv', b'TTX;tl', b'TTX;different'),
                               ('10min_parameter_mapping.csv', b'TL;tl', b'TL;different')):
            bodies = dict(self.bodies); bodies[name] = bodies[name].replace(old, new)
            with self.assertRaisesRegex(ValueError, 'RENAME_NOT_UNIQUE'):
                evidence.parse_evidence(bodies, self.protocol)
        bodies = dict(self.bodies)
        bodies['hourly_parameter_mapping.csv'] += b'TTX;tl\n'
        with self.assertRaisesRegex(ValueError, 'RENAME_NOT_UNIQUE'):
            evidence.parse_evidence(bodies, self.protocol)

    def test_reduced_pressure_or_wrong_pressure_unit_is_rejected(self):
        for change in (lambda obj: evidence.parameter(obj, 'PPX').update(desc='Luftdruck Meeresspiegel - letzter 10 Minutenwert der vollen Stunde'),
                       lambda obj: evidence.parameter(obj, 'PPX').update(unit='Pa')):
            with self.assertRaises(ValueError):
                evidence.parse_evidence(self.alter('legacy_hourly_metadata.json', change), self.protocol)

    def test_each_product_requires_individual_station_and_coverage_of_both_2022_windows(self):
        for name in ('legacy_hourly_metadata.json', 'legacy_10min_metadata.json', 'hourly_metadata.json', '10min_metadata.json'):
            def expire(obj):
                next(r for r in obj['stations'] if str(r['id']) == '16412')['valid_to'] = '2020-01-01T00:00:00'
            with self.assertRaisesRegex(ValueError, 'EPOCH_DOES_NOT_COVER'):
                evidence.parse_evidence(self.alter(name, expire), self.protocol)
        def combined(obj):
            next(r for r in obj['stations'] if str(r['id']) == '16412')['type'] = 'COMBINED'
        with self.assertRaisesRegex(ValueError, 'INDIVIDUAL_16412'):
            evidence.parse_evidence(self.alter('hourly_metadata.json', combined), self.protocol)

    def test_UTC_and_provider_release_evidence_are_both_required(self):
        bodies = dict(self.bodies)
        bodies['legacy_hourly_dataset.html'] = b'<p>Zeitzone MEZ</p>'
        with self.assertRaisesRegex(ValueError, 'PROVIDER_UTC'):
            evidence.parse_evidence(bodies, self.protocol)
        bodies = dict(self.bodies); bodies['provider_changelog.html'] = b'<p>No original migration record</p>'
        with self.assertRaisesRegex(ValueError, 'PROVIDER_VERSION_LINK'):
            evidence.parse_evidence(bodies, self.protocol)

    def test_CH_asset_drift_cannot_silently_change_the_registered_source(self):
        def changed(obj):
            obj['assets']['ogd-smn_dav_t_historical_2020-2029.csv']['file:checksum'] = '1220'+'0'*64
        with self.assertRaisesRegex(ValueError, 'CH_SOURCE_VERSION_DRIFT'):
            evidence.parse_evidence(self.alter('CH_DAV_STAC_current.json', changed), self.protocol)

    def test_evidence_archive_digest_is_checked_before_reading_records(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'changed.xz'; p.write_bytes(evidence.SNAPSHOT.read_bytes()+b' ')
            with patch.object(evidence, 'SNAPSHOT', p):
                with self.assertRaisesRegex(ValueError, 'EVIDENCE_SNAPSHOT_CHANGED'):
                    evidence.load_evidence()

    def test_time_admission_does_not_unblind_without_full_prediction_seal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(observations, 'StationCache', side_effect=AssertionError('NO_STATION_IO')):
                for call in (
                    lambda: pipeline.score_predictions(root/'no-seal', '0'*64, root/'scores/result.json', root/'private'),
                    lambda: observations.open_observations(self.protocol, root/'private', root/'no-seal', '0'*64)):
                    with self.assertRaises(FileNotFoundError):
                        call()
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
