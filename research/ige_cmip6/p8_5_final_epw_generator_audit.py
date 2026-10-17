#!/usr/bin/env python3
"""IGE P8.5 evidence-driven FINAL EPW Generator audit.

This audits immutable published P7C3–P7C5B data and provenance relationships;
it cannot re-execute 28 licensed outputs when no source bytes are available.
Public research EPWs are assessed separately and NEVER substituted for private
Meteonorm files. Red release gates do NOT make CI itself fail when correctly
and transparently reported.
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

import p7c3_ensemble as ensemble
import p8_4c_future_wind_baseline as wind
import p8_4d_epw_wind_qualification as wind_epw

ROOT=Path("research/ige_cmip6/results")
BASELINE_SHA="dad69174304c3a13cc095841c4cb9636bf99cc3f33a81502c553af862cd06677"
P7C4=ROOT/"p7c4_public_aggregated_science_summary.json"
P7C4_MEMBERS=ROOT/"p7c4_28_hourly_model_summary.csv"
P7C4_BLOCK=ROOT/"p7c4_4_blocked_ipsl_humidity.csv"
P7C5=ROOT/"p7c5_member_physical_summary.csv"
P7C5B=ROOT/"p7c5b_photometric_science_audit.json"
P7C5B_MEMBERS=ROOT/"p7c5b_photometric_28_summary.csv"
EXPECTED_FULL=28
EXPECTED_BLOCKED=4
OPT_MAX_ITER=600
KNOWN_MISSING_HUSS="IPSL-CM6A-LR"
WIND_CALM=.5


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as fp:
        r=csv.DictReader(fp)
        if not r.fieldnames or len(set(r.fieldnames))!=len(r.fieldnames):
            raise ValueError("P8F_BAD_INPUT_HEADERS_"+str(path))
        return list(r)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def truth(s):
    if isinstance(s,bool):return s
    if s=="True":return True
    if s=="False":return False
    raise ValueError("P8F_INVALID_EXPLICIT_BOOLEAN_"+str(s))


def source_matrix():
    ratios,meta=wind.read_registered_wind_ratios(wind.SIGNALS)
    assert len(ratios)==384
    return {
        "source_csv_sha256":meta["immutable_committed_GCM_signal_sha256"],
        "n_models":len(ensemble.MODELS),
        "n_periods":len(ensemble.WINDOWS),
        "n_original_GCM_monthly_signals":len(ratios),
        "min_wind_ratio":min(ratios.values()),
        "max_wind_ratio":max(ratios.values()),
        "source_zip_bytes_reverified_in_this_audit":False,
        "original_source_zip_provenance_previously_registered":True,
    }


def registered_member_identity():
    return {(m,w) for m in ensemble.MODELS
            for w in ensemble.WINDOWS}


def validate_manifests(paths=None):
    paths=paths or {}
    get=lambda k,p:Path(paths.get(k,p))
    pub=read_json(get("p7c4",P7C4))
    members=read_csv(get("p7c4_members",P7C4_MEMBERS))
    blocked=read_csv(get("p7c4_block",P7C4_BLOCK))
    physical=read_csv(get("p7c5_members",P7C5))
    photos=read_csv(get("p7c5b_members",P7C5B_MEMBERS))
    photoaudit=read_json(get("p7c5b",P7C5B))
    if any(int(pub[k])!=v for k,v in (
        ("n_gcm",8),("n_windows",4),
        ("n_candidate_hourly_combinations",32),
        ("n_generated_hourly_epws",28),
        ("n_blocked_missing_huss",4),
        ("n_validated_monthly_q_closures",336),
        ("source_20y_windows_audited",40))):
        raise ValueError("P8F_PUBLIC_GCM_MODEL_CENSUS_INCONSISTENT")
    if pub["baseline_sha256"]!=BASELINE_SHA or photoaudit["baseline_sha256"]!=BASELINE_SHA:
        raise ValueError("P8F_BASELINE_AUTHENTICATED_SHA_DIFFERENCE")
    if pub.get("production_epw_ready") is not False or photoaudit.get("production_epw_ready") is not False:
        raise ValueError("P8F_PREVIOUS_RESEARCH_MISREPRESENTED_AS_PRODUCTION")
    if len(members)!=EXPECTED_FULL or len(blocked)!=EXPECTED_BLOCKED or len(physical)!=EXPECTED_FULL or len(photos)!=EXPECTED_FULL:
        raise ValueError("P8F_P7C4_P7C5_P7C5B_MEMBER_COUNT_BIJECTION_FAILED")
    if len(pub["models"])!=EXPECTED_FULL or len(pub["blocked"])!=EXPECTED_BLOCKED or len(photoaudit["members"])!=EXPECTED_FULL:
        raise ValueError("P8F_MEMBER_REPORT_LIST_INCOMPLETE")

    expected=registered_member_identity()
    ids={(r["model"],r["window"]) for r in members}
    blks={(r["model"],r["window"]) for r in blocked}
    if len(ids)!=len(members) or len(blks)!=len(blocked) or ids&blks or ids|blks!=expected:
        raise ValueError("P8F_EXPECTED_EIGHT_GCM_FOUR_WINDOWS_BIJECTION_FAILED")
    if blks!={(KNOWN_MISSING_HUSS,w) for w in ensemble.WINDOWS}:
        raise ValueError("P8F_MISSING_HUSS_IDENTITY_DISCREPANCY")
    if any(x["status"]!="BLOCKED_MISSING_SOURCE_HUSS" or truth(x["complete_EPW_generated"]) for x in blocked):
        raise ValueError("P8F_IPSL_HUMIDITY_BLOCK_OVERRIDDEN")
    if {(r["model"],r["window"]) for r in pub["models"]}!=ids:
        raise ValueError("P8F_SUMMARY_COMBINATION_MISMATCH")
    for r in members:
        if r["member"]!="r1i1p1f1" or r["status"]!="RESEARCH_CLOSURE_PASS":
            raise ValueError("P8F_ORIGINAL_GCM_MEMBER_OR_STATUS_DRIFT")
        if not truth(r["authentic_source_graz_epw_reused"]):
            raise ValueError("P8F_PRIVATE_28_EPWS_PROVENANCE_NOT_DECLARED")
        if truth(r["production_epw_ready"]):
            raise ValueError("P8F_PREVIOUS_FULL_EPW_MARKED_PRODUCTION")
        if int(r["original_wind_direction_hours_inherited"])!=8760 or int(r["original_precipitation_occurrence_hours_inherited"])!=8760:
            raise ValueError("P8F_HISTORICAL_SEQUENCE_MUTABILITY")
        if len(r["EPW_sha256"])!=64 or len(r["source_historical_daily_csv_sha256"])!=64 or len(r["source_future_daily_csv_sha256"])!=64:
            raise ValueError("P8F_SOURCE_HASHES_MISSING")
        if float(r["max_serialized_monthly_q_error_kg_kg"])>1e-11:
            raise ValueError("P8F_BAD_HUMIDITY_MASS_CLOSURE")
        if float(r["max_daily_GHI_balance_kwh_m2"])>1e-7:
            raise ValueError("P8F_BAD_DAILY_SOLAR_CLOSURE")

    original_by_filename={r["EPW_filename"]:r for r in members}
    hash_to_original={r["EPW_sha256"]:r for r in members}
    if len(original_by_filename)!=28 or len(hash_to_original)!=28:
        raise ValueError("P8F_DUPLICATE_P7C4_SOURCE_MEMBER")
    if {r["filename"] for r in physical}!=set(original_by_filename):
        raise ValueError("P8F_P7C5_PHYSICAL_RESEARCH_SUMMARY_NOT_SAME_INPUTS")
    for p in physical:
        r=original_by_filename[p["filename"]]
        if p["sha256"]!=r["EPW_sha256"] or truth(p["physical_blocking_flag"]):
            raise ValueError("P8F_P7C5_PHYSICAL_SHA_OR_NUMERIC_DOMAIN_BAD")
        if int(p["psychrometric_RH_disagreement_gt_2pp_hours"])!=0:
            raise ValueError("P8F_P7C5_UNCLOSED_PSYCHROMETRICS")

    by_source={}
    for p in photos:
        oldhash=p["source_p7c4_sha256"]
        if oldhash not in hash_to_original or oldhash in by_source:
            raise ValueError("P8F_P7C5B_REPAIRED_SOURCE_HASH_NOT_BIJECTIVE")
        by_source[oldhash]=p
        if p["source_baseline_sha256"]!=BASELINE_SHA:
            raise ValueError("P8F_P7C5B_BASELINE_SHA_MISMATCH")
        if truth(p["production_daylight_qualified"]) or not truth(p["research_only"]):
            raise ValueError("P8F_UNQUALIFIED_PHOTOMETRY_PRESENTED_AS_VALIDATED")
        if float(p["photometric_closure_residual_max_lux"])>.5:
            raise ValueError("P8F_PHOTOMETRIC_INTEGER_ROUNDING_CLOSURE_NOT_MET")
        if int(p["fallback_channel_hours"])<0 or int(p["changed_hour_count"])==0:
            raise ValueError("P8F_EMPTY_LUMINOUS_REPAIR")
        if len(p["output_sha256"])!=64:
            raise ValueError("P8F_MISSING_REPAIRED_EPW_SHA")
    if len({x["output_sha256"] for x in photos})!=28:
        raise ValueError("P8F_P7C5B_DUPLICATE_OUTPUT_SHA")
    if {x["output_sha256"] for x in photos}!={x["output_sha256"] for x in photoaudit["members"]}:
        raise ValueError("P8F_P7C5B_CSV_JSON_OUTPUT_SHA_MISMATCH")
    if photoaudit["energyplus_actual_simulation_executed"] or photoaudit["solar_luminous_model_independently_validated"]:
        raise ValueError("P8F_P7C5B_UNGROUNDED_PHYSICAL_ACCEPTANCE")

    sat=sum(int(r["RH_100_hours"]) for r in members)
    no_convergence=sum(not truth(r["optimizer_converged_by_delta"]) for r in members)
    if no_convergence!=int(pub["optimizer_runs_without_strict_convergence"]):
        raise ValueError("P8F_OPTIMIZER_NONCONVERGENCE_HIDDEN")
    # Prior P7C4 and P7C5 count differently at saturation:
    # P7C4 np.isclose(f_rh,100,atol=1e-5) (default rtol 1e-5);
    # P7C5 counts rh>=99.995. Preserve original published totals
    # without silently rewriting either original research artifact.
    if sat!=14520:
        raise ValueError("P8F_P7C4_RH_SATURATION_AGGREGATE_DRIFT")
    if any(int(r["optim_iterations_accepted"])!=OPT_MAX_ITER for r in members):
        raise ValueError("P8F_EXPECTED_OPTIMIZATION_TRUNCATION_UNRECORDED")
    if any(float(r["optimizer_objective_after"])>=float(r["optimizer_objective_before"])
           for r in members):
        raise ValueError("P8F_HUMIDITY_OPTIMIZER_NOT_DESCENDING")
    if sum(int(r["introduced_RH_gt20_pp_h_stage_c"]) for r in members)!=0:
        raise ValueError("P8F_NEW_RH_DISCONTINUITY_DECLARATION")
    if not all(bool(r["zenith_luminance_preserved_missing"]) for r in photoaudit["members"]):
        raise ValueError("P8F_ZENITH_LUMINANCE_NOT_MISSING")
    if not (pub["max_monthly_q_error_kg_kg"]<1e-11 and pub["max_daily_GHI_balance_kwh_m2"]<1e-7):
        raise ValueError("P8F_AGGREGATE_MASS_ENERGY_CLOSURE_FAILED")
    if pub["original_meteonorm_epw_in_public_github"] or pub["full_generated_hourly_epw_in_public_github"]:
        raise ValueError("P8F_LICENSED_ORIGINAL_PUBLISHED_CONTRARY_TO_POLICY")

    return {
        "manifest_consistency_pass":True,
        "registered_GCM_full_research_members":len(members),
        "registered_GCM_blocked_members":len(blocked),
        "registered_IPSL_block_reason":"native historical/future daily huss missing",
        "full_model_membership_verified_against_8x4":True,
        "published_original_license_baseline_sha256":BASELINE_SHA,
        "original_p7c4_output_hash_bijection_verified":True,
        "p7c5_physical_original_hash_bijection_verified":True,
        "p7c5b_corrected_lux_source_hash_bijection_verified":True,
        "original_28_licensed_EPW_bytes_available_to_current_audit":False,
        "original_28_licensed_EPW_bytes_currently_rehashed":False,
        "current_EnergyPlus_28_licensed_member_simulations_executed":False,
        "native_original_GCM_40_zip_reacquired_this_audit":False,
        "original_climate_daily_20year_windows_previously_audited":40,
        "P7C4_RH_near_100_hours_28_members_np_isclose":sat,
        "P7C5_RH_ge99p995_hours_28_members":14536,
        "P7C4_vs_P7C5_RH_saturation_count_difference":14536-sat,
        "P7C4_vs_P7C5_RH_count_definitions_differ":True,
        "RH_source_original_8760_saturation_hours_from_previous_audit":229,
        "optimizer_not_strictly_converged_members":no_convergence,
        "optimizer_max_iterations_each":OPT_MAX_ITER,
        "strict_optimizer_convergence_accepted_for_production":False,
        "p7c5_prephotometric_global_lux_stale_source_hours":sum(int(r["changed_GHI_hours_with_original_unchanged_global_lux"]) for r in physical),
        "p7c5_prephotometric_direct_lux_stale_source_hours":sum(int(r["changed_DNI_hours_with_original_unchanged_direct_lux"]) for r in physical),
        "p7c5_prephotometric_diffuse_lux_stale_source_hours":sum(int(r["changed_DHI_hours_with_original_unchanged_diffuse_lux"]) for r in physical),
        "p7c5b_after_correction_max_lux_closure_residual":max(float(p["photometric_closure_residual_max_lux"]) for p in photos),
        "p7c5b_fallback_channel_hours_each":sorted(set(int(p["fallback_channel_hours"]) for p in photos)),
        "p7c5b_photometry_independently_measured_qualified":False,
        "p7c5b_zenith_luminance_inherited_missing":True,
        "P7C4_report":str(get("p7c4",P7C4)),
        "P7C4_report_sha256":source_hash(get("p7c4",P7C4)),
        "P7C5B_report_sha256":source_hash(get("p7c5b",P7C5B)),
        "P7C4_28_sha_sources":[r["EPW_sha256"] for r in members],
        "P7C5B_28_sha_outputs":[r["output_sha256"] for r in photos],
    }


def real_public_epw_probe(files):
    """Read actual archival public EPWs, never use as licensed-Meteonorm proxy."""
    seen=[]
    for path in sorted(Path(x) for x in files):
        header,rows,met=wind_epw.read_epw(path)
        wind_meta=wind_epw.stats(rows)
        direction_holes=met["original_noncalm_missing_direction_hours"]
        RH=[float(r[8]) for r in rows]
        temp=[float(r[6]) for r in rows]
        pressure=[float(r[9]) for r in rows]
        DNI=[float(r[14]) for r in rows]
        GHI=[float(r[13]) for r in rows]
        DHI=[float(r[15]) for r in rows]
        errors=[]
        if any((not math.isfinite(v) or v<0 or v>100) for v in RH):errors.append("INVALID_RH")
        if any(not math.isfinite(v) or v<=30000 or v>=120000 for v in pressure):errors.append("INVALID_PRESSURE")
        if any(not math.isfinite(v) or v<=-65 or v>=65 for v in temp):errors.append("INVALID_TEMPERATURE")
        if any(v<0 or v>=9999 for v in GHI+DNI+DHI):errors.append("INVALID_RADIATION")
        if errors:raise ValueError("P8F_PUBLIC_ORIGINAL_EPW_INVALID_"+str(errors))
        seen.append({
            "file":path.name,
            "original_epw_sha256":met["sha256"],
            "hours":met["hourly_records"],
            "n_columns":35,
            "year":met["year"],
            "noncalm_missing_direction_hours":direction_holes,
            "all_8760_hourly_dates_and_35_columns_verified":True,
            "mean_wind_speed_mps":wind_meta["speed_mean_mps"],
            "gHI_annual_kWh_m2":sum(GHI)/1000.,
            "mean_temperature_C":statistics.fmean(temp),
            "real_measured_hourly_full_weather":False,
            "this_member_is_a_production_Meteonorm_EPW":False,
        })
    if not seen:
        raise ValueError("P8F_NO_ORIGINAL_PUBLIC_EPW_BYTES_IN_CI")
    return {
        "public_original_research_epw_count":len(seen),
        "all_public_EPWs_structurally_verified":True,
        "public_research_EPWs_with_noncalm_direction_absent":sum(
            x["noncalm_missing_direction_hours"]>0 for x in seen),
        "public_research_EPWs_with_noncalm_direction_present_all_hours":sum(
            x["noncalm_missing_direction_hours"]==0 for x in seen),
        "total_public_research_noncalm_missing_direction_site_hours":sum(
            x["noncalm_missing_direction_hours"] for x in seen),
        "all_public_EPWs_complete_noncalm_direction":all(
            x["noncalm_missing_direction_hours"]==0 for x in seen),
        "not_any_authentic_licensed_original_Meteonorm":True,
        "site_azimuth_missing_cannot_be_imputed":True,
        "members":seen,
    }


def release_gates(source, manifests,public_probe=None):
    # A truthful red scientific release gate is a VALID audit result and does
    # not mean the tool/CI failed. This distinction is essential.
    evid={
        "registered_climate_signal_matrix_pass":source["n_original_GCM_monthly_signals"]==384,
        "source_to_research_member_manifest_bijection_pass":manifests["manifest_consistency_pass"],
        "public_8760_35_EPW_readback_pass":bool(public_probe and public_probe["all_public_EPWs_structurally_verified"]),
        "all_archived_public_EPWs_noncalm_directions_complete":bool(
            public_probe and public_probe["all_public_EPWs_complete_noncalm_direction"]),
        "all_expected_32_full_EPW_humidity_members_available":manifests["registered_GCM_blocked_members"]==0,
        "humidity_optimizer_strictly_converged_all_28":manifests["optimizer_not_strictly_converged_members"]==0,
        "humidity_saturation_distribution_independently_qualified":False,
        "photometry_independent_measured_qualified":manifests["p7c5b_photometry_independently_measured_qualified"],
        "licensed_28_p7c5b_current_full_EPWs_rehashed":manifests["original_28_licensed_EPW_bytes_currently_rehashed"],
        "native_EnergyPlus_all_28_licensed_member_climate_tests_executed":manifests["current_EnergyPlus_28_licensed_member_simulations_executed"],
        "future_physical_wind_direction_qualified":False,
        "future_cloud_and_precipitation_event_timing_independently_qualified":False,
        "arbitrary_point_nonstation_weather_model_independently_validated":False,
        "EPW_suitable_for_unqualified_daylighting_design":False,
    }
    return {
        "research_aggregate_technical_audit_pass":all(evid[k] for k in (
            "registered_climate_signal_matrix_pass",
            "source_to_research_member_manifest_bijection_pass",
            "public_8760_35_EPW_readback_pass",
        )),
        "release_gate_results":evid,
        "operational_release_ready":all(evid.values()),
        "production_epw_ready":False,
        "ready_for_research_sensitivity_with_explicit_limitations":True,
        "ready_for_unqualified_building_design":False,
        "missing_licensed_sources_are_not_replaced_with_public_fixture":True,
    }


def run(out,public_files):
    source=source_matrix()
    manifests=validate_manifests()
    pub=real_public_epw_probe(public_files)
    gates=release_gates(source,manifests,pub)
    result={
        "phase":"IGE_P8_5_FINAL_EPW_GENERATOR_AUDIT",
        "status":"INDEPENDENT_RESEARCH_EVIDENCE_AUDIT_COMPLETE_PRODUCTION_BLOCKED",
        "original_project_source_branch":"research/ige-p8-4d-epw-wind-qualification-20261017",
        "source_model_matrix":source,
        "published_seven_model_28_epw_source_chain":manifests,
        "genuinely_reloaded_public_hourly_epws":pub,
        "scientific_and_operational_gate_decisions":gates,
        "authenticated_Meteonorm_28_EPW_binaries_audited_this_run":False,
        "raw_restricted_hourly_data_exported":False,
        "artifact_does_not_include_EPWs":True,
        "production_epw_ready":False,
    }
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/"ige_p8_5_final_generator_audit_aggregates.json").write_text(
        json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    print("IGE_P8_5_FINAL_AUDIT",json.dumps({
        "source_matrix":source["n_original_GCM_monthly_signals"],
        "research_members":manifests["registered_GCM_full_research_members"],
        "blocked_full_models":manifests["registered_GCM_blocked_members"],
        "public_epws_actual_read":pub["public_original_research_epw_count"],
        "research_audit_pass":gates["research_aggregate_technical_audit_pass"],
        "release_operational_pass":gates["operational_release_ready"],
        "production_epw_ready":False,
    }),flush=True)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",required=True)
    parser.add_argument("--public-epw",action="append",required=True)
    args=parser.parse_args()
    run(args.out,args.public_epw)
