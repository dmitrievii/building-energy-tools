#!/usr/bin/env python3
"""IGE P8.4D real native EnergyPlus wind+stack opening-area sensitivity.

Actual native EPlus annual simulations, directional and speed variations on
the public P7B5 research EPW. NOT AirflowNetwork/CFD nor calibrated windows.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import subprocess
from pathlib import Path

import p7c5_energyplus_benchmark as ep7
from p8_4d_epw_wind_qualification import read_epw,write_epw,sha

EPW_SETTINGS=((.5,0.),(1.0,0.),(1.5,0.),(1.0,90.))
MODEL_PARAMETERS={
    "opening_area_m2":.25,"opening_effectiveness":"Autocalculate",
    "opening_outward_normal_from_north_deg":180.,
    "height_difference_m":.5,
    "opening_discharge_coefficient":"Autocalculate",
    "min_indoor_C":21.,"max_indoor_C":40.,
    "minimum_indoor_minus_outdoor_K":.5,
    "min_outdoor_C":10.,"max_outdoor_C":28.,
    "max_outdoor_wind_speed_mps":15.,
}
WIND_AND_STACK=(
    "ZoneVentilation:WindandStackOpenArea,\n"
    "  IGE Research WindAndStack Opening,\n"
    "  ZONE ONE,\n"
    "  0.25,\n"                  # Aopen (m²)
    "  AlwaysOn,\n"              # Schedule
    "  Autocalculate,\n"         # angle-sensitive opening effectiveness Cw
    "  180.0,\n"                # opening outward normal
    "  0.5,\n"                  # height difference
    "  Autocalculate,\n"         # discharge coefficient Cd
    "  21.0,\n"                 # minimum indoor
    "  ,\n"                    # min indoor schedule
    "  40.0,\n"                 # maximum indoor
    "  ,\n"                    # max indoor schedule
    "  0.5,\n"                  # minimum indoor-outdoor temperature delta
    "  ,\n"                    # delta schedule
    "  10.0,\n"                 # min outdoor
    "  ,\n"                    # min outdoor schedule
    "  28.0,\n"                 # max outdoor
    "  ,\n"                    # max outdoor schedule
    "  15.0;\n"                # max wind speed
)
VENT_VAR="Zone Ventilation Standard Density Volume Flow Rate"
HEAT_VAR="Zone Ideal Loads Supply Air Total Heating Energy"
COOL_VAR="Zone Ideal Loads Supply Air Total Cooling Energy"


def build_native_opening_model(official):
    model=ep7.generate_from_official(official)
    if "ZoneVentilation:WindandStackOpenArea" in model:
        raise AssertionError("P8D_DUPLICATE_NATIVE_OPENING")
    return model+"\n"+WIND_AND_STACK+(
        "\nOutput:Variable, *, Zone Ventilation Standard Density Volume Flow Rate, Hourly;\n"
    )


def wind_and_azimuth_fixture(source,scale,rotate_deg):
    if scale<=0 or not math.isfinite(scale) or not math.isfinite(rotate_deg):
        raise ValueError("P8D_INVALID_WIND_TEST_CONTROL")
    out=[x.copy() for x in source]
    for old,row in zip(source,out):
        w=float(old[21]);direction=float(old[20])
        row[21]=f"{w*scale:.3f}"
        if direction==999:
            row[20]=old[20]
        elif rotate_deg:
            row[20]=f"{(direction+rotate_deg)%360.:.3f}"
        if any(old[i]!=row[i] for i in range(35) if i not in (20,21)):
            raise AssertionError("P8D_OPENING_TEST_MUTATES_NONWIND_EPW_FIELD")
    return out


def read_energyplus_sql(path):
    cx=sqlite3.connect(path)
    names=(VENT_VAR,HEAT_VAR,COOL_VAR)
    with cx:
        rows=cx.execute("""SELECT dd.Name, dd.Units, COUNT(rd.Value),
          SUM(rd.Value), MIN(rd.Value), MAX(rd.Value)
          FROM ReportData rd JOIN ReportDataDictionary dd
          ON dd.ReportDataDictionaryIndex=rd.ReportDataDictionaryIndex
          WHERE dd.ReportingFrequency='Hourly' AND dd.Name IN (?,?,?)
          GROUP BY dd.Name,dd.Units""",names).fetchall()
    cx.close()
    vals={}
    for name,unit,n,total,minimum,maximum in rows:
        if n<8760 or not all(math.isfinite(x) for x in (total,minimum,maximum)):
            raise RuntimeError("P8D_NATIVE_OPENING_INVALID_SQL_"+name)
        vals[name]={"n_hourly":n,"unit":unit,"mean":total/n,"total":total,
                    "max":maximum,"min":minimum}
    if set(vals)!=set(names):
        raise RuntimeError("P8D_NATIVE_OPENING_MISSING_VENTILATION_OR_LOAD_REPORT")
    if any(vals[n]["min"]<-1e-8 for n in names):
        raise RuntimeError("P8D_NATIVE_OPENING_NEGATIVE_FLOW_OR_ENERGY")
    return {
        "ventilation_mean_m3_s":vals[VENT_VAR]["mean"],
        "ventilation_peak_m3_s":vals[VENT_VAR]["max"],
        "heating_kwh":vals[HEAT_VAR]["total"]/3.6e6,
        "cooling_kwh":vals[COOL_VAR]["total"]/3.6e6,
        "reported_variables":vals,
    }


def run(binary,official,base,out):
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    header,original,source=read_epw(base)
    idf=folder/"research_wind_stack.idf"
    idf.write_text(build_native_opening_model(Path(official).read_text()))
    series=[]
    for speed_multiplier,rotate in EPW_SETTINGS:
        label=f"speed_{speed_multiplier:.1f}_azimuth_{int(rotate)}"
        weather=folder/(label+".epw")
        new=wind_and_azimuth_fixture(original,speed_multiplier,rotate)
        write_epw(weather,header,new)
        target=folder/label;target.mkdir(exist_ok=True)
        task=[str(Path(binary).absolute()),"--weather",str(weather.absolute()),
              "--output-directory",str(target.absolute()),str(idf.absolute())]
        executed=subprocess.run(task,capture_output=True,text=True,timeout=420)
        (target/"stdout.txt").write_text(executed.stdout[-11000:])
        (target/"stderr.txt").write_text(executed.stderr[-11000:])
        if executed.returncode!=0:
            e=target/"eplusout.err"
            tail=e.read_text(errors="replace")[-12000:] if e.exists() else executed.stderr[-4000:]
            raise RuntimeError("P8D_NATIVE_EPLUS_OPENING_FAILED_"+label+": "+tail)
        warnings=ep7.check_errors(target/"eplusout.err")
        result=read_energyplus_sql(target/"eplusout.sql")
        series.append({
            "scenario":label,"speed_multiplier":speed_multiplier,
            "azimuth_rotation_deg":rotate,
            "changed_EPWs_columns":[21]+([20] if rotate else []),
            "same_temperature_humidity_solar_precipitation":True,
            "native_EnergyPlus":True,"weather_sha256":sha(weather),
            **warnings,**result,
        })
        weather.unlink()  # never archive full derived EPW
    basecase=next(x for x in series if x["speed_multiplier"]==1 and x["azimuth_rotation_deg"]==0)
    low=next(x for x in series if x["speed_multiplier"]==.5)
    high=next(x for x in series if x["speed_multiplier"]==1.5)
    rotated=next(x for x in series if x["azimuth_rotation_deg"]==90)
    nonzero=basecase["ventilation_mean_m3_s"]>1e-8
    magnitude=abs(high["ventilation_mean_m3_s"]-low["ventilation_mean_m3_s"])>1e-6
    directional=abs(rotated["ventilation_mean_m3_s"]-basecase["ventilation_mean_m3_s"])>1e-7
    if not (nonzero and magnitude and directional):
        raise AssertionError("P8D_NATIVE_OPENING_WIND_SPEED_OR_AZIMUTH_INSENSITIVE")
    artifact={
        "phase":"IGE_P8_4D_NATIVE_WIND_AND_STACK_OPENING_RESEARCH",
        "official_energyplus_version":ep7.ENERGYPLUS_VERSION,
        "source_EPWs":"P7B5 research-only (not original Meteonorm)",
        "source_EPWs_sha256":source["sha256"],
        "n_real_annual_simulations":len(series),
        "opening_parameters":MODEL_PARAMETERS,
        "actual_wind_speed_sensitivity_measured":magnitude,
        "actual_wind_direction_sensitivity_measured":directional,
        "nat_ventilation_research_executed":True,
        "real_building_window_configuration_validated":False,
        "AirflowNetwork_or_CFD_validation_performed":False,
        "original_hourly_EPWs_published":False,
        "production_epw_ready":False,
        "results":series,
    }
    (folder/"p8_4d_native_energyplus_4_opening_cases_aggregate.json").write_text(
        json.dumps(artifact,indent=2,sort_keys=True)+"\n")
    print("IGE_P8_4D_OPENING",json.dumps({
        "n_runs":len(series),
        "mean_ventilation_flow_rates_m3s":[r["ventilation_mean_m3_s"] for r in series],
        "speed_effect":magnitude,"direction_effect":directional,
        "production_epw_ready":False
    }),flush=True)
    return artifact


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--energyplus",required=True)
    a.add_argument("--original-idf",required=True)
    a.add_argument("--base-epw",required=True)
    a.add_argument("--out",required=True)
    opt=a.parse_args()
    run(opt.energyplus,opt.original_idf,opt.base_epw,opt.out)
