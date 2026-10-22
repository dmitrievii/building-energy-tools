"""Bounded public-source reader. No global xarray load, no observation scoring.

ARCO uses native hybrid VERTICAL coordinates on a remapped horizontal grid.
It is never relabelled as original CDS GRIB or native future CanESM5 pressure.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import urllib.parse
import urllib.request
import zipfile

import numpy as np
from numcodecs import get_codec

from p9_3b3_compare_vertical_frame import SourceBlocked


HOSTS={"storage.googleapis.com","dataset.api.hub.geosphere.at","data.geo.admin.ch","opendata.dwd.de"}
AT="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata"
CH="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv"
DE="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate_urban/10_minutes/pressure/historical/10minutenwerte_P0_STADT_00399_20150701_20241231_hist.zip"


class BoundedCache:
    def __init__(self,root,protocol):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.protocol=protocol;self.downloaded=0;self.requests=0;self.records=[]

    def fetch(self,url):
        u=urllib.parse.urlsplit(url)
        if u.scheme!="https" or u.hostname not in HOSTS or u.port is not None:
            raise ValueError("P93REF_SOURCE_HOST_NOT_ALLOWED")
        path=self.root/(hashlib.sha256(url.encode()).hexdigest()+".bin")
        cached=path.is_file()
        if cached:
            if path.stat().st_size>self.protocol['max_object_bytes']:raise SourceBlocked("P93REF_CACHED_OBJECT_BUDGET")
            b=path.read_bytes()
        else:
            if self.requests>=self.protocol['max_requests']:raise SourceBlocked("P93REF_REQUEST_BUDGET")
            remaining=self.protocol['max_download_bytes']-self.downloaded
            if remaining<=0:raise SourceBlocked("P93REF_DOWNLOAD_BUDGET")
            limit=min(remaining,self.protocol['max_object_bytes']);self.requests+=1
            req=urllib.request.Request(url,headers={'User-Agent':'IGE-P1-P2-source-only-reference/1.0'})
            with urllib.request.urlopen(req,timeout=self.protocol['source_timeout_seconds']) as r:
                if urllib.parse.urlsplit(r.geturl()).hostname not in HOSTS:raise ValueError("P93REF_REDIRECT_HOST")
                declared=int(r.headers['Content-Length']) if 'Content-Length' in r.headers else None
                if declared is not None and declared>limit:raise SourceBlocked("P93REF_OBJECT_OR_DOWNLOAD_BUDGET")
                parts=[];received=0
                while received<limit:
                    part=r.read(min(1024*1024,limit-received))
                    if not part:break
                    received+=len(part);self.downloaded+=len(part);parts.append(part)
                # With unknown length, refuse a full boundary-sized object
                # conservatively rather than downloading a byte over budget.
                if received==limit and declared!=limit:raise SourceBlocked("P93REF_OBJECT_OR_DOWNLOAD_BUDGET")
                if declared is not None and received!=declared:raise SourceBlocked("P93REF_SOURCE_BODY_TRUNCATED")
                b=b''.join(parts)
            temporary=path.with_suffix('.partial');temporary.write_bytes(b);temporary.replace(path)
        if len(b)>self.protocol['max_object_bytes']:raise SourceBlocked("P93REF_CACHED_OBJECT_BUDGET")
        self.records.append({'url':url,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'from_cache':cached})
        return b


class ArcoSource:
    def __init__(self,base,cache):
        self.base,self.cache=base,cache
        raw=cache.fetch(base+'/.zmetadata');obj=json.loads(raw)
        self.m=obj['metadata'];self.metadata_sha=hashlib.sha256(raw).hexdigest()
        self.attrs=self.m['.zattrs'];self._coords={}

    def array(self,name):
        a=self.m[name+'/.zarray'];attrs=self.m[name+'/.zattrs']
        if a['zarr_format']!=2 or a['order']!='C' or a.get('filters') not in (None,[]):
            raise SourceBlocked("P93REF_UNSUPPORTED_ARRAY_ENCODING")
        if a['compressor'].get('id')!='blosc':raise SourceBlocked("P93REF_UNSUPPORTED_COMPRESSOR")
        return a,attrs

    def chunk(self,name,indices):
        a,_=self.array(name);dtype=np.dtype(a['dtype'])
        size=math.prod(a['chunks'])*dtype.itemsize
        if size>self.cache.protocol['max_decompressed_chunk_bytes']:raise SourceBlocked("P93REF_DECOMPRESSED_CHUNK_BUDGET")
        raw=self.cache.fetch(self.base+'/'+name+'/'+'.'.join(map(str,indices)))
        # Blosc v1 header: nbytes at offset 4, compressed length at offset 12.
        # Check before decode, so a mismatched payload cannot allocate > budget.
        if (len(raw)<16 or struct.unpack_from('<I',raw,4)[0]!=size or
                struct.unpack_from('<I',raw,12)[0]!=len(raw)):
            raise ValueError("P93REF_BLOSC_DECLARED_LENGTH")
        decoded=get_codec(a['compressor']).decode(raw)
        if len(decoded)!=size:raise ValueError("P93REF_DECODED_CHUNK_LENGTH")
        return np.frombuffer(decoded,dtype=dtype).reshape(a['chunks'])

    def coordinate(self,name):
        if name in self._coords:return self._coords[name]
        a,attrs=self.array(name)
        if attrs['_ARRAY_DIMENSIONS']!=[name] or len(a['shape'])!=1:raise ValueError("P93REF_COORDINATE_SCHEMA")
        result=np.concatenate([self.chunk(name,[i]) for i in range(math.ceil(a['shape'][0]/a['chunks'][0]))])[:a['shape'][0]]
        self._coords[name]=result
        return result

    def time_index(self,stamp):
        when=dt.datetime.fromisoformat(stamp)
        if when.tzinfo is not None or when.minute or when.second or when.microsecond:
            raise ValueError("P93REF_SOURCE_EXPECTS_EXPLICIT_UTC_HOUR_NODE")
        if not self.attrs['valid_time_start']<=stamp[:10]<=self.attrs['valid_time_stop']:
            raise SourceBlocked("P93REF_TIME_NOT_IN_STABLE_SOURCE_RANGE")
        a,attrs=self.array('time')
        if attrs.get('units')!='hours since 1900-01-01 00:00:00' or attrs.get('calendar')!='proleptic_gregorian':
            raise ValueError("P93REF_TIME_COORDINATE_SEMANTICS")
        expected=int((when-dt.datetime(1900,1,1)).total_seconds()/3600)
        first=int(self.chunk('time',[0])[0]);index=expected-first
        if not 0<=index<a['shape'][0]:raise SourceBlocked("P93REF_TIME_INDEX_OUTSIDE_SOURCE")
        value=self.chunk('time',[index//a['chunks'][0]])[index%a['chunks'][0]]
        if int(value)!=expected:raise ValueError("P93REF_TIME_VALUE_NOT_EXACT_REQUESTED_HOUR")
        return index

    def point_values(self,name,stamp,points,levels=None):
        a,attrs=self.array(name);dims=attrs['_ARRAY_DIMENSIONS']
        expected=['time','latitude','longitude'] if levels is None else ['time','hybrid','latitude','longitude']
        if dims!=expected or a['chunks'][0]!=1 or a['chunks'][-2:]!=a['shape'][-2:]:
            raise SourceBlocked("P93REF_CHUNK_LAYOUT_CHANGED_REVIEW_BUDGET_AND_READER")
        if levels is not None and not np.array_equal(self.coordinate('hybrid'),np.arange(1,138)):
            raise ValueError("P93REF_NATIVE_HYBRID_COORDINATES_NOT_1_TO_137")
        lat,lon=self.coordinate('latitude'),self.coordinate('longitude')
        indices=[]
        for la,lo in points:
            li=np.flatnonzero(abs(lat-la)<1e-6);lj=np.flatnonzero(abs(lon-lo)<1e-6)
            if len(li)!=1 or len(lj)!=1:raise ValueError("P93REF_EXACT_SOURCE_GRID_COORDINATE_REQUIRED")
            indices.append((int(li[0]),int(lj[0])))
        t=self.time_index(stamp)
        if levels is None:
            data=self.chunk(name,[t,0,0])
            out=np.array([data[0,i,j] for i,j in indices],float)
        else:
            if not levels or any(type(x) is not int or not 1<=x<=137 for x in levels):raise ValueError("P93REF_LEVEL_SELECTION")
            out=np.empty((len(points),len(levels)))
            for group in sorted({(level-1)//a['chunks'][1] for level in levels}):
                data=self.chunk(name,[t,group,0,0])
                for k,level in enumerate(levels):
                    if (level-1)//a['chunks'][1]!=group:continue
                    for p,(i,j) in enumerate(indices):out[p,k]=data[0,(level-1)%a['chunks'][1],i,j]
        if not np.isfinite(out).all():raise SourceBlocked("P93REF_SOURCE_VALUES_MISSING_OR_NONFINITE")
        return out

    def pv_coefficients(self):
        ta=self.array('temperature')[1];qa=self.array('specific_humidity')[1]
        if (ta.get('units')!='K' or qa.get('units')!='kg kg**-1' or
                ta.get('GRIB_typeOfLevel')!='hybrid' or qa.get('GRIB_typeOfLevel')!='hybrid'):
            raise ValueError("P93REF_MODEL_LEVEL_UNITS_OR_VERTICAL_TYPE")
        pv=ta.get('GRIB_pv')
        if not isinstance(pv,list) or len(pv)!=276 or pv!=qa.get('GRIB_pv'):
            raise ValueError("P93REF_T_Q_SOURCE_HYBRID_COEFFICIENTS_DIFFER")
        return pv[:138],pv[138:]


def four_corners(latitude,longitude):
    if not -89.75<=latitude<=89.75 or not 0<=longitude<359.75:raise ValueError("P93REF_REGIONAL_CORNER_DOMAIN")
    a,b=math.floor(latitude*4)/4,math.floor(longitude*4)/4
    return [(a,b),(a,b+.25),(a+.25,b),(a+.25,b+.25)]


def parse_station_metadata(country,raw):
    """Use native fields; a current barometer snapshot is not a height history."""
    if country=='AT':
        obj=json.loads(raw)
        station=next(s for s in obj['stations'] if int(s['id'])==30)
        result={'station_id':'30','latitude':float(station['lat']),'longitude':float(station['lon']),
        'general_station_height_m':station['altitude'],'barometer_height_m':None,
        'barometer_height_status':'NOT_IN_READ_SOURCE','thermo_nominal_AGL_m':2.,
        'thermo_absolute_history_status':'NOT_ESTABLISHED','height_valid_for_2021_sensor_validation':False,
        'source':AT,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'source_fields':station,'parameter_metadata':[x for x in obj['parameters'] if x['name'] in ('p','tl','rf')]}
    elif country=='CH':
        try:text=raw.decode('utf-8-sig');encoding='utf-8-sig'
        except UnicodeDecodeError:text=raw.decode('latin1');encoding='latin1'
        station=next(r for r in csv.DictReader(io.StringIO(text),delimiter=';') if r['station_abbr'].strip()=='DAV')
        baro=station.get('station_height_barometer_masl','').strip()
        result={'station_id':'DAV','latitude':float(station['station_coordinates_wgs84_lat']),
        'longitude':float(station['station_coordinates_wgs84_lon']),
        'general_station_height_m':float(station['station_height_masl']),
        'barometer_height_m':float(baro) if baro else None,
        'barometer_height_status':'SOURCE_CURRENT_SNAPSHOT_NOT_HISTORY' if baro else 'NOT_IN_READ_SOURCE',
        'thermo_nominal_AGL_m':2.,'thermo_absolute_history_status':'NOT_ESTABLISHED',
        'height_valid_for_2021_sensor_validation':False,'source':CH,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'source_encoding':encoding,'source_fields':station}
    elif country=='DE':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=('Metadaten_Geographie_00399.txt','Metadaten_Parameter_zehn_st_min_p0_00399.txt')
            if any(z.getinfo(name).file_size>2_000_000 for name in names):raise SourceBlocked('P93REF_STATION_METADATA_SIZE')
            geo,parameter=(z.read(name) for name in names)
        rows=list(csv.DictReader(io.StringIO(geo.decode('latin1')),delimiter=';'))
        eligible=[r for r in rows if r.get('von_datum','').strip()<='20210201' and
              (not r.get('bis_datum','').strip() or r['bis_datum'].strip()>='20210814')]
        if len(eligible)!=1:raise SourceBlocked("P93REF_DWD_GEOGRAPHY_HISTORY_NOT_UNIQUE_FOR_2021")
        station={k:v.strip() for k,v in eligible[0].items()}
        if int(station['Stations_id'])!=399:raise ValueError("P93REF_DWD_WRONG_STATION")
        description=parameter.decode('latin1')
        if 'P0_ST_10;momentaner Luftdruck Stationshoehe;' not in description or 'PP_ST_10;momentaner Luftdruck Normal Null;' not in description:
            raise ValueError("P93REF_DWD_PRESSURE_SEMANTICS_DRIFT")
        result={'station_id':'00399','latitude':float(station['Geogr.Breite']),
        'longitude':float(station['Geogr.Laenge']),'general_station_height_m':float(station['Stationshoehe']),
        'barometer_height_m':None,'barometer_height_status':'SEPARATE_SENSOR_HEIGHT_NOT_IN_READ_SOURCE',
        'thermo_nominal_AGL_m':None,'thermo_absolute_history_status':'NOT_ESTABLISHED',
        'height_valid_for_2021_sensor_validation':False,'source':DE,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'source_fields':station,'parameter_metadata_sha256':hashlib.sha256(parameter).hexdigest(),
        'absolute_pressure_field':'P0_ST_10','sea_level_pressure_field':'PP_ST_10',
        'observation_product_not_parsed_or_scored':True}
    else:raise ValueError('P93REF_COUNTRY_OUTSIDE_AT_DE_CH')
    if (not all(math.isfinite(float(result[k])) for k in ('latitude','longitude','general_station_height_m')) or
            not -90<=result['latitude']<=90 or not 0<=result['longitude']<360 or
            not -500<float(result['general_station_height_m'])<9000 or
            result['barometer_height_m'] is not None and not -500<result['barometer_height_m']<9000):
        raise ValueError('P93REF_STATION_COORDINATE_DOMAIN')
    result['status']='SOURCE_METADATA_READ_SENSOR_HISTORY_UNQUALIFIED'
    result['general_height_is_not_barometer_height']=True
    result['vertical_datum_history_status']='NATIONAL_MASL_METADATA_NOT_A_VERIFIED_ERA5_DATUM_TRANSFORMATION'
    return result


def station_metadata(cache):
    # Retain all countries in the denominator when one provider is unavailable.
    data={}
    for country,url in (('AT',AT),('CH',CH),('DE',DE)):
        try:
            raw=cache.fetch(url)
            data[country]=parse_station_metadata(country,raw)
        except (OSError,ValueError,KeyError,StopIteration,zipfile.BadZipFile) as exc:
            data[country]={'station_id':{'AT':'30','CH':'DAV','DE':'00399'}[country],
                'status':'SOURCE_BLOCKED','reason':type(exc).__name__+':'+str(exc),
                'height_valid_for_2021_sensor_validation':False}
    return data
