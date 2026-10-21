"""C2 reproducible 2013/2014 regressions, immutable controls and daily ledgers.

These years and 2021 station windows have already been revealed. No fitting,
new holdout, future pressure recovery, full EPW or production qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time

import numpy as np
import scipy

from p9_3b3_c2_projection import (MODES, CorrectionBudget, ProjectionMetric,
    ProjectionPolicy, project_day)
from p9_3b3_compare_vertical_frame import fingerprint


ROOT=Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL=Path(__file__).with_name("p9_3b3_c2_protocol.json")


def load_protocol(path=DEFAULT_PROTOCOL):
    p=json.loads(Path(path).read_text())
    expected={"phase":"P9.3B3_C2_PHYSICAL_PROJECTION_20261021",
        "base_commit":"f49f5029632e33aaf159e07958a36a49932e9fcd",
        "modes":list(MODES),"countries":["AT","DE","CH"],
        "station_windows":[["2021-02-01","2021-02-14"],["2021-08-01","2021-08-14"]],
        "station_seeds":[7313,7314,7315,7316,7317],"regression_years":[2013,2014],
        "regression_seed":7313,"source_values_immutable":True,
        "pressure_is_optimization_variable":False,"B4_qualified":False,
        "production_epw_ready":False,"merge_main":False,
        "source_donor_policy":"B3_EXACT_SELECTED_DONOR_ELSE_LEXICOGRAPHIC_FIRST_ELIGIBLE",
        "station_role":"REVEALED_2021_RECONSTRUCTION_DIAGNOSTIC_NOT_NEW_HOLDOUT",
        "regression_pressure":"REGISTERED_DONOR_PRESSURE_SENSITIVITY_NOT_NATIVE_TARGET_DAY_OR_FUTURE_PS",
        "station_pressure":"EXTERNAL_TARGET_DAY_GRID_FIXED_IDENTICAL_FOR_ALL_MODES",
        "independent_accuracy":"NOT_REESTABLISHED",
        "baseline_repair_json_sha256":"d4ba53ebaf30f8bd730b35f63e814a648fda47b3fcd602a59e6845f325e394e7",
        "all_modes_share_donor_pressure_and_strict_witness":True,
        "expected_strict_regression":{"EXACT_DEFINED_OPERATORS":727,"CERTIFIED_INFEASIBLE":5},
        "metric":{"q_scale_gkg":1.,"RH_scale_pp":5.,"correlation":0.,
            "interpretation":"SENSITIVITY_METRIC_NOT_ERROR_COVARIANCE",
            "evidence":"PREREGISTERED_DIMENSIONAL_SCALES_NO_NEX_ERROR_CALIBRATION"},
        "prior":{"lambda_shape":.01,"temperature_scale_K":2.,"q_scale_floor_gkg":1.,"roughness_hours":1.},
        "solver":{"max_iterations":180,"strict_starts":2,"projection_starts":3,
            "preserve_validated_exact_first":True,"global_optimality_claim":False},
        "correction_budget":{"q_limit_gkg":None,"RH_limit_pp":None,"interpretation":"NOT_ESTABLISHED",
            "evidence":"NO_INDEPENDENT_NEX_PROCESSING_ERROR_BUDGET"}}
    if any(p.get(k)!=v for k,v in expected.items()):raise ValueError("P93C2_FROZEN_PROTOCOL_DRIFT")
    return p


def control_integrity(protocol):
    rows=[]
    for relative,expected in protocol["protected_control_sha256"].items():
        actual=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        if actual!=expected:raise ValueError("P93C2_PROTECTED_CONTROL_CHANGED_"+relative)
        rows.append({"path":relative,"sha256":actual,"status":"UNCHANGED"})
    if len(rows)!=40:raise ValueError("P93C2_EXPECTED_40_PROTECTED_CONTROLS")
    return rows


def settings(protocol):
    s=protocol["solver"]
    return (ProjectionMetric(**protocol["metric"]),CorrectionBudget(**protocol["correction_budget"]),
        ProjectionPolicy(**protocol["prior"],**{k:s[k] for k in
            ("max_iterations","strict_starts","projection_starts")}))


def choose_common_donor(target,donors,wet,strict,pressure=None):
    """Select before seeing ANY C2 objective or correction, identical in all modes."""
    eligible=sorted((d for d in donors if d.date[5:7]==target.date[5:7] and d.wet==wet),key=lambda d:d.date)
    if strict["status"]=="EXACT_DEFINED_OPERATORS":
        selected=[d for d in eligible if d.date==strict.get("donor_date")]
        if len(selected)!=1:raise ValueError("P93C2_STRICT_DONOR_NOT_ELIGIBLE_OR_UNIQUE")
        donor=selected[0]
    elif eligible:donor=eligible[0]
    else:return None
    return replace(donor,pressure=pressure) if pressure is not None else donor


def project_modes(target,donor,strict,protocol,pressure_alignment):
    metric,budget,policy=settings(protocol)
    if donor is None:
        return [{"date":target.date,"mode":m,"status":"SOURCE_BLOCKED_NO_ELIGIBLE_DONOR",
                 "source_modified":False,"journal":[{"variable":field,"source_value":value,
                     "achieved_value":None,"delta":None,"correction_applied":False,
                     "reason":"NO_ELIGIBLE_DONOR"} for field,value in
                     (("huss",target.q_mean_kgkg),("hurs",target.RH_mean_pct))],
                 "production_eligible":False} for m in MODES]
    results=[project_day(donor.T_K,donor.q_kgkg,target,donor.pressure,mode=m,
        donor_date=donor.date,pressure_alignment=pressure_alignment,metric=metric,budget=budget,policy=policy,
        strict_witness=strict if strict["status"]=="EXACT_DEFINED_OPERATORS" else None) for m in MODES]
    if len({r["pressure_reference"]["fingerprint"] for r in results})!=1:
        raise AssertionError("P93C2_ABLATION_PRESSURE_DIFFERS")
    if strict["status"]=="EXACT_DEFINED_OPERATORS":
        if any(r["status"]!="EXACT_SOURCE_PRESERVED" for r in results):
            raise AssertionError("P93C2_EXACT_SOURCE_UNEXPECTEDLY_MODIFIED")
        for r in results:
            for key in ("T_K","p_Pa","q_kgkg"):
                if any(abs(a-b)>1e-12 for a,b in zip(r[key],strict[key])):
                    raise AssertionError("P93C2_STRICT_STATE_WAS_NOT_PRESERVED")
    return results


def compact(row):
    omitted={"T_K","p_Pa","q_kgkg","diagnostics","q_weights","RH_weights","T_weights"}
    result={k:v for k,v in row.items() if k not in omitted and k!="validation"}
    if "validation" in row:
        result["validation"]={k:v for k,v in row["validation"].items() if k!="diagnostics"}
        result["state_sha256"]=fingerprint({k:row[k] for k in ("T_K","p_Pa","q_kgkg")})
    return result


def summarize(rows):
    out={"total":len(rows),"counts":dict(Counter(r["status"] for r in rows)),
        "physically_valid_candidates":sum("validation" in r for r in rows),
        "source_modified_candidates":sum(r.get("source_modified",False) for r in rows),
        "budget_status_counts":dict(Counter(r.get("correction_acceptance","NO_VALID_CANDIDATE") for r in rows)),
        "independent_accuracy":"NOT_TESTED","operational_ready":False}
    for field in ("huss","hurs"):
        changes=[j["delta"] for r in rows for j in r.get("journal",[]) if j["variable"]==field and j["delta"] is not None]
        out[field]={"count":len(changes),"max_abs_delta":max(map(abs,changes),default=None),
            "mean_abs_delta":sum(map(abs,changes))/len(changes) if changes else None,
            "unit":"kg/kg" if field=="huss" else "%"}
    return out


def source_regression(original_zip,baseline_path,protocol,report,out):
    from p9_3b3_generator import generate,from_legacy_day
    from p9_3b3_joint_solver import SolverPolicy
    from p9_3b3_regression_audit import native_targets,read_registered
    from p9_3b3_source_semantics import SourceSemantics
    from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year
    from p9_3a_original_canesm5_2014_year_pressure_temperature_q import EXPECTED_ERA5_CANONICAL_SHA
    raw=Path(baseline_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=protocol["baseline_repair_json_sha256"]:
        raise ValueError("P93C2_IMMUTABLE_REPAIR_ARTIFACT_SHA_MISMATCH")
    baseline=json.loads(raw)
    source_rows,source=read_registered(original_zip)
    donors=[];provenance=[]
    for year in (2019,2020):
        old,meta=original_era5_year(year)
        if meta["canonical_source_weather_sha256"]!=EXPECTED_ERA5_CANONICAL_SHA[year]:
            raise ValueError("P93C2_ORIGINAL_DONOR_CANONICAL_WEATHER_DRIFT")
        donors.extend(from_legacy_day(d) for d in old);provenance.append(meta)
    report.update(source=source,donor_provenance=provenance,years=[])
    counts=Counter();total_modes={m:[] for m in MODES};started=time.monotonic()
    for year in protocol["regression_years"]:
        targets,wet=native_targets(source_rows,year,SourceSemantics("DERIVED_TAS_MIDRANGE","WATER_ICE"))
        members=[m for m in baseline["members"] if m["year"]==year and m["variant"]=="L3_JOINT_SOURCE_PHASE"]
        if len(members)!=1:raise ValueError("P93C2_BASELINE_YEAR_NOT_UNIQUE")
        prior={d["date"]:d for d in members[0]["days"]}
        if set(prior)!={t.date for t in targets}:raise ValueError("P93C2_BASELINE_CALENDAR_DRIFT")
        strict,summary=generate(targets,donors,seed=protocol["regression_seed"],
            policy=SolverPolicy(lower_bound_seconds=.25),wet_by_date=wet)
        counts.update(summary["counts"])
        strict_bydate={r["date"]:r for r in strict}
        year_rows={m:[] for m in MODES}
        for target in targets:
            control=strict_bydate[target.date];old=prior[target.date]
            if control["status"]!=old["status"]:
                raise AssertionError("P93C2_STRICT_BASELINE_DAY_STATUS_DRIFT_"+target.date)
            if control["status"]=="EXACT_DEFINED_OPERATORS" and control["donor_date"]!=old["donor_date"]:
                raise AssertionError("P93C2_STRICT_BASELINE_SELECTED_DONOR_DRIFT_"+target.date)
            donor=choose_common_donor(target,donors,wet[target.date],control)
            for r in project_modes(target,donor,control,protocol,"REGISTERED_DONOR_PRESSURE_SENSITIVITY"):
                r["baseline_strict_status"]=control["status"]
                year_rows[r["mode"]].append(compact(r))
        members_c2=[{"mode":m,"summary":summarize(year_rows[m]),"days":year_rows[m]} for m in MODES]
        for m in MODES:total_modes[m].extend(year_rows[m])
        report["years"].append({"year":year,"records_including_boundary":len(targets),
            "strict_rerun_summary":summary,"members":members_c2})
        print("P93C2_REGRESSION_YEAR",json.dumps({"year":year,"strict":summary["counts"],
            "C2":{m:summarize(year_rows[m])["counts"] for m in MODES}}),flush=True)
        write_report(out,report)
    if dict(counts)!=protocol["expected_strict_regression"]:
        raise AssertionError("P93C2_STRICT_727_PLUS_5_ACCOUNTING_DRIFT")
    report.update(strict_rerun_counts=dict(counts),elapsed_source_regression_seconds=time.monotonic()-started,
        comparison_summary={m:summarize(total_modes[m]) for m in MODES},
        total_records_per_mode_including_boundaries=732,unique_dates=731,core_year_days=730,
        original_727_exact_states_actually_rerun_and_independently_validated=True,
        source_regression_status="COMPLETED_REVEALED_REGRESSION_NOT_INDEPENDENT_ACCURACY")


def write_report(out,report):
    (Path(out)/"c2_comparison.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")


def synthetic_cost_pilot(protocol):
    """50 fixed synthetic cases, no station data or revealed regression years."""
    from p9_3b3_pressure_reference import PressureReference
    from p9_3b3_source_semantics import DailyTarget,SourceSemantics
    rng=np.random.default_rng(20261021)
    metric,budget,policy=settings(protocol)
    cases=[];start=time.monotonic();cpu=time.process_time()
    for i in range(50):
        T=281+5*np.sin(np.arange(24)*2*np.pi/24)+rng.uniform(-.1,.1,24)
        P=PressureReference(tuple(97000+rng.uniform(-80,80,24)),"PREREGISTERED_SYNTHETIC_COST_PILOT",
            "SYNTHETIC_POINT",reference_date="2021-02-01")
        q=rng.uniform(.0008,.0012,24)
        target=DailyTarget("2021-02-01",float(T.min()),float(T.max()),float((T.min()+T.max())/2),
            float(q.mean()),80.,SourceSemantics("DERIVED_TAS_MIDRANGE","WATER",
                time_support="SYNTHETIC_DISCRETE_NODE_DAY",verified=True))
        before=time.monotonic()
        row=project_day(T,q,target,P,mode=MODES[i%3],donor_date="2019-02-01",
            metric=metric,budget=budget,policy=policy)
        cases.append({"case":i,"elapsed_seconds":time.monotonic()-before,**compact(row)})
    durations=np.array([r["elapsed_seconds"] for r in cases])
    return {"source":"50_SYNTHETIC_CASES_NO_REVEALED_YEARS_OR_STATION_VALUES",
        "recipe_seed":20261021,"mode_selection":"CYCLE_THROUGH_THREE_MODES_NO_MODEL_SELECTION",
        "wall_seconds":time.monotonic()-start,"process_CPU_seconds":time.process_time()-cpu,
        "median_seconds":float(np.median(durations)),"p95_seconds":float(np.quantile(durations,.95)),
        "peak_process_RSS_KiB":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "summary":summarize(cases),"cases":cases}


def run(out,protocol_path=DEFAULT_PROTOCOL,original_zip=None,baseline_path=None,stations=False,cache=None,pilot=False):
    wall_start=time.monotonic();cpu_start=time.process_time()
    protocol=load_protocol(protocol_path);controls=control_integrity(protocol)
    if (original_zip is None)!=(baseline_path is None):raise ValueError("P93C2_BOTH_SOURCE_AND_BASELINE_REQUIRED")
    if stations and cache is None:raise ValueError("P93C2_PRIVATE_CACHE_REQUIRED_FOR_STATION_RUN")
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    implementation={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*p9_3b3_c2_*.py"))}
    report={"phase":protocol["phase"],"protocol_sha256":fingerprint(protocol),"algorithm_commit":commit,
        "working_tree_dirty":bool(subprocess.check_output(["git","status","--porcelain"],cwd=ROOT,text=True).strip()),
        "runtime":{"python":platform.python_version(),"numpy":np.__version__,"scipy":scipy.__version__,
            "system_logical_CPUs":os.cpu_count(),
            "OPENBLAS_NUM_THREADS":os.environ.get("OPENBLAS_NUM_THREADS"),"OMP_NUM_THREADS":os.environ.get("OMP_NUM_THREADS")},
        "implementation_file_sha256":implementation,"implementation_manifest_sha256":fingerprint(implementation),
        "controls":controls,"claim_status":{"code_correctness":"SEE_TEST_LOG",
            "physical_admissibility":"VALIDATED_CANDIDATES_CONDITIONAL_ON_DECLARED_DISCRETE_POLICY",
            "independent_accuracy":"NOT_REESTABLISHED_NO_NEW_HOLDOUT","operational_ready":False},
        "source_values_modified":False,"pressure_is_optimization_variable":False,"B4_qualified":False,
        "production_epw_ready":False,"new_independent_holdout_opened":False,"legacy_results_overwritten":False,
        "station_diagnostic_status":"NOT_RUN","source_regression_status":"NOT_RUN"}
    write_report(out,report)
    try:
        if pilot:report["synthetic_cost_pilot"]=synthetic_cost_pilot(protocol)
        if original_zip is not None:source_regression(original_zip,baseline_path,protocol,report,out)
        if stations:
            from p9_3b3_c2_stations import station_diagnostic
            report["station_diagnostic"]=station_diagnostic(protocol,out,cache)
            report["station_diagnostic_status"]="COMPLETED_OR_SOURCE_BLOCKED_SEE_CELL_DENOMINATORS"
    except Exception as error:
        report["run_failure"]={"type":type(error).__name__,"message":str(error)}
        report.update(elapsed_run_wall_seconds=time.monotonic()-wall_start,
            elapsed_run_process_CPU_seconds=time.process_time()-cpu_start)
        write_report(out,report)
        raise
    control_integrity(protocol)
    report.update(elapsed_run_wall_seconds=time.monotonic()-wall_start,
        elapsed_run_process_CPU_seconds=time.process_time()-cpu_start,
        peak_process_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    write_report(out,report)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",required=True);p.add_argument("--protocol",default=str(DEFAULT_PROTOCOL))
    p.add_argument("--original-canesm5-registered-zip");p.add_argument("--immutable-repair-audit")
    p.add_argument("--stations",action="store_true");p.add_argument("--private-cache")
    p.add_argument("--pilot",action="store_true")
    a=p.parse_args()
    run(a.out,a.protocol,a.original_canesm5_registered_zip,a.immutable_repair_audit,a.stations,a.private_cache,a.pilot)
