#!/usr/bin/env python3
"""IGE P8.4B2 frozen source-only wind speed + direction donor suitability.

Training uses only 2023 donor observations (at 6h cadence). Retrospective
evaluations: 2024 leap-year and 2025, six sites never entering donor sets.
Derived aggregates only, no original station time series/DEM copied.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from p8_1e_swiss_external import fetch, parse_meta
from p8_2e_crossyear import ROOT, annual_hours
from p8_3a_wind_spatial import CALM_MPS, circular_error_deg, usable_wind, wind_coverage
from p8_3d_wind_terrain_donors import (
    MIN_TARGET, MIN_WIND_YEAR, choose_donors, score_site, ranking_score
)

TRAIN_YEAR=2023
EVALUATION_YEARS=(2024,2025)
TARGETS=("DIA","CDM","GRE","BIZ","SAE","CRM")
METHODS=("distance_idw4","altitude_idw4","joint_source_coherence_idw4")
CANDIDATES=10
DONORS=4
MIN_STATIONS=150
MIN_QUALIFIED_DONORS=65
MIN_TRAIN_COVERAGE=.75
MIN_HOLDOUT_COVERAGE=.80
TRAIN_CADENCE_H=6
MIN_SHARED_TRAIN_NONCALM=120
COEFFICIENT_GEOMETRY=.65
COEFFICIENT_DIRECTION=.25
COEFFICIENT_COVERAGE=.10
BOOTSTRAP_DAYS=7
BOOTSTRAP_REPS=400
BASE_SEED=20261017
MIN_SOURCE_YEAR_COVERAGE=.90
CALM=CALM_MPS


def train_hours():
    begin=dt.datetime(TRAIN_YEAR,1,1)
    return tuple(begin+dt.timedelta(hours=h) for h in range(0,8760,TRAIN_CADENCE_H))


def source_three_years(raw,site):
    """Only selected 2023 6h training + 2024/2025 full data retained."""
    try:
        src=raw.decode("utf-8-sig","strict")
    except UnicodeDecodeError as exc:
        raise ValueError("B2_ORIGINAL_CSV_BAD_ENCODING_"+site) from exc
    reader=csv.DictReader(io.StringIO(src),delimiter=";")
    needed={"station_abbr","reference_timestamp","fkl010h0","dkl010h0"}
    if not needed.issubset(reader.fieldnames or []):
        raise ValueError("B2_MISSING_ORIGINAL_WIND_FIELDS_"+site)
    result={TRAIN_YEAR:{},**{y:{} for y in EVALUATION_YEARS}}
    clockset=set(train_hours())
    for row in reader:
        if (row.get("station_abbr") or "").strip().upper()!=site:
            continue
        stamp=row.get("reference_timestamp") or ""
        if len(stamp)<16 or stamp[6:10] not in ("2023","2024","2025"):
            continue
        try:
            when=dt.datetime.strptime(stamp,"%d.%m.%Y %H:%M")
        except ValueError as exc:
            raise ValueError("B2_INVALID_ORIGINAL_WIND_TIMESTAMP_"+site) from exc
        if when.minute!=0 or when.second:
            raise ValueError("B2_NONHOURLY_ORIGINAL_STAMP_"+site)
        if when.year==TRAIN_YEAR and when not in clockset:
            continue
        if when in result[when.year]:
            raise ValueError("B2_DUPLICATE_ORIGINAL_WIND_STAMP_"+site)
        def value(key,hi):
            try:
                v=float(row[key])
                return v if math.isfinite(v) and 0<=v<=hi else None
            except (ValueError,TypeError):
                return None
        s=value("fkl010h0",90.)
        d=value("dkl010h0",360.)
        result[when.year][when]={"speed":s,"direction":d%360 if d is not None else None}
    return result,tuple(c for c in (reader.fieldnames or ()) if
                         c in ("fkl010h0_flag","dkl010h0_flag","fkl010h0_qc","dkl010h0_qc"))


def one_station(site):
    address=f"{ROOT}/{site.lower()}/ogd-smn_{site.lower()}_h_historical_2020-2029.csv"
    raw,sha=fetch(address,max_bytes=40_000_000)
    data,flags=source_three_years(raw,site)
    del raw
    counts={}
    for year in EVALUATION_YEARS:
        hours=annual_hours(year)
        c=wind_coverage(data[year],hours)
        counts[year]={"usable_hours":c["usable_wind_hours"],
                      "available_hours":c["speed_hours"],
                      "qualified":c["usable_wind_hours"]>=math.ceil(MIN_SOURCE_YEAR_COVERAGE*len(hours))}
    training=sum(usable_wind(data[TRAIN_YEAR].get(t)) for t in train_hours())
    counts[TRAIN_YEAR]={
        "sample_count":len(train_hours()),
        "usable_hours":training,
        "qualified":training>=math.ceil(MIN_TRAIN_COVERAGE*len(train_hours()))}
    return site,data,{"station_id":site,"original_sha256":sha,
                      "read_ok":True,"source_qc_fields":flags,
                      "per_record_quality_semantics_verified":False,
                      "coverage":counts}


def source_census(metadata):
    """Attempt every official station, no geographic shortlist."""
    ids=tuple(sorted(metadata))
    if len(ids)<MIN_STATIONS:
        raise ValueError("B2_SOURCE_CATALOG_NOT_FULL")
    rows=[]
    byyear={year:{} for year in (TRAIN_YEAR,)+EVALUATION_YEARS}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        tasks={pool.submit(one_station,sid):sid for sid in ids}
        for future in concurrent.futures.as_completed(tasks):
            sid=tasks[future]
            try:
                site,data,report=future.result()
                for year in byyear:
                    byyear[year][site]=data[year]
                rows.append(report)
            except Exception as exc:
                rows.append({"station_id":sid,"read_ok":False,
                             "source_error":type(exc).__name__+": "+str(exc)[:180],
                             "per_record_quality_semantics_verified":False})
    rows.sort(key=lambda r:r["station_id"])
    if len(rows)!=len(ids) or {r["station_id"] for r in rows}!=set(ids):
        raise AssertionError("B2_NOT_ALL_METADATA_SITES_ATTEMPTED")
    qualified={}
    for year in EVALUATION_YEARS:
        qualified[year]=set(
            r["station_id"] for r in rows if r["read_ok"]
            and r["coverage"][year]["qualified"]
            and r["coverage"][TRAIN_YEAR]["qualified"]
            and r["station_id"] not in TARGETS
        )
        if len(qualified[year])<MIN_QUALIFIED_DONORS:
            raise ValueError("B2_INSUFFICIENT_FULL_CENSUS_ELIGIBLE_DONORS_"+str(year))
        for sid in TARGETS:
            rec=next(r for r in rows if r["station_id"]==sid)
            if not rec["read_ok"] or not rec["coverage"][year]["qualified"]:
                raise ValueError("B2_FROZEN_TARGET_NO_WIND_COVERAGE_"+sid+"_"+str(year))
    return byyear,qualified,rows


def donor_pair_direction_dissimilarity(a,b,training):
    """Only original same-UTC 2023 donor readings; no target values."""
    x=training.get(a,{})
    y=training.get(b,{})
    diffs=[]
    for hour in train_hours():
        p=x.get(hour);q=y.get(hour)
        if (not usable_wind(p) or not usable_wind(q)
                or p["speed"]<CALM or q["speed"]<CALM):
            continue
        diffs.append(circular_error_deg(p["direction"],q["direction"])/180.)
    if len(diffs)<MIN_SHARED_TRAIN_NONCALM:
        return 1.0,len(diffs),True
    return statistics.mean(diffs),len(diffs),False


def candidate_pool(target,metadata,qualified):
    from p8_1e_swiss_external import haversine
    ranked=[]
    for site in qualified:
        if site in TARGETS:
            raise AssertionError("B2_GLOBAL_TARGET_DONOR_LEAK")
        record=metadata[site]
        dist=float(haversine(target["lat"],target["lon"],record["lat"],record["lon"]))
        score=ranking_score(target,record,dist,{}, "altitude_idw4")
        ranked.append((score,dist,site))
    ranked.sort(key=lambda v:(v[0],v[1],v[2]))
    if len(ranked)<CANDIDATES:
        raise ValueError("B2_NOT_ENOUGH_CANDIDATES")
    return tuple(ranked[:CANDIDATES])


def joint_source_coherence_selector(target,metadata,qualified,training):
    """Frozen 10-choose-4 geometric/source directional coherence selector."""
    ranked=candidate_pool(target,metadata,qualified)
    median_geometry=statistics.median(r[0] for r in ranked)
    if median_geometry<=0:
        raise ValueError("B2_BAD_GEOMETRY_SCALE")
    ids=[x[2] for x in ranked]
    covered={}
    for sid in ids:
        row=training[sid]
        covered[sid]=sum(usable_wind(row.get(t)) for t in train_hours())/len(train_hours())
    pair={}
    pair_evidence={}
    for a,b in itertools.combinations(sorted(ids),2):
        pair[(a,b)],n,insufficient=donor_pair_direction_dissimilarity(a,b,training)
        pair_evidence[(a,b)]={"hours":n,"insufficient":insufficient}
    options=[]
    for group in itertools.combinations(ranked,DONORS):
        geom=statistics.mean(x[0]/median_geometry for x in group)
        pairs=[pair[tuple(sorted((a[2],b[2])))] for a,b in itertools.combinations(group,2)]
        disagreement=statistics.mean(pairs)
        coverage=statistics.mean(1.-covered[x[2]] for x in group)
        objective=(COEFFICIENT_GEOMETRY*geom+
                   COEFFICIENT_DIRECTION*disagreement+
                   COEFFICIENT_COVERAGE*coverage)
        options.append((objective,tuple(sorted(x[2] for x in group)),group,
                        {"geometric":geom,"pair_direction_disagreement":disagreement,
                         "source_missing_fraction":coverage}))
    options.sort(key=lambda r:(r[0],r[1]))
    _,chosen,group,components=options[0]
    return (
        [(float(next(x[1] for x in ranked if x[2]==sid)),metadata[sid]) for sid in chosen],
        {"candidate_ids":[x[2] for x in ranked],
         "chosen_ids":list(chosen),
         "search_combinations":len(options),
         "frozen_training_year":TRAIN_YEAR,
         "objective":options[0][0],
         "components":components,
         "n_pairwise_low_evidence":sum(v["insufficient"] for v in pair_evidence.values()),
         "no_target_observations_used":True},
    )


def selected_donors(target,metadata,qualified,training):
    if any(s in qualified for s in TARGETS):
        raise AssertionError("B2_TARGET_WAS_ELIGIBLE_DONOR")
    distance=choose_donors(target,metadata,qualified,{},"distance_idw4")
    altitude=choose_donors(target,metadata,qualified,{},"altitude_idw4")
    joint,evidence=joint_source_coherence_selector(target,metadata,qualified,training)
    all_sets={"distance_idw4":distance,"altitude_idw4":altitude,
              "joint_source_coherence_idw4":joint}
    for name,rows in all_sets.items():
        if len(rows)!=DONORS or {r["station_id"] for _,r in rows}.intersection(TARGETS):
            raise AssertionError("B2_DONOR_LEAK_OR_COUNT_"+name)
    return all_sets,evidence


def union_direction(row):
    if row["vector_direction"] is not None:
        return row["vector_direction"]
    return row["unit_direction"]


def paired_predictions(site,year,selections,observations):
    hours=annual_hours(year)
    predicted={name:score_site(site,hours,donors,observations)
               for name,donors in selections.items()}
    same=set(hours)
    for p in predicted.values():
        same.intersection_update(p)
    if len(same)<math.ceil(MIN_HOLDOUT_COVERAGE*len(hours)):
        raise ValueError("B2_TOO_FEW_IDENTICAL_TEST_HOURS_"+site+"_"+str(year))
    return predicted,tuple(sorted(same))


def method_metrics(site,year,method,predicted,common):
    reference=predicted[method]
    noncalm=[t for t in common if reference[t]["reference_direction"] is not None]
    e=[reference[t]["scalar"]-reference[t]["reference_speed"] for t in common]
    result={"site":site,"year":year,"method":method,
            "n_common_full_year_hours":len(common),
            "n_reference_noncalm":len(noncalm),
            "scalar_speed_MAE_mps":statistics.mean(abs(v) for v in e),
            "scalar_speed_bias_mps":statistics.mean(e),
            "scalar_speed_RMSE_mps":math.sqrt(statistics.mean(v*v for v in e))}
    for title,methodfn in (("vector",lambda r:r["vector_direction"]),
                           ("unit",lambda r:r["unit_direction"]),
                           ("union",union_direction)):
        found=[t for t in noncalm if methodfn(reference[t]) is not None]
        scores=[circular_error_deg(methodfn(reference[t]),reference[t]["reference_direction"])
                for t in found]
        result.update({
            title+"_n_resolved":len(found),
            title+"_coverage_pct":100*len(found)/len(noncalm) if noncalm else None,
            title+"_direction_emitted_MAE_deg":statistics.mean(scores) if scores else None,
            title+"_fixed90_missing_diagnostic_deg":(
                (sum(scores)+90*(len(noncalm)-len(found)))/len(noncalm)
                if noncalm else None),
        })
    return result


def equal_hour_joint_inference(site,year,predicted,common):
    strict=[t for t in common
            if predicted[METHODS[0]][t]["reference_direction"] is not None
            and all(union_direction(predicted[m][t]) is not None for m in METHODS)]
    angles={m:(statistics.mean(circular_error_deg(
        union_direction(predicted[m][t]),predicted[m][t]["reference_direction"])
        for t in strict) if strict else None) for m in METHODS}
    return {"site":site,"year":year,
            "n_three_selector_resolved_direction_hours":len(strict),
            "strict_common_union_direction_MAE_deg":angles}


def speed_effect_pairs(predicted,common,comp="joint_source_coherence_idw4",
                       baseline="altitude_idw4"):
    return tuple((t,abs(predicted[comp][t]["scalar"]-predicted[comp][t]["reference_speed"])
                  -abs(predicted[baseline][t]["scalar"]-predicted[baseline][t]["reference_speed"]))
                 for t in common)


def calendar_block_ci(pairs,year,site,reps=BOOTSTRAP_REPS):
    """7-calendar-day bootstrap, correct leap-year 2024; no day-gap imputation."""
    n_days=(dt.date(year+1,1,1)-dt.date(year,1,1)).days
    daily={dt.date(year,1,1)+dt.timedelta(days=i):[0.,0] for i in range(n_days)}
    for timestamp,error in pairs:
        if timestamp.date() not in daily:
            raise ValueError("B2_PAIRS_OUTSIDE_EVALUATION_YEAR")
        daily[timestamp.date()][0]+=error
        daily[timestamp.date()][1]+=1
    dates=tuple(sorted(daily))
    blocks=[]
    for i in range(n_days-BOOTSTRAP_DAYS+1):
        rows=[daily[d] for d in dates[i:i+BOOTSTRAP_DAYS]]
        count=sum(x[1] for x in rows)
        if count>=.75*BOOTSTRAP_DAYS*24:
            blocks.append((sum(x[0] for x in rows),count))
    if len(blocks)<180 or not pairs:
        raise ValueError("B2_INSUFFICIENT_CONTIGUOUS_REAL_OBSERVATIONS")
    seed=int.from_bytes(hashlib.sha256(
        f"P8.4B2:{BASE_SEED}:{site}:{year}".encode()).digest()[:8],"big")
    rng=random.Random(seed)
    values=[]
    for _ in range(reps):
        chosen=[blocks[rng.randrange(len(blocks))]
                for _ in range(math.ceil(n_days/BOOTSTRAP_DAYS))]
        values.append(sum(x[0] for x in chosen)/sum(x[1] for x in chosen))
    values.sort()
    return {"year":year,"site":site,"n_paired_hours":len(pairs),
            "calendar_days":n_days,
            "block_days":BOOTSTRAP_DAYS,"n_bootstrap":reps,
            "delta_MAE_mps":statistics.mean(x[1] for x in pairs),
            "CI95_low_mps":values[int((reps-1)*.025)],
            "CI95_high_mps":values[int((reps-1)*.975)]}


def site_result(site,year,metadata,qualified,training,observed):
    methods,evidence=selected_donors(metadata[site],metadata,qualified,training)
    predicted,common=paired_predictions(site,year,methods,observed)
    metrics=[method_metrics(site,year,m,predicted,common) for m in METHODS]
    inference=equal_hour_joint_inference(site,year,predicted,common)
    ci=calendar_block_ci(speed_effect_pairs(predicted,common),year,site)
    return {"site":site,"year":year,"same_UTC_hours":len(common),
            "metrics":metrics,"joint_speed_delta_bootstrap":ci,
            "strict_direction_comparison":inference,
            "source_coherence_training_only":evidence,
            "donors":{m:[{"id":v["station_id"],"distance_km":dist,
                          "altitude_masl":v["hoehe_m"]} for dist,v in rows]
                      for m,rows in methods.items()},
            "joint_selection_differs_from_altitude":{
                v["station_id"] for _,v in methods["joint_source_coherence_idw4"]}!={
                v["station_id"] for _,v in methods["altitude_idw4"]}}


def evaluate_gates(records,year):
    group=[r for r in records if r["year"]==year]
    if len(group)!=len(TARGETS):
        raise ValueError("B2_NOT_SIX_VALIDATION_SITES")
    a={};n={}
    for r in group:
        a[r["site"]]=next(m for m in r["metrics"] if m["method"]=="altitude_idw4")
        n[r["site"]]=next(m for m in r["metrics"] if m["method"]=="joint_source_coherence_idw4")
    ave=lambda ref,key:statistics.mean(ref[s][key] for s in TARGETS)
    delta_speed=ave(n,"scalar_speed_MAE_mps")-ave(a,"scalar_speed_MAE_mps")
    delta_cov=ave(n,"union_coverage_pct")-ave(a,"union_coverage_pct")
    delta_angle=ave(n,"union_fixed90_missing_diagnostic_deg")-ave(a,"union_fixed90_missing_diagnostic_deg")
    speed_nonworse=sum(n[s]["scalar_speed_MAE_mps"]<=a[s]["scalar_speed_MAE_mps"]+1e-8 for s in TARGETS)
    max_site_speed_loss=max(n[s]["scalar_speed_MAE_mps"]-a[s]["scalar_speed_MAE_mps"] for s in TARGETS)
    max_site_coverage_loss=max(a[s]["union_coverage_pct"]-n[s]["union_coverage_pct"] for s in TARGETS)
    gates={
        "equal_site_speed_MAE_nonworsening":delta_speed<=0,
        "equal_site_direction_coverage_within_minus_2pp":delta_cov>=-2.,
        "equal_site_fixed90_diagnostic_nonworsening":delta_angle<=0,
        "no_site_coverage_loss_gt_10pp":max_site_coverage_loss<=10.,
        "no_site_speed_loss_gt_0p15mps":max_site_speed_loss<=.15,
        "at_least_four_of_six_sites_nonworse_speed":speed_nonworse>=4}
    return {"year":year,"joint_selection_accepted":all(gates.values()),
            "gates":gates,
            "equal_site_delta_speed_MAE_mps":delta_speed,
            "equal_site_delta_union_coverage_pp":delta_cov,
            "equal_site_delta_fixed90_deg":delta_angle,
            "max_site_speed_loss_mps":max_site_speed_loss,
            "max_site_union_coverage_loss_pp":max_site_coverage_loss,
            "speed_nonworsening_site_count":speed_nonworse}


def run(out):
    raw,sha=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
    metadata,_=parse_meta(raw)
    if not set(TARGETS).issubset(metadata):
        raise ValueError("B2_PREDECLARED_TARGET_METADATA_MISSING_"+str(sorted(set(TARGETS)-set(metadata))))
    original,qualified,census=source_census(metadata)
    results=[]
    for year in EVALUATION_YEARS:
        for site in TARGETS:
            results.append(site_result(site,year,metadata,qualified[year],
                                       original[TRAIN_YEAR],original[year]))
    years=[evaluate_gates(results,year) for year in EVALUATION_YEARS]
    overall=all(x["joint_selection_accepted"] for x in years)
    result={
        "phase":"IGE_P8_4B2",
        "status":"ORIGINAL_SOURCE_JOINT_WIND_VALIDATION_EXECUTED",
        "source_metadata_sha256":sha,
        "source_catalog_size":len(metadata),
        "source_catalog_attempted":len(census),
        "source_census":census,
        "source_2023_training_only":True,
        "training_sampling_cadence_hours":TRAIN_CADENCE_H,
        "target_ids":list(TARGETS),
        "evaluation_years":list(EVALUATION_YEARS),
        "n_qualified_exclusive_donors":{str(k):len(v) for k,v in qualified.items()},
        "source_2023_target_weather_excluded_from_selection":True,
        "site_results":results,
        "annual_acceptance":years,
        "scientific_joint_selector_accepted":overall,
        "historical_same_hour_donor_observations_only":True,
        "wind_rose_generalization_beyond_switzerland_qualified":False,
        "observed_source_per_record_QC_verified":False,
        "instrument_height_and_surface_roughness_verified":False,
        "future_climate_wind_generator_accepted":False,
        "production_epw_ready":False,
        "original_hourly_observations_published":False,
    }
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    (folder/"p8_4b2_joint_wind_2024_2025_original_aggregates.json").write_text(
        json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IGE_P8_4B2",json.dumps({
        "status":result["status"],"attempted":len(census),
        "qualified":result["n_qualified_exclusive_donors"],
        "annual_acceptance":years,
        "scientific_joint_selector_accepted":overall,
        "production_epw_ready":False,
    },ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--out",required=True)
    arg=a.parse_args()
    run(arg.out)
