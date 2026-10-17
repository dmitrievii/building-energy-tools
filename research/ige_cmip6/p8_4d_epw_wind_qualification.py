#!/usr/bin/env python3
"""IGE P8.4D: source-provenanced wind-only EPW qualification, NOT production EPWs.

Public CI fixture: P7B.5 original QC-supported wind-analogue EPW with research
synthetic P7B.4 thermodynamics. Proprietary files allowed only local with
authenticated user authorization. Wind-change GCM ratios are not future angles.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

import p8_4c_future_wind_baseline as p8c
import p7c3_ensemble as p7c3

N=8760
EPW_WIDTH=35
SPEED=21
FROM=20
CALM=.5
SCENARIOS=32
WIND_ONLY_REFERENCE="P7B5_QC_WIND_ANALOGUE_SYNTHETIC_THERMODYNAMICS"
PROPRIETARY_REFERENCE="USER_AUTHORIZED_PROPRIETARY_METEONORM_EPW"


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as fh:
        for item in iter(lambda:fh.read(1024*1024),b""):
            h.update(item)
    return h.hexdigest()


def read_epw(path):
    p=Path(path)
    with p.open(encoding="utf-8-sig",newline="") as f:
        source=list(csv.reader(f))
    if len(source)!=8+N:
        raise ValueError("P8D_EPW_REQUIRES_8_HEADERS_AND_8760_HOURS")
    h=source[:8];rows=source[8:]
    if h[0][0]!="LOCATION" or h[7][0]!="DATA PERIODS":
        raise ValueError("P8D_NOT_AN_EPW_HEADER")
    if any(len(r)!=EPW_WIDTH for r in rows):
        raise ValueError("P8D_EPW_REQUIRES_35_FIELDS")
    first_year=int(rows[0][0])
    if first_year%4==0 and (first_year%100!=0 or first_year%400==0):
        raise ValueError("P8D_LEAP_YEAR_EPWS_REQUIRE_EXPLICIT_NOLEAP_MAPPING")
    if len(set(r[0] for r in rows))!=1:
        raise ValueError("P8D_MIXED_YEAR_SOURCE_NOT_SUPPORTED")
    begin=dt.date(first_year,1,1)
    for index,r in enumerate(rows):
        day=begin+dt.timedelta(days=index//24)
        expected=(first_year,day.month,day.day,(index%24)+1,60)
        try:
            observed=tuple(int(r[k]) for k in range(5))
            speed=float(r[SPEED]);angle=float(r[FROM])
        except (ValueError,IndexError) as exc:
            raise ValueError("P8D_NONNUMERIC_SOURCE_WIND_OR_DATE") from exc
        if observed!=expected:
            raise ValueError("P8D_EPW_CLOCK_MISMATCH_OR_DST")
        if not math.isfinite(speed) or speed<0 or speed>=999:
            raise ValueError("P8D_INVALID_MISSING_OR_NEGATIVE_WIND_SPEED")
        if not math.isfinite(angle) or (angle!=999 and not 0<=angle<=360):
            raise ValueError("P8D_INVALID_METEOROLOGICAL_FROM_AZIMUTH")
    return h,rows,{
        "sha256":sha(p),"filename":p.name,
        "year":first_year,"hourly_records":N,
        "original_missing_direction_hours":sum(float(r[FROM])==999 for r in rows),
        "original_noncalm_missing_direction_hours":sum(
            float(r[SPEED])>=CALM and float(r[FROM])==999 for r in rows),
        "calendar":"365-day, 8760 hour, no DST",
    }


def authenticate(path,metadata,provenance,source_type):
    if source_type=="p7b5_public":
        if provenance is None:
            raise ValueError("P8D_PUBLIC_REQUIRES_ORIGINAL_P7B5_AUDIT")
        original=json.loads(Path(provenance).read_text())
        expected=original.get("derived_sha256",{}).get(Path(path).name)
        if not expected or expected!=metadata["sha256"]:
            raise ValueError("P8D_PUBLIC_P7B5_IMMUTABLE_SHA_MISMATCH")
        if original.get("production_epw_ready") is not False:
            raise ValueError("P8D_PUBLIC_RESEARCH_ONLY_STATUS_MISSING")
        return {"evidence_tier":WIND_ONLY_REFERENCE,
                "original_p7b5_scientific_audit_sha256":sha(provenance),
                "original_p7b5_epw_sha256":expected,
                "authenticated_licensed_meteonorm":False,
                "baseline_direction_is_station_QC_analogue_not_original_same_date":True}
    if source_type=="licensed_local":
        if provenance is None:
            raise ValueError("P8D_LICENSED_REQUIRES_USER_AUTHORIZED_PROVENANCE")
        original=json.loads(Path(provenance).read_text())
        if (not original.get("user_authorized_research_use")
                or not original.get("provider","").lower().startswith("meteonorm")
                or original.get("sha256")!=metadata["sha256"]):
            raise ValueError("P8D_LICENSE_OR_SHA_NOT_AUTHENTICATED")
        return {"evidence_tier":PROPRIETARY_REFERENCE,
                "original_EPW_sha256":metadata["sha256"],
                "authenticated_licensed_meteonorm":True,
                "distribute_source_or_derived_hours":False}
    raise ValueError("P8D_UNREGISTERED_SOURCE_TYPE")


def rose16(rows):
    bins=[0]*16
    n=0
    for r in rows:
        speed=float(r[SPEED]);angle=float(r[FROM])
        if speed<CALM or angle==999:
            continue
        sector=int(((angle%360.+11.25)%360.)//22.5)
        bins[sector]+=1;n+=1
    return {"defined_noncalm_hour_count":n,"sectors":[v/n for v in bins] if n else [0.]*16}


def stats(rows):
    values=[float(r[SPEED]) for r in rows]
    a=sorted(values)
    n=len(a)
    if n<1:raise ValueError("P8D_EMPTY_WIND")
    high=[v>=5. for v in values]
    persistent_3=p8c.run_count(values,3,5.)
    persistent_6=p8c.run_count(values,6,5.)
    az=rose16(rows)
    return {
        "speed_mean_mps":statistics.fmean(values),
        "speed_p05_mps":p8c.quantile(values,.05),
        "speed_p50_mps":p8c.quantile(values,.5),
        "speed_p95_mps":p8c.quantile(values,.95),
        "speed_max_mps":max(values),
        "calm_lt0p5_pct":100*sum(v<CALM for v in values)/n,
        "speed_ge2_pct":100*sum(v>=2. for v in values)/n,
        "speed_ge5_pct":100*sum(high)/n,
        "high_wind_3h_rolling_windows":persistent_3,
        "high_wind_6h_rolling_windows":persistent_6,
        "noncalm_valid_direction_pct":100*az["defined_noncalm_hour_count"]/
                sum(v>=CALM for v in values) if any(v>=CALM for v in values) else None,
        "rose16":az["sectors"],
    }


def monthly_scalar_wind_morph(headers,source,model,window,ratios):
    if len(source)!=N:raise ValueError("P8D_SOURCE_NOT_8760")
    out=[r.copy() for r in source]
    factor={m:ratios[(model,window,m)] for m in range(1,13)}
    months=collections.defaultdict(list)
    for i,(old,row) in enumerate(zip(source,out)):
        month=int(old[1])
        speed=float(old[SPEED])
        dest=speed*factor[month]
        if dest<0 or not math.isfinite(dest):
            raise ValueError("P8D_NEGATIVE_NONFINITE_WIND_MORPH")
        row[SPEED]=f"{dest:.3f}"
        if row[FROM]!=old[FROM] or any(row[k]!=old[k] for k in range(EPW_WIDTH) if k!=SPEED):
            raise AssertionError("P8D_MODIFIED_ANY_EPW_FIELD_OTHER_THAN_WIND_SPEED")
        months[month].append(i)
    diagnostics=[]
    highest=0.
    for m,idxs in sorted(months.items()):
        source_m=statistics.fmean(float(source[i][SPEED]) for i in idxs)
        new_m=statistics.fmean(float(out[i][SPEED]) for i in idxs)
        err=abs(new_m-source_m*factor[m])
        highest=max(highest,err)
        if err>.001+1e-12:
            raise AssertionError("P8D_MONTHLY_GCM_CHANGE_FACTOR_PARITY_FAILED")
        diagnostics.append({"month":m,"factor":factor[m],
                            "monthly_source_mean_mps":source_m,
                            "monthly_morphed_mean_mps":new_m,
                            "monthly_balance_error_mps":err})
    baseline=stats(source);future=stats(out)
    promoted=sum(
        float(source[i][SPEED])<CALM and float(out[i][SPEED])>=CALM
        for i in range(N))
    demoted=sum(
        float(source[i][SPEED])>=CALM and float(out[i][SPEED])<CALM
        for i in range(N))
    none_new=sum(
        float(out[i][SPEED])>=CALM and float(out[i][FROM])==999
        for i in range(N))
    blocking=none_new+sum(
        float(source[i][SPEED])<CALM and float(out[i][SPEED])>=CALM
        for i in range(N))
    return out,{
        "model":model,"window":window,
        "n_hours":N,"wind_direction_preserved_exactly":True,
        "nonwind_34_epw_fields_preserved_exactly":True,
        "maximum_monthly_speed_balance_mps":highest,
        "newly_promoted_unqualified_source_calm_direction_hours":promoted,
        "demoted_noncalm_to_calm_hours":demoted,
        "morphed_noncalm_missing_direction_hours":none_new,
        "physical_wind_exposure_blocker_hours":blocking,
        "EPW_wind_physical_direction_quality_pass":blocking==0,
        "baseline":baseline,"morphed":future,
        "rose16_total_variation":0.5*sum(
            abs(a-b) for a,b in zip(baseline["rose16"],future["rose16"])),
        "monthly":diagnostics,
        "seasonal":[
            {"season":s,
             "source":stats([source[i] for i in range(N) if p8c.SEASONS[int(source[i][1])]==s]),
             "morphed":stats([out[i] for i in range(N) if p8c.SEASONS[int(source[i][1])]==s])}
            for s in ("DJF","MAM","JJA","SON")
        ],
        "IPSL_full_EPW_qualified":False,
        "future_direction_not_independently_modelled":True,
    }


def write_epw(path,headers,rows):
    dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("w",newline="",encoding="utf-8") as fp:
        w=csv.writer(fp,lineterminator="\n")
        w.writerows(headers);w.writerows(rows)


def counterfactuals(headers,source,folder,scale_values=(.5,1.,1.5)):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    data={}
    for scalar in scale_values:
        if not math.isfinite(scalar) or scalar<=0:
            raise ValueError("P8D_INVALID_WIND_COUNTERFACTUAL_FACTOR")
        derived=[r.copy() for r in source]
        for row in derived:
            row[SPEED]=f"{float(row[SPEED])*scalar:.3f}"
        name=f"research_wind_only_x{scalar:.1f}.epw"
        path=folder/name
        write_epw(path,headers,derived)
        data[str(scalar)]={
            "filename":name,"sha256":sha(path),
            "wind_multiplier":scalar,
            "nonwind_epw_fields_unchanged":True,
            "wind_mean_mps":statistics.fmean(float(r[SPEED]) for r in derived),
            "noncalm_missing_direction_hours":sum(
                float(r[SPEED])>=CALM and float(r[FROM])==999 for r in derived),
            "promoted_source_calm_hour_count":sum(
                float(a[SPEED])<CALM and float(b[SPEED])>=CALM
                for a,b in zip(source,derived)),
        }
    manifest=folder/"p8_4d_wind_only_counterfactual_manifest.json"
    manifest.write_text(json.dumps({
        "source_file_sha256":None, # supplied by original separate science audit
        "research_wind_only":True,
        "full_future_EPWs":False,
        "same_34_fields_except_speed":True,
        "members":data},indent=2)+"\n")
    return data


def run(base,audit,out,source_type,signals=p8c.SIGNALS):
    headers,source,source_metadata=read_epw(base)
    auth=authenticate(base,source_metadata,audit,source_type)
    ratio,ratio_metadata=p8c.read_registered_wind_ratios(signals)
    result=[]
    for model in p7c3.MODELS:
        for window in p7c3.WINDOWS:
            transformed,metrics=monthly_scalar_wind_morph(
                headers,source,model,window,ratio)
            result.append(metrics)
    if len(result)!=SCENARIOS or any(
        m["maximum_monthly_speed_balance_mps"]>.001 for m in result):
        raise ValueError("P8D_32_WIND_ONLY_SCENARIOS_NOT_CLOSED")
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    counter=counterfactuals(headers,source,out/"_private_hourly_epws")
    payload={
        "phase":"IGE_P8_4D",
        "status":"EPW_WIND_ONLY_STRUCTURE_QC_COMPLETED",
        "input_source":auth,
        "input_epw":source_metadata,
        "registered_wind_ratios":ratio_metadata,
        "n_models":len(p7c3.MODELS),
        "n_windows":len(p7c3.WINDOWS),
        "n_wind_only_scenario_audits":len(result),
        "scenario_metrics":result,
        "counterfactual_manifest":counter,
        "all_32_wind_morphs_structurally_valid":True,
        "scenarios_with_physical_wind_exposure_blockers":sum(
            m["physical_wind_exposure_blocker_hours"]>0 for m in result),
        "authenticated_28_meteonorm_EPWs_executed":False,
        "independent_native_future_wind_direction_proven":False,
        "wind_rose_is_conditional_on_calm_speed_threshold":True,
        "natural_ventilation_physically_calibrated":False,
        "energyplus_wind_sensitive_executed":False,
        "production_epw_ready":False,
    }
    (out/"p8_4d_epw_wind_32_scenario_aggregates.json").write_text(
        json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("IGE_P8_4D_WIND_ONLY",json.dumps({
        "source_tier":auth["evidence_tier"],
        "n_scenarios":len(result),
        "blocked_states":payload["scenarios_with_physical_wind_exposure_blockers"],
        "production_epw_ready":False,
    }),flush=True)
    return payload


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--base",required=True)
    parser.add_argument("--audit",required=True)
    parser.add_argument("--source-type",choices=("p7b5_public","licensed_local"),required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--signals",default=p8c.SIGNALS)
    options=parser.parse_args()
    run(options.base,options.audit,options.out,options.source_type,options.signals)
