"""Native ERA5 source lineage: bounded I/O, exact times, SH and N320 support.

Original GRIB and its CO-Zarr coefficient copy are checked before station
scoring. No AR regular-grid surface field is spliced into this native chain.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import struct
import threading
import urllib.parse
import urllib.request

import numpy as np

from p9_3b3_compare_vertical_frame import SourceBlocked,fingerprint
from p9_3b3_reference_sources import ArcoSource


HOSTS={'storage.googleapis.com','oscar.wmo.int','codes.wmo.int',
       'dataset.api.hub.geosphere.at','data.geo.admin.ch','opendata.dwd.de'}


class NativeCache:
    def __init__(self,root,protocol,cache_only=False):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.protocol=protocol;self.downloaded=0;self.requests=0;self.records=[]
        self._lock=threading.Lock();self._reserved=0
        self.cache_only=cache_only

    def fetch(self,url,limit=None,byte_range=None):
        u=urllib.parse.urlsplit(url)
        if u.scheme!='https' or u.hostname not in HOSTS or u.port not in (None,443):
            raise ValueError('P93N_SOURCE_HOST_NOT_ALLOWED')
        cap=min(limit or self.protocol['max_object_bytes'],self.protocol['max_object_bytes'])
        if byte_range is not None:
            a,b=byte_range
            if type(a) is not int or type(b) is not int or not 0<=a<=b or b-a+1>cap:
                raise SourceBlocked('P93N_RANGE_BUDGET')
            cap=b-a+1
        suffix='' if byte_range is None else '|bytes='+str(byte_range[0])+'-'+str(byte_range[1])
        path=self.root/(hashlib.sha256((url+suffix).encode()).hexdigest()+'.bin')
        cached=path.is_file()
        if cached:
            if path.stat().st_size>cap:raise SourceBlocked('P93N_CACHED_OBJECT_BUDGET')
            body=path.read_bytes()
        else:
            if self.cache_only:raise SourceBlocked('P93N_CACHE_ONLY_OBJECT_NOT_AVAILABLE')
            with self._lock:
                if self.requests>=self.protocol['max_requests']:raise SourceBlocked('P93N_REQUEST_BUDGET')
                if self.downloaded+self._reserved>=self.protocol['max_download_bytes']:
                    raise SourceBlocked('P93N_DOWNLOAD_BUDGET')
                self.requests+=1
            # Headers do not consume the HTTP-body byte budget. Reserving the
            # 80 MB object ceiling before learning Content-Length can reject
            # concurrent 1-2 MB chunks whose actual combined bodies fit.
            # Reserve the declared body atomically before the first body read.
            reserved=0
            headers={'User-Agent':'IGE-P9.3B3-native-source-lineage/1.0'}
            if byte_range is not None:
                a,b=byte_range
                headers['Range']='bytes='+str(a)+'-'+str(b)
            req=urllib.request.Request(url,headers=headers)
            try:
              with urllib.request.urlopen(req,timeout=self.protocol['source_timeout_seconds']) as response:
                if urllib.parse.urlsplit(response.geturl()).hostname not in HOSTS:
                    raise ValueError('P93N_REDIRECT_HOST')
                if byte_range is not None:
                    expected='bytes '+str(byte_range[0])+'-'+str(byte_range[1])+'/'
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(expected):
                        raise SourceBlocked('P93N_RANGE_IGNORED_REFUSE_WHOLE_MONTH_DOWNLOAD')
                length=int(response.headers['Content-Length']) if 'Content-Length' in response.headers else None
                if length is not None and not 0<=length<=cap:raise SourceBlocked('P93N_OBJECT_OR_DOWNLOAD_BUDGET')
                with self._lock:
                    remaining=self.protocol['max_download_bytes']-self.downloaded-self._reserved
                    if length is None:
                        read_cap=min(cap,remaining)
                        if read_cap<=0:raise SourceBlocked('P93N_DOWNLOAD_BUDGET')
                    else:
                        if length>remaining:raise SourceBlocked('P93N_DOWNLOAD_BUDGET')
                        read_cap=length
                    self._reserved+=read_cap;reserved=read_cap
                parts=[];received=0
                while received<read_cap:
                    part=response.read(min(1024*1024,read_cap-received))
                    if not part:break
                    parts.append(part);received+=len(part)
                    with self._lock:self.downloaded+=len(part);self._reserved-=len(part)
                    reserved-=len(part)
                if length is None and received==read_cap:raise SourceBlocked('P93N_OBJECT_OR_DOWNLOAD_BUDGET')
                if length is not None and received!=length:raise SourceBlocked('P93N_TRUNCATED_BODY')
                body=b''.join(parts)
            finally:
                with self._lock:self._reserved-=reserved
            tmp=path.with_suffix('.partial');tmp.write_bytes(body);tmp.replace(path)
        if byte_range is not None and len(body)!=byte_range[1]-byte_range[0]+1:
            raise SourceBlocked('P93N_RANGE_BODY_LENGTH')
        self.records.append({'url':url,'range':list(byte_range) if byte_range is not None else None,
            'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'from_cache':cached})
        return body


def utc_hour(stamp):
    value=dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))
    if value.utcoffset() not in (None,dt.timedelta(0)) or value.minute or value.second or value.microsecond:
        raise ValueError('P93N_EXACT_UTC_HOUR_REQUIRED')
    return value.replace(tzinfo=None)


def cf_seconds(units):
    kind,origin=units.split(' since ',1)
    scale={'hours':3600,'seconds':1,'days':86400}.get(kind)
    if scale is None:raise ValueError('P93N_TIME_UNITS')
    return scale,dt.datetime.fromisoformat(origin)


class NativeSource(ArcoSource):
    def _vector(self,name):
        if name not in self._coords:
            a,attrs=self.array(name)
            if len(a['shape'])!=1:raise ValueError('P93N_ONE_DIMENSIONAL_SOURCE_COORDINATE')
            self._coords[name]=np.concatenate([self.chunk(name,[i]) for i in range(math.ceil(a['shape'][0]/a['chunks'][0]))])[:a['shape'][0]]
        return self._coords[name]

    def time_index(self,stamp):
        when=utc_hour(stamp)
        if not self.attrs['valid_time_start']<=when.date().isoformat()<=self.attrs['valid_time_stop']:
            raise SourceBlocked('P93N_TIME_OUTSIDE_STABLE_SOURCE')
        a,attrs=self.array('time');values=self._vector('time')
        if attrs.get('calendar') not in ('proleptic_gregorian','gregorian'):
            raise ValueError('P93N_TIME_CALENDAR')
        scale,origin=cf_seconds(attrs['units']);wanted=(when-origin).total_seconds()/scale
        stride=3600/scale;offset=(wanted-float(values[0]))/stride
        if offset!=int(offset) or not 0<=offset<len(values):raise SourceBlocked('P93N_EXACT_SOURCE_HOUR_ABSENT')
        i=int(offset)
        if values[i]!=wanted or (i and values[i]-values[i-1]!=stride):
            raise ValueError('P93N_SOURCE_TIME_VALUE_OR_HOURLY_STRIDE')
        if 'valid_time/.zarray' in self.m:
            _,va=self.array('valid_time');vs,vo=cf_seconds(va['units'])
            if vo+dt.timedelta(seconds=float(self._vector('valid_time')[i])*vs)!=when:
                raise ValueError('P93N_VALID_TIME_MISMATCH')
        if 'step/.zarray' in self.m and 'step' not in self._coords:
            spec=self.m['step/.zarray']
            if spec['shape']!=[] or spec['compressor'] is not None:raise ValueError('P93N_ANALYSIS_STEP_SCHEMA')
            raw=self.cache.fetch(self.base+'/step/0');step=np.frombuffer(raw,dtype=np.dtype(spec['dtype']))
            if step.shape!=(1,) or step[0]!=0:raise ValueError('P93N_NONZERO_FORECAST_STEP')
            self._coords['step']=step
        return i

    def levels(self,levels):
        a,attrs=self.array('hybrid')
        if a['shape']!=[137] or a['chunks']!=[1] or attrs['_ARRAY_DIMENSIONS']!=['hybrid']:
            raise ValueError('P93N_HYBRID_AXIS_SCHEMA')
        missing=[level for level in levels if 'level_'+str(level) not in self._coords]
        if not missing:return
        def read(level):
            value=self.chunk('hybrid',[level-1])[0]
            if value!=level:raise ValueError('P93N_HYBRID_INDEX_NOT_ACTUAL_REQUESTED_LEVEL')
            return level,value
        with ThreadPoolExecutor(max_workers=6) as pool:
            for level,value in pool.map(read,missing):self._coords['level_'+str(level)]=value

    def field(self,name,stamp,level=None):
        a,attrs=self.array(name);i=self.time_index(stamp)
        dims=['time','values'] if level is None else ['time','hybrid','values']
        chunks=[1,a['shape'][-1]] if level is None else [1,1,a['shape'][-1]]
        if attrs['_ARRAY_DIMENSIONS']!=dims or a['chunks']!=chunks:
            raise SourceBlocked('P93N_NATIVE_CHUNK_LAYOUT_CHANGED')
        if level is not None:
            if type(level) is not int or not 1<=level<=137:raise ValueError('P93N_LEVEL_DOMAIN')
            self.levels([level])
        vector=self.chunk(name,[i,0] if level is None else [i,level-1,0]).reshape(-1)
        if not np.isfinite(vector).all():raise SourceBlocked('P93N_MISSING_NATIVE_VALUES')
        return vector


def real_coefficients(values,truncation):
    """ECMWF m-major Re/Im pairs -> SHTOOLS real 4π, no-CS coefficients.

    ECMWF normalized P has (1/2) integral P² dmu = 1. Real 4π P has
    another sqrt(2) for m>0; summing conjugate waves gives C=sqrt(2)Re X,
    S=-sqrt(2)Im X. The zonal m=0 coefficient is copied once.
    """
    v=np.asarray(values,float);n=truncation
    if type(n) is not int or not 0<=n<=639 or v.shape!=((n+1)*(n+2),) or not np.isfinite(v).all():
        raise ValueError('P93N_SPECTRAL_COEFFICIENT_COUNT_OR_DOMAIN')
    out=np.zeros((2,n+1,n+1));j=0
    for m in range(n+1):
        length=n+1-m;pair=v[2*j:2*(j+length)].reshape(-1,2)
        if m==0 and np.any(pair[:,1]!=0):raise ValueError('P93N_NONREAL_ZONAL_COEFFICIENT')
        factor=1. if m==0 else math.sqrt(2)
        out[0,m:,m]=factor*pair[:,0];out[1,m:,m]=-factor*pair[:,1];j+=length
    return out


def synthesize(values,points,truncation=639):
    import pyshtools
    c=real_coefficients(values,truncation)
    if any(not -90<=a<=90 or not 0<=b<360 for a,b in points):raise ValueError('P93N_SPECTRAL_POINT_DOMAIN')
    return np.array([pyshtools.expand.MakeGridPoint(c,float(a),float(b),norm=1,csphase=1)
                     for a,b in points],float)


class GaussianGrid:
    def __init__(self,latitude,longitude):
        self.latitude,self.longitude=(np.asarray(v,float) for v in (latitude,longitude))
        if (self.latitude.ndim!=1 or self.longitude.shape!=self.latitude.shape or
                not np.isfinite(np.r_[self.latitude,self.longitude]).all()):raise ValueError('P93N_GAUSSIAN_COORDINATE_SCHEMA')
        self.rings=np.unique(self.latitude)
        self.ring_indices={float(a):np.flatnonzero(self.latitude==a) for a in self.rings}
        for js in self.ring_indices.values():
            if self.longitude[js][0]!=0 or np.any(np.diff(self.longitude[js])<=0) or self.longitude[js][-1]>=360:
                raise ValueError('P93N_GAUSSIAN_LONGITUDE_ORDER')

    def neighbors(self,latitude,longitude):
        if not self.rings[0]<latitude<self.rings[-1] or not 0<=longitude<360:
            raise SourceBlocked('P93N_REGIONAL_TARGET_OUTSIDE_GAUSSIAN_GRID')
        i=int(np.searchsorted(self.rings,latitude,side='right'));result=[]
        for ring in self.rings[i-1:i+1]:
            js=self.ring_indices[float(ring)];values=self.longitude[js]
            k=int(np.searchsorted(values,longitude,side='right'))
            result.extend([int(js[(k-1)%len(js)]),int(js[k%len(js)])])
        if len(set(result))!=4:raise ValueError('P93N_FOUR_DISTINCT_GEOMETRIC_NEIGHBORS_REQUIRED')
        return result

    def points(self,indices):return [(float(self.latitude[i]),float(self.longitude[i])) for i in indices]


def original_surface_grib(cache,url,stamp,param_id):
    """Read the first exact message by HTTP range, never an entire month."""
    import eccodes
    head=cache.fetch(url,byte_range=(0,15))
    if head[:4]!=b'GRIB' or head[7]!=2:raise ValueError('P93N_ORIGINAL_GRIB2_HEADER')
    length=struct.unpack_from('>Q',head,8)[0]
    if not 16<length<=cache.protocol['max_original_GRIB_message_bytes']:
        raise SourceBlocked('P93N_ORIGINAL_GRIB_MESSAGE_BUDGET')
    raw=cache.fetch(url,byte_range=(0,length-1));handle=eccodes.codes_new_from_message(raw)
    try:
        metadata={k:eccodes.codes_get(handle,k) for k in ('edition','paramId','gridType','J','K','M','level','dataDate','dataTime','packingType','bitsPerValue','typeOfLevel','step','dataType')}
        wanted=utc_hour(stamp)
        if (metadata['paramId']!=param_id or metadata['gridType']!='sh' or
                (metadata['J'],metadata['K'],metadata['M'])!=(639,639,639) or metadata['level']!=1 or
                metadata['typeOfLevel']!='hybrid' or metadata['step']!=0 or metadata['dataType']!='an' or
                metadata['dataDate']!=int(wanted.strftime('%Y%m%d')) or metadata['dataTime']!=wanted.hour*100):
            raise ValueError('P93N_ORIGINAL_GRIB_IDENTITY_DATE_GRID_OR_PARAMETER')
        values=eccodes.codes_get_array(handle,'values').copy()
        metadata['hybrid_pv_sha256']=fingerprint(eccodes.codes_get_array(handle,'pv').tolist())
    finally:eccodes.codes_release(handle)
    return values,{'url':url,'range':[0,length-1],'bytes':length,'sha256':hashlib.sha256(raw).hexdigest(),**metadata}


def verify_grib_copy(original,co_values):
    if not np.array_equal(np.asarray(original,dtype='<f4'),np.asarray(co_values,dtype='<f4')):
        raise SourceBlocked('P93N_ORIGINAL_GRIB_CO_FLOAT32_COPY_NOT_EXACT')
    return {'status':'ORIGINAL_GRIB_TO_CO_FLOAT32_EXACT','coefficient_count':len(original),
            'max_abs_float32_cast_error':float(np.max(abs(np.asarray(original,float)-co_values)))}
