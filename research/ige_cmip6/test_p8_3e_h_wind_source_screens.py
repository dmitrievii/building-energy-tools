"""P8.3E-H contracts: mathematical/domain tests only, no unverified source claims."""
import datetime as dt, math, unittest
from p8_3e_h_wind_source_screens import (
    log_profile,era5_decode,axial_difference,lowest_opposing_axis,
    axial_wind,complete_days,block_bootstrap)

class TestWindSourceChecks(unittest.TestCase):
    def test_meteoswiss_parameter_table_utf8(self):
        from p8_3e_h_wind_source_screens import decode_wind_parameter_metadata
        raw = 'parameter;description\nfkl010h0;wind speed\ndkl010h0;wind direction\n'.encode('utf-8')
        records, codec = decode_wind_parameter_metadata(raw)
        self.assertEqual(codec, 'utf-8-sig')
        self.assertEqual(len(records), 2)

    def test_meteoswiss_parameter_table_cp1252(self):
        from p8_3e_h_wind_source_screens import decode_wind_parameter_metadata
        raw = b'parameter;description\nfkl010h0;vitesse du vent \xe8 10 m\ndkl010h0;direction\n'
        records, codec = decode_wind_parameter_metadata(raw)
        self.assertEqual(codec, 'cp1252')
        self.assertIn('\u00e8', records[0]['description'])
        self.assertEqual(len(records), 2)

    def test_meteoswiss_parameter_table_missing_parameters_rejected(self):
        from p8_3e_h_wind_source_screens import decode_wind_parameter_metadata
        with self.assertRaisesRegex(ValueError, 'WIND_PARAMETER_METADATA_FIELDS_NOT_FOUND'):
            decode_wind_parameter_metadata(b'parameter;description\nother;not wind\n')

    def test_log_identity(self):
        self.assertAlmostEqual(log_profile(4,10,10,.1),4)
    def test_log_higher_height(self):
        self.assertGreater(log_profile(4,5,10,.1),4)
    def test_no_fabricated_instrument_height(self):
        with self.assertRaisesRegex(ValueError,'UNVERIFIED'):log_profile(3,None,10,.03)
    def test_log_invalid_roughness(self):
        with self.assertRaises(ValueError):log_profile(3,10,10,10)
    def test_log_negative_speed(self):
        with self.assertRaises(ValueError):log_profile(-3,10,15,.1)
    def test_era5_rejects_empty(self):
        with self.assertRaisesRegex(ValueError,'ERA5_API_SCHEMA'):era5_decode({})
    def test_era5_source_hours_and_speed_units(self):
        start=dt.datetime(2024,1,1)
        hours=[(start+dt.timedelta(hours=i)).isoformat(timespec='minutes') for i in range(744)]
        fixture={'hourly':{'time':hours,'wind_speed_10m':[2.]*744,'wind_direction_10m':[180.]*744},
                 'hourly_units':{'wind_speed_10m':'m/s'}}
        self.assertEqual(len(era5_decode(fixture)),744)
        fixture['hourly_units']['wind_speed_10m']='km/h'
        with self.assertRaisesRegex(ValueError,'UNIT'):era5_decode(fixture)
    def test_era5_rejects_gaps(self):
        fixture={'hourly':{'time':['2024-01-01T00:00'],'wind_speed_10m':[1.],'wind_direction_10m':[0.]},
                 'hourly_units':{'wind_speed_10m':'m/s'}}
        with self.assertRaisesRegex(ValueError,'HOUR_COUNT'):era5_decode(fixture)
    def test_axis_180_wrap(self):
        self.assertAlmostEqual(axial_difference(0,180),0)
        self.assertAlmostEqual(axial_difference(10,170),20)
    def test_valley_axis_north_south(self):
        x=[100.]*12;x[0]=0;x[6]=0
        a,contrast=lowest_opposing_axis(x)
        self.assertEqual(a,0);self.assertGreater(contrast,0)
    def test_valley_axis_east_west(self):
        x=[100.]*12;x[3]=0;x[9]=0
        self.assertEqual(lowest_opposing_axis(x)[0],90)
    def test_reject_dem_nan(self):
        with self.assertRaisesRegex(ValueError,'DEM_RING'):lowest_opposing_axis([0.]*11+[math.nan])
    def test_axial_bimodal_north_south(self):
        x={dt.datetime(2024,1,1)+dt.timedelta(hours=i):{'speed':3,'direction':0 if i%2 else 180} for i in range(6200)}
        axis,r,n=axial_wind(x)
        self.assertLess(min(axis,180-axis),1e-8)
        self.assertAlmostEqual(r,1)
        self.assertEqual(n,6200)
    def test_complete_day_required(self):
        start=dt.datetime(2022,1,1)
        day={start+dt.timedelta(hours=i):{'speed':2,'direction':0} for i in range(23)}
        self.assertFalse(complete_days(day))
    def test_block_bootstrap_seeded(self):
        train={dt.date(2021,m,1):{h:{'speed':m,'direction':30} for h in range(24)} for m in range(1,13)}
        a=block_bootstrap(train,2025,77);b=block_bootstrap(train,2025,77)
        self.assertEqual(a,b)
        self.assertEqual(len(a),8760)
        self.assertEqual(a[dt.datetime(2025,5,1)]['speed'],5)
    def test_missing_training_month_fail_closed(self):
        train={dt.date(2021,1,1):{h:{'speed':3,'direction':20} for h in range(24)}}
        with self.assertRaisesRegex(ValueError,'NO_COMPLETE'):block_bootstrap(train,2025,123)

if __name__=='__main__':unittest.main()
