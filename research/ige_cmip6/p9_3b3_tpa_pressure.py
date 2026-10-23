"""Sealed NV2 pressure at each thermohygrometer, with no observation access."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import zipfile

from p9_3b3_compare_vertical_frame import SourceBlocked, fingerprint
from p9_3b3_tpa_contracts import PressureTrajectory


NV2_ZIP_SHA = 'dd4bb285c22cc081deba891c33ec2aafff549e53028103cfd09c2736ca0727ea'


def load_sealed_nv2(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != NV2_ZIP_SHA:
        raise ValueError('TPA_NV2_ARCHIVE_CHANGED')
    with zipfile.ZipFile(path) as archive:
        seal = json.loads(archive.read('prediction_seal.json'))
        if seal['station_pressure_products_opened'] is not False:
            raise ValueError('TPA_PREDICTIONS_NOT_SOURCE_ONLY')
        models = {}
        for name, digest in seal['source_products_sha256'].items():
            if name not in ('historical_sensor_references.json', 'native_source_lineage.json',
                            'source_geometry_and_fixed_donors.json', 'sealed_pressure_predictions.json',
                            'native_primary_profiles.json', 'deep_column_sensitivity.json'):
                raise ValueError('TPA_OBSERVATION_OR_UNKNOWN_PRODUCT_NOT_ALLOWED')
            body = archive.read(name)
            if hashlib.sha256(body).hexdigest() != digest:
                raise ValueError('TPA_SOURCE_MODEL_SEAL_CHANGED')
            models[name] = json.loads(body)
    if len(models) != 6:
        raise ValueError('TPA_SIX_SEALED_SOURCE_PRODUCTS_REQUIRED')
    return models


def pressure_at_thermo(models, country, day, variant, slot, *, target_date=None):
    if country not in ('AT', 'DE', 'CH') or variant not in ('P1_ISOTHERMAL', 'P1_LAPSE_0065', 'P2_NATIVE'):
        raise ValueError('TPA_UNREGISTERED_COUNTRY_OR_METHOD')
    h = models['historical_sensor_references.json'][country]
    temperature, humidity = h['sensors']['temperature'], h['sensors']['RH_water']
    geometry = ('latitude', 'longitude', 'height_MSL_m')
    if any(abs(temperature[k]-humidity[k]) > 1e-9 for k in geometry):
        raise SourceBlocked('TPA_T_AND_RH_NOT_COLOCATED_ADAPTER_NOT_ESTABLISHED')
    instant = dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc)
    for sensor in (temperature, humidity):
        period = sensor.get('deployment_period', ())
        if (sensor.get('historical_height_reference_confirmed') is not True or len(period) != 2
                or not period[0] or instant < dt.datetime.fromisoformat(period[0].replace('Z', '+00:00'))
                or period[1] and instant+dt.timedelta(hours=23) >= dt.datetime.fromisoformat(period[1].replace('Z', '+00:00'))):
            raise SourceBlocked('TPA_SOURCE_DAY_OUTSIDE_CONFIRMED_SENSOR_EPOCH')
    p, t, q, anchors, margins = [], [], [], [], []
    method = variant+'_'+slot
    for hour in range(24):
        stamp = day+'T'+str(hour).zfill(2)+':00'
        roles = models['sealed_pressure_predictions.json']['hourly'][stamp][country]['roles']
        a, b = roles['temperature'], roles['RH_water']
        if any(not role['admissions'][slot]['admitted'] for role in (a, b)):
            raise SourceBlocked('TPA_FIXED_DONOR_NOT_IN_THERMO_AIR_DOMAIN_NO_SUBSTITUTION')
        value, rh_value = a['methods'][method], b['methods'][method]
        if 'pressure_Pa' not in value or value != rh_value:
            # Different targets include their evidence string, so compare the
            # actual numerical state/anchor rather than unrelated WMO codes.
            keys = ('pressure_Pa', 'target_layer_T_K', 'target_layer_q_kgkg',
                    'anchor_phi_m2s2', 'anchor_log_pressure', 'source_column_fingerprint')
            if any(value.get(k) != rh_value.get(k) for k in keys) or 'pressure_Pa' not in value:
                raise SourceBlocked('TPA_T_RH_STATE_OR_ANCHOR_MISMATCH')
        if value.get('gas_formulation') != 'B3_GAS_CONSISTENT':
            raise SourceBlocked('TPA_GAS_FORMULATION_MISMATCH')
        if value['target']['role'] != 'THERMO_SENSOR' or abs(value['target']['value']-temperature['height_MSL_m']) > 1e-9:
            raise SourceBlocked('TPA_BAROMETER_OR_OTHER_HEIGHT_NOT_THERMO_REFERENCE')
        p.append(value['pressure_Pa'])
        t.append(value['target_layer_T_K'])
        q.append(value['target_layer_q_kgkg'])
        anchors.append({k: value[k] for k in ('anchor_phi_m2s2', 'anchor_log_pressure', 'source_column_fingerprint')})
        margins.append(a['admissions'][slot]['target_minus_surface_m'])
    target_date = day if target_date is None else target_date
    provenance = {'country': country, 'NV2_run_id': 39925504607, 'role': 'THERMO_SENSOR',
        'T_sensor_reference': temperature, 'RH_sensor_reference': humidity,
        'anchors_by_hour': anchors, 'minimum_target_minus_surface_m': min(margins),
        'buffer_2m_pass': min(margins) >= 2, 'source_predictor_sha256': fingerprint(models['sealed_pressure_predictions.json'])}
    return PressureTrajectory(target_date, day, tuple(day+'T'+str(h).zfill(2)+':00' for h in range(24)),
        tuple(p), tuple(t), tuple(q), temperature['latitude'], temperature['longitude'], temperature['height_MSL_m'],
        'THERMO_SENSOR', variant, slot, NV2_ZIP_SHA, json.dumps(provenance, sort_keys=True, allow_nan=False),
        'TARGET_DAY_EXTERNAL_FIXED' if target_date == day else 'DONOR_DATE_SENSITIVITY')
