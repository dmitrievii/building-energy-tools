"""Offline A1.4 build from original donor/background bodies; no target input."""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np
import pandas as pd

from a14_prepare import (ROOT,R,REGISTRATION,SOURCES,RESULTS,REUSED,REUSED_SHA,
    FIRST,ANCHOR,LAST,registered,request_for)
from a14_acquire import checked_sources
from a13_prepare import registered as a13_registered
from a13_acquire import packet
from a13_run import model_temperature,bound_temperature
from epw_climate_analyzer.engine.historical import assemble_historical,json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
from epw_climate_analyzer.engine.station_year import (reconstruct_nodes,assemble_station_year,
    serialize_station_epw,T,RH,P,Q,PS)
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.station_reconstruction import model_reference_operator,reconstruct_temperature

OP="mean_six_10min_nominal_nodes"


def annual_donor_subset(raw,sid):
    if sid not in ("DEM","ENG","GES","MOE","RUE"):
        raise ValueError("A14_ONLY_FROZEN_DONOR_T_MAY_BE_OPENED")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),delimiter=";")
    if not {"station_abbr","reference_timestamp","tre200h0"}<=set(reader.fieldnames or []) or len(set(reader.fieldnames))!=len(reader.fieldnames):
        raise ValueError("A14_DONOR_SOURCE_SCHEMA")
    if any("tre200h0"+s in reader.fieldnames for s in ("_qc","_flag")):
        raise ValueError("A14_UNDOCUMENTED_ROW_QC")
    rows=[];previous=None
    for row in reader:
        if None in row or (row["station_abbr"] or "").strip().upper()!=sid:
            raise ValueError("A14_DONOR_CROSS_STATION_OR_COLUMNS")
        stamp=(row["reference_timestamp"] or "").strip()
        if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}",stamp):raise ValueError("A14_DONOR_TIME_FORMAT")
        if stamp[6:10] not in ("2024","2025"):continue
        when=pd.to_datetime(stamp,format="%d.%m.%Y %H:%M",utc=True)
        if not FIRST<=when<=LAST:continue
        if when.minute or (previous is not None and when<=previous):raise ValueError("A14_DONOR_DUPLICATE_OR_NONHOURLY_TIME")
        previous=when;rows.append([sid,stamp,row["tre200h0"]])
    stream=io.StringIO(newline="");writer=csv.writer(stream,delimiter=";",lineterminator="\n")
    writer.writerow(["station_abbr","reference_timestamp","tre200h0"]);writer.writerows(rows)
    return stream.getvalue().encode()


def prefix_temperature(raw,annual,annual_proof):
    obj=json.loads(raw)
    clock=pd.date_range("2024-12-28",periods=96,freq="h",tz="UTC")
    if (obj.get("utc_offset_seconds")!=0 or obj.get("hourly_units",{}).get("temperature_2m")!="°C"
            or obj.get("hourly",{}).get("time")!=clock.strftime("%Y-%m-%dT%H:%M").tolist()):
        raise ValueError("A14_PREFIX_CLOCK_OR_UNIT")
    if [obj.get("latitude"),obj.get("longitude")]!=annual_proof["returned_provider_grid_xy"] or obj.get("elevation")!=annual_proof["provider_elevation_unverified"]:
        raise ValueError("A14_PREFIX_AND_ANNUAL_MODEL_CELL_DIFFER")
    values=obj["hourly"]["temperature_2m"]
    if len(values)!=96 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) or not -80<=v<=65 for v in values):
        raise ValueError("A14_PREFIX_BACKGROUND_MISSING_OR_DOMAIN")
    result=pd.concat([pd.Series(values,index=clock,name=T),annual]).loc[ANCHOR:LAST]
    if not result.index.equals(pd.date_range(ANCHOR,LAST,freq="h")):raise ValueError("A14_SUPPORT_BACKGROUND_CLOCK")
    result.attrs["unit"]="°C"
    return result


