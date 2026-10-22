"""Historical height and identity oracles; no pressure residual is an input."""
import unittest

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_native_heights import at_historical_member,sensor_records


WSI='0-276-6-399';STAMPS=['2021-02-01T00:00','2021-08-01T23:00']


def xml(code=216,height=82.5,agl=None,start='2016-07-27T00:00:00Z',end='',reference='localGround',duplicate=False):
    agl_node='' if agl is None else '<w:heightAboveLocalReferenceSurface uom="m">'+str(agl)+'</w:heightAboveLocalReferenceSurface>'
    obs=f'''<o:OM_Observation><o:procedure><w:Process><w:deployment><w:Deployment>
    <w:validPeriod><g:TimePeriod><g:beginPosition>{start}</g:beginPosition><g:endPosition>{end}</g:endPosition></g:TimePeriod></w:validPeriod>
    <w:deployedEquipment><w:Equipment><w:geospatialLocation><w:GeospatialLocation>
    <w:geoLocation><g:Point><g:pos>52.520718 13.409375 {height}</g:pos></g:Point></w:geoLocation>
    <w:validPeriod><g:TimePeriod><g:beginPosition>{start}</g:beginPosition><g:endPosition>{end}</g:endPosition></g:TimePeriod></w:validPeriod>
    </w:GeospatialLocation></w:geospatialLocation></w:Equipment></w:deployedEquipment>
    {agl_node}<w:localReferenceSurface x:href="http://codes.wmo.int/wmdr/ReferenceSurfaceType/{reference}"/>
    </w:Deployment></w:deployment></w:Process></o:procedure>
    <o:observedProperty x:href="http://codes.wmo.int/wmdr/ObservedVariableAtmosphere/{code}"/></o:OM_Observation>'''
    return f'''<w:WIGOSMetadataRecord xmlns:w="http://def.wmo.int/wmdr/2017" xmlns:g="http://www.opengis.net/gml/3.2" xmlns:o="http://www.opengis.net/om/2.0" xmlns:x="http://www.w3.org/1999/xlink">
    <w:ObservingFacility><g:identifier>{WSI}</g:identifier>{obs+obs if duplicate else obs}</w:ObservingFacility></w:WIGOSMetadataRecord>'''.encode()


class HeightHistoryOracles(unittest.TestCase):
    def test_dated_barometer_82_5_is_not_station_ground_35_8(self):
        r=sensor_records(xml(),WSI,216,STAMPS,'BAROMETER')
        self.assertEqual(r['height_MSL_m'],82.5)
        self.assertTrue(r['historical_height_reference_confirmed'])
        self.assertFalse(r['datum_transformation_verified'])

    def test_instrument_msl_altitude_is_not_increased_by_agl_again(self):
        r=sensor_records(xml(code=224,height=37.8,agl=2,start='2015-07-01T00:00:00Z'),WSI,224,STAMPS,'THERMO_SENSOR')
        self.assertEqual(r['height_MSL_m'],37.8)
        self.assertFalse(r['AGL_added_to_absolute_altitude'])
        # An unspecified nested location period inherits the dated deployment,
        # not the current snapshot's epoch. This occurs in the AT source XML.
        from xml.etree import ElementTree as E
        node=E.fromstring(xml(code=224,height=368.7,agl=2))
        ns={'w':'http://def.wmo.int/wmdr/2017','g':'http://www.opengis.net/gml/3.2'}
        loc=node.find('.//w:GeospatialLocation/w:validPeriod/g:TimePeriod/g:beginPosition',ns);loc.text=None
        inherited=sensor_records(E.tostring(node),WSI,224,STAMPS,'THERMO_SENSOR')
        self.assertIn('INHERITS_DATED_DEPLOYMENT',inherited['geolocation_time_support'])

    def test_five_cm_sensor_not_substituted_for_two_metre_temperature(self):
        with self.assertRaises(SourceBlocked):sensor_records(xml(code=224,height=35.85,agl=.05),WSI,224,STAMPS,'THERMO_SENSOR')

    def test_current_2023_reference_cannot_qualify_2021(self):
        with self.assertRaises(SourceBlocked):sensor_records(xml(start='2023-06-29T00:00:00Z'),WSI,216,STAMPS,'BAROMETER')
        with self.assertRaises(SourceBlocked):sensor_records(xml(end='2020-12-31T00:00:00Z'),WSI,216,STAMPS,'BAROMETER')
        offset=sensor_records(xml(start='2021-02-01T01:00:00+02:00'),WSI,216,STAMPS,'BAROMETER')
        self.assertEqual(offset['height_MSL_m'],82.5)

    def test_wrong_wsi_or_property_rejected(self):
        with self.assertRaises(ValueError):sensor_records(xml(),'0-20000-0-10389',216,STAMPS,'BAROMETER')
        with self.assertRaises(SourceBlocked):sensor_records(xml(),WSI,224,STAMPS,'THERMO_SENSOR')

    def test_duplicate_program_affiliations_do_not_create_fake_ambiguity(self):
        a=sensor_records(xml(duplicate=True),WSI,216,STAMPS,'BAROMETER')
        self.assertEqual(a['height_MSL_m'],82.5)

    def test_contradictory_absolute_height_references_are_blocked(self):
        with self.assertRaisesRegex(SourceBlocked,'CONTRADICTORY'):
            sensor_records(xml(height=378.8,agl=366.7,reference='seaSurface'),WSI,216,STAMPS,'BAROMETER')

    def test_combined_at_series_requires_unique_dated_individual_member(self):
        old={'id':16412,'group_id':30,'type':'INDIVIDUAL','valid_from':'1988-06-01','valid_to':'2026-07-01'}
        new={'id':16414,'group_id':30,'type':'INDIVIDUAL','valid_from':'2022-09-01','valid_to':'2100-12-31'}
        self.assertEqual(at_historical_member({'stations':[old,new]},STAMPS)['id'],16412)
        with self.assertRaises(SourceBlocked):at_historical_member({'stations':[new]},STAMPS)
        with self.assertRaises(SourceBlocked):at_historical_member({'stations':[old,dict(old)]},STAMPS)


if __name__=='__main__':unittest.main()
