"""Dated instrument references from WMDR, distinct from station ground metadata.

WMDR instrument geospatial altitude is read once as MSL altitude. AGL is a
separate reference distance and is not added to that altitude a second time.
An MSL-to-ERA5 datum transformation is not certified by this parser.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from xml.etree import ElementTree as ET

from p9_3b3_compare_vertical_frame import SourceBlocked,fingerprint
from p9_3b3_native_sources import utc_hour
from p9_3b3_reference_run import distance_km
from p9_3b3_reference_sources import AT,CH,DE,parse_station_metadata


W='http://def.wmo.int/wmdr/2017';G='http://www.opengis.net/gml/3.2'
O='http://www.opengis.net/om/2.0';H='{http://www.w3.org/1999/xlink}href'
NS={'w':W,'g':G,'o':O}


def dates(parent):
    if parent is None:return None,None
    a=parent.find('.//g:beginPosition',NS);b=parent.find('.//g:endPosition',NS)
    return ((a.text or '').strip() or None if a is not None else None,
            (b.text or '').strip() or None if b is not None else None)


def includes(period,stamps):
    start,end=period
    if not start:return False
    def utc(value):
        parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is not None:parsed=parsed.astimezone(dt.timezone.utc)
        return parsed.replace(tzinfo=None)
    a=utc(start);b=utc(end) if end else None
    return all(a<=utc_hour(t) and (b is None or utc_hour(t)<b) for t in stamps)


def facility(root,wsi):
    nodes=root.findall('.//w:ObservingFacility',NS)
    if len(nodes)!=1:raise ValueError('P93N_ONE_WMDR_FACILITY_REQUIRED')
    f=nodes[0];identity=f.find('g:identifier',NS)
    if identity is None or (identity.text or '').strip()!=wsi:raise ValueError('P93N_WMDR_WRONG_STATION')
    return f


def sensor_records(raw,wsi,property_code,stamps,role):
    root=ET.fromstring(raw);f=facility(root,wsi);rows=[]
    expected='http://codes.wmo.int/wmdr/ObservedVariableAtmosphere/'+str(property_code)
    for obs in f.findall('.//o:OM_Observation',NS):
        prop=obs.find('o:observedProperty',NS)
        if prop is None or prop.get(H)!=expected:continue
        for dep in obs.findall('.//w:Deployment',NS):
            period=dates(dep.find('w:validPeriod',NS))
            if not includes(period,stamps):continue
            agl_node=dep.find('w:heightAboveLocalReferenceSurface',NS)
            agl=None if agl_node is None or not (agl_node.text or '').strip() else float(agl_node.text)
            if agl is not None and agl_node.get('uom')!='m':raise ValueError('P93N_HEIGHT_UNIT_M_REQUIRED')
            ref=dep.find('w:localReferenceSurface',NS);reference='' if ref is None else ref.get(H,'')
            if role=='THERMO_SENSOR' and (agl!=2.0 or not reference.endswith(('/localGround','/naturalGround'))):
                continue  # Do not substitute the separate 5-cm temperature.
            locations=dep.findall('w:deployedEquipment/w:Equipment/w:geospatialLocation/w:GeospatialLocation',NS)
            candidates=[]
            for loc in locations:
                position=loc.find('w:geoLocation/g:Point/g:pos',NS)
                if position is None or not (position.text or '').strip():continue
                loc_period=dates(loc.find('w:validPeriod',NS))
                if loc_period[0] and not includes(loc_period,stamps):continue
                vector=[float(x) for x in position.text.split()]
                if len(vector)!=3 or not all(math.isfinite(x) for x in vector):continue
                height=vector[2]
                if reference.endswith('/seaSurface') and agl is not None and abs(height-agl)>1e-6:
                    raise SourceBlocked('P93N_CONTRADICTORY_ABSOLUTE_HEIGHT_REFERENCES')
                candidates.append({'latitude':vector[0],'longitude':vector[1],'height_MSL_m':height,
                    'equipment_geolocation_period':list(loc_period),
                    'geolocation_time_support':'EXPLICIT_LOCATION_PERIOD' if loc_period[0] else 'INHERITS_DATED_DEPLOYMENT_UNSPECIFIED_LOCATION_PERIOD',
                    'height_origin':'INSTRUMENT_GEOSPATIAL_POSITION_MSL'})
            if not candidates and reference.endswith('/seaSurface') and agl is not None:
                # An explicitly MSL-referenced deployment height can stand on
                # its own; a dated facility position is still needed for xy.
                for loc in f.findall('w:geospatialLocation/w:GeospatialLocation',NS):
                    pos=loc.find('w:geoLocation/g:Point/g:pos',NS)
                    if pos is None or not includes(dates(loc.find('w:validPeriod',NS)),stamps):continue
                    vector=[float(x) for x in pos.text.split()]
                    if len(vector)<2:continue
                    candidates.append({'latitude':vector[0],'longitude':vector[1],'height_MSL_m':agl,
                        'equipment_geolocation_period':[None,None],'height_origin':'DEPLOYMENT_HEIGHT_ABOVE_SEA_SURFACE'})
            for candidate in candidates:
                if not -90<=candidate['latitude']<=90 or not 0<=candidate['longitude']<360 or not -500<candidate['height_MSL_m']<9000:
                    raise ValueError('P93N_WMDR_COORDINATE_DOMAIN')
                rows.append({**candidate,'role':role,'observed_property':expected,
                    'deployment_period':list(period),'AGL_or_reference_distance_m':agl,'local_reference_surface':reference,
                    'AGL_added_to_absolute_altitude':False,'historical_height_reference_confirmed':True,
                    'datum_transformation_verified':False,'geopotential_height_approximation':'DECLARED_H_EQUALS_MSL_HEIGHT_CONSTANT_G0',
                    'source_WSI':wsi,'source_sha256':hashlib.sha256(raw).hexdigest()})
    # Program affiliations can repeat the same physical deployment. Preserve
    # one distinct geometric/history state, never pick by a pressure residual.
    distinct={fingerprint({k:v for k,v in r.items() if k!='source_sha256'}):r for r in rows}
    if not distinct:raise SourceBlocked('P93N_NO_DATED_SENSOR_REFERENCE:'+str(property_code))
    if len(distinct)!=1:raise SourceBlocked('P93N_SENSOR_REFERENCE_AMBIGUOUS:'+str(property_code))
    return next(iter(distinct.values()))


def at_historical_member(metadata,stamps):
    eligible=[s for s in metadata['stations'] if s.get('group_id')==30 and s.get('type')=='INDIVIDUAL'
              and includes((s['valid_from'],s['valid_to']),stamps)]
    if len(eligible)!=1 or int(eligible[0]['id'])!=16412:
        raise SourceBlocked('P93N_AT_COMBINED_30_UNIQUE_2021_MEMBER_NOT_16412')
    return eligible[0]


def historical_heights(cache,protocol):
    stamps=[day+'T'+hour for day in protocol['development_days'] for hour in ('00:00','23:00')]
    result={}
    for country,url in (('AT',AT),('DE',DE),('CH',CH)):
        try:
            raw=cache.fetch(url);meta=parse_station_metadata(country,raw)
            member=at_historical_member(json.loads(raw),stamps) if country=='AT' else None
            wsi=protocol['station_WSI'][country];source='https://oscar.wmo.int/surface/rest/api/wmd/download/'+wsi
            xml=cache.fetch(source,limit=3_000_000)
            sensors={}
            for key,code,role in (('pressure',216,'BAROMETER'),('temperature',224,'THERMO_SENSOR'),('RH_water',12249,'THERMO_SENSOR')):
                sensors[key]=sensor_records(xml,wsi,code,stamps,role)
            # Match the provider's dated station identity, allowing the actual
            # separate instrument coordinates. No inference from p values.
            m=member if member is not None else {'lat':meta['latitude'],'lon':meta['longitude']}
            separation=distance_km(m['lat'],m['lon'],sensors['temperature']['latitude'],sensors['temperature']['longitude'])
            if separation>.5:raise SourceBlocked('P93N_PROVIDER_WMDR_IDENTITY_SPATIAL_MISMATCH')
            result[country]={'status':'HISTORICAL_SENSOR_HEIGHT_REFERENCES_CONFIRMED_CONDITIONAL_MSL_DATUM',
                'station_id':meta['station_id'],'provider_metadata':meta,'historical_member':member,
                'source_WMDR':source,'source_WMDR_sha256':hashlib.sha256(xml).hexdigest(),'sensors':sensors,
                'provider_to_thermo_distance_km':separation,'pressure_to_thermo_horizontal_distance_km':distance_km(
                    sensors['pressure']['latitude'],sensors['pressure']['longitude'],sensors['temperature']['latitude'],sensors['temperature']['longitude']),
                'RH_convention':'WATER_WMDR_OBSERVED_VARIABLE_12249',
                'datum_transformation_verified':False,'operational_ready':False}
        except (SourceBlocked,OSError,KeyError,ValueError,ET.ParseError) as exc:
            result[country]={'status':'SOURCE_BLOCKED','station_id':protocol['station_ids'][country] if 'station_ids' in protocol else {'AT':'30','DE':'00399','CH':'DAV'}[country],
                'reason':type(exc).__name__+':'+str(exc),'datum_transformation_verified':False}
    return result
