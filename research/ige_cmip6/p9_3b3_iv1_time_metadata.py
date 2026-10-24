"""Read DWD parameter metadata with ranges, without reading product members.

Only the ZIP end record, central directory and one named metadata member are
requested. A server ignoring ranges is rejected before its body is read.
This is a source audit, not an observation downloader or a timing inference.
"""
from __future__ import annotations

import hashlib
import re
import struct
import urllib.parse
import urllib.request
import zlib


class MetadataZip:
    def __init__(self, url, opener=None):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'opendata.dwd.de'
                or parsed.port is not None or parsed.query or parsed.fragment
                or not parsed.path.startswith('/climate_environment/CDC/observations_germany/climate_urban/10_minutes/')
                or not parsed.path.endswith('_hist.zip')):
            raise ValueError('IV1_DWD_METADATA_URL')
        self.url, self.opener = url, opener or urllib.request.urlopen
        self.requests, self.total, self.etag = [], None, None

    def _range(self, start, end=None):
        header = f'bytes={start}' if start < 0 else f'bytes={start}-{end}'
        headers = {'Range': header, 'Accept-Encoding': 'identity',
                   'User-Agent': 'IGE-IV1-parameter-metadata-only/1.0'}
        if self.etag:
            headers['If-Range'] = self.etag
        with self.opener(urllib.request.Request(self.url, headers=headers), timeout=25) as r:
            if urllib.parse.urlsplit(r.geturl()).hostname != 'opendata.dwd.de':
                raise ValueError('IV1_METADATA_REDIRECT')
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', r.headers.get('Content-Range', ''))
            if r.status != 206 or not match:
                raise ValueError('IV1_METADATA_RANGE_REQUIRED_NO_BODY_READ')
            a, b, total = map(int, match.groups())
            expected = (total+start, total-1) if start < 0 else (start, end)
            if ((a, b) != expected or not 0 <= a <= b < total or b-a+1 > 100_000
                    or total > 20_000_000 or self.total not in (None, total)):
                raise ValueError('IV1_METADATA_RANGE_OR_SIZE')
            etag = r.headers.get('ETag')
            if self.etag is not None and etag != self.etag:
                raise ValueError('IV1_METADATA_ARCHIVE_CHANGED_DURING_READ')
            self.total, self.etag = total, etag
            raw = r.read(b-a+2)
            if len(raw) != b-a+1:
                raise ValueError('IV1_METADATA_RANGE_LENGTH')
            self.requests.append({'byte_range': [a, b], 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'ETag': etag,
                'Last-Modified': r.headers.get('Last-Modified')})
            return raw

    def read_parameter(self, member):
        if not re.fullmatch(r'Metadaten_Parameter_zehn_st_min_(tu|p0)_00399\.txt', member):
            raise ValueError('IV1_ONLY_REGISTERED_PARAMETER_METADATA_ALLOWED')
        if self.requests:
            raise ValueError('IV1_USE_NEW_METADATA_READER_FOR_EACH_ARCHIVE')
        end = self._range(-22)
        fields = struct.unpack('<4s4H2LH', end)
        sig, disk, cd_disk, disk_count, count, size, offset, comment = fields
        if (sig != b'PK\x05\x06' or disk or cd_disk or disk_count != count
                or comment or not 0 < count <= 100 or not 0 < size <= 100_000
                or offset+size != self.total-22):
            raise ValueError('IV1_METADATA_UNSUPPORTED_ZIP_END')
        cd = self._range(offset, offset+size-1)
        entries, i = [], 0
        while i < len(cd):
            if i+46 > len(cd):
                raise ValueError('IV1_METADATA_TRUNCATED_CENTRAL_DIRECTORY')
            h = struct.unpack_from('<4s6H3I5H2I', cd, i)
            nl, el, cl = h[10:13]
            if h[0] != b'PK\x01\x02' or i+46+nl+el+cl > len(cd):
                raise ValueError('IV1_METADATA_CENTRAL_DIRECTORY')
            name = cd[i+46:i+46+nl].decode('ascii')
            entries.append({'name': name, 'flags': h[3], 'method': h[4],
                'crc32': h[7], 'compressed': h[8], 'uncompressed': h[9], 'offset': h[-1]})
            i += 46+nl+el+cl
        if len(entries) != count or len({e['name'] for e in entries}) != count:
            raise ValueError('IV1_METADATA_MEMBER_CENSUS')
        matches = [e for e in entries if e['name'] == member]
        if len(matches) != 1:
            raise ValueError('IV1_METADATA_MEMBER_NOT_FOUND')
        entry = matches[0]
        if (entry['flags'] & 1 or entry['method'] not in (0, 8)
                or not 0 < entry['compressed'] <= 30_000
                or not 0 < entry['uncompressed'] <= 30_000):
            raise ValueError('IV1_METADATA_MEMBER_SIZE_OR_ENCODING')
        start = entry['offset']
        # Refuse overlapping directory/local records before any member reads.
        ordered = sorted(entries, key=lambda e: e['offset'])
        for a, b in zip(ordered, ordered[1:]):
            if a['offset']+30+len(a['name'])+a['compressed'] > b['offset']:
                raise ValueError('IV1_METADATA_OVERLAPPING_MEMBERS')
        header = self._range(start, start+29)
        h = struct.unpack('<4s5H3I2H', header)
        nl, el = h[-2:]
        if h[0] != b'PK\x03\x04' or h[2] != entry['flags'] or h[3] != entry['method'] or nl != len(member) or el > 4096:
            raise ValueError('IV1_METADATA_LOCAL_HEADER')
        name = self._range(start+30, start+29+nl+el)[:nl].decode('ascii')
        if name != member:
            raise ValueError('IV1_METADATA_LOCAL_MEMBER_MISMATCH')
        first = start+30+nl+el
        last = first+entry['compressed']-1
        next_offset = min([e['offset'] for e in entries if e['offset'] > start]+[offset])
        if last >= next_offset:
            raise ValueError('IV1_METADATA_MEMBER_OVERLAPS_OTHER_DATA')
        packed = self._range(first, last)
        if entry['method'] == 8:
            inflater = zlib.decompressobj(-15)
            raw = inflater.decompress(packed, 30_001)
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                raise ValueError('IV1_METADATA_DEFLATE_BOUNDARY')
        else:
            raw = packed
        if len(raw) != entry['uncompressed'] or zlib.crc32(raw) != entry['crc32']:
            raise ValueError('IV1_METADATA_CRC_OR_LENGTH')
        return raw, {'url': self.url, 'member': member,
            'member_sha256': hashlib.sha256(raw).hexdigest(), 'archive_bytes': self.total,
            'central_directory_sha256': hashlib.sha256(cd).hexdigest(),
            'requests': self.requests, 'archive_members': entries,
            'station_product_members_requested': False,
            'station_product_members_decompressed': False,
            'whole_zip_downloaded': False}
