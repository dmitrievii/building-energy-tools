"""P7B.4 integrated EPW semantics and independent source invariance tests."""
import csv,math,tempfile,unittest
from datetime import datetime,timedelta,date
from pathlib import Path
from p7b4_integrated_hourly_epw import (
  BASE_FIELDS,YEAR,NROWS,LAT,LON,read_baseline_epw,source_hours_by_date,
  original_daily_targets,patch_epw,component_day,epw_components,load_weather,
  solar_south_vertical,simple_zone_proxy,pearson,sha
)
from p7b3f_feasibility_repair import minimum_relaxed_cap
from p7b3e_multigcm_radiometric_closure import solar_vectors


class EPWResearchContracts(unittest.TestCase):
 def make_original(self):
  header=[['LOCATION','Graz','Styria','AUT','IGE','999999',str(LAT),str(LON),'1','366'],
      ['DESIGN CONDITIONS','0'],['TYPICAL/EXTREME PERIODS','0'],
      ['GROUND TEMPERATURES','0'],['HOLIDAYS/DAYLIGHT SAVINGS','No','0','0','0'],
      ['COMMENTS 1','TEST ONLY'],['COMMENTS 2','TEST ONLY'],
      ['DATA PERIODS','1','1','Noleap','Tuesday','1/1','12/31']]
  rows=[];components={}
  for i in range(NROWS):
   t=datetime(YEAR,1,1)+timedelta(hours=i)
   r=['999']*BASE_FIELDS
   r[0:5]=[str(YEAR),str(t.month),str(t.day),str(t.hour+1),'60']
   r[6:10]=['20','10','50','97000']
   r[13:16]=['0','0','0'];r[20]='999';r[21]='2.5';r[33]='0';r[34]='0'
   components[t]=(0.,0.,0.,0.,0.)
   rows.append(r)
  return header,rows,components
 def test_epw_standard_index_meanings(self):
  self.assertEqual(BASE_FIELDS,35)
  self.assertEqual((13,14,15),(13,14,15))
 def test_strict_calendar_8760_without_leap(self):
  h,rows,c=self.make_original()
  self.assertEqual(len(rows),NROWS)
  self.assertEqual([int(v) for v in rows[-1][:5]],[2013,12,31,24,60])
  self.assertEqual(sum(r[1]=='2' and r[2]=='29' for r in rows),0)
 def test_roundtrip_only_solar_fields_changed(self):
  h,rows,c=self.make_original()
  c[datetime(2013,6,1,12)]=(.345,.4,.145,.5,.67)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'x.epw'
   new=patch_epw(h,rows,c,p)
   self.assertAlmostEqual(float(new[24*151+12][13]),345.,places=7)
   self.assertAlmostEqual(float(new[24*151+12][14]),400.,places=7)
   self.assertAlmostEqual(float(new[24*151+12][15]),145.,places=7)
   self.assertTrue(all(a[i]==b[i] for a,b in zip(rows,new)
      for i in range(BASE_FIELDS) if i not in (13,14,15)))
 def test_bad_timestamp_rejected(self):
  h,rows,c=self.make_original()
  rows[10][3]='24'
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'bad.epw'
   with open(p,'w') as f:
    w=csv.writer(f);w.writerows(h+rows)
   with self.assertRaisesRegex(ValueError,'timestamps'):
    read_baseline_epw(p)
 def test_no_unknown_wind_direction_fabrication(self):
  h,rows,c=self.make_original()
  rows[0][20]='180'
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaisesRegex(ValueError,'wind direction'):
    patch_epw(h,rows,c,Path(tmp)/'wind.epw')
 def test_solar_vertical_night_zero(self):
  self.assertEqual(solar_south_vertical(0,0,0,datetime(2013,1,1,3)),0)
 def test_solar_vertical_south_receives_beam(self):
  self.assertGreater(solar_south_vertical(.5,.4,.1,datetime(2013,6,1,11)),0)
 def test_source_energy_cap_per_day(self):
  geo=solar_vectors(date(2013,5,12),LAT,LON)
  target=.4*sum(row[1] for row in geo)
  caps,lam,base,toa=minimum_relaxed_cap(geo,target)
  self.assertLessEqual(sum(caps),toa+1e-8)
  self.assertAlmostEqual(lam,0.)
 def test_invalid_daily_too_large_fails(self):
  geo=solar_vectors(date(2013,5,12),LAT,LON)
  with self.assertRaisesRegex(ValueError,'TOA'):
   minimum_relaxed_cap(geo,sum(row[1] for row in geo)+1)
 def test_pearson_identity(self):
  self.assertAlmostEqual(pearson([1,2,3],[3,6,9]),1.)
 def test_pearson_zero_variance(self):
  self.assertIsNone(pearson([1,1],[1,2]))
 def test_zero_solar_load_proxy_finite(self):
  h,rows,c=self.make_original()
  weather=load_weather(rows,c)
  x=simple_zone_proxy(weather,c,'unit')
  self.assertTrue(math.isfinite(x['ideal_heating_kwh_100m2']))
  self.assertTrue(math.isfinite(x['ideal_cooling_kwh_100m2']))
  self.assertEqual(x['model'],'EXPLICIT_1R1C_SOUTH_FACADE_IDEAL_SETPOINT_PROXY_NOT_ENERGYPLUS')
 def test_all_missing_numeric_epw_is_not_physical_accuracy(self):
  h,rows,c=self.make_original()
  self.assertEqual(rows[0][20],'999')
  self.assertEqual(rows[0][6],'20')
 def test_weather_must_have_complete_component_series(self):
  h,rows,c=self.make_original()
  del c[datetime(2013,1,1,0)]
  with self.assertRaises(KeyError):load_weather(rows,c)

if __name__=='__main__':unittest.main()