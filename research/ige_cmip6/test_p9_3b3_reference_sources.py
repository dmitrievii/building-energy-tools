"""Small real-codec fixtures: source semantics, bounds, and no hidden filling."""
import io
import json
import struct
import unittest
import zipfile

import numpy as np
from numcodecs import Blosc

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_reference_sources import ArcoSource,AT,CH,DE,four_corners,parse_station_metadata,station_metadata


TIME='2021-02-01T00:00'


class MemorySource:
    def __init__(self):
        self.protocol={'max_decompressed_chunk_bytes':80_000_000};self.data={};self.reads=[]

    def fetch(self,url):
        self.reads.append(url)
        if url not in self.data:raise SourceBlocked('FIXTURE_SOURCE_OBJECT_MISSING')
        return self.data[url]


def source_fixture():
    cache=MemorySource();meta={'.zattrs':{'valid_time_start':'2021-02-01','valid_time_stop':'2021-02-01'}}
    compressor=Blosc(cname='lz4',clevel=5,shuffle=1)
    def array(name,values,dims,attrs=None,chunks=None):
        v=np.asarray(values);shape=list(v.shape);ch=shape if chunks is None else chunks
        meta[name+'/.zarray']={'zarr_format':2,'shape':shape,'chunks':ch,'dtype':v.dtype.str,
            'order':'C','filters':None,'compressor':compressor.get_config()}
        meta[name+'/.zattrs']={'_ARRAY_DIMENSIONS':dims,**(attrs or {})}
        cache.data['https://fixture/'+name+'/'+'.'.join(['0']*v.ndim)]=compressor.encode(v)
    array('time',np.array([1061448],dtype='<i8'),['time'],
        {'units':'hours since 1900-01-01 00:00:00','calendar':'proleptic_gregorian'})
    array('latitude',np.array([47.25,47.],dtype='<f8'),['latitude'])
    array('longitude',np.array([15.25,15.5],dtype='<f8'),['longitude'])
    array('hybrid',np.arange(1,138,dtype='<i8'),['hybrid'])
    pv=[0.]*138+np.linspace(0,1,138).tolist()
    for name,units,offset in [('temperature','K',200),('specific_humidity','kg kg**-1',0)]:
        values=np.arange(137*4,dtype='<f4').reshape(1,137,2,2)+offset
        array(name,values,['time','hybrid','latitude','longitude'],
            {'units':units,'GRIB_typeOfLevel':'hybrid','GRIB_pv':pv})
    cache.data['https://fixture/.zmetadata']=json.dumps({'metadata':meta}).encode()
    return cache,ArcoSource('https://fixture',cache),meta


def at_fixture():
    return json.dumps({'stations':[{'id':'30','lat':47.08,'lon':15.448056,'altitude':366}],
        'parameters':[{'name':x} for x in ('p','tl','rf')]}).encode()


def ch_fixture():
    return ('station_abbr;station_name;station_coordinates_wgs84_lat;station_coordinates_wgs84_lon;'
        'station_height_masl;station_height_barometer_masl\nDAV;Davos Höhe;46.812969;9.843558;1594;1596\n').encode('latin1')


def de_fixture(semantics=True,epoch=True):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('Metadaten_Geographie_00399.txt',
            'Stations_id;Stationshoehe;Geogr.Breite;Geogr.Laenge;von_datum;bis_datum;Stationsname\n'
            '399;35.80;52.5198;13.4057;'+('20150701' if epoch else '20220101')+';;Berlin\n')
        z.writestr('Metadaten_Parameter_zehn_st_min_p0_00399.txt',
            ('P0_ST_10;momentaner Luftdruck Stationshoehe;hpa\n'
             'PP_ST_10;momentaner Luftdruck Normal Null;hpa\n') if semantics else 'P0_ST_10;MSL;hpa')
        # Deliberately corrupt product. A metadata reader must never open it.
        z.writestr('produkt_observations.txt',b'not observations\x00\xff')
    return buffer.getvalue()


