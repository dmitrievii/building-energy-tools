"""Exact registered AT/DE/CH observation adapters, used only after full seal.

Current AT time admission is unresolved. No values are fetched by importing
or testing these parsers. The production entry checks admission itself too.
"""
from __future__ import annotations

from collections import Counter
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.parse
import urllib.request
import zipfile

import p9_1a_global_historical_backbone as era
from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_iv1_admission import load_time_metadata
from p9_3b3_iv1_integration_common import OBSERVATION_BUDGET, require_time_admission, sha
from p9_3b3_iv1_preflight import cohort
from p9_3b3_pressure_reference import station_pressure


AT = 'https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h'
SCHEMA_SHA = '3adcd42d6a217de8b239a70ce726ef19372702a40c60d760f5c900bc5dff415c'


def new_observations(country):
    return {'country': country, 'values': {'T_K': {}, 'RH_pp': {}, 'p_barometer_Pa': {}},
            'QC_counts': {}, 'sources': []}


def numeric(value, variable):
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(v):
        return None
    if variable == 'T_K': return v+273.15 if -95 < v < 65 else None
    if variable == 'RH_pp': return v if 0 <= v <= 105 else None
    return v*100 if 450 < v < 1100 else None


def parse_AT(raw, start, end):
    schema = Path(__file__).with_name('p9_3b3_iv1_integration_AT_response_schema_20261024.json')
    if sha(schema) != SCHEMA_SHA:
        raise ValueError('IV1_AT_RESPONSE_SCHEMA_CHANGED')
    obj = json.loads(raw)
    features = obj['features']
    if len(features) != 1 or str(features[0]['properties']['station']) != '16412':
        raise ValueError('IV1_AT_INDIVIDUAL_16412_REQUIRED_NO_COMBINED_SUBSTITUTION')
    expected = [(dt.datetime.fromisoformat(start)+dt.timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M')
                for i in range(336)]
    stamps = []
    for t in obj['timestamps']:
        value = dt.datetime.fromisoformat(t.replace('Z', '+00:00'))
        if (value.tzinfo is None or value.utcoffset() != dt.timedelta(0)
                or value.minute or value.second or value.microsecond):
            raise ValueError('IV1_AT_EXPLICIT_EXACT_UTC_NODES_REQUIRED')
        stamps.append(value.strftime('%Y-%m-%dT%H:%M'))
    if stamps != expected or expected[-1][:10] != end:
        raise ValueError('IV1_AT_REGISTERED_TIME_AXIS')
    out = new_observations('AT')
    parameters = features[0]['properties']['parameters']
    for field, variable, unit in (('tl', 'T_K', '°C'), ('rf', 'RH_pp', '%'), ('p', 'p_barometer_Pa', 'hPa')):
        data, flags = parameters[field], parameters[field+'_flag']['data']
        if data['unit'] != unit or len(data['data']) != 336 or len(flags) != 336:
            raise ValueError('IV1_AT_NATIVE_FIELD_UNITS_OR_LENGTH')
        out['QC_counts'][field] = dict(Counter(map(str, flags)))
        for stamp, value, flag in zip(stamps, data['data'], flags):
            v = numeric(value, variable)
            if type(flag) in (int, float) and flag in (10, 11, 12, 20, 21, 22) and v is not None:
                out['values'][variable][stamp] = v
    out['quality_tier'] = 'GEOSPHERE_NATIVE_VARIABLE_GOOD_FLAGS'
    return out


def parse_DE(raw, product, wanted):
    out = new_observations('DE'); flags = Counter()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.startswith('produkt_') and n.endswith('.txt')]
        if len(names) != 1 or archive.getinfo(names[0]).file_size > 200_000_000:
            raise ValueError('IV1_DWD_UNIQUE_BOUNDED_PRODUCT_REQUIRED')
        with archive.open(names[0]) as stream:
            reader = csv.DictReader(io.TextIOWrapper(stream, encoding='latin-1'), delimiter=';')
            fields = {f.strip() for f in reader.fieldnames or []}
            required = {'MESS_DATUM', 'STATIONS_ID', 'QN'} | ({'TT_ST_10', 'RF_ST_10'} if product == 'T_RH' else {'P0_ST_10'})
            if not required <= fields:
                raise ValueError('IV1_DWD_OWN_URBAN_FIELDS_REQUIRED_NO_GENERIC_OR_REDUCED_SUBSTITUTE')
            seen = set()
            for values in reader:
                row = {k.strip(): v.strip() for k, v in values.items() if k is not None}
                text = row['MESS_DATUM']
                if len(text) != 12 or not text.endswith('00'):
                    continue
                stamp = dt.datetime.strptime(text, '%Y%m%d%H%M').strftime('%Y-%m-%dT%H:%M')
                if stamp not in wanted:
                    continue
                if row['STATIONS_ID'] not in ('399', '00399') or stamp in seen:
                    raise ValueError('IV1_DWD_OTHER_STATION_OR_DUPLICATE_HOUR')
                seen.add(stamp); flags[row['QN']] += 1
                if row['QN'] != '3':
                    continue
                if product == 'T_RH':
                    data = {'T_K': numeric(row['TT_ST_10'], 'T_K'), 'RH_pp': numeric(row['RF_ST_10'], 'RH_pp')}
                else:
                    value, _ = station_pressure(row, 'DWD_URBAN_10MIN')
                    data = {'p_barometer_Pa': value}
                for key, value in data.items():
                    if value is not None:
                        out['values'][key][stamp] = value
    out['QC_counts'][product] = dict(flags)
    out['quality_tier'] = 'DWD_URBAN_QN_3_PRIMARY_EMPTY_NOT_FINAL'
    return out


