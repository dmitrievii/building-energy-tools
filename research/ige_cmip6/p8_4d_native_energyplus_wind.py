#!/usr/bin/env python3
"""IGE P8.4D official EnergyPlus 26.2 paired wind-only sensitivity.

Five TRUE native EPlus runs, same nonwind weather. Does not infer calibrated
wind-pressure, weather source accuracy or a natural ventilation opening model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
from pathlib import Path
import statistics

import p7c5_energyplus_benchmark as upstream

OFFICIAL_RELEASE="v26.2.0"
OFFICIAL_TARBALL_SHA256="b848da8236482a2171a67d7eab00c82162105b653ffab3ae3b6c2217c433a8a1"
P7C5_INFILTRATION=(
    "ZoneInfiltration:DesignFlowRate, IGE Infiltration, ZONE ONE, "
    "AlwaysOn, Flow/Zone, 0.080, , , , 1.0, 0.0, 0.0, 0.0;"
)
WIND_INFILTRATION=(
    "ZoneInfiltration:DesignFlowRate, IGE Infiltration, ZONE ONE, "
    "AlwaysOn, Flow/Zone, 0.080, , , , 0.10, 0.0, 0.20, 0.0;"
)
OUT_VARIABLES=(
    "Zone Infiltration Standard Density Volume Flow Rate",
    "Zone Ideal Loads Supply Air Total Heating Energy",
    "Zone Ideal Loads Supply Air Total Cooling Energy",
)
SPEEDS=(.5,1.,1.5)
CASES=tuple(("wind_responsive",f"{x:.1f}") for x in SPEEDS)+(
    ("constant_infiltration","0.5"),("constant_infiltration","1.5")
)


def build_model(original_text,wind_responds):
    s=upstream.generate_from_official(original_text)
    if s.count(P7C5_INFILTRATION)!=1:
        raise ValueError("P8D_PINNED_P7C5_INFILTRATION_DRIFT")
    if wind_responds:
        s=s.replace(P7C5_INFILTRATION,WIND_INFILTRATION)
    for name in OUT_VARIABLES:
        if f"Output:Variable, *, {name}, Hourly;" not in s:
            s+=f"\nOutput:Variable, *, {name}, Hourly;\n"
    if s.count("ZoneInfiltration:DesignFlowRate, IGE Infiltration")!=1:
        raise AssertionError("P8D_INFILTRATION_OBJECT_DUPLICATED")
    return s


def extract_sql(path):
    if not Path(path).is_file():
        raise RuntimeError("P8D_ENERGYPLUS_SQL_NOT_PRODUCED")
    with sqlite3.connect(path) as cx:
        cols=cx.execute("""SELECT dd.Name,dd.Units, COUNT(rd.Value),
                  SUM(rd.Value),MIN(rd.Value),MAX(rd.Value)
                  FROM ReportData rd
                  JOIN ReportDataDictionary dd
                  ON dd.ReportDataDictionaryIndex=rd.ReportDataDictionaryIndex
                  WHERE dd.Name IN (?,?,?) AND dd.ReportingFrequency='Hourly'
                  GROUP BY dd.Name,dd.Units""",OUT_VARIABLES).fetchall()
    data={}
    for name,unit,n,total,vmin,vmax in cols:
        if int(n)<8760 or not all(math.isfinite(float(x)) for x in (total,vmin,vmax)):
            raise RuntimeError("P8D_INVALID_HOURLY_EPLUS_OUTPUT_"+name)
        data[name]={"unit":unit,"hourly_count":int(n),"sum":float(total),
                    "minimum":float(vmin),"maximum":float(vmax),
                    "mean":float(total)/n}
    if set(data)!=set(OUT_VARIABLES):
        raise RuntimeError("P8D_MISSING_HOURLY_EPLUS_WIND_OR_HVAC_VARIABLES")
    for name in OUT_VARIABLES:
        if data[name]["minimum"]<-1e-9:
            raise RuntimeError("P8D_NEGATIVE_INFILTRATION_OR_HVAC_ENERGY")
    return {
        "mean_infiltration_std_density_m3_s":data[OUT_VARIABLES[0]]["mean"],
        "heating_kwh":data[OUT_VARIABLES[1]]["sum"]/3.6e6,
        "cooling_kwh":data[OUT_VARIABLES[2]]["sum"]/3.6e6,
        "raw_metadata":data,
    }


def run(bin_path,official_idf,epw_dir,out):
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    source=Path(official_idf).read_text()
    idfs={}
    for name,active in (("wind_responsive",True),("constant_infiltration",False)):
        model=folder/(name+".idf")
        model.write_text(build_model(source,active))
        idfs[name]=model
    reports=[]
    for kind,mult in CASES:
        epw=Path(epw_dir)/f"research_wind_only_x{mult}.epw"
        if not epw.is_file():
            raise FileNotFoundError("P8D_REQUIRED_PUBLIC_WIND_EPW_NOT_FOUND_"+str(epw))
        run_dir=folder/(kind+"_wind_"+mult)
        run_dir.mkdir(exist_ok=True)
        args=[str(Path(bin_path).absolute()),"--weather",str(epw.absolute()),
              "--output-directory",str(run_dir.absolute()),str(idfs[kind].absolute())]
        p=subprocess.run(args,capture_output=True,text=True,timeout=420)
        (run_dir/"stdout.txt").write_text(p.stdout[-12000:])
        (run_dir/"stderr.txt").write_text(p.stderr[-12000:])
        if p.returncode:
            diagnostic=run_dir/"eplusout.err"
            detail=diagnostic.read_text(errors="replace")[-18000:] if diagnostic.exists() else ""
            raise RuntimeError(
                f"P8D_NATIVE_ENERGYPLUS_EXIT_{p.returncode}_{kind}_{mult}: {detail}")
        warnings=upstream.check_errors(run_dir/"eplusout.err")
        measures=extract_sql(run_dir/"eplusout.sql")
        reports.append({
            "type":kind,"wind_scale":float(mult),
            "epw_sha256":hashlib.sha256(epw.read_bytes()).hexdigest(),
            "EnergyPlus_native_executed":True,**warnings,**measures})
    wind=sorted((r for r in reports if r["type"]=="wind_responsive"),key=lambda r:r["wind_scale"])
    fixed=sorted((r for r in reports if r["type"]=="constant_infiltration"),key=lambda r:r["wind_scale"])
    responsive=[r["mean_infiltration_std_density_m3_s"] for r in wind]
    reference=[r["mean_infiltration_std_density_m3_s"] for r in fixed]
    if not (responsive[0]<responsive[1]<responsive[2]) or responsive[0]<=0:
        raise AssertionError("P8D_NATIVE_ENERGYPLUS_WIND_INFILTRATION_NOT_MONOTONIC")
    # Constant infiltration weather still changes outdoor forced convection in
    # native EnergyPlus, so only assert that its AIRFLOW stays fixed, not loads.
    if abs(reference[1]-reference[0])>max(1e-5,.02*statistics.fmean(reference)):
        raise AssertionError("P8D_NEGATIVE_CONTROL_CONSTANT_AIRFLOW_CHANGED")
    if any((not math.isfinite(r["heating_kwh"]) or r["heating_kwh"]<=0
            or not math.isfinite(r["cooling_kwh"])) for r in reports):
        raise AssertionError("P8D_NONPHYSICAL_NATIVE_HEATING_COOLING")
    product={
        "phase":"IGE_P8_4D_NATIVE_ENERGYPLUS_WIND_SENSITIVITY",
        "source_epw_kind":"P7B5 publicly archived research-only wind analogue; not Meteonorm",
        "EnergyPlus_version":upstream.ENERGYPLUS_VERSION,
        "EnergyPlus_release_sha256":OFFICIAL_TARBALL_SHA256,
        "native_EnergyPlus_executed":True,
        "n_weather_building_simulations":len(reports),
        "wind_responsive_infiltration_A_B_C_D":[.10,0,.20,0],
        "constant_infiltration_A_B_C_D":[1,0,0,0],
        "wind_sensitivity_coefficients_calibrated_to_building":False,
        "nat_ventilation_simulated":False,
        "exterior_convection_may_depend_on_wind_even_in_constant_infiltration_control":True,
        "wind_responding_infiltration_monotonic":True,
        "constant_infiltration_negative_control_pass":True,
        "results":reports,
        "production_epw_ready":False,
    }
    (folder/"p8_4d_native_energyplus_5_wind_cases_aggregate.json").write_text(
        json.dumps(product,indent=2,sort_keys=True)+"\n")
    print("IGE_P8_4D_ENERGYPLUS",json.dumps({
        "n_runs":len(reports),
        "responsive_mean_infiltration_m3_s":responsive,
        "fixed_mean_infiltration_m3_s":reference,
        "native_executed":True,"production_epw_ready":False}),flush=True)
    return product


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--energyplus",required=True)
    a.add_argument("--original-idf",required=True)
    a.add_argument("--epw-dir",required=True)
    a.add_argument("--out",required=True)
    arg=a.parse_args()
    run(arg.energyplus,arg.original_idf,arg.epw_dir,arg.out)