class PublicSourceContracts(unittest.TestCase):
    def test_exact_time_and_vertical_axis_select_requested_point_and_bottom_levels(self):
        cache,source,m=source_fixture()
        # Independent calendar arithmetic, not a hard-coded array index.
        import datetime as dt
        hour=int((dt.datetime(2021,2,1)-dt.datetime(1900,1,1)).total_seconds()/3600)
        codec=Blosc(cname='lz4',clevel=5,shuffle=1)
        cache.data['https://fixture/time/0']=codec.encode(np.array([hour],dtype='<i8'))
        result=source.point_values('temperature',TIME,[(47.,15.5),(47.25,15.25)],[109,137])
        np.testing.assert_array_equal(result,[[200+108*4+3,200+136*4+3],[200+108*4,200+136*4]])
        self.assertEqual(cache.reads.count('https://fixture/temperature/0.0.0.0'),1)

    def test_wrong_calendar_units_and_offset_time_are_rejected(self):
        cache,source,m=source_fixture();source.m['time/.zattrs']['units']='days since 1900-01-01'
        with self.assertRaisesRegex(ValueError,'SEMANTICS'):source.time_index(TIME)
        with self.assertRaisesRegex(ValueError,'UTC_HOUR'):source.time_index(TIME+'+01:00')

    def test_37_pressure_levels_cannot_masquerade_as_137_hybrid_levels(self):
        cache,source,m=source_fixture()
        source._coords['hybrid']=np.arange(1,38)
        with self.assertRaisesRegex(ValueError,'HYBRID_COORDINATES'):source.point_values('temperature',TIME,[(47.,15.5)],[137])

    def test_tq_coefficients_and_units_must_match_before_reconstruction(self):
        cache,source,m=source_fixture();self.assertEqual(len(source.pv_coefficients()[0]),138)
        source.m['specific_humidity/.zattrs']['GRIB_pv']=source.m['specific_humidity/.zattrs']['GRIB_pv'].copy()
        source.m['specific_humidity/.zattrs']['GRIB_pv'][10]=1
        with self.assertRaisesRegex(ValueError,'COEFFICIENTS_DIFFER'):source.pv_coefficients()
        source.m['specific_humidity/.zattrs']['units']='g kg-1'
        with self.assertRaisesRegex(ValueError,'UNITS'):source.pv_coefficients()

    def test_budget_checked_before_source_object_is_read(self):
        cache,source,m=source_fixture();cache.protocol['max_decompressed_chunk_bytes']=16
        with self.assertRaisesRegex(SourceBlocked,'CHUNK_BUDGET'):source.chunk('temperature',[0,0,0,0])
        self.assertNotIn('https://fixture/temperature/0.0.0.0',cache.reads)

    def test_blosc_header_cannot_request_unbounded_allocation(self):
        cache,source,m=source_fixture();url='https://fixture/temperature/0.0.0.0'
        raw=bytearray(cache.data[url]);struct.pack_into('<I',raw,4,1_000_000_000);cache.data[url]=bytes(raw)
        with self.assertRaisesRegex(ValueError,'BLOSC_DECLARED_LENGTH'):source.chunk('temperature',[0,0,0,0])

    def test_missing_chunks_not_filled_and_offgrid_points_not_nearest_silently(self):
        cache,source,m=source_fixture()
        with self.assertRaises(SourceBlocked):source.chunk('temperature',[9,0,0,0])
        with self.assertRaisesRegex(ValueError,'EXACT_SOURCE_GRID'):source.point_values('temperature',TIME,[(47.08,15.448)],[137])

    def test_corner_geometry_fixed_without_observations(self):
        self.assertEqual(four_corners(46.812969,9.843558),[(46.75,9.75),(46.75,10.),(47.,9.75),(47.,10.)])
        self.assertEqual(len(set(four_corners(47.,15.5))),4)
        with self.assertRaises(ValueError):four_corners(90.,0.)


class StationHeightContracts(unittest.TestCase):
    def test_ch_native_barometer_field_distinct_from_general_height_and_epoch(self):
        s=parse_station_metadata('CH',ch_fixture())
        self.assertEqual((s['general_station_height_m'],s['barometer_height_m']),(1594.,1596.))
        self.assertEqual(s['source_encoding'],'latin1')
        self.assertFalse(s['height_valid_for_2021_sensor_validation'])

    def test_at_station_altitude_is_not_assigned_to_barometer(self):
        s=parse_station_metadata('AT',at_fixture())
        self.assertEqual(s['general_station_height_m'],366.)
        self.assertIsNone(s['barometer_height_m'])

    def test_dwd_historical_general_altitude_and_pressure_semantics_without_observations(self):
        s=parse_station_metadata('DE',de_fixture())
        self.assertEqual(s['general_station_height_m'],35.8)
        self.assertEqual(s['absolute_pressure_field'],'P0_ST_10')
        self.assertEqual(s['sea_level_pressure_field'],'PP_ST_10')
        self.assertIsNone(s['barometer_height_m'])
        self.assertTrue(s['observation_product_not_parsed_or_scored'])

    def test_dwd_wrong_epoch_and_absolute_sealevel_swap_cannot_pass(self):
        with self.assertRaisesRegex(SourceBlocked,'HISTORY'):parse_station_metadata('DE',de_fixture(epoch=False))
        with self.assertRaisesRegex(ValueError,'SEMANTICS'):parse_station_metadata('DE',de_fixture(semantics=False))

    def test_provider_failure_keeps_all_three_countries_in_denominator(self):
        c=MemorySource();c.data={AT:at_fixture(),DE:de_fixture()}
        s=station_metadata(c)
        self.assertEqual(set(s),{'AT','DE','CH'})
        self.assertEqual(s['CH']['status'],'SOURCE_BLOCKED')
        self.assertEqual(s['DE']['general_station_height_m'],35.8)


if __name__=='__main__':unittest.main()
