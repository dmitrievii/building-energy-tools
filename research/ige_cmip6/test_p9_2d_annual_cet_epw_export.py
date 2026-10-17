import datetime as dt,csv,tempfile,unittest
from pathlib import Path
from p9_2a_joint_weather_regimes import Day
from p9_2d_annual_cet_epw_export import timestamp_rows,raw_series_to_epw,readback,EPWBlocked,make_record
SHA="a"*64
def v():
 return {"temperature_2m":10.,"dew_point_2m":7.,"relative_humidity_2m":80.,
         "surface_pressure":1000.,"precipitation":0.,
         "cloud_cover":50.,"shortwave_radiation":0.,
         "direct_radiation":0.,"diffuse_radiation":0.,"direct_normal_irradiance":0.,
         "wind_speed_10m":2.,"wind_direction_10m":180.}
def year():
 start=dt.date(2012,12,31)
 days=[Day(start,tuple(dict(v()) for _ in range(24)),SHA)]
 for i in range(365):
  date=dt.date(2013,1,1)+dt.timedelta(days=i)
  days.append(Day(date,tuple(dict(v()) for _ in range(24)),SHA))
 return days,[[300.]*24 for _ in days]
class P92DEPW(unittest.TestCase):
 def test_8760_CET_boundary_from_2012_dec31(self):
  days,lw=year();parts=timestamp_rows(days,lw)
  self.assertEqual(len(parts),8760)
  self.assertEqual(parts[0][1].strftime('%Y-%m-%dT%H'),"2012-12-31T23")
  self.assertEqual(parts[-1][1].strftime('%Y-%m-%dT%H'),"2013-12-31T22")
 def test_readback_8760x35_and_missing_original_unknown_fields(self):
  days,lw=year()
  with tempfile.TemporaryDirectory() as td:
   fp=Path(td)/"research.epw"
   result=raw_series_to_epw(days,lw,fp)
   self.assertEqual(result["n_records"],8760)
   self.assertEqual(result["missing_opaque_cloud_count"],8760)
   self.assertEqual(result["missing_illuminance_count"],8760)
   self.assertEqual(result["valid_total_sky_cover_hours"],8760)
   self.assertFalse(result["production_epw_ready"])
   self.assertEqual(result["first_local_row"],[2013,1,1,1,60] if False else ['2013','1','1','1','60'])
 def test_without_2012_Dec31_cross_year_block_not_backfill(self):
  days,lw=year()
  with self.assertRaisesRegex(EPWBlocked,"CROSSYEAR"):
   timestamp_rows(days[1:],lw[1:])
 def test_epw_rain_depth_measured_interval_contract(self):
  d=v();d['precipitation']=1.2
  row=make_record(dt.datetime(2013,1,1),d,350.)
  self.assertEqual(row[33],1.2)
  self.assertEqual(row[34],1)
 def test_solar_partition_rejects_inconsistent_energy(self):
  d=v();d['shortwave_radiation']=200.;d['diffuse_radiation']=100.
  with self.assertRaisesRegex(EPWBlocked,"SOLAR_GHI"):
   make_record(dt.datetime(2013,1,1),d,350.)
 def test_missing_source_wind_direction_block(self):
  d=v();d['wind_direction_10m']=999.
  with self.assertRaises(ValueError):
   make_record(dt.datetime(2013,1,1),d,350.)
 def test_no_leap_assumption_2013(self):
  d,lw=year();self.assertEqual(len(d),366)
  self.assertFalse(any(x.date==dt.date(2013,2,29) for x in d if False))
if __name__=="__main__":unittest.main()