def csv_bytes(frame):
    # Output grid only: equations and acceptance checks use full precision.
    out=frame.copy(deep=True)
    for key in out.select_dtypes(include=["floating"]).columns:
        places=15 if ("q_" in key or "specific_humidity" in key or "mixing_ratio" in key) else 9
        out[key]=out[key].round(places)
        out.loc[out[key]==0,key]=0.0  # canonical positive zero, including residuals
        out[key]=out[key].map(lambda v: "" if pd.isna(v) else format(float(v),f".{places}f"))
    return out.to_csv(index=True,date_format="%Y-%m-%dT%H:%M:%SZ",float_format="%.9f",na_rep="",lineterminator="\n").encode()


def rounded(obj):
    if isinstance(obj,dict):return {k:rounded(v) for k,v in obj.items()}
    if isinstance(obj,list):return [rounded(v) for v in obj]
    if isinstance(obj,(float,np.floating)):
        # Keep sub-micro diagnostic tolerances nonzero. This is output-only;
        # all state equations and acceptance checks precede serialization.
        value=(float(format(float(obj),".2g")) if 0<abs(float(obj))<1e-6 else round(float(obj),8))
        return 0.0 if value==0 else value
    if isinstance(obj,np.integer):return int(obj)
    return obj


def regression(key,means):
    # Existing revealed values only; do not open A13 full target-body packet.
    pairs=pd.read_csv(R/"a13_paired_temperatures_20261025.csv")
    part=pairs[pairs.target_key==key].copy()
    clock=pd.to_datetime(part.reference_time_UTC,utc=True)
    actual=means.reindex(clock).to_numpy()
    old=part.R1_C.to_numpy(dtype=float)
    error=float(np.max(np.abs(actual-old)))
    if len(part)!=672 or not np.isfinite(actual).all() or error>5.1e-10:
        raise ValueError("A14_FROZEN_R1_REGRESSION_CHANGED:"+key)
    return {"hours":len(part),"R1_mean_matches_A13_10_decimal_grid":True,
        "max_difference_bound_K":5.1e-10,
        "revealed_only_not_independent":True,
        "MAE_mean_reconstruction_K":float(np.mean(np.abs(actual-part.observed_C.to_numpy()))),
        "MAE_B0_K":float(np.mean(np.abs(part.B0_C-part.observed_C)))}


