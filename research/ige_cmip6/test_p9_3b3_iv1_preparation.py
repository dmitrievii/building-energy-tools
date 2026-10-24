"""IV1 preparation: original timing evidence, unchanged solvers and seals.

All weather arrays below are artificial numerical controls, never held-out
station values. Network ZIP fixtures contain only a sentinel product body.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_generator import ThermoDonor, _choose
from p9_3b3_iv1_admission import (admission_report, dwd_parameter, load_time_metadata,
                                 source_plan, time_admission)
from p9_3b3_iv1_component_seal import census, replay_case, seal_components, verify_components
from p9_3b3_iv1_methods import (IV1PressureTrajectory, METHODS, ReferenceConstraints,
                               choose_common_prior, compare_five, reference_constraints)
from p9_3b3_iv1_preflight import cohort, guard
from p9_3b3_iv1_time_metadata import MetadataZip
from p9_3b3_state_validation import _es
from p9_3b3_thermodynamics import MK, q_from_e, q_saturation, saturation
from test_p9_3b3_tpa_contracts import example_pressure


def fixture(soft=False):
    day = '2022-02-15'
    T = np.linspace(270., 280., 24)
    P = np.linspace(94500., 95500., 24)
    q = q_from_e(.6*saturation(T, 'WATER_ICE'), P, 287.05/461.5)
    old = example_pressure(T=T, P=P, q=q)
    values = asdict(old)
    values.update(target_date=day, source_date=day,
                  timestamps_UTC=[day+f'T{h:02d}:00' for h in range(24)])
    pressure = IV1PressureTrajectory(**values)
    target = ReferenceConstraints(day, 270., 280., 275., float(np.mean(q)), 60.,
                                  'b'*64, 'ARTIFICIAL_OPERATOR_CONTROL_NOT_STATION_DATA')
    if soft:
        # Deliberately contradictory daily controls: exercise soft projection,
        # not an assertion about a real reference day or a held-out station.
        target = replace(target, q_mean_kgkg=.9*float(np.mean(q_saturation(T, P))), RH_mean_pct=20.)
    donor = ThermoDonor('2019-02-15', tuple(T), tuple(q),
                        replace(old.comparison_reference(), mode='ERA5_GRID_PROVISIONAL', reference_date='2019-02-15'))
    return target, pressure, donor


def blocked_cohort():
    return [{'country': r['country'], 'date': r['date'],
        'case_id': 'IV1|'+r['country']+'|'+r['date']+'|P2_NATIVE_THERMO',
        'station_values_opened': False, 'shared_blocker': 'ARTIFICIAL_SOURCE_FAILURE_FOR_CENSUS_TEST',
        'results': [{'IV1_method': m, 'status': 'SOURCE_BLOCKED'} for m in METHODS]}
        for r in cohort(guard())]


class ZipMetadataOnly(unittest.TestCase):
    def setUp(self):
        self.member = 'Metadaten_Parameter_zehn_st_min_tu_00399.txt'
        self.url = ('https://opendata.dwd.de/climate_environment/CDC/observations_germany/'
                    'climate_urban/10_minutes/air_temperature/historical/fixture_hist.zip')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(self.member, b'metadata only')
            z.writestr('produkt_zehn_st_min_tu_sentinel.txt', b'PRODUCT_SENTINEL_NOT_OBSERVATIONS'*100)
        self.raw = stream.getvalue()
        self.reads = []

    def opener(self, request, timeout):
        header = request.get_header('Range')
        if header == 'bytes=-22':
            a, b = len(self.raw)-22, len(self.raw)-1
        else:
            a, b = map(int, re.fullmatch(r'bytes=(\d+)-(\d+)', header).groups())
        parent = self
        class Response:
            status = 206
            headers = {'Content-Range': f'bytes {a}-{b}/{len(parent.raw)}', 'ETag': 'fixture-v1'}
            def geturl(self): return parent.url
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, n):
                parent.reads.append((a, b))
                return parent.raw[a:b+1][:n]
        return Response()

    def test_only_directory_and_metadata_body_are_requested(self):
        raw, proof = MetadataZip(self.url, self.opener).read_parameter(self.member)
        self.assertEqual(raw, b'metadata only')
        product = next(e for e in proof['archive_members'] if e['name'].startswith('produkt_'))
        first = product['offset']+30+len(product['name'])
        last = first+product['compressed']-1
        self.assertTrue(all(b < first or a > last for a, b in self.reads))
        self.assertEqual(len(self.reads), 5)
        self.assertFalse(proof['station_product_members_requested'])

    def test_product_member_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, 'ONLY_REGISTERED_PARAMETER'):
            MetadataZip(self.url, self.opener).read_parameter('produkt_zehn_st_min_tu_sentinel.txt')
        self.assertEqual(self.reads, [])

    def test_ignored_range_rejected_before_body_read(self):
        def ignored(req, timeout):
            response = self.opener(req, timeout)
            response.status = 200
            return response
        with self.assertRaisesRegex(ValueError, 'NO_BODY_READ'):
            MetadataZip(self.url, ignored).read_parameter(self.member)
        self.assertEqual(self.reads, [])

    def test_changing_etag_is_rejected_before_second_body(self):
        calls = []
        def changed(req, timeout):
            response = self.opener(req, timeout)
            if calls:
                response.headers['ETag'] = 'changed'
            calls.append(True)
            return response
        with self.assertRaisesRegex(ValueError, 'CHANGED_DURING_READ'):
            MetadataZip(self.url, changed).read_parameter(self.member)
        self.assertEqual(len(self.reads), 1)


class ParameterEvidence(unittest.TestCase):
    def test_original_urban_fields_explicit_current_and_absolute(self):
        result = time_admission(guard())
        self.assertEqual(result['admitted_fields'], 6)
        self.assertEqual(result['DWD_metadata_range_bytes'], 2958)
        self.assertEqual(result['DWD_metadata_range_requests'], 10)
        self.assertTrue(all(r['status'] == 'ADMITTED' for r in result['countries']['DE'].values()))
        self.assertTrue(all(r['status'] == 'SOURCE_BLOCKED' for r in result['countries']['AT'].values()))
        self.assertFalse(result['all_parameter_time_operators_admitted'])

    def test_generic_or_averaged_temperature_metadata_cannot_admit_urban(self):
        _, bodies = load_time_metadata()
        raw = bodies['DE_urban_T_RH_parameters.txt'].replace(b'momentane Lufttemperatur in 2m Hoehe', b'10-Minuten-Mittel der Lufttemperatur')
        with self.assertRaisesRegex(ValueError, 'NOT_EXPLICIT_INSTANT'):
            dwd_parameter(raw, 'TT_ST_10', ['2022-02-15'])

    def test_wrong_epoch_or_station_cannot_reuse_parameter_evidence(self):
        _, bodies = load_time_metadata()
        raw = bodies['DE_urban_T_RH_parameters.txt']
        for body, day in ((raw, '2014-02-15'), (raw.replace(b'399;', b'400;'), '2022-02-15')):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, 'EPOCH_NOT_UNIQUE'):
                dwd_parameter(body, 'TT_ST_10', [day])

    def test_reduced_pressure_description_cannot_be_relabelled_absolute(self):
        _, bodies = load_time_metadata()
        raw = bodies['DE_urban_pressure_parameters.txt'].replace(b'Luftdruck Stationshoehe', b'Luftdruck Normal Null')
        with self.assertRaisesRegex(ValueError, 'ABSOLUTE_STATION_PRESSURE'):
            dwd_parameter(raw, 'P0_ST_10', ['2022-08-28'])

    def test_full_plan_and_raw_sensor_replay_work_without_network(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('NO_NETWORK_IN_ADMISSION')):
            result = admission_report()
        p = result['source_plan']
        self.assertEqual((p['target_days'], p['site_hours'], p['method_records_expected']), (84, 2016, 420))
        self.assertEqual((p['native_source_hour_count'], p['native_column_hour_count']), (676, 2028))
        self.assertEqual(p['reference_request_count'], 18)
        self.assertTrue(all(h[:4] == '2022' for h in p['native_source_hours']))
        self.assertEqual(p['fixed_native_grid_indices'], {'AT': 73689, 'DE': 57155, 'CH': 73673})
        self.assertFalse(result['ready_for_native_source_collection'])
        self.assertFalse(result['ready_to_open_observations'])
        self.assertEqual(result['dated_sensors']['DE']['temperature']['height_MSL_m'], 37.8)


class ReferenceAndMethods(unittest.TestCase):
    def test_reference_operators_match_independent_scalar_equations(self):
        _, pressure, _ = fixture()
        T = np.r_[np.full(12, 268.), np.full(6, 272.), np.full(6, 280.)]
        Td = T-4
        result = reference_constraints(pressure.target_date, T, Td, pressure, 'c'*64)
        epsilon = 287.05/461.5
        e = [_es(float(t), 'WATER', MK) for t in Td]
        q = [epsilon*v/(p-(1-epsilon)*v) for v, p in zip(e, pressure.values_Pa)]
        RH = [100*v/_es(float(t), 'WATER_ICE', MK) for v, t in zip(e, T)]
        self.assertAlmostEqual(result.q_mean_kgkg, sum(q)/24, places=14)
        self.assertAlmostEqual(result.RH_mean_pct, sum(RH)/24, places=10)
        self.assertEqual(result.tas_K, 274.)
        self.assertNotEqual(result.tas_K, float(np.mean(T)))
        self.assertIn('NOT_NATIVE_NEX', result.source_kind)
        self.assertFalse(result.fully_verified)

    def test_nonphysical_reference_is_blocked_instead_of_clipped(self):
        _, pressure, _ = fixture()
        with self.assertRaisesRegex(ValueError, 'NONPHYSICAL_REFERENCE_NO_CLIPPING'):
            reference_constraints(pressure.target_date, [280.]*24, [281.]*24, pressure, 'c'*64)

    def test_donor_selection_frozen_before_method_feasibility(self):
        target, _, first = fixture()
        second = replace(first, date='2020-02-28', T_K=tuple(t+1 for t in first.T_K),
                         pressure=replace(first.pressure, reference_date='2020-02-28'))
        selected = choose_common_prior(target, [second, first], False)
        self.assertEqual(selected, _choose([(first, None), (second, None)], target.legacy_target(), None, 7313)[0])
        self.assertEqual(selected, choose_common_prior(target, [first, second], False))
        with self.assertRaisesRegex(ValueError, 'SHARED_TARGET_BLOCKED'):
            choose_common_prior(target, [first], True)
        with self.assertRaisesRegex(ValueError, 'UNREGISTERED_DONOR_WINDOW'):
            choose_common_prior(target, [replace(first, date='2022-02-15')], False)

    def test_strict_witness_is_preserved_without_extra_starts(self):
        target, pressure, donor = fixture()
        with patch('p9_3b3_iv1_methods.run_starts', side_effect=AssertionError('NO_SOFT_OPTIMIZATION_FOR_STRICT_WITNESS')):
            case = compare_five('AT', target, pressure, donor)
        self.assertEqual([r['IV1_method'] for r in case['results']], list(METHODS))
        self.assertEqual(len({r['common_prior_sha256'] for r in case['results']}), 1)
        for row in case['results'][2:]:
            self.assertEqual(row['T_K'], case['results'][0]['T_K'])
            self.assertEqual(row['q_kgkg'], case['results'][0]['q_kgkg'])
            self.assertEqual(row['p_Pa'], list(pressure.values_Pa))
        self.assertEqual(replay_case(case), {'state_count': 5, 'failure_count': 0, 'shared_blocked': False})

    def test_twelve_starts_solve_original_soft_objective_and_are_replayable(self):
        target, pressure, donor = fixture(soft=True)
        case = compare_five('AT', target, pressure, donor)
        trials = case['scaled_12_diagnostics']['trials']
        self.assertEqual(len(trials), 12)
        self.assertEqual(trials[3]['T_segment_fraction'], .9)
        best = case['results'][-1]
        finite = [r for r in trials if r.get('physical_admissibility') == 'VALIDATED']
        self.assertEqual(best['objective']['total'], min(r['F_original'] for r in finite))
        self.assertLessEqual(best['objective']['total'], case['results'][3]['objective']['total']+1e-8)
        self.assertFalse(best['global_optimum_certified'])
        self.assertEqual(replay_case(case)['state_count'], 4)

    def test_pressure_date_and_country_errors_cannot_enter_solver(self):
        target, pressure, donor = fixture()
        with self.assertRaises(ValueError):
            replace(pressure, source_date='2021-02-15')
        with self.assertRaisesRegex(ValueError, 'COUNTRY_OR_PRESSURE'):
            compare_five('FR', target, pressure, donor)
        self.assertTrue(pressure.comparison_reference().source.startswith('IV1_NATIVE_THERMO'))
        self.assertNotIn('NV2', pressure.comparison_reference().source)

    def test_observed_or_wrong_date_donor_is_rejected_before_any_solver(self):
        target, pressure, donor = fixture()
        for reference in (replace(donor.pressure, mode='OBSERVED_SITE_VALIDATION_ONLY'),
                          replace(donor.pressure, reference_date='2022-02-15')):
            wrong = replace(donor, pressure=reference)
            with patch('p9_3b3_iv1_methods.strict_joint', side_effect=AssertionError('MUST_NOT_RUN')):
                with self.assertRaisesRegex(ValueError, 'OBSERVATIONS_FORBIDDEN'):
                    compare_five('AT', target, pressure, wrong)
                with self.assertRaisesRegex(ValueError, 'OBSERVATIONS_FORBIDDEN'):
                    choose_common_prior(target, [wrong], False)


class ComponentSeal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = compare_five('AT', *fixture())

    def test_actual_physics_is_checked_instead_of_success_flags(self):
        case = deepcopy(self.case)
        case['results'][0]['q_kgkg'][0] = .09
        case['results'][0]['validation'] = {'physical_admissibility': 'PASS'}
        with self.assertRaises(ValueError):
            replay_case(case)

    def test_original_objective_and_correction_ledger_are_checked(self):
        for change in ('objective', 'journal'):
            case = deepcopy(self.case)
            row = case['results'][-1]
            if change == 'objective': row['objective']['total'] += 1.
            else: row['journal_all_diagnostics'][0]['signed_delta'] += 1.
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'OBJECTIVE_CHANGED|LEDGER_CHANGED'):
                replay_case(case)

    def test_420_explicit_failures_are_retained_without_qualification(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'new'
            report = seal_components(out, blocked_cohort())
            self.assertEqual(report['cases'], 84)
            self.assertEqual(report['explicit_failures_retained'], 420)
            self.assertEqual(report['physical_states_replayed'], 0)
            self.assertFalse(report['ready_to_open_observations'])
            self.assertEqual(verify_components(out), report)
            with self.assertRaises(FileExistsError): seal_components(out, blocked_cohort())

    def test_incomplete_or_duplicate_cohort_is_rejected(self):
        cases = blocked_cohort()
        for changed in (cases[:-1], cases[:-1]+[cases[0]]):
            with self.assertRaisesRegex(ValueError, 'FULL_84_CASE_CENSUS'):
                census(changed, guard())

    def test_tampering_with_sealed_results_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'new'
            seal_components(out, blocked_cohort())
            p = out/'method_components.json'
            p.write_bytes(p.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'SEAL_MEMBER_CHANGED'):
                verify_components(out)

    def test_rehashed_nonphysical_state_still_fails_independent_replay(self):
        cases = blocked_cohort()
        cases[0] = deepcopy(self.case)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'new'
            seal_components(out, cases)
            cases[0]['results'][0]['q_kgkg'][0] = .09
            member = out/'method_components.json'
            member.write_text(json.dumps(cases))
            path = out/'component_prediction_seal.json'
            seal = json.loads(path.read_text())
            seal['members_sha256'][member.name] = hashlib.sha256(member.read_bytes()).hexdigest()
            path.write_text(json.dumps(seal))
            with self.assertRaisesRegex(ValueError, 'SUPERSATURATION'):
                verify_components(out)

    def test_nonfinite_ledger_cannot_pass_by_nan_comparison(self):
        case = deepcopy(self.case)
        case['results'][-1]['journal_all_diagnostics'][0]['signed_delta'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'NONFINITE_CORRECTION_LEDGER'):
            replay_case(case)

    def test_full_artificial_cohort_roundtrips_through_json_and_physics(self):
        cases = []
        base_target, base_pressure, base_donor = fixture()
        for row in cohort(guard()):
            date = row['date']
            target = replace(base_target, date=date)
            pressure = replace(base_pressure, source_date=date, target_date=date,
                timestamps_UTC=[date+f'T{h:02d}:00' for h in range(24)])
            donor = replace(base_donor, date='2019-'+date[5:],
                pressure=replace(base_donor.pressure, reference_date='2019-'+date[5:]))
            cases.append(compare_five(row['country'], target, pressure, donor))
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'new'
            report = seal_components(out, cases)
            self.assertEqual(report['physical_states_replayed'], 420)
            self.assertEqual(report['explicit_failures_retained'], 0)
            self.assertEqual(verify_components(out), report)
            self.assertFalse(report['ready_to_open_observations'])


if __name__ == '__main__':
    unittest.main()
