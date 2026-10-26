"""V1 published-temperature operators; nominal support is not an instrument filter.

This module adds a separate DWD ten-minute route. It never changes A1's
unresolved TT_TU contract or transports urban-station semantics to it.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import csv
import io
import json
import math
import zipfile
import numpy as np
import pandas as pd

from epw_climate_analyzer.station_reconstruction import (
    StationReference, StationBatch, T, _build, _field, _number,
    decode_geosphere_hourly, decode_meteoswiss_hourly, model_reference_operator)
from epw_climate_analyzer.station_admission import admitted_reference


@dataclass(frozen=True)
class TimeOperator:
    country: str
    product: str
    field: str
    published_operator: str
    nominal_offsets_minutes: tuple[int, ...]
    model_node_weights: tuple[float, float]
    source_QC_stratum: str
    inference: bool
    instrument_filter_period_certified: bool = False


def operator(country, product, field, first, last):
    a,b=pd.Timestamp(first),pd.Timestamp(last)
    if a.tz is None or b.tz is None or a>b:
        raise ValueError('V1_AWARE_ORDERED_SUPPORT_REQUIRED')
    if (country,product,field)==('AT','klima-v2-1h','tl'):
        return TimeOperator(country,product,field,'published_nominal_node',(0,),(0.,1.),
            'AT_MANUAL_ORIGINAL_22_PRIMARY; AUTO_ORIGINAL_12_SECONDARY',True)
    if (country,product,field)==('DE','climate-10_minutes-air_temperature','TT_10'):
        if a<pd.Timestamp('2000-01-01',tz='UTC'):
            raise ValueError('V1_DE_PRE_2000_MEZ_NOT_ADMITTED')
        return TimeOperator(country,product,field,'published_nominal_node',(0,),(0.,1.),
            'DE_10MIN_QN3_AUTOMATIC_CONTROL_AND_CORRECTION_NOT_HOURLY_QN10',False)
    if (country,product,field)==('CH','ogd-smn-h','tre200h0'):
        if a<pd.Timestamp('2018-01-01',tz='UTC'):
            raise ValueError('V1_CH_PRE_2018_OPERATOR_NOT_ADMITTED')
        return TimeOperator(country,product,field,'mean_six_10min_nominal_nodes',
            (-50,-40,-30,-20,-10,0),(5/12,7/12),
            'CH_PUBLISHED_HISTORICAL_NO_PER_ROW_FLAG',False)
    if (country,product,field)==('CH','ogd-smn-t','tre200s0'):
        if a<pd.Timestamp('2018-01-01',tz='UTC'):
            raise ValueError('V1_CH_SECONDARY_PRE_2018_NOT_REGISTERED')
        return TimeOperator(country,product,field,'published_nominal_node',(0,),(0.,1.),
            'CH_T_HISTORICAL_NO_PER_ROW_FLAG_SECONDARY',False)
    raise ValueError('V1_PRODUCT_FIELD_OPERATOR_NOT_ADMITTED')


def dwd_geometry(raw, sid, first, last):
    """Metadata-only ten-minute ZIP, three distinct dated facts required."""
    from a12_prepare_history import dated_rows
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=['Metadaten_'+k+'_'+sid+'.txt' for k in
               ('Geographie','Geraete_Lufttemperatur','Parameter')]
        if any(z.getinfo(n).file_size>100000 for n in names):
            raise ValueError('V1_DE_METADATA_MEMBER_BUDGET')
        bodies={n:z.read(n) for n in names}
    geo,device,parameter=[dated_rows(bodies[n],sid,a,b,first,last,**kwargs)
        for n,a,b,kwargs in zip(names,
            ('von_datum','Von_Datum','Von_Datum'),
            ('bis_datum','Bis_Datum','Bis_Datum'),
            ({},{},{'parameter':'TT_10'}))]
    if any(len(x)!=1 for x in (geo,device,parameter)):
        raise ValueError('V1_DE_DATED_PARAMETER_GEOMETRY_NOT_UNIQUE')
    g,d,p=geo[0],device[0],parameter[0]
    lat,lon=float(g['Geogr.Breite']),float(g['Geogr.Laenge'])
    ground,height=float(g['Stationshoehe']),float(d['Geberhoehe ueber Grund [m]'])
    if abs(ground-float(d['Stationshoehe [m]']))>1e-9:
        raise ValueError('V1_DE_DATED_GROUND_CONFLICT')
    if abs(lat-float(d['Geo. Breite [Grad]']))>.005000001 or abs(lon-float(d['Geo. Laenge [Grad]']))>.005000001:
        raise ValueError('V1_DE_COORDINATE_ROUNDING_CELL_CONFLICT')
    if p['Einheit']!='°C' or 'momentane Lufttemperatur in 2m' not in p['Parameterbeschreibung'] or p['Zusatz-Info']!='HHMM UTC':
        raise ValueError('V1_DE_TT10_DEFINITION_OR_UTC_NOT_CONFIRMED')
    return {'latitude':lat,'longitude':lon,'AGL_m':height,
        'local_reference_surface':'localGround','site_altitude_as_reported_m':ground,
        'geospatial_z_as_reported_m':ground+height,
        'height_origin':'DWD_DATED_GROUND_PLUS_SEPARATE_SENSOR_AGL',
        'deployment_period_inclusive_dates':[d['Von_Datum'],d['Bis_Datum']],
        'geography_period_inclusive_dates':[g['von_datum'],g['bis_datum']],
        'device_type':d['Geraetetyp Name'],'parameter_row':p,
        'datum_transformation_verified':False}, {n:sha256(v).hexdigest() for n,v in bodies.items()}


def text_csv(raw):
    try: text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    reader=csv.DictReader(io.StringIO(text),delimiter=';')
    if not reader.fieldnames:raise ValueError('V1_CSV_HEADER_MISSING')
    reader.fieldnames=[s.strip() for s in reader.fieldnames]
    if len(set(reader.fieldnames))!=len(reader.fieldnames):raise ValueError('V1_DUPLICATE_CSV_COLUMNS')
    return reader


def decode_at(raw, station):
    """Native integer-valued QC codes accept JSON 22 and 22.0 equally.

    A value is never rounded into another QC class. Original packet bytes
    and their hash remain authoritative; only integer code representation
    is canonicalized for the existing A1 decoder.
    """
    obj=json.loads(raw)
    for feature in obj.get('features',[]):
        parameters=feature['properties']['parameters']
        if 'tl_flag' not in parameters:raise ValueError('V1_AT_NATIVE_TL_FLAG_REQUIRED')
        flags=[]
        for q in parameters['tl_flag']['data']:
            if q is None:flags.append(q)
            elif isinstance(q,(int,float)) and not isinstance(q,bool) and math.isfinite(q) and float(q).is_integer():flags.append(int(q))
            elif isinstance(q,str) and q.strip().isdigit():flags.append(int(q))
            else:raise ValueError('V1_AT_NONINTEGER_NATIVE_QC_CODE')
        parameters['tl_flag']['data']=flags
    decoded=decode_geosphere_hourly(json.dumps(obj,ensure_ascii=False,allow_nan=False).encode(),station)
    data=decoded.data.copy(deep=True);data.attrs['source_sha256']=sha256(raw).hexdigest()
    data.attrs['QC_representation']='integer-valued native code canonicalization only; no QC policy change'
    return StationBatch(station,data,decoded.fields,sha256(raw).hexdigest())


def selected_swiss(raw, sid, first, last, *, field='tre200h0', hour_nodes_only=True):
    """Select station/time support before numeric extraction, including spinup."""
    product='ogd-smn-h' if field=='tre200h0' else 'ogd-smn-t'
    op=operator('CH',product,field,first,last)
    reader=text_csv(raw)
    if not {'station_abbr','reference_timestamp',field}<=set(reader.fieldnames):
        raise ValueError('V1_CH_SOURCE_SCHEMA')
    if any(field+s in reader.fieldnames for s in ('_flag','_qc')):
        raise ValueError('V1_UNDOCUMENTED_SWISS_ROW_QC')
    a,b=pd.Timestamp(first),pd.Timestamp(last);selected=[];seen=set();previous=None
    lower,upper=a.strftime('%Y%m%d%H%M'),b.strftime('%Y%m%d%H%M')
    for r in reader:
        if None in r:raise ValueError('V1_CSV_EXTRA_COLUMNS')
        if r['station_abbr'].strip().upper()!=sid:raise ValueError('V1_CROSS_STATION_SOURCE')
        stamp=r['reference_timestamp'].strip()
        if len(stamp)!=16:raise ValueError('V1_CH_TIMESTAMP_FORMAT')
        if stamp[6:10]!=str(a.year):continue
        # Compare calendar strings before parsing or extracting temperatures.
        # This also bounds work for the large decade ten-minute controls.
        iso=stamp[6:10]+stamp[3:5]+stamp[:2]+stamp[11:13]+stamp[14:16]
        if not lower<=iso<=upper:continue
        t=pd.to_datetime(stamp,format='%d.%m.%Y %H:%M',utc=True)
        if not a<=t<=b:continue
        if t.minute:
            if field=='tre200h0':raise ValueError('V1_CH_H_NONHOUR_REFERENCE')
            if t.minute%10:raise ValueError('V1_CH_T_MISALIGNED_REFERENCE')
            if hour_nodes_only:continue  # endpoint test is HH:00, never an average
        if t in seen or (previous is not None and t<previous):raise ValueError('V1_DUPLICATE_OR_REORDERED_SOURCE')
        seen.add(t);previous=t;selected.append((t,r[field]))
    index=pd.DatetimeIndex([t for t,_ in selected],tz='UTC')
    values=pd.Series([_number(v) for _,v in selected],index=index,dtype=float,name=T)
    values=values.where(values.between(-80,65));values.attrs.update(unit='°C',reference_operator=op.published_operator)
    return values,pd.Series(values.notna().to_numpy(),index=index,dtype=bool)


def selected_dwd(raw, station, first, last):
    """Original ten-minute records; retain only full-hour TT_10, never mean it."""
    operator('DE','climate-10_minutes-air_temperature','TT_10',first,last)
    r=text_csv(raw)
    if not {'STATIONS_ID','MESS_DATUM','QN','TT_10'}<=set(r.fieldnames):
        raise ValueError('V1_DE_TT10_SOURCE_SCHEMA')
    a,b=pd.Timestamp(first),pd.Timestamp(last);times=[];values=[];flags=[];seen=set();previous=None
    lower,upper=a.strftime('%Y%m%d%H%M'),b.strftime('%Y%m%d%H%M')
    for row in r:
        if None in row:raise ValueError('V1_CSV_EXTRA_COLUMNS')
        if int(row['STATIONS_ID'])!=int(station.station_id):raise ValueError('V1_CROSS_STATION_SOURCE')
        stamp=row['MESS_DATUM'].strip()
        if len(stamp)!=12 or not stamp.isdigit():raise ValueError('V1_DE_TT10_TIMESTAMP_FORMAT')
        minute=int(stamp[-2:])
        if minute%10:raise ValueError('V1_DE_TT10_OFF_GRID')
        if not lower<=stamp<=upper or minute:continue
        t=pd.to_datetime(stamp,format='%Y%m%d%H%M',utc=True)
        if t in seen or (previous is not None and t<previous):raise ValueError('V1_DUPLICATE_OR_REORDERED_SOURCE')
        seen.add(t);previous=t;times.append(t);values.append(_number(row['TT_10']));flags.append(row['QN'].strip())
    spec=_field('TT_10','°C','published_nominal_node')
    if not times:return None
    return _build(station,raw,times,{T:values},{T:flags},{T:spec},
        {'primary':['3'],'secondary':[],'label':'DWD_TT10_QN3_AUTOMATIC_NOT_HOURLY_QN10'})


def bind(batch, record, *, provider_field):
    """V1 field-specific admission without altering the old A1 DE contract."""
    station=admitted_reference(record)
    if batch is None:return None
    if station.key!=batch.station.key:raise ValueError('V1_CROSS_STATION_ADMISSION')
    field=batch.fields[T]
    if field['provider_field']!=provider_field or field['unit']!='°C' or field['time_operator']!=record['time_contract']['operator']:
        raise ValueError('V1_FIELD_OPERATOR_OR_UNIT_MISMATCH')
    index=batch.data.index
    if not ((index>=pd.Timestamp(record['reference_first_UTC']))&(index<=pd.Timestamp(record['reference_last_UTC']))).all():
        raise ValueError('V1_SERIES_OUTSIDE_METADATA_ADMISSION')
    return batch.series(T),batch.data['quality_accepted__'+T].copy()
