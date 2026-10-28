"""CPU-portability audit, separate from exact frozen UI snapshot identity.

Original weather is never overwritten. Compare serialized quantization cells
and recheck the ORIGINAL A1.4 physical tolerances; do not assert portable ZIP
identity for exp/log implementations selected by different CPU instruction sets.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from decimal import Decimal
from hashlib import sha256
import io
import json
import re
import zipfile

import numpy as np
import pandas as pd

from epw_climate_analyzer.engine.thermodynamics import e_from_q,saturation_water_pa,pressure_at_2m

T,TD,RH,P,Q,PS=("dry_bulb_temperature_c","dew_point_temperature_c","relative_humidity_pct",
    "atmospheric_station_pressure_pa","specific_humidity_kg_kg","surface_pressure_proxy_pa")


def check_cell(a,b,places):
    """Two round-to-nearest cells may meet at their shared boundary."""
    if a==b:return Decimal(0)
    pattern=rf"-?\d+\.\d{{{places}}}"
    if not re.fullmatch(pattern,a) or not re.fullmatch(pattern,b):
        raise ValueError("A15_REPLAY_NUMERIC_GRID_CHANGED")
    delta=abs(Decimal(a)-Decimal(b))
    if delta>Decimal(10)**(-places):raise ValueError("A15_REPLAY_QUANTIZATION_CELLS_DISJOINT")
    return delta


def compare_csv(a,b,kind):
    x=list(csv.reader(io.StringIO(a.decode())));y=list(csv.reader(io.StringIO(b.decode())))
    if len(x)!=len(y) or not x or x[0]!=y[0]:raise ValueError("A15_REPLAY_CSV_SCHEMA_OR_ROWS")
    header=x[0];maxima={};count=0
    for u,v in zip(x[1:],y[1:]):
        if len(u)!=len(header) or len(v)!=len(header):raise ValueError("A15_REPLAY_CSV_WIDTH")
        for column,(left,right) in enumerate(zip(u,v)):
            if left==right:continue
            key=header[column];count+=1
            if column==0 or (kind=="states" and key not in (TD,RH,P,Q)) or key.startswith("original_"):
                raise ValueError("A15_REPLAY_CLOCK_INPUT_OR_UNADJUSTED_WEATHER_CHANGED:"+key)
            if key=="RH_before_q_projection_pct":
                # The old serializer printed this diagnostic at 15 places
                # because its name contains q_. It is checked independently
                # against q0/T/ps below, using the original RH tolerance.
                delta=abs(Decimal(left)-Decimal(right))
                if delta>Decimal("1e-7"):raise ValueError("A15_REPLAY_PREPROJECTION_RH_CHANGED")
            else:
                places=15 if ("q_" in key or "specific_humidity" in key or "mixing_ratio" in key) else 9
                delta=check_cell(left,right,places)
            maxima[key]=max(maxima.get(key,Decimal(0)),delta)
    return {"different_cells":count,"max_absolute_differences":{k:str(v) for k,v in maxima.items()}}


def check_state_and_ledger(states_raw,ledger_raw):
    states=pd.read_csv(io.BytesIO(states_raw),index_col=0,float_precision="round_trip")
    ledger=pd.read_csv(io.BytesIO(ledger_raw),index_col=0,float_precision="round_trip")
    if len(states)!=8760 or not states.index.equals(ledger.index):raise ValueError("A15_REPLAY_FULL_STATE_LEDGER_CLOCK")
    t,td,rh,p,q,ps=(states[k].to_numpy(dtype=float) for k in (T,TD,RH,P,Q,PS))
    e=e_from_q(q,p)
    residuals={"RH_pp":float(np.max(np.abs(100*e/saturation_water_pa(t)-rh))),
        "Td_vapour_pa":float(np.max(np.abs(saturation_water_pa(td)-e))),
        "conditional_p_pa":float(np.max(np.abs(pressure_at_2m(t,q,ps)-p)))}
    q0=ledger.inferred_background_q_kg_kg.to_numpy();bound=ledger.saturation_q_upper_kg_kg.to_numpy()
    qp=ledger.projected_q_kg_kg.to_numpy()
    if not np.array_equal(qp,np.minimum(q0,bound)):raise ValueError("A15_REPLAY_Q_PROJECTION_CHANGED")
    pre=100*e_from_q(q0,pressure_at_2m(t,q0,ps))/saturation_water_pa(t)
    residuals["preprojection_RH_pp"]=float(np.max(np.abs(pre-ledger.RH_before_q_projection_pct)))
    if (np.any((rh<0)|(rh>100)) or np.any(td>t+1e-9) or residuals["RH_pp"]>1e-7
            or residuals["Td_vapour_pa"]>1e-5 or residuals["conditional_p_pa"]>1e-7
            or residuals["preprojection_RH_pp"]>1e-7):
        raise ValueError("A15_REPLAY_ORIGINAL_PHYSICAL_TOLERANCE_FAILED")
    return residuals


def normal_manifest(value,files):
    out=deepcopy(value)
    for name,h in out["product_sha256"].items():
        if sha256(files[name]).hexdigest()!=h:raise ValueError("A15_REPLAY_MANIFEST_HASH_FAILED")
    if out["epw_readback"]["sha256"]!=sha256(files["weather.epw"]).hexdigest() or out["epw_readback"]["bytes"]!=len(files["weather.epw"]):
        raise ValueError("A15_REPLAY_EPW_HASH_OR_BYTES_FAILED")
    out["product_sha256"]={k:"CHECKED_AGAINST_OWN_BYTES" for k in out["product_sha256"]}
    out["epw_readback"]["sha256"]="CHECKED_AGAINST_OWN_BYTES"
    out["epw_readback"]["bytes"]="CHECKED_AGAINST_OWN_BYTES"
    return out


def audit_replay(expected_raw,replayed_raw):
    with zipfile.ZipFile(io.BytesIO(expected_raw)) as a,zipfile.ZipFile(io.BytesIO(replayed_raw)) as b:
        names=a.namelist()
        if len(names)!=13 or len(set(names))!=13 or set(names)!=set(b.namelist()) or len(b.namelist())!=13:
            raise ValueError("A15_REPLAY_ARCHIVE_CENSUS")
        frozen={n:a.read(n) for n in names};replay={n:b.read(n) for n in names}
    reports={};normalized=[{},{}]
    for folder in ("CH_BAS_2025","CH_ALT_2025"):
        left={n.split("/",1)[1]:v for n,v in frozen.items() if n.startswith(folder+"/")}
        right={n.split("/",1)[1]:v for n,v in replay.items() if n.startswith(folder+"/")}
        for name in ("R1_donor_admission_ledger.csv","temperature_mean_inverse_ledger.csv"):
            if left[name]!=right[name]:raise ValueError("A15_REPLAY_TEMPERATURE_OR_DONOR_DECISION_CHANGED")
        states=compare_csv(left["hourly_states.csv"],right["hourly_states.csv"],"states")
        ledger=compare_csv(left["humidity_pressure_adjustment_ledger.csv"],right["humidity_pressure_adjustment_ledger.csv"],"ledger")
        physical=[check_state_and_ledger(d["hourly_states.csv"],d["humidity_pressure_adjustment_ledger.csv"]) for d in (left,right)]
        u=list(csv.reader(io.StringIO(left["weather.epw"].decode())));v=list(csv.reader(io.StringIO(right["weather.epw"].decode())))
        if len(u)!=8768 or len(v)!=8768 or u[:8]!=v[:8]:raise ValueError("A15_REPLAY_EPW_HEADER_OR_ROWS")
        changes=0
        for row,(x,y) in enumerate(zip(u[8:],v[8:])):
            if len(x)!=35 or len(y)!=35:raise ValueError("A15_REPLAY_EPW_WIDTH")
            for col,(p,q) in enumerate(zip(x,y)):
                if p==q:continue
                if col not in (7,8,9):raise ValueError("A15_REPLAY_EPW_CLOCK_T_OR_BACKGROUND_CHANGED")
                check_cell(p,q,7);changes+=1
        key=folder[:6].replace("_",":")
        for i,files in enumerate((left,right)):
            normalized[i][key]=normal_manifest(json.loads(files["manifest.json"]),files)
        if normalized[0][key]!=normalized[1][key]:raise ValueError("A15_REPLAY_SCIENTIFIC_METADATA_CHANGED")
        reports[key]={"states":states,"ledger":ledger,"physical_residuals_frozen_and_replay":physical,
            "different_EPWs_cells":changes,"T_donor_and_mean_inverse_ledgers_byte_exact":True}
    census=[]
    for i,files in enumerate((frozen,replay)):
        value=json.loads(files["a14_results_20261026.json"])
        for key in normalized[i]:
            own=normal_manifest(value["targets"][key],{n.split("/",1)[1]:v for n,v in files.items() if n.startswith(key.replace(":","_")+"_2025/")})
            if own!=normalized[i][key]:raise ValueError("A15_REPLAY_TARGET_CENSUS_DISAGREES")
        value["targets"]=normalized[i];census.append(value)
    if census[0]!=census[1]:raise ValueError("A15_REPLAY_SOURCE_IDENTITY_OR_COUNTS_CHANGED")
    return {"schema":"IGE_A15_SOURCE_REPLAY_PORTABILITY_AUDIT_v1",
        "byte_exact":expected_raw==replayed_raw,"numerical_quantization_compatibility":True,
        "frozen_ZIP_sha256":sha256(expected_raw).hexdigest(),"replayed_ZIP_sha256":sha256(replayed_raw).hexdigest(),
        "targets":reports,"original_physical_tolerances_changed":False,
        "source_T_donors_operators_or_objective_changed":False,
        "UI_uses_replayed_values":False,"portable_bitwise_parent_recalculation_qualified":False}
