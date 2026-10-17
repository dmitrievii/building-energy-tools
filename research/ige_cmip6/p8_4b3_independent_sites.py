#!/usr/bin/env python3
"""IGE P8.4B3 frozen 18 unseen elevation-stratified Swiss wind targets.

Predeclared original SwissMetNet 2023 donor-only and full 2024/2025 source
wind data. Frozen B2 source-direction-coherence selector is NOT refitted.
All original source rows stay transient; only site/year scientific aggregates.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
import p8_4b2_joint_wind as b2
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2e_crossyear import ROOT

# IDs from the earlier P8.3 and P8.4 target evaluation protocols. These are
# excluded BEFORE source-availability or novel site errors are reviewed.
PRIOR_TARGETS=frozenset(
    "ABO BER PAY BAS CHD GRA MUB STG VIS MOE MAS NEU GUT FRU BOL "
    "AIG THU INT RAG ZER VIT DIA CDM GRE BIZ SAE CRM".split()
)
BIN_COUNTS=(("low",0.,600.,6),
            ("mid",600.,1300.,6),
            ("high",1300.,5000.,6))
N_SITES=18
SPACING_KM=15.
SOURCE_BLOCK_RADIUS_KM=25.
SCENARIOS=("unbuffered","exclude_25km")
EXPECTED_WEIGHTS=(.65,.25,.10)
SCIENTIFIC_MIN_EFFECT_MPS=.02
SCIENTIFIC_IMPROVED_SITES=6
SCIENTIFIC_NONWORSE_SITES=12


def tie_key(site):
    return hashlib.sha256(
        ("IGE-P8.4B3-20261017:"+site).encode("ascii")).hexdigest()


def choose_new_targets(metadata,eligible_ids):
    """No observed weather values, donor prediction or holdout errors enter."""
    candidates=set(metadata).intersection(eligible_ids)-PRIOR_TARGETS
    if len(candidates)<N_SITES:
        raise ValueError("B3_TOO_FEW_ELIGIBLE_UNSEEN_STATION_IDS")
    selected=[]
    bins={}
    for group,lo,hi,n in BIN_COUNTS:
        pool=[
            sid for sid in candidates if lo<=metadata[sid]["hoehe_m"]<hi
            and sid not in selected
        ]
        if len(pool)<n:
            raise ValueError("B3_INSUFFICIENT_ALTITUDE_BIN_"+group)
        chosen=[]
        for _ in range(n):
            distances={}
            for sid in pool:
                if selected:
                    nearest=min(
                        float(haversine(metadata[sid]["lat"],metadata[sid]["lon"],
                                        metadata[other]["lat"],metadata[other]["lon"]))
                        for other in selected)
                else:
                    nearest=float("inf")
                if nearest>=SPACING_KM:
                    distances[sid]=nearest
            if not distances:
                raise ValueError("B3_PREDECLARED_GEOGRAPHIC_SPACING_UNAVAILABLE_"+group)
            if selected:
                sid=min(distances,key=lambda s:(-distances[s],tie_key(s),s))
            else:
                sid=min(distances,key=lambda s:(tie_key(s),s))
            chosen.append(sid)
            selected.append(sid)
            pool.remove(sid)
        bins[group]=chosen
    if len(selected)!=N_SITES or len(set(selected))!=N_SITES:
        raise AssertionError("B3_TARGET_ID_CENSUS_BROKEN")
    if PRIOR_TARGETS.intersection(selected):
        raise AssertionError("B3_TARGET_WAS_PREVIOUSLY_TESTED")
    return tuple(selected),bins


def geometrically_blocked(target,metadata,qualified):
    eligible={
        sid for sid in qualified
        if float(haversine(target["lat"],target["lon"],
                           metadata[sid]["lat"],metadata[sid]["lon"]))>=SOURCE_BLOCK_RADIUS_KM
    }
    if len(eligible)<b2.CANDIDATES:
        raise ValueError("B3_INSUFFICIENT_BUFFERED_DONORS_"+target["station_id"])
    return eligible


def registered_research_gates(records,year,scenario):
    group=[r for r in records if r["year"]==year and r["scenario"]==scenario]
    if len(group)!=N_SITES or len({r["site"] for r in group})!=N_SITES:
        raise ValueError("B3_MISSING_18_UNIQUE_STATION_RESULTS")
    delta_speed=[]
    delta_cov=[]
    delta_fixed90=[]
    improved=0
    nonworse=0
    maxloss_speed=float("-inf")
    maxloss_coverage=float("-inf")
    for r in group:
        data={x["method"]:x for x in r["result"]["metrics"]}
        baseline=data["altitude_idw4"]
        joint=data["joint_source_coherence_idw4"]
        d=joint["scalar_speed_MAE_mps"]-baseline["scalar_speed_MAE_mps"]
        coverage=joint["union_coverage_pct"]-baseline["union_coverage_pct"]
        azimuth=(joint["union_fixed90_missing_diagnostic_deg"]-
                 baseline["union_fixed90_missing_diagnostic_deg"])
        delta_speed.append(d)
        delta_cov.append(coverage)
        delta_fixed90.append(azimuth)
        improved+=d<=-SCIENTIFIC_MIN_EFFECT_MPS
        nonworse+=d<=1e-8
        maxloss_speed=max(maxloss_speed,d)
        maxloss_coverage=max(maxloss_coverage,-coverage)
    mean_speed=statistics.mean(delta_speed)
    mean_cov=statistics.mean(delta_cov)
    mean_angle=statistics.mean(delta_fixed90)
    gates={
        "material_equal_site_MAE_gain_0p02mps":mean_speed<=-SCIENTIFIC_MIN_EFFECT_MPS,
        "at_least_six_sites_gain_0p02mps":improved>=SCIENTIFIC_IMPROVED_SITES,
        "at_least_twelve_sites_speed_nonworsening":nonworse>=SCIENTIFIC_NONWORSE_SITES,
        "no_site_speed_deterioration_gt_0p15mps":maxloss_speed<=.15,
        "mean_union_direction_coverage_within_2pp":mean_cov>=-2.,
        "no_site_union_direction_coverage_loss_gt_10pp":maxloss_coverage<=10.,
        "mean_fixed90_missing_diagnostic_nonworsening":mean_angle<=0.,
    }
    return {
        "year":year,"scenario":scenario,
        "passed":all(gates.values()),"gates":gates,
        "mean_delta_speed_MAE_mps":mean_speed,
        "n_improved_by_at_least_0p02":improved,
        "n_speed_nonworse":nonworse,
        "max_speed_deterioration_mps":maxloss_speed,
        "mean_delta_union_coverage_pp":mean_cov,
        "max_union_coverage_loss_pp":maxloss_coverage,
        "mean_delta_fixed90_deg":mean_angle,
    }


def run(out):
    if (b2.COEFFICIENT_GEOMETRY,b2.COEFFICIENT_DIRECTION,
        b2.COEFFICIENT_COVERAGE)!=EXPECTED_WEIGHTS:
        raise AssertionError("B3_FROZEN_B2_COEFFICIENTS_DRIFTED")
    raw,metadata_sha=fetch(ROOT+"/ogd-smn_meta_stations.csv",max_bytes=1_500_000)
    metadata,_=parse_meta(raw)
    original,qualified,census=b2.source_census(metadata)
    if len(metadata)<b2.MIN_STATIONS or len(census)!=len(metadata):
        raise AssertionError("B3_NOT_A_FULL_CATALOG_CENSUS")
    # Availability requirement in both years and frozen donor-only training
    # was applied by B2.source_census; NEVER inspect new target wind error.
    eligible=qualified[2024].intersection(qualified[2025])
    selected,altitude_groups=choose_new_targets(metadata,eligible)
    excluded=set(selected)|set(b2.TARGETS)
    if excluded.intersection(eligible-set(selected)-set(b2.TARGETS)):
        raise AssertionError("B3_INCONSISTENT_TARGET_EXCLUSION")
    eval_results=[]
    for year in b2.EVALUATION_YEARS:
        eligible_donors=set(qualified[year])-excluded
        if len(eligible_donors)<b2.MIN_QUALIFIED_DONORS:
            raise ValueError("B3_INSUFFICIENT_INDEPENDENT_DONORS")
        for target_id in selected:
            target=metadata[target_id]
            for scenario in SCENARIOS:
                candidates=(eligible_donors if scenario=="unbuffered" else
                            geometrically_blocked(target,metadata,eligible_donors))
                # original B2 selected_donors and all thresholds are IMMUTABLE.
                result=b2.site_result(
                    target_id,year,metadata,candidates,
                    original[b2.TRAIN_YEAR],original[year]
                )
                for mode in b2.METHODS:
                    if any(record["id"] in excluded for record in result["donors"][mode]):
                        raise AssertionError("B3_GLOBAL_TARGET_DONOR_LEAK")
                    if scenario=="exclude_25km" and any(
                        record["distance_km"]<SOURCE_BLOCK_RADIUS_KM-1e-7
                        for record in result["donors"][mode]):
                        raise AssertionError("B3_SPATIAL_BUFFER_LEAK")
                eval_results.append({
                    "site":target_id,
                    "year":year,
                    "scenario":scenario,
                    "altitude_bin":next(g for g,sites in altitude_groups.items() if target_id in sites),
                    "result":result,
                })
    accept=[registered_research_gates(eval_results,y,s)
            for y in b2.EVALUATION_YEARS for s in SCENARIOS]
    research_pass=all(x["passed"] for x in accept)
    artifact={
        "stage":"IGE_P8_4B3",
        "status":"FROZEN_INDEPENDENT_TARGET_SPATIAL_STRESS_COMPLETED",
        "metadata_original_sha256":metadata_sha,
        "catalog_size":len(metadata),
        "source_catalog_attempted":len(census),
        "full_catalog_original_provenance":census,
        "known_prior_targets_excluded":sorted(PRIOR_TARGETS),
        "new_targets":list(selected),
        "new_target_altitude_groups":altitude_groups,
        "target_selection_uses_holdout_prediction_skill":False,
        "source_eligibility_based_on_retro_2023_2024_2025_data_availability":True,
        "globally_excluded_donor_target_ids":sorted(excluded),
        "qualified_source_pool_2024":len(qualified[2024]-excluded),
        "qualified_source_pool_2025":len(qualified[2025]-excluded),
        "frozen_coherence_weights":list(EXPECTED_WEIGHTS),
        "new_target_minimum_spacing_km":SPACING_KM,
        "source_block_radius_km":SOURCE_BLOCK_RADIUS_KM,
        "target_site_year_scenario_results":eval_results,
        "scientific_gate_results":accept,
        "broad_elevation_stratified_swiss_generalization_accepted":research_pass,
        "same_hour_original_historical_donors_not_future_wind":True,
        "source_per_record_quality_flags_verified":False,
        "wind_anemometer_height_roughness_verified":False,
        "frozen_b2_source_2023_training_only":True,
        "production_epw_ready":False,
        "original_provider_hourly_observations_published":False,
    }
    folder=Path(out)
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"p8_4b3_independent_targets_2024_2025_aggregates.json").write_text(
        json.dumps(artifact,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IGE_P8_4B3",json.dumps({
        "status":artifact["status"],
        "catalog_attempted":len(census),
        "targets":list(selected),
        "acceptance":accept,
        "generalization_accepted":research_pass,
        "production_epw_ready":False
    },sort_keys=True,ensure_ascii=False),flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    run(args.out)
