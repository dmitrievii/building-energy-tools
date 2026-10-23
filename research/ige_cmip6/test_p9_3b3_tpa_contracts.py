"""TPA pressure/operator contracts and source-only admission boundaries."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_thermodynamics import saturation, q_from_e
from p9_3b3_tpa_contracts import DailyClimateConstraints, PressureTrajectory, UNIFORM
from p9_3b3_tpa_pressure import load_sealed_nv2, pressure_at_thermo
from p9_3b3_tpa_run import load_protocol, protected_controls, audit_semantics, ROOT, SEMANTICS_SHA


def example_pressure(T=None, P=None, q=None):
    T = np.asarray(np.linspace(270, 280, 24) if T is None else T, float)
    P = np.asarray([95000.]*24 if P is None else P, float)
    q = q_from_e(.6*saturation(T, 'WATER_ICE'), P, 287.05/461.5) if q is None else q
    day = '2021-02-01'
    return PressureTrajectory(day, day, tuple(day+'T'+str(h).zfill(2)+':00' for h in range(24)),
        tuple(P), tuple(T), tuple(q), 47.0777777778, 15.4488888889, 368.7,
        'THERMO_SENSOR', 'P2_NATIVE', 'D2', 'a'*64, '{"fixture":true}')


def example_target(pressure=None, **kwargs):
    p = pressure or example_pressure()
    values = dict(date=p.target_date, Tmin_K=min(p.prior_T_K), Tmax_K=max(p.prior_T_K),
        tas_K=(min(p.prior_T_K)+max(p.prior_T_K))/2, q_mean_kgkg=float(np.mean(p.prior_q_kgkg)),
        RH_mean_pct=60., source_kind='SYNTHETIC_OPERATOR_CONTROL', source_sha256='b'*64,
        semantics_sha256=SEMANTICS_SHA, source_identity='REGISTERED_SYNTHETIC_FIXTURE')
    return DailyClimateConstraints(**(values | kwargs))


def example_models():
    """No station weather truth: only the sealed model-side product schema."""
    models = {name: {} for name in ('historical_sensor_references.json', 'native_source_lineage.json',
        'source_geometry_and_fixed_donors.json', 'sealed_pressure_predictions.json',
        'native_primary_profiles.json', 'deep_column_sensitivity.json')}
    hourly = models['sealed_pressure_predictions.json']['hourly'] = {}
    for country, height, margin in (('AT', 368.7, 28.835917), ('DE', 37.8, .5059419), ('CH', 1593.93, 387.1)):
        sensor = {'height_MSL_m': height, 'latitude': 47., 'longitude': 15., 'role': 'THERMO_SENSOR',
            'deployment_period': ['2000-01-01T00:00:00Z', '2030-01-01T00:00:00Z'],
            'historical_height_reference_confirmed': True}
        models['historical_sensor_references.json'][country] = {'sensors': {
            'temperature': deepcopy(sensor), 'RH_water': deepcopy(sensor)}}
        for day in ('2021-02-01', '2021-08-01'):
            for hour in range(24):
                stamp = day+'T'+str(hour).zfill(2)+':00'
                t = (270 if '-02-' in day else 290)+3*np.sin(hour*np.pi/12)
                state = {'pressure_Pa': 95000.+hour, 'target_layer_T_K': float(t), 'target_layer_q_kgkg': .002,
                    'anchor_phi_m2s2': 3000., 'anchor_log_pressure': 11.46,
                    'source_column_fingerprint': 'c'*64, 'gas_formulation': 'B3_GAS_CONSISTENT',
                    'target': {'role': 'THERMO_SENSOR', 'value': height}}
                role = {'admissions': {s: {'admitted': country != 'AT' or s == 'D2',
                    'target_minus_surface_m': margin if s == 'D2' or country != 'AT' else -3.8593} for s in ('D1', 'D2')},
                    'methods': {v+'_'+s: dict(state) for s in ('D1', 'D2')
                                for v in ('P1_ISOTHERMAL', 'P1_LAPSE_0065', 'P2_NATIVE')}}
                hourly.setdefault(stamp, {})[country] = {'roles': {'temperature': deepcopy(role), 'RH_water': deepcopy(role)}}
    return models


class ImmutableContracts(unittest.TestCase):
    def test_SI_calendar_units_and_hashes_fail_closed(self):
        p = example_pressure()
        for update in ({'values_Pa': (950.,)*24}, {'prior_T_K': (12.,)*24}, {'prior_q_kgkg': (-.01,)*24},
                       {'source_archive_sha256': 'z'*64}, {'role': 'BAROMETER'}, {'usage': 'OBSERVED_VALIDATION_ONLY'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                replace(p, **update)
        for update in ({'date': '2012-02-29'}, {'q_mean_kgkg': 5.}, {'RH_mean_pct': 106.},
                       {'tas_K': 273.}, {'source_sha256': 'x'*64}, {'fully_verified': True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                replace(example_target(p), **update)

    def test_weights_nonuniform_zero_support_and_immutability(self):
        u = [0.]+[1/23]*23
        t = example_target(q_weights=u)
        u[0] = .5
        self.assertEqual(t.q_weights[0], 0.)
        self.assertIsInstance(t.q_weights, tuple)
        for weights in ([1/24]*23, [-1.]+[2/23]*23, [0.]*24, [float('nan')]*24):
            with self.assertRaises(ValueError):
                replace(t, RH_weights=weights)

    def test_ordered_UTC_nodes_and_explicit_source_date(self):
        p = example_pressure()
        with self.assertRaisesRegex(ValueError, 'ORDERED_SOURCE_UTC'):
            replace(p, timestamps_UTC=tuple(reversed(p.timestamps_UTC)))
        with self.assertRaisesRegex(ValueError, 'DAY_MISMATCH'):
            replace(p, target_date='2013-01-08')
        sensitivity = replace(p, target_date='2013-01-08', alignment='DONOR_DATE_SENSITIVITY')
        self.assertEqual(sensitivity.comparison_reference().reference_date, '2021-02-01')
        with self.assertRaisesRegex(ValueError, 'NOT_TARGET_DAY_GENERATOR'):
            sensitivity.generation_reference()
        self.assertEqual(p.generation_reference().reference_date, p.target_date)

    def test_frozen_protocol_and_109_scientific_controls(self):
        protocol = load_protocol()
        self.assertEqual(len(protected_controls(protocol)), 109)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'protocol.json'
            protocol['C2_metric']['RH_scale_pp'] = 4.9
            path.write_text(json.dumps(protocol))
            with self.assertRaisesRegex(ValueError, 'PROTOCOL_CHANGED'):
                load_protocol(path)

    def test_native_headers_retain_conflict_missing_bounds_and_phase(self):
        audit = audit_semantics(ROOT/load_protocol()['source_semantics_file'])
        self.assertEqual(audit['raw_response_count'], 30)
        self.assertFalse(audit['fully_verified'])
        self.assertFalse(audit['daily_bounds_verified'])
        self.assertEqual(audit['rh_phase'], 'WATER_ICE')
        self.assertEqual(audit['temperature_operator'], 'DERIVED_TAS_MIDRANGE')
        self.assertTrue(all(not h['time_support']['interval_semantics_verified'] for h in audit['headers']))
        tas = [h for h in audit['headers'] if h['variable'] == 'tas']
        self.assertTrue(all('time: maximum' in h['native_attributes']['cell_methods'] for h in tas))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'snapshot.json'
            source = json.loads((ROOT/load_protocol()['source_semantics_file']).read_bytes())
            source['fully_verified'] = True
            path.write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, 'SNAPSHOT_CHANGED'):
                audit_semantics(path)


class ThermoPressureAdmission(unittest.TestCase):
    def test_AT_D1_blocked_D2_thermo_height(self):
        m = example_models()
        with self.assertRaisesRegex(SourceBlocked, 'NOT_IN_THERMO_AIR_DOMAIN'):
            pressure_at_thermo(m, 'AT', '2021-02-01', 'P2_NATIVE', 'D1')
        p = pressure_at_thermo(m, 'AT', '2021-02-01', 'P2_NATIVE', 'D2')
        self.assertEqual(p.height_MSL_m, 368.7)
        self.assertNotEqual(p.height_MSL_m, 378.8)
        self.assertEqual(p.role, 'THERMO_SENSOR')

    def test_Berlin_nominal_admission_is_not_two_meter_qualification(self):
        p = pressure_at_thermo(example_models(), 'DE', '2021-02-01', 'P1_ISOTHERMAL', 'D1')
        provenance = json.loads(p.provenance_json)
        self.assertAlmostEqual(provenance['minimum_target_minus_surface_m'], .5059419)
        self.assertFalse(provenance['buffer_2m_pass'])
        self.assertEqual(p.height_MSL_m, 37.8)
        self.assertFalse(p.metadata()['station_2m_observation_operator_qualified'])

    def test_mismatched_T_RH_height_or_location_blocked(self):
        for field in ('height_MSL_m', 'latitude', 'longitude'):
            m = example_models()
            m['historical_sensor_references.json']['AT']['sensors']['RH_water'][field] += .01
            with self.subTest(field=field), self.assertRaisesRegex(SourceBlocked, 'NOT_COLOCATED'):
                pressure_at_thermo(m, 'AT', '2021-02-01', 'P2_NATIVE', 'D2')

    def test_historical_epoch_required_for_actual_source_day(self):
        m = example_models()
        m['historical_sensor_references.json']['AT']['sensors']['temperature']['deployment_period'][0] = '2022-01-01T00:00:00Z'
        with self.assertRaisesRegex(SourceBlocked, 'SENSOR_EPOCH'):
            pressure_at_thermo(m, 'AT', '2021-02-01', 'P2_NATIVE', 'D2')

    def test_wrong_role_or_mismatched_anchor_blocked(self):
        for fault in ('target', 'anchor_log_pressure'):
            m = example_models()
            x = m['sealed_pressure_predictions.json']['hourly']['2021-02-01T00:00']['AT']['roles']['temperature']['methods']['P2_NATIVE_D2']
            x[fault] = {'role': 'BAROMETER', 'value': 378.8} if fault == 'target' else 10.
            with self.subTest(fault=fault), self.assertRaises(SourceBlocked):
                pressure_at_thermo(m, 'AT', '2021-02-01', 'P2_NATIVE', 'D2')

    def test_sealed_loader_never_opens_observation_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'sealed.zip'
            models = example_models()
            bodies = {k: json.dumps(v).encode() for k, v in models.items()}
            seal = {'station_pressure_products_opened': False,
                'source_products_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in bodies.items()}}
            with zipfile.ZipFile(path, 'w') as z:
                for k, v in bodies.items():
                    z.writestr(k, v)
                z.writestr('prediction_seal.json', json.dumps(seal))
                z.writestr('revealed_pressure_scores_NV2.json', b'NOT JSON: must never be read')
                z.writestr('G0_regression_pressure_scores.json', b'NO OBSERVATIONS IN THIS TASK')
            with patch('p9_3b3_tpa_pressure.NV2_ZIP_SHA', hashlib.sha256(path.read_bytes()).hexdigest()):
                self.assertEqual(set(load_sealed_nv2(path)), set(models))
            path.write_bytes(path.read_bytes()+b'x')
            with self.assertRaisesRegex(ValueError, 'ARCHIVE_CHANGED'):
                load_sealed_nv2(path)


if __name__ == '__main__':
    unittest.main()
