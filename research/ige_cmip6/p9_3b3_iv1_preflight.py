"""IV1 registered cohort and source-only admission; never opens station values.

This command deliberately cannot score observations or assert that a missing
2022 native pressure bundle is available. A completed metadata audit remains
distinct from admission of all time operators and sealed predictions.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import lzma
from pathlib import Path

from p9_3b3_cd1_run import write_new
from p9_3b3_compare_vertical_frame import fingerprint


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name('p9_3b3_iv1_protocol.json')
PROTOCOL_SHA = '9480a1a4b75196ba8f88627c437ff32c79ea5838056de15e9df11ce2a016b7d0'


def observation_field_guard(fields):
    if fields['DE']['p'] != 'P0_ST_10' or fields['DE']['forbidden_reduced_pressure'] != 'PP_ST_10':
        raise ValueError('IV1_ABSOLUTE_DWD_PRESSURE_REQUIRED')
    if [fields['CH'][k] for k in ('T', 'RH', 'p')] != ['tre200s0', 'ure200s0', 'prestas0']:
        raise ValueError('IV1_CURRENT_CH_VALUES_REQUIRED_NO_HOURLY_MEAN_SUBSTITUTION')


def guard():
    p = json.loads(PROTOCOL.read_text())
    if fingerprint(p) != PROTOCOL_SHA:
        raise ValueError('IV1_REGISTERED_PROTOCOL_CHANGED')
    for path, expected in p['protected_control_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != expected:
            raise ValueError('IV1_PROTECTED_CONTROL_CHANGED_'+path)
    observation_field_guard(p['observation_fields'])
    return p


def cohort(p):
    rows = []
    for country in p['countries']:
        for season, (start, end) in enumerate(p['windows_UTC']):
            a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            for offset in range((b-a).days+1):
                date = (a+dt.timedelta(days=offset)).isoformat()
                if int(date[:4]) in p['donor_design']['years']:
                    raise ValueError('IV1_DONOR_TARGET_YEAR_LEAKAGE')
                rows.append({'country': country, 'station_id': p['stations'][country]['id'],
                    'season_index': season, 'date': date,
                    'hours_UTC': [date+f'T{h:02d}:00' for h in range(24)]})
    if len(rows) != p['expected_target_days'] or sum(len(r['hours_UTC']) for r in rows) != p['expected_site_hours_before_QC']:
        raise ValueError('IV1_COHORT_CENSUS')
    return rows


def load_metadata(p):
    archive = ROOT/p['source_metadata_archive']['path']
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != p['source_metadata_archive']['sha256']:
        raise ValueError('IV1_METADATA_ARCHIVE_CHANGED')
    wrapper = json.loads(lzma.decompress(raw))
    if wrapper['station_values_opened']:
        raise ValueError('IV1_METADATA_SNAPSHOT_HAS_OPENED_OBSERVATIONS')
    bodies = {}
    for name, member in wrapper['members'].items():
        body = base64.b64decode(member['base64'], validate=True)
        if hashlib.sha256(body).hexdigest() != member['sha256']:
            raise ValueError('IV1_METADATA_MEMBER_CHANGED_'+name)
        bodies[name] = body
    return bodies


def preflight():
    p = guard()
    rows = cohort(p)
    bodies = load_metadata(p)
    sensors = json.loads(bodies['dated_2022_sensor_admission.json'])
    AT = json.loads(bodies['AT_metadata.json'])
    station = next(s for s in AT['stations'] if s['id'] == 16412)
    if station['type'] != 'INDIVIDUAL' or station['group_id'] != 30:
        raise ValueError('IV1_AT_HISTORICAL_IDENTITY_CHANGED')
    for country in p['countries']:
        if sensors[country]['status'] != 'DATED_2022_SENSORS_CONFIRMED':
            raise ValueError('IV1_DATED_SENSORS_NOT_ADMITTED_'+country)
        for sensor in sensors[country]['sensors'].values():
            if not sensor['historical_height_reference_confirmed']:
                raise ValueError('IV1_UNCONFIRMED_HEIGHT')
        if hashlib.sha256(bodies[country+'_WMDR.xml']).hexdigest() != sensors[country]['sha256']:
            raise ValueError('IV1_SENSOR_EVIDENCE_CHANGED')
    # Latin-1 is a byte-preserving metadata decode, not a lossy UTF-8 fallback.
    parameters = {r['parameter_shortname']: r for r in csv.DictReader(
        io.StringIO(bodies['CH_parameters.csv'].decode('latin-1')), delimiter=';')}
    for key in ('tre200s0', 'ure200s0', 'prestas0'):
        if parameters[key]['parameter_granularity'] != 'T' or 'current value' not in parameters[key]['parameter_description_en']:
            raise ValueError('IV1_CH_TIME_OPERATOR_DRIFT')
    stac = json.loads(bodies['CH_DAV_STAC.json'])
    asset = stac['assets']['ogd-smn_dav_t_historical_2020-2029.csv']
    if asset['href'] != p['CH_source_url'] or asset['file:checksum'] != p['CH_STAC_multihash_before_values_opened']:
        raise ValueError('IV1_REGISTERED_CH_ASSET_CHANGED_BEFORE_SCORING')
    ci = json.loads((ROOT/'research/ige_cmip6/p9_3b3_cd3_verified_CI_40009910484.json').read_text())
    if ci['conclusion'] != 'SUCCESS' or not ci['derivative_check_closed']:
        raise ValueError('IV1_CD3_NUMERICAL_GATE_NOT_PASSED')
    blockers = [
        {'scope': 'AT_TIME_SUPPORT', 'status': 'SOURCE_BLOCKED',
         'reason': 'PARAMETERS_SAY_STUNDEN_MESSWERT; WMDR_TIMESTAMP_MEANING_EMPTY; DO_NOT_INFER_INSTANT_OR_HOURLY_MEAN'},
        {'scope': 'DE_URBAN_T_RH_TIME_SUPPORT', 'status': 'SOURCE_BLOCKED',
         'reason': 'REQUIRE_NATIVE_URBAN_PARAMETER_METADATA; GENERIC_TT_10_INSTANT_IS_NOT_A_PROOF_FOR_ALL_URBAN_FIELDS'},
        {'scope': 'ALL_COUNTRIES_2022_NATIVE_PRESSURE_AND_PREDICTION_SEAL', 'status': 'NOT_PREPARED',
         'reason': 'ONLY_2021_SOURCE_PROFILES_ARCHIVED; 2022_PHI_S_LNSP_T_Q_AND_ALL_METHOD_PREDICTIONS_NOT_SEALED'}]
    return {'stage': 'IV1_SOURCE_ONLY_PREFLIGHT_NOT_STATION_SCORING', 'protocol_sha256': PROTOCOL_SHA,
        'registered_cohort': rows, 'target_days': len(rows), 'site_hours_before_QC': 2016,
        'dated_sensor_countries_confirmed': 3,
        'instrument_heights_MSL_m': {co: {k: s['height_MSL_m'] for k, s in v['sensors'].items()}
                                    for co, v in sensors.items()},
        'CH_exact_current_fields_and_asset_confirmed': True,
        'CD3_derivative_gate': 'PASS', 'protected_files_unchanged': len(p['protected_control_sha256']),
        'source_blockers': blockers, 'station_values_opened': False, 'station_scores_computed': False,
        'ready_to_open_observations': False, 'independent_accuracy': 'NOT_RUN',
        'operational_ready': False, 'production_epw_ready': False, 'main_merged': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    r = preflight()
    write_new(parser.parse_args().out, r)
    print(json.dumps({k: v for k, v in r.items() if k != 'registered_cohort'}))
