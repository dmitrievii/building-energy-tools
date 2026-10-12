"""Independent synthetic tests only; not a stand-in for EnergyPlus simulations."""
import csv,copy,importlib.util,unittest,tempfile
from pathlib import Path

ROOT=Path(__file__).parent

def load(name):
 p=ROOT/(name+'.py'); spec=importlib.util.spec_from_file_location(name,p); x=importlib.util.module_from_spec(spec);spec.loader.exec_module(x);return x

a=load('p7c5_epw_audit'); e=load('p7c5_energyplus_benchmark')

def demo():
 head=[['LOCATION','Graz','-','-','MN8','112400','46.983','15.450','1','342']]+[['COMMENT']]*7
 rows=[]
 import datetime
 for day in range(365):
  d=datetime.date(2005,1,1)+datetime.timedelta(days=day)
  for hr in range(1,25):
   row=['2005',str(d.month),str(d.day),str(hr),'60','test','12','5','63','98000', '0','0','310','0','0','0','0','0','0','9999','180','2','5','4','9999','99999','9','999999999','10','0.15','0','0','0.2','0','99']
   if 9<=hr<=17:
    for j,val in [(13,'350'),(14,'450'),(15,'110'),(16,'40000'),(17,'50000'),(18,'12000')]:row[j]=val
   rows.append(row)
 numeric={j:__import__('numpy').array([float(r[j]) for r in rows]) for j in range(35) if j not in (5,27)}
 return head,rows,numeric

class Tests(unittest.TestCase):
 def test_official_idf_guard_invalid(self):
  with self.assertRaises(ValueError):e.generate_from_official('Version, 26.2;')
 def test_official_idf_generation_annual_ideal(self):
  sample='! 1ZoneUncontrolled.idf\nVersion,26.2;\nSimulationControl,No,No,No,Yes,No;\nSite:Location,Denver,39,-105,-7,1800;\nRunPeriod,Annual,1,1,,12,31;\nZone,ZONE ONE;\n'
  gen=e.generate_from_official(sample)
  self.assertIn('IdealLoadsAirSystem',gen)
  self.assertIn('SimulationControl, No, No, No, No, Yes',gen)
  self.assertIn('Site:Location, Graz',gen)
 def test_singleton_summary_report_from_upstream_not_duplicated(self):
  upstream='! 1ZoneUncontrolled.idf\nVersion,26.2;\nSimulationControl,No,No,No,Yes,No;\nSite:Location,Denver,39,-105,-7,1800;\nRunPeriod,Annual,1,1,,12,31;\nZone,ZONE ONE;\nOutput:Table:SummaryReports, AllSummary;\n'
  gen=e.generate_from_official(upstream)
  self.assertEqual(gen.lower().count('output:table:summaryreports,'),1)
 def test_baseline_no_solar_change(self):
  base=demo();out=a.check(base,base)
  self.assertEqual(out['counts']['changed_GHI_hours_with_original_unchanged_global_lux'],0)
  self.assertEqual(out['counts']['wind_direction_missing_hours'],0)
 def test_solar_lux_inconsistency_detected(self):
  base=demo();h,rr,cs=base;new=copy.deepcopy(rr);new[12][13]='375'
  import numpy as np
  modified={j:np.array([float(r[j]) for r in new]) for j in range(35) if j not in (5,27)}
  out=a.check(base,(h,new,modified))
  self.assertTrue(out['research_warnings']['solar_luminous_cross_field_unmorphed'])
  self.assertEqual(out['counts']['changed_GHI_hours_with_original_unchanged_global_lux'],1)
 def test_immutable_wind_violation(self):
  base=demo();h,rr,cs=base;new=copy.deepcopy(rr);new[0][20]='20'
  import numpy as np
  modified={j:np.array([float(r[j]) for r in new]) for j in range(35) if j not in (5,27)}
  with self.assertRaises(ValueError):a.check(base,(h,new,modified))
 def test_zero_energy_sql_fail(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(RuntimeError):e.extract_annual_sql(Path(td)/'no.sql')
 def test_malformed_EPERR_missing(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(RuntimeError):e.check_errors(Path(td)/'eplusout.err')
 def test_epw_structure_required(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'wrong.epw';p.write_text('LOCATION,Graz\n')
   with self.assertRaises(Exception):a.epw(p)

if __name__=='__main__':unittest.main()