def build(output,sources_path=R/SOURCES):
    plan=registered();new,acquisition=checked_sources(sources_path)
    reused,old_manifest=packet(R/REUSED,expected_sha=REUSED_SHA,expected_phase="inputs")
    prior=a13_registered()
    output.mkdir(parents=True,exist_ok=False)
    models={};proofs={};donors={};donor_receipts={}
    clock=pd.date_range(FIRST,LAST,freq="h")
    for key,row in plan["full_support_admission"].items():
        spec=next(s for s in prior["inputs"] if s["station_key"]==key and s["kind"]=="model_background")
        annual,proof=model_temperature(reused[spec["member"]],spec)
        prefix=next(s for s in plan["new_source_plan"] if s["station_key"]==key and s["kind"]=="temperature_prefix")
        models[key]=prefix_temperature(new[prefix["member"]],annual,proof);proofs[key]=proof
        if key in plan["targets"]:continue
        donor_spec=next(s for s in prior["inputs"] if s["station_key"]==key and s["kind"]=="station_observation")
        subset=annual_donor_subset(reused[donor_spec["member"]],key.split(":")[1])
        donors[key]=bound_temperature(subset,row)
        donor_receipts[key]={"original_body_sha256":sha256(reused[donor_spec["member"]]).hexdigest(),
            "derived_T_only_subset_sha256":sha256(subset).hexdigest(),"rows":len(subset.splitlines())-1,
            "QC_stratum":"PUBLISHED_NO_ROW_QC_NOT_DWD_QN10_EQUIVALENT"}
    results={}
    for key,case in plan["targets"].items():
        target=plan["full_support_admission"][key]
        b0=model_reference_operator(models[key],clock,OP)
        refs=[];observed={};background={};quality={}
        for donor in case["metadata_admitted_donors"]:
            row=plan["full_support_admission"][donor];refs.append(admitted_reference(row))
            bound=donors[donor]
            observed[donor]=bound.values if bound else pd.Series(np.nan,index=clock)
            observed[donor].attrs.update(unit="°C",reference_operator=OP)
            background[donor]=model_reference_operator(models[donor],clock,OP)
            quality[donor]=bound.quality_accepted if bound else pd.Series(False,index=clock)
        mean,r1ledger=reconstruct_temperature(admitted_reference(target),b0,refs,observed,background,quality)
        nodes,inverse=reconstruct_nodes(models[key],mean)
        request=request_for(key,target)
        payloads={};receipts=[]
        for kind in ("open_meteo","nasa_power"):
            spec=next(s for s in plan["new_source_plan"] if s["station_key"]==key and s["kind"]==kind)
            payloads[kind]=new[spec["member"]]
            receipt=deepcopy(next(r for r in acquisition["sources"] if r["id"]==spec["id"]))
            receipt["id"]=kind;receipt.update(provider=spec["provider"],dataset=spec["dataset"])
            receipts.append(receipt)
        baseline=assemble_historical(request,payloads,receipts)
        if not np.array_equal(baseline.data[T].to_numpy(),models[key].reindex(request.utc_ends).to_numpy()):
            raise ValueError("A14_FULL_WEATHER_T_DIFFERS_FROM_REUSED_BACKGROUND_VERSION:"+key)
        exported=nodes.reindex(request.utc_ends)
        chosen=inverse.loc[request.utc_ends]
        # Evaluate the exact same operator on endpoint states to prove support.
        reconstructed=model_reference_operator(nodes,request.utc_ends,OP)
        if np.max(np.abs(reconstructed-chosen.selected_mean_C))>1e-11:raise ValueError("A14_NODE_MEAN_ROUNDTRIP")
        temp_diag={"R1_admitted_export_means":int(chosen.R1_admitted.sum()),
            "explicit_B0_mean_fallbacks":int((~chosen.R1_admitted).sum()),
            "spinup_R1_fallbacks":int((~inverse.loc[:request.utc_ends[0]-pd.Timedelta(hours=1)].R1_admitted).sum()),
            "inverse_max_frequency_gain":6,"boundary_sensitivity_bound_20K_at_first_export_K":20*(5/7)**73,
            "previous_export_boundary_temperature_C":float(nodes.loc[request.utc_ends[0]-pd.Timedelta(hours=1)]),
            "max_absolute_endpoint_change_K":float(np.abs(exported.to_numpy()-baseline.data[T].to_numpy()).max()),
            "max_endpoint_hourly_step_K":float(np.abs(np.diff(exported)).max()),
            "RMS_endpoint_hourly_step_K":float(np.sqrt(np.mean(np.diff(exported)**2))),
            "RMS_B0_endpoint_hourly_step_K":float(np.sqrt(np.mean(np.diff(baseline.data[T])**2))),
            "internal_mean_roundtrip_bound_K":1e-11,
            "instantaneous_T_accuracy_qualified":False}
        g=target["geometry"];f=target["frozen_station"]
        result,humidity=assemble_station_year(baseline,exported,station_key=key,latitude=g["latitude"],longitude=g["longitude"],
            nominal_elevation_m=f["nominal_site_elevation_m"],name="A14 "+key.split(":")[1],
            r1_source={"reused_predictor_packet_sha256":REUSED_SHA,"registration_sha256":sha256((R/REGISTRATION).read_bytes()).hexdigest(),
                "target_observation_input":False,"frozen_donor_slots":case["frozen_donor_slots"]},temperature_diagnostics=temp_diag)
        epw,readback=serialize_station_epw(result)
        # Real application parser is an additional format check, not its phase adapter.
        from epw_climate_analyzer.epw_parser import parse_epw
        parsed=parse_epw(io.BytesIO(epw))
        parsed_frame=parsed.data
        if len(parsed_frame)!=8760:raise ValueError("A14_APPLICATION_PARSER_INCOMPLETE_YEAR")
        epw_t=np.asarray([float(row[6]) for row in list(csv.reader(io.StringIO(epw.decode())))[8:]])
        previous=np.r_[temp_diag["previous_export_boundary_temperature_C"],epw_t[:-1]]
        mean_error=float(np.max(np.abs((5*previous+7*epw_t)/12-chosen.selected_mean_C.to_numpy())))
        if mean_error>5.1e-8:raise ValueError("A14_EPW_MEAN_ROUNDTRIP")
        regression_result=regression(key,mean)
        folder=output/(key.replace(":","_")+"_2025");folder.mkdir()
        products={"weather.epw":epw,"hourly_states.csv":csv_bytes(result.data),
            "temperature_mean_inverse_ledger.csv":csv_bytes(inverse),"R1_donor_admission_ledger.csv":csv_bytes(r1ledger),
            "humidity_pressure_adjustment_ledger.csv":csv_bytes(humidity)}
        canonical=result.to_canonical()
        if canonical.temporal.calendar_mode!="historical" or canonical.temporal.source_years!=(2025,):
            raise ValueError("A14_CANONICAL_HISTORICAL_CALENDAR_CHANGED")
        summary={"station_key":key,"records":len(result.data),"EPW_fields":35,
            "calendar":"ACTUAL_2025_FIXED_CET_NO_DST; UTC interval starts preserved",
            "first_UTC_start":request.utc_starts[0].isoformat(),"last_UTC_start":request.utc_starts[-1].isoformat(),
            "temperature":temp_diag,"old_revealed_regression":regression_result,"epw_readback":readback,
            "application_parser_records":len(parsed_frame),"application_parser_used_for_physical_humidity_analysis":False,
            "max_EPW_to_selected_mean_roundtrip_K":mean_error,
            "q_projection_hours":int(humidity.q_projection_active.sum()),
            "max_q_reduction_g_per_kg_moist_air":float(-1000*humidity.delta_q_kg_kg.min()),
            "mean_q_change_g_per_kg_moist_air":float(1000*humidity.delta_q_kg_kg.mean()),
            "max_RH_before_projection_pct":float(humidity.RH_before_q_projection_pct.max()),
            "T_endpoint_range_C":[float(result.data[T].min()),float(result.data[T].max())],
            "quality":result.quality.__dict__,"full_weather_closure_qualified":False,"independent_accuracy_qualified":False,
            "pressure_local_accuracy_qualified":False,"production_ready":False,
            "sources":result.sources,"fields":{k:v.__dict__ for k,v in result.fields.items()},
            "background_diagnostics":baseline.diagnostics,"geometry":g,
            "product_sha256":{n:sha256(b).hexdigest() for n,b in products.items()}}
        # Numeric diagnostics are printed on a fixed grid, separate from tested internal thresholds.
        summary=rounded(summary)
        for n,b in products.items():write_exclusive(folder/n,b)
        write_exclusive(folder/"manifest.json",json_bytes(summary));results[key]=summary
    census={"schema":"IGE_A14_TWO_COMPLETE_CH_RESEARCH_YEARS_v1","registration_sha256":sha256((R/REGISTRATION).read_bytes()).hexdigest(),
        "new_source_packet_sha256":sha256(Path(sources_path).read_bytes()).hexdigest(),"reused_predictor_packet_sha256":REUSED_SHA,
        "original_new_assets":11,"new_HTTP_attempts":acquisition["HTTP_attempts"],
        "new_decoded_body_bytes_all_attempts":acquisition["decoded_body_bytes_all_attempts"],
        "original_donor_subset_receipts":donor_receipts,"model_response_geometry":proofs,
        "new_target_observation_requests":0,"annual_target_T_numerically_opened":False,
        "previous_revealed_regression_hours":1344,"targets":results,
        "independent_accuracy_qualified":False,"UI_defaults_changed":False,"production_ready":False}
    census=rounded(census);write_exclusive(output/RESULTS,json_bytes(census))
    print(json.dumps({"records":{k:v["records"] for k,v in results.items()},
        "R1_coverage":{k:v["temperature"]["R1_admitted_export_means"] for k,v in results.items()},
        "projection_hours":{k:v["q_projection_hours"] for k,v in results.items()}},indent=2))
    return census


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--out",type=Path,required=True);p.add_argument("--sources",type=Path,default=R/SOURCES)
    a=p.parse_args();build(a.out,a.sources)