def parse_CH(raw, wanted):
    out = new_observations('CH')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';')
    required = {'station_abbr', 'reference_timestamp', 'tre200s0', 'ure200s0', 'prestas0'}
    if not required <= set(reader.fieldnames or []):
        raise ValueError('IV1_CH_CURRENT_VALUES_REQUIRED_NO_HOURLY_MEAN_SUBSTITUTION')
    seen = set()
    for row in reader:
        text = row['reference_timestamp']
        try:
            value = dt.datetime.strptime(text, '%d.%m.%Y %H:%M')
        except ValueError:
            value = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
            if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
                raise ValueError('IV1_CH_TIMESTAMP_WITHOUT_DOCUMENTED_UTC')
        if value.second or value.microsecond:
            raise ValueError('IV1_CH_EXACT_HOUR_NODE_REQUIRED')
        if value.minute:
            continue
        stamp = value.strftime('%Y-%m-%dT%H:%M')
        if stamp not in wanted:
            continue
        if row['station_abbr'].strip().upper() != 'DAV' or stamp in seen:
            raise ValueError('IV1_CH_OTHER_STATION_OR_DUPLICATE_HOUR')
        seen.add(stamp)
        for field, key in (('tre200s0', 'T_K'), ('ure200s0', 'RH_pp'), ('prestas0', 'p_barometer_Pa')):
            v = numeric(row[field], key)
            if v is not None:
                out['values'][key][stamp] = v
    out['quality_tier'] = 'PUBLISHED_CURRENT_VALUES_NO_COMPARABLE_PER_SAMPLE_QC_SEPARATE_TIER'
    return out


