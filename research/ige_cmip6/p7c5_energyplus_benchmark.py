#!/usr/bin/env python3
"""Pinned EnergyPlus testfile adaptation, CLI execution and fail-closed SQL extraction.

The original EnergyPlus 26.2.0 testfile 1ZoneUncontrolled.idf is obtained from the
upstream tagged release. The suite DOES NOT call a proxy calculation EnergyPlus.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,sqlite3,subprocess,sys
from pathlib import Path

OFFICIAL_SOURCE="https://raw.githubusercontent.com/NatLabRockies/EnergyPlus/v26.2.0/testfiles/1ZoneUncontrolled.idf"
ENERGYPLUS_VERSION="26.2.0"

EXTRA_IDF="""
! P7C.5 independent benchmark additions: sealed no-window 232.25 m2 zone
ScheduleTypeLimits, IGE Setpoint Type, 0, 4, Discrete;
ScheduleTypeLimits, IGE Temperature, -60, 200, Continuous, Temperature;
Schedule:Constant, IGE Thermostat Choice, IGE Setpoint Type, 4;
Schedule:Constant, IGE Heat Setpoint, IGE Temperature, 20;
Schedule:Constant, IGE Cool Setpoint, IGE Temperature, 26;
ThermostatSetpoint:DualSetpoint, IGE Dual Setpoints, IGE Heat Setpoint, IGE Cool Setpoint;
ZoneControl:Thermostat, IGE Zone Thermostat, ZONE ONE, IGE Thermostat Choice, ThermostatSetpoint:DualSetpoint, IGE Dual Setpoints;
ZoneHVAC:EquipmentConnections, ZONE ONE, IGE Equipment List, IGE ZONE INLET, , IGE ZONE AIR NODE, IGE ZONE RETURN;
ZoneHVAC:EquipmentList, IGE Equipment List, SequentialLoad, ZoneHVAC:IdealLoadsAirSystem, IGE Ideal Loads, 1, 1;
ZoneHVAC:IdealLoadsAirSystem, IGE Ideal Loads, AlwaysOn, IGE ZONE INLET;
ZoneInfiltration:DesignFlowRate, IGE Infiltration, ZONE ONE, AlwaysOn, Flow/Zone, 0.080, , , , 1.0, 0.0, 0.0, 0.0;
Output:Variable, *, Zone Ideal Loads Supply Air Total Heating Energy, Hourly;
Output:Variable, *, Zone Ideal Loads Supply Air Total Cooling Energy, Hourly;
Output:Variable, *, Zone Mean Air Temperature, Hourly;
Output:Variable, *, Site Outdoor Air Drybulb Temperature, Hourly;
Output:SQLite, SimpleAndTabular;
Output:Table:SummaryReports, AnnualBuildingUtilityPerformanceSummary;
"""

def generate_from_official(txt: str)->str:
 if '1ZoneUncontrolled.idf' not in txt or 'ZONE ONE' not in txt: raise ValueError('Unexpected upstream benchmark model')
 if 'Version,26.2;' not in txt.replace(' ',''):raise ValueError('Requires officially pinned EnergyPlus 26.2 model')
 idf,n=re.subn(r'(?is)\bSimulationControl\s*,.*?;', 'SimulationControl, No, No, No, No, Yes, No, 1;', txt, count=1)
 if n!=1:raise ValueError('No unique SimulationControl')
 idf,n=re.subn(r'(?is)\bSite:Location\s*,.*?;', 'Site:Location, Graz, 46.983, 15.450, 1.0, 342;', idf, count=1)
 if n!=1:raise ValueError('No unique Site:Location')
 if not re.search(r'(?is)\bRunPeriod\s*,',idf):raise ValueError('No annual RunPeriod')
 if 'ZoneHVAC:IdealLoadsAirSystem,' in idf:raise ValueError('Official fixture unexpectedly already conditioned')
 return idf+'\n'+EXTRA_IDF

def check_errors(err_file:Path):
 if not err_file.exists():raise RuntimeError('EnergyPlus ERR diagnostic file missing')
 err=err_file.read_text(errors='replace')
 severe=len(re.findall(r'\*\*\s*Severe\s*\*\*',err,re.I))
 fatal=len(re.findall(r'\*\*\s*Fatal\s*\*\*',err,re.I))
 if severe or fatal:raise RuntimeError(f'EnergyPlus ERR reports severe={severe} fatal={fatal}; tail='+err[-3000:])
 if 'EnergyPlus Completed Successfully' not in err:raise RuntimeError('EnergyPlus did not confirm successful completion')
 return {'severe':severe,'fatal':fatal,'warning_count':len(re.findall(r'\*\*\s*Warning\s*\*\*',err,re.I))}

def extract_annual_sql(path: Path):
 if not path.is_file():raise RuntimeError('EnergyPlus did not produce SQL database')
 connection=sqlite3.connect(path)
 names=('Zone Ideal Loads Supply Air Total Heating Energy','Zone Ideal Loads Supply Air Total Cooling Energy', 'Zone Mean Air Temperature')
 with connection:
  exists={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if not {'ReportDataDictionary','ReportData'}.issubset(exists):raise RuntimeError('EnergyPlus SQL schema missing ReportData')
  result={}
  for variable in names:
   data=connection.execute("""SELECT rd.Value FROM ReportData rd JOIN ReportDataDictionary dd
    ON dd.ReportDataDictionaryIndex=rd.ReportDataDictionaryIndex
    WHERE dd.Name=? AND dd.ReportingFrequency='Hourly'""",(variable,)).fetchall()
   if not data:raise RuntimeError('Missing actual EnergyPlus hourly output: '+variable)
   values=[float(r[0]) for r in data]
   if variable.endswith('Energy'):
    if any(v<0 for v in values):raise RuntimeError('Negative ideal heating/cooling energy')
    result['heating_kwh' if 'Heating' in variable else 'cooling_kwh']=sum(values)/3.6e6
   else:
    result['zone_air_mean_C']=sum(values)/len(values)
   result['n_'+variable.replace(' ','_')]=len(values)
  return result

def benchmark(eplus:Path,idf:Path,weather_dir:Path,out:Path):
 out.mkdir(parents=True,exist_ok=True)
 files=sorted(weather_dir.glob('*.epw'))
 if len(files)<2:raise ValueError('Need baseline and future EPWs')
 records=[]
 for f in files:
  work=out/f.stem;work.mkdir(exist_ok=True)
  cmd=[str(eplus),'--weather',str(f.absolute()),'--output-directory',str(work.absolute()),str(idf.absolute())]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=350)
  (work/'stdout.txt').write_text(p.stdout[-18000:]);(work/'stderr.txt').write_text(p.stderr[-18000:])
  if p.returncode!=0:raise RuntimeError(f'EnergyPlus exit code {p.returncode} for {f.name}: '+p.stderr[-1200:]+' '+p.stdout[-1200:])
  errors=check_errors(work/'eplusout.err')
  energy=extract_annual_sql(work/'eplusout.sql')
  records.append({'EPW_filename':f.name,'EPW_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),**errors,**energy,'energyplus_real_executed':True})
 with (out/'p7c5_energyplus_real_benchmark.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,records[0].keys());w.writeheader();w.writerows(records)
 (out/'p7c5_energyplus_real_benchmark_audit.json').write_text(json.dumps({'energyplus_version':ENERGYPLUS_VERSION,'model':'upstream 1ZoneUncontrolled modified to ideal loads, 232.25m2, no window, 20/26C dual setpoints', 'run_weather_count':len(records),'authentic_meteonorm_executed_in_public_CI':False,'results':records,'production_epw_ready':False},indent=2)+'\n')
 return records

def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='action',required=True)
 b=sub.add_parser('build');b.add_argument('--official-idf',required=True);b.add_argument('--out',required=True)
 c=sub.add_parser('run');c.add_argument('--energyplus',required=True);c.add_argument('--idf',required=True);c.add_argument('--weather-dir',required=True);c.add_argument('--out',required=True)
 a=ap.parse_args()
 if a.action=='build':Path(a.out).write_text(generate_from_official(Path(a.official_idf).read_text()))
 else:print(json.dumps(benchmark(Path(a.energyplus),Path(a.idf),Path(a.weather_dir),Path(a.out)),indent=2))

if __name__=='__main__':main()