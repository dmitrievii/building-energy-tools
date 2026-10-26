"""A1.4 registration and full-support metadata checks, without weather values."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
R=ROOT/"research/ige_cmip6"
sys.path.insert(0,str(ROOT/"tools/climate_analyzer"))
from epw_climate_analyzer.engine.contracts import HistoricalRequest
from epw_climate_analyzer.engine.historical import source_plan,json_bytes
from epw_climate_analyzer.station_admission import admitted_reference
from a12_prepare_history import history_sources,wmdr_geometry
from a13_prepare import parent_inputs,registered as a13_registered

BASE="3ba27b7b618820d9f714c312a0fec5ae989c37f6"
DATE="20261026"
BRANCH="research/ige-a1-4-local-historical-year-20261026"
REGISTRATION=f"a14_registration_{DATE}.json"
SOURCES=f"a14_original_sources_{DATE}.zip"
RESULTS=f"a14_results_{DATE}.json"
REUSED="a13_input_sources_20261025.zip"
REUSED_SHA="c11d9df67f27fb67dbc2233c2101f628edbca8380e2d2f2a5b05e39b581aabbd"
FIRST=pd.Timestamp("2024-12-29T00:00:00Z")
ANCHOR=FIRST-pd.Timedelta(hours=1)
LAST=pd.Timestamp("2025-12-31T23:00:00Z")
CODE=["research/ige_cmip6/"+n for n in ("a14_prepare.py","a14_acquire.py","a14_run.py","a14_verify.py")]
CODE += ["tools/climate_analyzer/epw_climate_analyzer/engine/station_year.py",
    "tools/climate_analyzer/tests/test_ige_a14_station_year.py",
    ".github/workflows/ige-a1-4-local-year-20261026.yml"]


def code_hashes():
    return {n:sha256((ROOT/n).read_bytes()).hexdigest() for n in CODE}


def annual_admission():
    protocol,prior=parent_inputs()
    bodies,_=history_sources()
    targets={c["target_key"]:deepcopy(c) for c in prior["cases"]
        if c["target_key"] in ("CH:BAS","CH:ALT") and c["season"]=="winter"}
    keys=sorted({*targets,*[k for c in targets.values() for k in c["metadata_admitted_donors"]]})
    records={}
    for key in keys:
        row=deepcopy(prior["station_windows"][key]["winter"])
        member="CH_"+key.split(":")[1]+"_WMDR.xml"
        geometry=wmdr_geometry(bodies[member],row["geometry"]["source_WSI"],"CH",ANCHOR,LAST)
        if geometry["AGL_m"]!=2. or geometry["local_reference_surface"]!="localGround":
            raise ValueError("A14_FULL_YEAR_STRICT_2M_GEOMETRY_BLOCKED:"+key)
        row.update({"season":"A14_FULL_SUPPORT_WITH_SPINUP","reference_first_UTC":FIRST.isoformat(),
            "reference_last_UTC":LAST.isoformat(),"actual_nominal_sample_support_first_UTC":
                (FIRST-pd.Timedelta(minutes=50)).isoformat(),"geometry":geometry})
        admitted_reference(row)
        if any(geometry[k]!=prior["station_windows"][key]["winter"]["geometry"][k] for k in
                ("latitude","longitude","AGL_m","geospatial_z_as_reported_m")):
            raise ValueError("A14_FULL_YEAR_GEOMETRY_DIFFERS_FROM_FROZEN_R1:"+key)
        records[key]=row
    return targets,records


def request_for(key,record):
    g=record["geometry"];f=record["frozen_station"]
    return HistoricalRequest(g["latitude"],g["longitude"],2025,60,"A14 "+key.split(":")[1],
        site_elevation_m=f["nominal_site_elevation_m"],
        site_elevation_reference="Frozen nominal station height; vertical datum and model-orography transfer unqualified")


def build_registration():
    targets,records=annual_admission()
    old=a13_registered(); specs=[]
    for key in records:
        previous=next(s for s in old["inputs"] if s["station_key"]==key and s["kind"]=="model_background")
        pars=dict(previous["parameters"]);pars.update(start_date="2024-12-28",end_date="2024-12-31")
        specs.append({"id":"prefix_"+key.replace(":","_"),"kind":"temperature_prefix",
            "station_key":key,"url":"https://archive-api.open-meteo.com/v1/archive?"+urlencode(pars),
            "parameters":pars,"member":"prefix_"+key.replace(":","_")+".json","max_body_bytes":1_000_000})
    for key in targets:
        for source,spec in source_plan(request_for(key,records[key])).items():
            specs.append({"id":source+"_"+key.replace(":","_"),"kind":source,"station_key":key,
                **spec,"member":source+"_"+key.replace(":","_")+".json","max_body_bytes":16_777_216})
    return {"schema":"IGE_A14_LIMITED_CH_YEAR_REGISTRATION_v1","date":"2026-10-26","parent_commit":BASE,
        "product_function":"A historical local temperature year and research EPW",
        "targets":targets,"full_support_admission":records,
        "reference_first_UTC":FIRST.isoformat(),"reference_last_UTC":LAST.isoformat(),
        "background_anchor_UTC":ANCHOR.isoformat(),"spinup_hours":72,
        "new_source_plan":specs,"reused_predictor_packet":REUSED,"reused_predictor_packet_sha256":REUSED_SHA,
        "source_budget":{"max_decoded_body_bytes_all_attempts":200_000_000,"assets":11,
            "attempts_per_asset":3,"timeout_seconds":45,"parallel_downloads":1,
            "new_station_observation_requests":0,"alternate_source_model_or_station_allowed":False},
        "temperature_policy":{"R1":"UNCHANGED_A1_1_IDW2_MIN2_PRIMARY_QC_DONORS",
            "blocked_donor_slots":"retain CH:TIT blocked; never replace",
            "raw_missing_R1":"NaN retained and admission ledger; product selects B0 MEAN explicitly",
            "inverse":"delta_H=(12*(selected_mean_H-A(B0)_H)-5*delta_(H-1))/7; anchor delta=0",
            "operator":"A(T)_H=(5*T_(H-1)+7*T_H)/12 under disclosed linear subhourly path",
            "inverse_frequency_gain_max":6,"anchor_sensitivity_factor_at_first_export":(5/7)**73,
            "smoothing_fitting_target_observations_or_new_lapse_rate":False,
            "instantaneous_T_accuracy_qualified":False},
        "humidity_policy":{"source_vapour":"provider rounded T/RH liquid-water Magnus 17.625/243.04; Td diagnostic only",
            "source_q":"implicit q(e,p2) with p2=ps*exp[-2g/(Rd*Tv(T0,q))]",
            "projection":"argmin 0.5*(q-q0)^2 subject to 0<=q<=coupled_qsat(T,ps); q*=min(q0,qsat)",
            "output_phase":"Murphy-Koop liquid water below and above zero; historical, no NEX daily constraint",
            "pressure":"original absolute model-surface proxy, conditional 2m adapter; no site-height transfer",
            "atmospheric_mass_latent_heat_or_precipitation_flux_conserved":False,
            "zero_source_RH":"fail; no arbitrary humidity floor"},
        "missing_background_or_physical_failure":"FAIL_WITH_EXPLICIT_BLOCK; no source substitution or relaxed limits",
        "regression":"A1.3 already revealed 1344 paired temperatures only; compare means, no annual target T opening",
        "acceptance":["2 complete 8760x35 EPWs and exact UTC/fixed-CET clock",
            "full-support dated strict 2m temperature geometry for all seven admitted sensors",
            "R1 matches frozen A1.3 on all 1344 reference hours to CSV quantization",
            "mean inverse internal error <=1e-11 K; export error <=5.1e-8 K",
            "separate raw-R1 coverage, explicit fallback and full hourly humidity adjustment ledgers",
            "conditional internal RH<=1e-7 pp; vapour<=1e-5 Pa; pressure<=1e-7 Pa residual",
            "EPW readback closure compatible with seven-decimal rounding intervals",
            "prior 259 tests and new meaningful tests pass; old engine/UI/EPWs/science unchanged",
            "offline original-source replay matches local/CI output bytes"],
        "independent_accuracy_qualified":False,"full_weather_cross_field_accuracy_qualified":False,
        "UI_connected":False,"production_ready":False,"global_validation_deferred":True,
        "expected_cost":{"new_assets":11,"original_body_budget_MB":200,"source_requests_expected_seconds":[30,300],
            "offline_build_expected_seconds":[5,90],"tests_expected_seconds":[40,150],"CI_expected_minutes":[2,8]}}


def registered():
    raw=(R/REGISTRATION).read_bytes(); plan=build_registration()
    if raw!=json_bytes(plan):raise ValueError("A14_REGISTRATION_OR_METADATA_CHANGED")
    return plan


if __name__=="__main__":
    from epw_climate_analyzer.engine.epw import write_exclusive
    write_exclusive(R/REGISTRATION,json_bytes(build_registration()))
    print(REGISTRATION)