class StationCache:
    def __init__(self, root, allowed_urls):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.allowed_urls = set(allowed_urls); self.downloaded = 0; self.records = []

    def fetch(self, url, *, expected_sha=None, expected_etag=None, limit=512*1024**2):
        if url not in self.allowed_urls:
            raise ValueError('IV1_UNREGISTERED_OBSERVATION_URL')
        path = self.root/(hashlib.sha256(url.encode()).hexdigest()+'.bin')
        meta_path = path.with_suffix('.metadata.json')
        if path.is_file():
            meta = json.loads(meta_path.read_text())
            if sha(path) != meta['sha256'] or meta['url'] != url or (expected_etag and meta['ETag'] != expected_etag):
                raise ValueError('IV1_OBSERVATION_CACHE_VERSION_CHANGED')
            if path.stat().st_size > limit:
                raise ValueError('IV1_OBSERVATION_OBJECT_BUDGET')
            raw = path.read_bytes()
        else:
            remaining = min(limit, OBSERVATION_BUDGET-self.downloaded)
            if remaining <= 0:
                raise ValueError('IV1_OBSERVATION_TOTAL_BUDGET')
            with era._no_redirect_opener().open(urllib.request.Request(url, headers={'User-Agent': 'IGE-IV1-after-seal/1.0'}), timeout=30) as response:
                if response.geturl() != url:
                    raise ValueError('IV1_OBSERVATION_REDIRECT_NOT_REGISTERED')
                etag = response.headers.get('ETag')
                if expected_etag and etag != expected_etag:
                    raise SourceBlocked('IV1_DWD_ARCHIVE_VERSION_DRIFT_BEFORE_BODY_READ')
                length = int(response.headers['Content-Length']) if 'Content-Length' in response.headers else None
                if length is not None and (length < 0 or length > remaining):
                    raise ValueError('IV1_OBSERVATION_TOTAL_BUDGET')
                raw = response.read(length if length is not None else remaining)
            self.downloaded += len(raw)
            if (length is None and len(raw) == remaining) or (length is not None and len(raw) != length):
                raise ValueError('IV1_OBSERVATION_SIZE_OR_TRUNCATION')
            meta = {'url': url, 'ETag': etag, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            with path.open('xb') as stream: stream.write(raw)
            with meta_path.open('x') as stream: json.dump(meta, stream)
        if expected_sha and hashlib.sha256(raw).hexdigest() != expected_sha:
            raise SourceBlocked('IV1_REGISTERED_CH_ASSET_CHECKSUM_CHANGED_EXPLICIT_VERSION_ACCOUNTING_REQUIRED')
        self.records.append(meta)
        return raw


def open_observations(protocol, private_cache, prediction_directory, expected_seal_sha256):
    require_time_admission()  # Also protect direct calls to this I/O entry point.
    from p9_3b3_iv1_integration import verify_predictions
    _, _, registered = verify_predictions(prediction_directory, expected_seal_sha256)
    if protocol != registered:
        raise ValueError('IV1_OBSERVATION_PROTOCOL_DIFFERS_FROM_VERIFIED_PREDICTIONS')
    wrapper, bodies = load_time_metadata()
    urls = wrapper['source_urls']
    AT_urls = [AT+'?'+urllib.parse.urlencode({'station_ids': '16412',
        'parameters': 'tl,tl_flag,rf,rf_flag,p,p_flag', 'output_format': 'geojson',
        'start': start+'T00:00Z', 'end': end+'T23:00Z'}) for start, end in protocol['windows_UTC']]
    cache = StationCache(private_cache, [*AT_urls, urls['DE_urban_T_RH_parameters.txt'],
                                       urls['DE_urban_pressure_parameters.txt'], protocol['CH_source_url']])
    wanted = {h for r in cohort(protocol) if r['country'] == 'AT' for h in r['hours_UTC']}
    output = {co: new_observations(co) for co in protocol['countries']}
    provenance = {}
    for country in protocol['countries']:
        try:
            parts = []
            if country == 'AT':
                for url, (start, end) in zip(AT_urls, protocol['windows_UTC']):
                    parts.append(parse_AT(cache.fetch(url, limit=12_000_000), start, end))
            elif country == 'DE':
                for product, member, proof_name in (('T_RH', 'DE_urban_T_RH_parameters.txt', 'DE_urban_T_RH_range_proof.json'),
                                                     ('p', 'DE_urban_pressure_parameters.txt', 'DE_urban_pressure_range_proof.json')):
                    proof = json.loads(bodies[proof_name])
                    etags = {r['ETag'] for r in proof['requests']}
                    if len(etags) != 1:
                        raise ValueError('IV1_DWD_ARCHIVE_METADATA_VERSION_NOT_UNIQUE')
                    parts.append(parse_DE(cache.fetch(urls[member], expected_etag=next(iter(etags)), limit=30_000_000), product, wanted))
            else:
                checksum = protocol['CH_STAC_multihash_before_values_opened']
                if not checksum.startswith('1220') or len(checksum) != 68:
                    raise ValueError('IV1_CH_SHA256_MULTIHASH_REQUIRED')
                parts.append(parse_CH(cache.fetch(protocol['CH_source_url'], expected_sha=checksum[4:]), wanted))
            for part in parts:
                for key, values in part['values'].items():
                    if set(values) & set(output[country]['values'][key]):
                        raise ValueError('IV1_DUPLICATE_OBSERVATION_SOURCE_HOURS')
                    output[country]['values'][key].update(values)
                output[country]['QC_counts'].update(part['QC_counts'])
                output[country]['quality_tier'] = part['quality_tier']
            provenance[country] = {'status': 'SOURCE_READ', 'QC_counts': output[country]['QC_counts'],
                'quality_tier': output[country]['quality_tier'],
                'valid_hours': {k: len(v) for k, v in output[country]['values'].items()}}
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
            output[country] = new_observations(country)
            provenance[country] = {'status': 'SOURCE_BLOCKED', 'reason': type(error).__name__+':'+str(error)}
    provenance['source_objects'] = cache.records
    provenance['downloaded_bytes'] = cache.downloaded
    return output, provenance
