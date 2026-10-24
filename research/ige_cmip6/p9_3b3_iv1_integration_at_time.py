"""Nominal AT published-node admission from the provider's original v1/v2 chain.

No claim about a zero-duration sensor impulse response is made. The archived
provider calls the 10-minute product a base value at the reporting node and
the hourly product the last such value at the full hour. This is a published
sample-selection operator, not a one-hour mean. Its transfer to v2 follows
the provider's release notes and explicit old/new parameter mapping tables.
No station values are read to establish this nominal operator.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import csv
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import json
import lzma
from pathlib import Path
import re
import subprocess

from p9_3b3_iv1_admission import admission_report
from p9_3b3_iv1_preflight import ROOT, guard


SNAPSHOT = Path(__file__).with_name('p9_3b3_iv1_at_time_evidence_20261024.json.xz')
SNAPSHOT_SHA = '18ef6d3278c6b779ccffcab0ff90ecde4bf1876767d3a751080705694df63158'
PARENT_COMMIT = '3e43d25405f0d53d01cab635c4b91ca2dce01c67'
METADATA_BASE = 'https://dataset.api.hub.geosphere.at/v1/station/historical/'
EXPECTED_URLS = {
    'hourly_metadata.json': METADATA_BASE+'klima-v2-1h/metadata',
    '10min_metadata.json': METADATA_BASE+'klima-v2-10min/metadata',
    'legacy_hourly_metadata.json': METADATA_BASE+'klima-v1-1h/metadata',
    'legacy_10min_metadata.json': METADATA_BASE+'klima-v1-10min/metadata',
    'raw_10min_metadata.json': METADATA_BASE+'tawes-v1-10min/metadata',
    'hourly_parameter_mapping.csv': 'https://dataset.api.hub.geosphere.at/v1/docs/_downloads/503a659c37d2e1c5e9e5aeedff6b0e99/klima-v2-1h.csv',
    '10min_parameter_mapping.csv': 'https://dataset.api.hub.geosphere.at/v1/docs/_downloads/312d9ffbfec7a2bbe17d16a0f172397d/klima-v2-10min.csv',
    'provider_changelog.html': 'https://dataset.api.hub.geosphere.at/v1/docs/changelog.html',
    'legacy_hourly_dataset.html': 'https://data.hub.geosphere.at/dataset/klima-v1-1h',
    'current_hourly_dataset.html': 'https://data.hub.geosphere.at/dataset/klima-v2-1h',
    'CH_DAV_STAC_current.json': 'https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/dav'}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, text):
        self.parts.append(text)


def plain(raw):
    parser = Text(); parser.feed(raw.decode('utf-8'))
    return ' '.join(' '.join(parser.parts).split())


def load_evidence():
    raw = SNAPSHOT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_SHA:
        raise ValueError('IV1_AT_TIME_EVIDENCE_SNAPSHOT_CHANGED')
    wrapper = json.loads(lzma.decompress(raw))
    if (wrapper['schema'] != 'IGE_IV1_AT_PUBLISHED_NODE_TIME_EVIDENCE_v2_20261024'
            or wrapper['parent_commit'] != PARENT_COMMIT
            or wrapper['all_sources_metadata_only'] is not True
            or wrapper['heldout_2022_station_values_opened'] is not False
            or wrapper['station_product_URLs_requested'] is not False
            or set(wrapper['members']) != set(EXPECTED_URLS)):
        raise ValueError('IV1_AT_TIME_EVIDENCE_SCOPE')
    bodies = {}
    for name, entry in wrapper['members'].items():
        body = base64.b64decode(entry['base64'], validate=True)
        if (entry['source_url'] != EXPECTED_URLS[name] or len(body) != entry['bytes']
                or hashlib.sha256(body).hexdigest() != entry['sha256']):
            raise ValueError('IV1_AT_TIME_EVIDENCE_MEMBER_CHANGED_'+name)
        bodies[name] = body
    return wrapper, bodies


def parameter(obj, name):
    rows = [r for r in obj['parameters'] if r['name'] == name]
    if len(rows) != 1:
        raise ValueError('IV1_AT_TIME_PARAMETER_NOT_UNIQUE_'+name)
    return rows[0]


def rename(raw, old, new):
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';'))
    if [r['para_name_new'] for r in rows if r['para_name_old'] == old] != [new]:
        raise ValueError('IV1_AT_TIME_OFFICIAL_RENAME_NOT_UNIQUE_'+old)


def dated_station(obj, protocol):
    rows = [r for r in obj['stations'] if str(r['id']) == '16412' and r['type'] == 'INDIVIDUAL']
    if len(rows) != 1:
        raise ValueError('IV1_AT_TIME_INDIVIDUAL_16412_REQUIRED')
    row = rows[0]
    # These are station-series validity dates, not sensor heights. Retain the
    # previously admitted dated WMDR sensor references without replacement.
    first = dt.date.fromisoformat(row['valid_from'][:10])
    last = dt.date.fromisoformat(row['valid_to'][:10])
    if any(not first <= dt.date.fromisoformat(day) <= last
           for window in protocol['windows_UTC'] for day in window):
        raise ValueError('IV1_AT_TIME_STATION_EPOCH_DOES_NOT_COVER_REGISTERED_2022')
    return {k: row[k] for k in ('id', 'type', 'name', 'valid_from', 'valid_to')}


def parse_evidence(bodies, protocol):
    for name in ('legacy_hourly_dataset.html', 'current_hourly_dataset.html'):
        if 'Zeitzone UTC' not in plain(bodies[name]):
            raise ValueError('IV1_AT_TIME_PROVIDER_UTC_REQUIRED')
    changelog = plain(bodies['provider_changelog.html'])
    if any(t not in changelog for t in ('Parameter names have changed.', 'klima-v1-1h', 'klima-v2-1h', 'klima-v2-10min.csv')):
        raise ValueError('IV1_AT_TIME_PROVIDER_VERSION_LINK_REQUIRED')
    old_h, old_t, new_h, new_t = [json.loads(bodies[name]) for name in (
        'legacy_hourly_metadata.json', 'legacy_10min_metadata.json', 'hourly_metadata.json', '10min_metadata.json')]
    if [x['frequency'] for x in (old_h, old_t, new_h, new_t)] != ['1H', '10T', 'PT1H', 'PT10M']:
        raise ValueError('IV1_AT_TIME_NATIVE_FREQUENCIES_CHANGED')
    series = [dated_station(obj, protocol) for obj in (old_h, old_t, new_h, new_t)]
    output = {}
    for key, old_hourly, old_ten, current, unit in (
            ('T', 'TTX', 'TL', 'tl', '°C'), ('RH', 'FFX', 'RF', 'rf', '%'), ('p', 'PPX', 'P', 'p', 'hPa')):
        rename(bodies['hourly_parameter_mapping.csv'], old_hourly, current)
        rename(bodies['10min_parameter_mapping.csv'], old_ten, current)
        hour, ten, now, now_ten = [parameter(obj, field) for obj, field in (
            (old_h, old_hourly), (old_t, old_ten), (new_h, current), (new_t, current))]
        if (not re.search(r'letzter\s+10\s+Minutenwert\s+der\s+vollen\s+Stunde', hour['desc'])
                or 'Basiswert zur Minute10' not in ten['desc']
                or 'Stunden-Messwert' not in now['description']
                or '10-Minuten-Messwert' not in now_ten['description']):
            raise ValueError('IV1_AT_TIME_NOMINAL_BASE_SAMPLE_SELECTION_NOT_DOCUMENTED_'+current)
        if (hour['unit'] != ('mbar' if key == 'p' else unit)
                or any(r['unit'] != unit for r in (ten, now, now_ten))):
            raise ValueError('IV1_AT_TIME_UNITS_CHANGED_'+current)
        if key == 'p' and ('Stationsniveau' not in hour['desc'] or 'Stationsniveau' not in now['description']):
            raise ValueError('IV1_AT_TIME_ABSOLUTE_STATION_PRESSURE_REQUIRED')
        output[key] = {'field': current, 'status': 'ADMITTED', 'operator': 'CURRENT_VALUE_AT_EXACT_UTC_NODE',
            'original_parameter_record': now, 'legacy_hourly_record': hour, 'legacy_10min_record': ten,
            'nominal_operator': 'SELECT_PUBLISHED_10_MINUTE_BASE_SAMPLE_AT_THE_FULL_UTC_HOUR',
            'nominal_operator_v2_basis': 'INFERENCE_FROM_PROVIDER_RELEASE_AND_EXPLICIT_V1_V2_RENAME_TABLES',
            'instrument_filter_period_certified': False, 'instrument_averaging_window_seconds': None,
            'v1_v2_value_identity_checked': False, 'one_hour_mean_assumed': False,
            'source_snapshot_sha256': SNAPSHOT_SHA, 'registered_period_only': protocol['windows_UTC'],
            'pressure_unit_equivalence': '1_mbar_EQUALS_1_hPa_EQUALS_100_Pa' if key == 'p' else None}
    asset = json.loads(bodies['CH_DAV_STAC_current.json'])['assets']['ogd-smn_dav_t_historical_2020-2029.csv']
    if (asset['href'] != protocol['CH_source_url']
            or asset['file:checksum'] != protocol['CH_STAC_multihash_before_values_opened']):
        raise ValueError('IV1_REGISTERED_CH_SOURCE_VERSION_DRIFT_BEFORE_SOURCE_RUN')
    return {'AT': output, 'station_series_epoch_proof': series,
        'evidence_scope': 'NOMINAL_PUBLISHED_NODE_OPERATOR_NOT_ZERO_DURATION_INSTRUMENT_CERTIFICATE',
        'CH_registered_source_checksum_unchanged': True, 'heldout_2022_station_values_opened': False}


def current_admission_report():
    base = admission_report()
    subprocess.run(['git', 'merge-base', '--is-ancestor', PARENT_COMMIT, 'HEAD'],
                   cwd=ROOT, check=True, capture_output=True)
    _, bodies = load_evidence()
    proof = parse_evidence(bodies, guard())
    result = deepcopy(base)
    time = result['time_admission']
    time['countries']['AT'] = proof['AT']
    rows = [r for country in time['countries'].values() for r in country.values()]
    admitted = sum(r['status'] == 'ADMITTED' for r in rows)
    complete = len(rows) == time['required_fields'] == admitted
    time.update(admitted_fields=admitted, all_parameter_time_operators_admitted=complete,
                additional_AT_evidence_sha256=SNAPSHOT_SHA, instrument_filter_periods_certified=False)
    result.update(phase='IV1_NOMINAL_TIME_ADMISSION_WITH_PROVIDER_LEGACY_CHAIN_20261024',
        current_AT_time_evidence=proof, old_preparation_snapshot_unchanged=True,
        ready_for_native_source_collection=complete, ready_to_open_observations=False,
        unblinding_blockers=['NEW_2022_NATIVE_LINEAGE_AND_PROFILES_NOT_COLLECTED',
            'FULL_84_CASE_420_METHOD_PREDICTIONS_NOT_SEALED'])
    return result
