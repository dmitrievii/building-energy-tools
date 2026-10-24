"""IV1 fixed-column native 2022 collector; observations are not accessible.

Only admitted published-node timing and dated sensors permit network I/O.
The implementation can also be exercised with artificial readers in tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import urllib.request

import p9_1a_global_historical_backbone as era
from p9_3b3_compare_vertical_frame import fingerprint, SourceBlocked
from p9_3b3_iv1_integration_common import (CONTRACT_SHA, OBSERVATION_BUDGET, code_pins, execution_plan,
    fresh_directory, integration_guard, read_members, require_time_admission, sha, write_new)
from p9_3b3_iv1_preflight import ROOT
from p9_3b3_native_columns import NativeColumns
from p9_3b3_native_run import protocol_guard as native_guard
from p9_3b3_native_sources import NativeCache, synthesize
from p9_3b3_reference_column import hybrid_column


class ModelCache(NativeCache):
    def fetch(self, url, limit=None, byte_range=None):
        if not url.startswith('https://storage.googleapis.com/gcp-public-data-arco-era5/'):
            raise ValueError('IV1_NATIVE_CACHE_MODEL_HOST_ONLY')
        # The frozen NativeCache permits several station hosts for its older
        # source audit. This model-only collector must also refuse redirects
        # to them, so use an isolated no-redirect HTTP boundary here.
        cap = min(limit or self.protocol['max_object_bytes'], self.protocol['max_object_bytes'])
        suffix = ''
        if byte_range is not None:
            a, b = byte_range
            if type(a) is not int or type(b) is not int or not 0 <= a <= b or b-a+1 > cap:
                raise SourceBlocked('IV1_NATIVE_RANGE_BUDGET')
            cap = b-a+1; suffix = '|bytes='+str(a)+'-'+str(b)
        path = self.root/(hashlib.sha256((url+suffix).encode()).hexdigest()+'.bin')
        digest = path.with_suffix('.sha256')
        cached = path.is_file()
        if cached:
            if path.stat().st_size > cap or not digest.is_file() or sha(path) != digest.read_text().strip():
                raise SourceBlocked('IV1_NATIVE_PRIVATE_CACHE_DIGEST_OR_BUDGET')
            body = path.read_bytes()
        else:
            if self.cache_only:
                raise SourceBlocked('IV1_NATIVE_CACHE_ONLY_MISSING_OBJECT')
            with self._lock:
                if self.requests >= self.protocol['max_requests']:
                    raise SourceBlocked('IV1_NATIVE_REQUEST_BUDGET')
                if self.downloaded+self._reserved >= self.protocol['max_download_bytes']:
                    raise SourceBlocked('IV1_NATIVE_DOWNLOAD_BUDGET')
                self.requests += 1
            headers = {'User-Agent': 'IGE-IV1-native-model-only/1.0'}
            if byte_range is not None:
                headers['Range'] = 'bytes='+str(a)+'-'+str(b)
            reserved = 0
            try:
                with era._no_redirect_opener().open(urllib.request.Request(url, headers=headers),
                        timeout=self.protocol['source_timeout_seconds']) as response:
                    if response.geturl() != url:
                        raise SourceBlocked('IV1_NATIVE_REDIRECT_NOT_REGISTERED')
                    if byte_range is not None and (response.status != 206 or not response.headers.get(
                            'Content-Range', '').startswith('bytes '+str(a)+'-'+str(b)+'/')):
                        raise SourceBlocked('IV1_NATIVE_RANGE_IGNORED_REFUSE_WHOLE_MONTH')
                    length = int(response.headers['Content-Length']) if 'Content-Length' in response.headers else None
                    if length is not None and not 0 <= length <= cap:
                        raise SourceBlocked('IV1_NATIVE_OBJECT_BUDGET')
                    with self._lock:
                        remaining = self.protocol['max_download_bytes']-self.downloaded-self._reserved
                        read_cap = min(cap, remaining) if length is None else length
                        if read_cap > remaining or read_cap <= 0:
                            raise SourceBlocked('IV1_NATIVE_DOWNLOAD_BUDGET')
                        self._reserved += read_cap; reserved = read_cap
                    parts, received = [], 0
                    while received < read_cap:
                        part = response.read(min(1024*1024, read_cap-received))
                        if not part:
                            break
                        parts.append(part); received += len(part)
                        with self._lock:
                            self.downloaded += len(part); self._reserved -= len(part)
                        reserved -= len(part)
                    if (length is None and received == read_cap) or (length is not None and received != length):
                        raise SourceBlocked('IV1_NATIVE_SIZE_OR_UNPROVEN_EOF')
                    body = b''.join(parts)
            finally:
                with self._lock:
                    self._reserved -= reserved
            with path.open('xb') as stream:
                stream.write(body)
            digest.write_text(hashlib.sha256(body).hexdigest()+'\n')
        if byte_range is not None and len(body) != b-a+1:
            raise SourceBlocked('IV1_NATIVE_RANGE_BODY_LENGTH')
        self.records.append({'url': url, 'range': list(byte_range) if byte_range is not None else None,
            'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'from_cache': cached})
        return body


class IV1Columns(NativeColumns):
    def __init__(self, cache, config, sensors, contract):
        heights = {co: {'status': 'DATED_2022_SENSORS_CONFIRMED', 'sensors': s} for co, s in sensors.items()}
        super().__init__(cache, config, heights)
        self.indices = sorted(row[0] for row in contract['fixed_grid_points'].values())
        self.points = self.grid.points(self.indices)
        for index, latitude, longitude in contract['fixed_grid_points'].values():
            point = self.points[self.indices.index(index)]
            if max(abs(point[0]-latitude), abs(point[1]-longitude)) > 1e-9:
                raise SourceBlocked('IV1_FIXED_NATIVE_INDEX_COORDINATES_CHANGED')
        self.manifest['source_points'] = self.points
        self.field_attributes = {name: source.array(name)[1] for source, name in
            ((self.surface, 'z'), (self.surface, 'lnsp'), (self.temperature, 't'), (self.moisture, 'q'))}

    def raw_hour(self, stamp):
        columns = self.read(stamp, 124)
        z = synthesize(self.surface.field('z', stamp), self.points)
        lnsp = synthesize(self.surface.field('lnsp', stamp), self.points)
        rows = {}
        for i, index in enumerate(self.indices):
            c = columns[index]
            preimage = {'stamp': stamp, 'latitude': c.latitude, 'longitude': c.longitude,
                'first_level': 124, 'z': float(z[i]), 'lnsp': float(lnsp[i]),
                'T': list(c.temperature_K), 'q': list(c.specific_humidity_kgkg),
                'source_manifest': self.manifest['sources'], 'hybrid_pv': self.manifest['GRIB_pv_sha256']}
            if fingerprint(preimage) != c.source_sha256:
                raise ValueError('IV1_NATIVE_COLUMN_PREIMAGE_DOES_NOT_REPLAY')
            rows[str(index)] = {'preimage': preimage, 'column_fingerprint': c.fingerprint}
        return rows


def native_config(protocol, plan):
    frozen = native_guard(json.loads((ROOT/'research/ige_cmip6/p9_3b3_native_protocol.json').read_text()))
    config = dict(frozen)
    config.update(source_control_hours=plan['source_control_hours'],
        original_surface_GRIB=plan['source_surface_GRIB_pattern'],
        max_download_bytes=plan['max_network_bytes']-18*era.LIMIT_BYTES-OBSERVATION_BUDGET,
        max_requests=plan['max_requests']-23)
    return config


def fetch_reference(url, private_cache):
    # URL is generated by the frozen ERA5 request builder, never supplied by
    # an observation/scoring component. Keep one bounded request per window.
    if not url.startswith(era.SOURCE_URL+'?'):
        raise ValueError('IV1_REFERENCE_MODEL_URL_REQUIRED')
    path = Path(private_cache)/(hashlib.sha256(url.encode()).hexdigest()+'.reference.json')
    digest = path.with_suffix('.sha256')
    if path.is_file():
        if not digest.is_file() or sha(path) != digest.read_text().strip():
            raise ValueError('IV1_REFERENCE_PRIVATE_CACHE_CHANGED')
        if path.stat().st_size > era.LIMIT_BYTES:
            raise ValueError('IV1_REFERENCE_OBJECT_BUDGET')
        return path.read_bytes(), {'from_cache': True, 'bytes_downloaded': 0, 'requests': 0}
    with era._no_redirect_opener().open(urllib.request.Request(url,
            headers={'User-Agent': 'IGE-IV1-model-reference-only/1.0'}), timeout=25) as response:
        size = response.headers.get('Content-Length')
        if size and not 0 <= int(size) <= era.LIMIT_BYTES:
            raise ValueError('IV1_REFERENCE_OBJECT_BUDGET')
        raw = response.read(int(size) if size else era.LIMIT_BYTES)
    # Without Content-Length an exactly full buffer cannot establish EOF.
    # Block conservatively without downloading beyond the reserved budget.
    if (size and len(raw) != int(size)) or (not size and len(raw) == era.LIMIT_BYTES):
        raise ValueError('IV1_REFERENCE_SIZE_OR_UNPROVEN_EOF')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    digest.write_text(hashlib.sha256(raw).hexdigest()+'\n')
    return raw, {'from_cache': False, 'bytes_downloaded': len(raw), 'requests': 1}


def collect_sources(directory, private_cache):
    protocol, contract = integration_guard()
    admission = require_time_admission()  # Before directory/cache creation or any HTTP request.
    out = fresh_directory(directory)
    cache_path = Path(private_cache)
    if out.resolve() == cache_path.resolve() or out.resolve() in cache_path.resolve().parents:
        raise ValueError('IV1_PRIVATE_CACHE_MUST_BE_OUTSIDE_ARTIFACTS')
    cache_path.mkdir(parents=True, exist_ok=True)
    plan = execution_plan(protocol, contract)
    sensors = admission['dated_sensors']
    config = native_config(protocol, plan)
    cache = ModelCache(cache_path/'native', config)
    start = time.perf_counter()
    reader = IV1Columns(cache, config, sensors, contract)
    lineage = reader.controls()
    data = {'schema': 'IGE_IV1_SOURCE_DATA_v1', 'contract_sha256': CONTRACT_SHA,
        'plan': plan, 'sensors': sensors, 'lineage': lineage,
        'hybrid_pv': reader.A+reader.B, 'field_attributes': reader.field_attributes,
        'native_hours': {}, 'reference_requests': [], 'station_values_opened': False}
    failures = []
    for stamp in plan['native_source_hours']:
        try:
            data['native_hours'][stamp] = reader.raw_hour(stamp)
        except (OSError, ValueError) as error:
            failures.append({'scope': 'NATIVE_PROFILE', 'timestamp_UTC': stamp, 'reason': str(error)})
            data['native_hours'][stamp] = {'status': 'SOURCE_BLOCKED', 'reason': str(error)}
        print('IV1_NATIVE_SOURCE '+stamp, flush=True)
    reference_bytes, reference_network_requests = 0, 0
    members = {}
    for n, request in enumerate(plan['reference_requests']):
        sensor = sensors[request['country']]['temperature']
        url = era.request_url(sensor['latitude'], sensor['longitude'], request['start'], request['end'])
        entry = {'request': request, 'url': url}
        try:
            raw, network = fetch_reference(url, cache_path/'reference')
            era.parse_source(raw, sensor['latitude'], sensor['longitude'], request['start'], request['end'])
            name = f'reference_{n:02d}.json'
            with (out/name).open('xb') as stream:
                stream.write(raw)
            members[name] = sha(out/name)
            entry.update(status='SOURCE_READ', member=name, sha256=members[name])
            reference_bytes += network['bytes_downloaded']
            reference_network_requests += network['requests']
        except (OSError, ValueError) as error:
            entry.update(status='SOURCE_BLOCKED', reason=str(error))
            failures.append({'scope': 'MODEL_REFERENCE', 'request': request, 'reason': str(error)})
        data['reference_requests'].append(entry)
    data.update(source_failures=failures, complete=not failures,
        network_bytes=cache.downloaded+reference_bytes,
        network_requests=cache.requests+reference_network_requests,
        reference_failure_bytes_accounted_exactly=not any(r['scope'] == 'MODEL_REFERENCE' for r in failures),
        network_bytes_conservative_upper_bound=cache.downloaded+18*era.LIMIT_BYTES,
        network_requests_conservative_upper_bound=cache.requests+18,
        wall_seconds=time.perf_counter()-start)
    if data['network_bytes'] > plan['max_network_bytes'] or data['network_requests'] > plan['max_requests']:
        raise ValueError('IV1_TOTAL_SOURCE_BUDGET_EXCEEDED')
    write_new(out/'source_data.json', data)
    members['source_data.json'] = sha(out/'source_data.json')
    write_new(out/'source_seal.json', {'schema': 'IGE_IV1_SOURCE_SEAL_v1', 'members_sha256': members,
        'contract_sha256': CONTRACT_SHA, 'code_sha256': code_pins(), 'station_values_opened': False})
    return {'source_seal_sha256': sha(out/'source_seal.json'), 'complete': data['complete'],
            'source_failures': failures, 'network_bytes': data['network_bytes']}


def verify_sources(directory):
    protocol, contract = integration_guard()
    directory = Path(directory)
    seal = json.loads((directory/'source_seal.json').read_text())
    if (seal['schema'] != 'IGE_IV1_SOURCE_SEAL_v1' or seal['contract_sha256'] != CONTRACT_SHA
            or seal['code_sha256'] != code_pins() or seal['station_values_opened'] is not False):
        raise ValueError('IV1_SOURCE_SEAL_SCOPE_OR_CODE_CHANGED')
    paths = read_members(directory, seal['members_sha256'])
    data = json.loads(paths['source_data.json'].read_text())
    plan = execution_plan(protocol, contract)
    if (data['schema'] != 'IGE_IV1_SOURCE_DATA_v1' or data['plan'] != plan
            or data['contract_sha256'] != CONTRACT_SHA or data['station_values_opened'] is not False
            or set(data['native_hours']) != set(plan['native_source_hours'])):
        raise ValueError('IV1_SOURCE_PLAN_OR_NATIVE_HOUR_CENSUS_CHANGED')
    # Reparse original WMDR through the current source admission path.
    if fingerprint(data['sensors']) != fingerprint(admission_report_sensors()):
        raise ValueError('IV1_SOURCE_DATED_SENSOR_REFERENCE_CHANGED')
    attrs = data['field_attributes']
    for field, units, param, grid in (('z', 'm**2 s**-2', 129, 'sh'), ('lnsp', '~', 152, 'sh'),
                                    ('t', 'K', 130, 'sh'), ('q', 'kg kg**-1', 133, 'reduced_gg')):
        a = attrs[field]
        if (a['units'] != units or a['GRIB_paramId'] != param or a['GRIB_gridType'] != grid
                or a['GRIB_stepType'] != 'instant' or a['GRIB_typeOfLevel'] != 'hybrid'
                or a['GRIB_pv'] != data['hybrid_pv']):
            raise ValueError('IV1_NATIVE_FIELD_SEMANTICS_CHANGED')
        if (grid == 'sh' and [a['GRIB_'+k] for k in ('J', 'K', 'M')] != [639, 639, 639]
                or grid == 'reduced_gg' and a['GRIB_N'] != 320):
            raise ValueError('IV1_NATIVE_GRID_OR_TRUNCATION_CHANGED')
    lineage = data['lineage']
    expected_controls = {(t, v) for t in plan['source_control_hours'] for v in ('z', 'lnsp')}
    controls = lineage['original_GRIB_controls']
    if (lineage['paired_surface_lineage_status'] != 'ORIGINAL_GRIB_TO_CO_CAST_IDENTITY_CONFIRMED_AT_BOTH_CONTROL_HOURS'
            or len(controls) != 4 or {(r['timestamp_UTC'], r['variable']) for r in controls} != expected_controls
            or any(r['status'] != 'ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT'
                   or r['hybrid_pv_sha256'] != fingerprint(data['hybrid_pv']) for r in controls)):
        raise ValueError('IV1_ORIGINAL_GRIB_CO_LINEAGE_NOT_CONFIRMED')
    frozen = native_config(protocol, plan)
    for row in controls:
        stamp, field = row['timestamp_UTC'], row['variable']
        path = frozen['original_surface_GRIB'].format(month=stamp[:7].replace('-', ''),
                                                     variable='zs' if field == 'z' else 'lnsp')
        if (row['url'] != frozen['source_base']+'/'+path or row['dataDate'] != int(stamp[:10].replace('-', ''))
                or row['dataTime'] != 0 or row['paramId'] != {'z': 129, 'lnsp': 152}[field]
                or row['gridType'] != 'sh' or [row[k] for k in ('J', 'K', 'M')] != [639, 639, 639]
                or row['level'] != 1 or row['typeOfLevel'] != 'hybrid' or row['step'] != 0 or row['dataType'] != 'an'
                or row['coefficient_count'] != 410240 or len(row['sha256']) != 64):
            raise ValueError('IV1_RAW_GRIB_CONTROL_DATE_PARAMETER_OR_GRID_CHANGED')
    for role, key in (('surface', 'surface'), ('temperature', 'temperature'), ('moisture', 'moisture'), ('grid_reference', 'grid_reference')):
        if lineage['sources'][role]['url'] != frozen['source_base']+'/'+frozen[key]:
            raise ValueError('IV1_NATIVE_SOURCE_CHAIN_URL_CHANGED')
    columns = {}
    expected_indices = {str(r[0]) for r in contract['fixed_grid_points'].values()}
    for stamp, rows in data['native_hours'].items():
        if rows.get('status') == 'SOURCE_BLOCKED':
            continue
        if set(rows) != expected_indices:
            raise ValueError('IV1_FIXED_NATIVE_COLUMNS_CENSUS')
        columns[stamp] = {}
        for country, (index, latitude, longitude) in contract['fixed_grid_points'].items():
            row = rows[str(index)]
            raw = row['preimage']
            if (raw['stamp'] != stamp or raw['first_level'] != 124 or raw['latitude'] != latitude
                    or raw['longitude'] != longitude or raw['source_manifest'] != lineage['sources']
                    or raw['hybrid_pv'] != fingerprint(data['hybrid_pv'])):
                raise ValueError('IV1_NATIVE_COLUMN_TIME_GEOMETRY_OR_CHAIN_CHANGED')
            c = hybrid_column(raw['lnsp'], raw['z'], raw['T'], raw['q'],
                data['hybrid_pv'][:138], data['hybrid_pv'][138:], first_level=124,
                timestamp_UTC=stamp, latitude=latitude, longitude=longitude,
                source='ERA5_ORIGINAL_SH_CO_TO_NATIVE_N320_HYBRID_COLUMN', source_sha256=fingerprint(raw))
            if c.fingerprint != row['column_fingerprint']:
                raise ValueError('IV1_NATIVE_COLUMN_PHYSICS_DOES_NOT_REPLAY')
            columns[stamp][country] = c
    references = {}
    if len(data['reference_requests']) != 18 or [r['request'] for r in data['reference_requests']] != plan['reference_requests']:
        raise ValueError('IV1_REFERENCE_REQUEST_CENSUS_CHANGED')
    for entry in data['reference_requests']:
        if entry['status'] != 'SOURCE_READ':
            continue
        request = entry['request']; sensor = data['sensors'][request['country']]['temperature']
        expected_url = era.request_url(sensor['latitude'], sensor['longitude'], request['start'], request['end'])
        if entry['url'] != expected_url or entry['sha256'] != seal['members_sha256'][entry['member']]:
            raise ValueError('IV1_REFERENCE_GRID_MODEL_REQUEST_CHANGED')
        raw = paths[entry['member']].read_bytes()
        obj, arrays, meta = era.parse_source(raw, sensor['latitude'], sensor['longitude'], request['start'], request['end'])
        references[(request['country'], request['start'])] = (obj, arrays, meta)
    expected_members = {'source_data.json'} | {r['member'] for r in data['reference_requests'] if r['status'] == 'SOURCE_READ'}
    if set(paths) != expected_members:
        raise ValueError('IV1_UNREGISTERED_SOURCE_PRODUCT_IN_SEAL')
    complete = len(columns) == 676 and len(references) == 18 and not data['source_failures']
    if data['complete'] != complete:
        raise ValueError('IV1_SOURCE_COMPLETENESS_FLAG_DOES_NOT_REPLAY')
    return data, columns, references


def admission_report_sensors():
    from p9_3b3_iv1_admission import dated_sensors
    return dated_sensors(integration_guard()[0])
