"""Executable IV1 parameter admission and source plan; no observations.

Admission is computed from pinned original parameter records. A reporting
frequency alone is not an averaging operator. This command cannot unblind
observations or run the expensive native source collection.
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
from p9_3b3_iv1_preflight import ROOT, PROTOCOL_SHA, cohort, guard, load_metadata
from p9_3b3_native_heights import sensor_records


SNAPSHOT = Path(__file__).with_name('p9_3b3_iv1_time_metadata_20261024.json.xz')
SNAPSHOT_SHA = 'e93d604500aa698e64554f8485d2e19c6d162c2460ca3beee5afa39d7c3f3af6'
ADDENDUM = Path(__file__).with_name('p9_3b3_iv1_start_contract_addendum_20261024.json')
ADDENDUM_SHA = '41bb2b61c7cdccbc1b7b4c88434cc635e36d5effa1a157eccc3297459983cc28'


def load_time_metadata():
    raw = SNAPSHOT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_SHA:
        raise ValueError('IV1_PARAMETER_TIME_SNAPSHOT_CHANGED_NEW_EVIDENCE_VERSION_REQUIRED')
    wrapper = json.loads(lzma.decompress(raw))
    if wrapper['station_values_opened'] is not False or wrapper['station_product_members_requested'] is not False:
        raise ValueError('IV1_TIME_SNAPSHOT_CONTAINS_OPENED_OBSERVATIONS')
    bodies = {}
    for name, item in wrapper['members'].items():
        body = base64.b64decode(item['base64'], validate=True)
        if len(body) != item['bytes'] or hashlib.sha256(body).hexdigest() != item['sha256']:
            raise ValueError('IV1_PARAMETER_TIME_MEMBER_CHANGED')
        bodies[name] = body
    return wrapper, bodies


def dwd_parameter(raw, field, dates):
    rows = list(csv.DictReader(io.StringIO(raw.decode('latin-1')), delimiter=';'))
    rows = [r for r in rows if r.get('Parameter') == field]
    selected = []
    for date in dates:
        day = date.replace('-', '')
        matches = [r for r in rows if r['Stations_ID'] in ('399', '00399')
                   and r['Von_Datum'] <= day <= r['Bis_Datum']]
        if len(matches) != 1:
            raise ValueError('IV1_DWD_PARAMETER_EPOCH_NOT_UNIQUE_'+field)
        selected.append(matches[0])
    if not selected or any(r != selected[0] for r in selected):
        raise ValueError('IV1_DWD_PARAMETER_EPOCH_DRIFT_'+field)
    row = selected[0]
    if 'momentan' not in row['Parameterbeschreibung'].lower() or row['Zusatz-Info'].strip() != 'in UTC':
        raise ValueError('IV1_DWD_PARAMETER_NOT_EXPLICIT_INSTANT_UTC_'+field)
    if field == 'P0_ST_10' and 'stationshoehe' not in row['Parameterbeschreibung'].lower():
        raise ValueError('IV1_DWD_ABSOLUTE_STATION_PRESSURE_NOT_CONFIRMED')
    expected_units = {'TT_ST_10': '°C', 'RF_ST_10': '%', 'P0_ST_10': 'hpa'}
    if row['Einheit'] != expected_units[field]:
        raise ValueError('IV1_DWD_PARAMETER_UNIT_'+field)
    return {'field': field, 'status': 'ADMITTED', 'operator': 'CURRENT_VALUE_AT_EXACT_UTC_NODE',
        'original_parameter_record': row, 'evidence': 'OWN_URBAN_PARAMETER_METADATA_NOT_GENERIC_CLIMATE_DESCRIPTION',
        'instrument_filter_period_certified': False}


def time_admission(protocol):
    wrapper, bodies = load_time_metadata()
    dates = [r['date'] for r in cohort(protocol) if r['country'] == 'DE']
    DE = {k: dwd_parameter(bodies['DE_urban_T_RH_parameters.txt' if k in ('T', 'RH')
                               else 'DE_urban_pressure_parameters.txt'], field, dates)
          for k, field in (('T', 'TT_ST_10'), ('RH', 'RF_ST_10'), ('p', 'P0_ST_10'))}
    parameters = {p['name']: p for p in json.loads(bodies['AT_hourly_metadata.json'])['parameters']}
    AT = {k: {'field': field, 'status': 'SOURCE_BLOCKED', 'operator': None,
        'original_parameter_record': parameters[field],
        'reason': 'STUNDEN_MESSWERT_DOES_NOT_EXPLICITLY_IDENTIFY_NODE_OR_AVERAGING_INTERVAL'}
        for k, field in (('T', 'tl'), ('RH', 'rf'), ('p', 'p'))}
    # Replay the original current-value metadata, not the old preflight flags.
    old = load_metadata(protocol)
    CH_parameters = {r['parameter_shortname']: r for r in csv.DictReader(
        io.StringIO(old['CH_parameters.csv'].decode('latin-1')), delimiter=';')}
    CH = {}
    for key, field in (('T', 'tre200s0'), ('RH', 'ure200s0'), ('p', 'prestas0')):
        row = CH_parameters[field]
        if row['parameter_granularity'] != 'T' or 'current value' not in row['parameter_description_en']:
            raise ValueError('IV1_CH_CURRENT_VALUE_METADATA_CHANGED')
        CH[key] = {'field': field, 'status': 'ADMITTED', 'operator': 'CURRENT_VALUE_AT_EXACT_UTC_NODE',
                   'original_parameter_record': row, 'instrument_filter_period_certified': False}
    proofs = [json.loads(bodies[n]) for n in ('DE_urban_T_RH_range_proof.json', 'DE_urban_pressure_range_proof.json')]
    for proof, member in zip(proofs, ('DE_urban_T_RH_parameters.txt', 'DE_urban_pressure_parameters.txt')):
        if (proof['member_sha256'] != hashlib.sha256(bodies[member]).hexdigest()
                or proof['whole_zip_downloaded'] is not False
                or proof['station_product_members_requested'] is not False
                or proof['station_product_members_decompressed'] is not False):
            raise ValueError('IV1_DWD_METADATA_RANGE_PROOF')
    countries = {'AT': AT, 'DE': DE, 'CH': CH}
    return {'snapshot_sha256': SNAPSHOT_SHA, 'countries': countries,
        'admitted_fields': sum(r['status'] == 'ADMITTED' for country in countries.values() for r in country.values()),
        'required_fields': 9, 'all_parameter_time_operators_admitted': all(
            r['status'] == 'ADMITTED' for country in countries.values() for r in country.values()),
        'DWD_metadata_range_requests': sum(len(p['requests']) for p in proofs),
        'DWD_metadata_range_bytes': sum(r['bytes'] for p in proofs for r in p['requests']),
        'DWD_station_products_opened': False,
        'source_urls': wrapper['source_urls']}


def dated_sensors(protocol):
    old = load_metadata(protocol)
    expected = json.loads(old['dated_2022_sensor_admission.json'])
    rows = cohort(protocol)
    parsed = {}
    for country in protocol['countries']:
        stamps = [h for r in rows if r['country'] == country for h in r['hours_UTC']]
        parsed[country] = {key: sensor_records(old[country+'_WMDR.xml'], protocol['stations'][country]['WSI'],
            code, stamps, role) for key, code, role in (
                ('pressure', 216, 'BAROMETER'), ('temperature', 224, 'THERMO_SENSOR'), ('RH_water', 12249, 'THERMO_SENSOR'))}
        if parsed[country] != expected[country]['sensors']:
            raise ValueError('IV1_RAW_DATED_SENSOR_REPLAY_MISMATCH')
    return parsed


def source_plan(protocol):
    rows = cohort(protocol)
    targets = sorted({r['date'] for r in rows})
    nodes = sorted({h for r in rows for h in r['hours_UTC']})
    # Prospective execution detail, fixed before any new model profiles or
    # station products: one preceding-hour node and one raw-GRIB control day
    # per season. This resolves the old 676-hour cost estimate explicitly.
    controls = [(dt.date.fromisoformat(a)-dt.timedelta(days=1)).isoformat()+'T00:00'
                for a, _ in protocol['windows_UTC']]
    boundary = [(dt.datetime.fromisoformat(a)-dt.timedelta(hours=1)).isoformat(timespec='minutes')
                for a, _ in protocol['windows_UTC']]
    source_hours = sorted(set(nodes+controls+boundary))
    requests = [{'country': country, 'year': year,
        'start': f'{year}-{a[5:]}', 'end': f'{year}-{b[5:]}',
        'source': 'OPEN_METEO_ERA5', 'elevation': 'nan', 'cell_selection': 'nearest', 'timezone': 'GMT'}
        for country in protocol['countries'] for year in (2019, 2020, 2022)
        for a, b in protocol['windows_UTC']]
    return {'protocol_sha256': PROTOCOL_SHA, 'target_days': len(rows), 'site_hours': len(nodes)*3,
        'target_dates': targets, 'expected_case_ids': ['IV1|'+r['country']+'|'+r['date']+'|P2_NATIVE_THERMO' for r in rows],
        'native_source_hours': source_hours, 'native_source_hour_count': len(source_hours),
        'source_control_hours': controls, 'boundary_hours': boundary,
        'native_column_count': 3, 'native_column_hour_count': len(source_hours)*3,
        'fixed_native_grid_indices': protocol['pressure']['fixed_native_grid_indices'],
        'source_surface_GRIB_pattern': 'raw/ERA5GRIB/HRES/Month/2022/{month}_hres_{variable}.grb2',
        'raw_GRIB_control_parameters': ['z', 'lnsp'],
        'reference_requests': requests, 'reference_request_count': len(requests),
        'donor_days_expected': 168, 'method_records_expected': len(rows)*5,
        'prediction_node_slots_expected': len(rows)*5*24,
        'failures_retained_as_explicit_records_not_forced_predictions': True,
        'max_network_bytes': protocol['compute_estimate']['max_network_bytes'],
        'max_requests': protocol['compute_estimate']['max_requests'],
        'native_download_permitted_only_after_time_admission': True,
        'native_source_collection_implemented_here': False, 'station_scoring_implemented_here': False}


def admission_report():
    protocol = guard()
    if hashlib.sha256(ADDENDUM.read_bytes()).hexdigest() != ADDENDUM_SHA:
        raise ValueError('IV1_START_ADDENDUM_CHANGED')
    start = json.loads(ADDENDUM.read_text())
    module = Path(__file__).with_name('p9_3b3_cd3_stability.py')
    if hashlib.sha256(module.read_bytes()).hexdigest() != start['frozen_start_module_sha256']:
        raise ValueError('IV1_FROZEN_START_CODE_CHANGED')
    time = time_admission(protocol)
    sensors = dated_sensors(protocol)
    plan = source_plan(protocol)
    return {'phase': 'IV1_EXECUTABLE_TIME_ADMISSION_AND_PREDICTION_PREPARATION_20261024',
        'protocol_sha256': PROTOCOL_SHA, 'start_addendum_sha256': ADDENDUM_SHA,
        'frozen_files_unchanged': len(protocol['protected_control_sha256']),
        'time_admission': time, 'dated_sensors': sensors, 'source_plan': plan,
        'ready_for_native_source_collection': time['all_parameter_time_operators_admitted'],
        'ready_to_open_observations': False,
        'unblinding_blockers': ['ALL_PARAMETER_TIME_OPERATORS' ]*(not time['all_parameter_time_operators_admitted'])
            +['NEW_2022_NATIVE_LINEAGE_AND_PROFILES_NOT_COLLECTED', 'FULL_84_CASE_420_METHOD_PREDICTIONS_NOT_SEALED',
              'END_TO_END_SOURCE_AND_SCORER_PIPELINE_NOT_YET_IMPLEMENTED'],
        'station_values_opened': False, 'independent_accuracy': 'NOT_RUN',
        'B4_qualified': False, 'operational_ready': False, 'main_merged': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    result = admission_report()
    write_new(parser.parse_args().out, result)
    print(json.dumps({k: result[k] for k in ('phase', 'frozen_files_unchanged',
        'ready_for_native_source_collection', 'ready_to_open_observations', 'unblinding_blockers')}))
