"""Sealed C2 diagnostics on the REVEALED AT/DE/CH 2021 cohort.

ERA5-derived coherent daily constraints test reconstruction, not native NEX
processing errors. Station observations never enter donor/projection arguments.
All expected cells, including missing sources and generation failures, remain.
"""
from __future__ import annotations

from collections import Counter,defaultdict
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np

from p9_3b3_at_de_ch_validation import (PERIODS,SEEDS,SourceCache,_assert_pressure_alignment,
    _era5,_generate_days,_hour_predictions,coherent_target,preflight,read_sealed,sha_file,timestamps)
from p9_3b3_c2_projection import MODES
from p9_3b3_c2_run import ROOT,choose_common_donor,compact,control_integrity,project_modes,summarize
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_generator import from_legacy_day
from p9_3b3_joint_solver import SolverPolicy
from p9_3b3_pressure_diagnostics import target_day_references
from p9_3b3_thermodynamics import q_from_e,relative_humidity,saturation


VARIABLES=("T2m","RH2m","p_hPa","e_hPa","q_gkg")
METHODS=("B3_STRICT",)+MODES+("FULL_HOURLY_ERA5_RICH_REFERENCE",)


def expected_members():
    return [(c,period,method,seed) for c in ("AT","DE","CH") for period,_,_ in PERIODS
        for method in METHODS for seed in ((7313,) if method.startswith("FULL_") else SEEDS)]


def observation_values(source,period,variable):
    values=dict(source["cells"][period].get(variable,{}))
    if variable in ("e_hPa","q_gkg"):
        cells=source["cells"][period]
        common=set(cells["T2m"])&set(cells["RH2m"])
        if variable=="q_gkg":common&=set(cells["p_hPa"])
        for stamp in common:
            e=float(saturation(cells["T2m"][stamp]+273.15))*cells["RH2m"][stamp]/100
            values[stamp]=e/100 if variable=="e_hPa" else float(q_from_e(e,cells["p_hPa"][stamp]*100))*1000
    return values


def matched_errors(hourly,truth,variable,support,allowed):
    out={}
    for stamp in sorted(set(truth)&set(allowed)&set(hourly)):
        predicted=hourly[stamp][variable]
        if support=="PRECEDING_HOUR_MEAN_END_STAMP":
            previous=(dt.datetime.fromisoformat(stamp)-dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
            if previous not in hourly:continue
            predicted=(predicted+hourly[previous][variable])/2
        if not np.isfinite([predicted,truth[stamp]]).all():raise ValueError("P93C2_SCORING_NONFINITE")
        out[stamp]=float(predicted-truth[stamp])
    return out


def structure(hourly):
    ordered=sorted(hourly)
    if not ordered:return {"n_generated_nodes":0}
    a=np.array([[hourly[s][k] for k in VARIABLES] for s in ordered])
    spells=[];run=0;seams=[];previous=None
    for stamp,row in zip(ordered,a):
        current=dt.datetime.fromisoformat(stamp)
        contiguous=previous is not None and current-previous==dt.timedelta(hours=1)
        if not contiguous and run:spells.append(run);run=0
        if row[1]>=90:run+=1
        elif run:spells.append(run);run=0
        if contiguous and current.hour==0:seams.append(abs(hourly[stamp]["T2m"]-hourly[previous.isoformat(timespec="minutes")]["T2m"]))
        previous=current
    if run:spells.append(run)
    corr=lambda j:float(np.corrcoef(a[:,0],a[:,j])[0,1]) if np.std(a[:,0])>0 and np.std(a[:,j])>0 else None
    return {"n_generated_nodes":len(a),"water_saturated_fraction":float(np.mean(a[:,1]>=99.995)),
        "RH_ge90_spell_lengths_hours":spells,"T_RH_correlation":corr(1),"T_e_correlation":corr(3),
        "temperature_seam_max_K":max(seams) if seams else None,
        "T_p05_p50_p95_C":np.quantile(a[:,0],[.05,.5,.95]).tolist(),
        "q_p05_p50_p95_gkg":np.quantile(a[:,4],[.05,.5,.95]).tolist(),
        "structure_scores_are_not_independent_accuracy_qualification":True}


def score_sealed(manifest):
    if (not manifest.get("frozen_before_scoring") or manifest.get("countries")!=["AT","DE","CH"] or
            manifest.get("cohort_role")!="REVEALED_2021_RECONSTRUCTION_DIAGNOSTIC_NOT_NEW_HOLDOUT" or
            not re.fullmatch(r"[0-9a-f]{40}",manifest.get("algorithm_commit",""))):
        raise ValueError("P93C2_UNFROZEN_OR_OUT_OF_SCOPE_SCORING")
    predictions=read_sealed(manifest["predictions_path"],manifest["predictions_sha256"])
    observations=read_sealed(manifest["observations_path"],manifest["observations_sha256"])
    members={(m["country"],m["period"],m["method"],m["seed"]):m for m in predictions["members"]}
    if len(members)!=len(predictions["members"]) or not set(members)<=set(expected_members()):
        raise ValueError("P93C2_DUPLICATE_OR_UNREGISTERED_MEMBER")
    cells=[];error_maps={};structures=[]
    windows={name:timestamps(s,e) for name,s,e in PERIODS}
    for country,period,method,seed in expected_members():
        identity={"country":country,"period":period,"method":method,"seed":seed}
        hourly=members.get((country,period,method,seed),{}).get("hourly",{})
        if not set(hourly)<=set(windows[period]):raise ValueError("P93C2_PREDICTIONS_OUTSIDE_FROZEN_WINDOW")
        source=observations[country]
        structures.append({**identity,**structure(hourly)})
        for variable in VARIABLES:
            truth=observation_values(source,period,variable)
            errors=matched_errors(hourly,truth,variable,source["time_support"],windows[period])
            error_maps[(country,period,method,seed,variable)]=errors
            cell={**identity,"variable":variable,"expected_hours":336,"source_hours":len(truth),
                "matched_hours":len(errors),"qc_tier":source.get("qc_tier","UNKNOWN"),
                "source_time_support":source["time_support"],
                "prediction_support":"NODE_VALUE_OR_DECLARED_PRECEDING_HOUR_TRAPEZOID_PROXY",
                "derived_from_station_T_RH_p_not_independent_sensor":variable in ("e_hPa","q_gkg"),
                "status":"SCORED_REVEALED_LIMITED_DIAGNOSTIC" if len(errors)>=.9*336 else "SOURCE_OR_GENERATION_COVERAGE_BLOCKED"}
            if errors:
                a=np.array(list(errors.values()))
                cell.update(MAE=float(np.mean(abs(a))),RMSE=float(np.sqrt(np.mean(a*a))),bias=float(np.mean(a)))
            if variable=="p_hPa":
                cell["pressure_MAE_gate_hPa"]=2.
                cell["pressure_accuracy_gate"]=("INCONCLUSIVE_COVERAGE" if len(errors)<.9*336 else
                    "PASS_THIS_CELL_ONLY" if cell["MAE"]<=2 else "FAIL_THIS_CELL")
            cells.append(cell)
    paired=[]
    for country in ("AT","DE","CH"):
        for period,_,_ in PERIODS:
            for seed in SEEDS:
                for variable in VARIABLES:
                    control=error_maps[(country,period,"B3_STRICT",seed,variable)]
                    for method in MODES:
                        candidate=error_maps[(country,period,method,seed,variable)]
                        common=sorted(set(control)&set(candidate))
                        row={"country":country,"period":period,"seed":seed,"variable":variable,"mode":method,
                            "common_hours":len(common),"control_only_hours":len(set(control)-set(candidate)),
                            "candidate_only_hours":len(set(candidate)-set(control)),
                            "expected_hours":336,"status":"PAIRED_POINT_DIAGNOSTIC_NO_CONFIDENCE_OR_QUALIFICATION_CLAIM"}
                        if common:
                            before=np.array([control[s] for s in common]);after=np.array([candidate[s] for s in common])
                            row.update(delta_MAE=float(np.mean(abs(after))-np.mean(abs(before))),
                                delta_RMSE=float(np.sqrt(np.mean(after*after))-np.sqrt(np.mean(before*before))))
                        else:row["status"]="INCONCLUSIVE_NO_COMMON_OBSERVATION_SUPPORT"
                        paired.append(row)
    if len(cells)!=630:raise AssertionError("P93C2_EXPECTED_630_CELL_DENOMINATOR")
    return {"cells":cells,"expected_cells":630,"cell_status_counts":dict(Counter(c["status"] for c in cells)),
        "paired_comparisons":paired,"generated_structure":structures,
        "station_RH_phase":"DECLARED_WATER_NOT_PROVIDER_CERTIFIED_ALL_SITES",
        "derived_e_q_are_nonlinear_proxies_from_hourly_means":True,
        "CH_previous_hour_comparison":"DECLARED_TRAPEZOID_PROXY_FIRST_HOUR_MISSING_NO_LAG_FITTING",
        "ERA5_daily_constraints_are_coherent_not_native_NEX_error_evidence":True,
        "seeds_are_not_independent_observation_replicates":True,
        "no_confidence_intervals_or_noninferiority_qualification_claimed":True,
        "independent_accuracy":"NOT_REESTABLISHED_REVEALED_RECONSTRUCTION_ONLY",
        "pressure_model_qualified":False,"operational_ready":False,"production_epw_ready":False}


def _rich_nodes(reference,pressure_refs):
    rows=[]
    for day in reference:
        T=np.array([v["temperature_2m"]+273.15 for v in day.vectors])
        P=np.array(pressure_refs[day.date.isoformat()].values_Pa)
        q=q_from_e(saturation([v["dew_point_2m"]+273.15 for v in day.vectors]),P)
        e=q*P/((287.05/461.5)+(1-287.05/461.5)*q)
        rows.append({"date":day.date.isoformat(),"T_K":T.tolist(),"p_Pa":P.tolist(),"q_kgkg":q.tolist(),
            "diagnostics":{"RH_source_pct":relative_humidity(T,P,q).tolist(),"e_Pa":e.tolist()}})
    return rows


def station_diagnostic(protocol,out,cache_dir):
    out=Path(out);cache=SourceCache(cache_dir)
    observations_path,source_preflight=preflight(cache,out/"c2_station_source_preflight.json")
    # Seal source bytes now. Only site metadata is passed to weather retrieval.
    observations_sha=sha_file(observations_path)
    predictions={"members":[],"blockers":[]};ledgers=[];started=time.monotonic()
    for country in protocol["countries"]:
        site=source_preflight["cells"][country]["site"]
        for period,start,end in PERIODS:
            try:
                donors=[];provenance=[]
                for year in (2019,2020):
                    old,meta=_era5(cache,site["lat"],site["lon"],str(year)+start[4:],str(year)+end[4:])
                    donors.extend(from_legacy_day(d,frame="ERA5_GRID_"+country) for d in old)
                    provenance.append(meta)
                reference,meta=_era5(cache,site["lat"],site["lon"],start,end)
                targets=[coherent_target(d) for d in reference]
                if [t.date for t in targets]!=sorted({s[:10] for s in timestamps(start,end)}):
                    raise ValueError("P93C2_STATION_TARGET_CALENDAR_INCOMPLETE")
                pressure_refs=target_day_references(reference,meta,country)
                wet={d.date.isoformat():any(v["precipitation"]>0 for v in d.vectors) for d in reference}
            except (OSError,ValueError,KeyError) as exc:
                predictions["blockers"].append({"country":country,"period":period,"reason":str(exc),
                    "all_21_expected_members_retained_by_scorer":True})
                continue
            rich=_hour_predictions(_rich_nodes(reference,pressure_refs));_assert_pressure_alignment(rich,pressure_refs)
            predictions["members"].append({"country":country,"period":period,
                "method":"FULL_HOURLY_ERA5_RICH_REFERENCE","seed":7313,"hourly":rich})
            for seed in protocol["station_seeds"]:
                before=time.monotonic()
                strict,strict_summary=_generate_days(targets,donors,seed,wet,SolverPolicy(lower_bound_seconds=.25),
                    pressure_by_date=pressure_refs)
                strict_bydate={r["date"]:r for r in strict}
                modes={m:[] for m in MODES}
                for target in targets:
                    control=strict_bydate[target.date]
                    donor=choose_common_donor(target,donors,wet[target.date],control,pressure_refs[target.date])
                    for row in project_modes(target,donor,control,protocol,"TARGET_DAY_EXTERNAL_FIXED"):
                        row["baseline_strict_status"]=control["status"];modes[row["mode"]].append(row)
                for method,rows in (("B3_STRICT",strict),*modes.items()):
                    hourly=_hour_predictions(rows);_assert_pressure_alignment(hourly,pressure_refs)
                    predictions["members"].append({"country":country,"period":period,
                        "method":method,"seed":seed,"hourly":hourly})
                ledgers.append({"country":country,"period":period,"seed":seed,
                    "strict_summary":strict_summary,"source_provenance":provenance+[meta],
                    "elapsed_generation_seconds":time.monotonic()-before,
                    "modes":[{"mode":m,"summary":summarize(modes[m]),"days":[compact(r) for r in modes[m]]} for m in MODES]})
                print("P93C2_STATION_MEMBER",json.dumps({"country":country,"period":period,"seed":seed,
                    "strict":strict_summary["counts"],"modes":{m:summarize(modes[m])["counts"] for m in MODES}}),flush=True)
                (out/"c2_station_correction_ledger.json").write_text(json.dumps(ledgers,indent=2,allow_nan=False)+"\n")
    prediction_path=cache.root/"c2_predictions_PRIVATE_DO_NOT_PUBLISH.json"
    prediction_path.write_text(json.dumps(predictions,sort_keys=True,allow_nan=False))
    manifest={"frozen_before_scoring":True,"countries":protocol["countries"],
        "algorithm_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "protocol_sha256":fingerprint(protocol),"cohort_role":protocol["station_role"],
        "predictions_path":str(prediction_path),"predictions_sha256":sha_file(prediction_path),
        "observations_path":str(observations_path),"observations_sha256":observations_sha}
    control_integrity(protocol)
    manifest_public={k:v for k,v in manifest.items() if not k.endswith("_path")}
    (out/"c2_station_sealed_manifest.json").write_text(json.dumps(manifest_public,indent=2)+"\n")
    scored=score_sealed(manifest)
    scored.update(seal=manifest_public,elapsed_total_seconds=time.monotonic()-started,
        downloaded_bytes=cache.downloaded,source_blockers=predictions["blockers"],
        actual_generated_members=len(predictions["members"]),expected_members=len(expected_members()))
    (out/"c2_station_scores.json").write_text(json.dumps(scored,indent=2,allow_nan=False)+"\n")
    return {"score_file":"c2_station_scores.json","ledger_file":"c2_station_correction_ledger.json",
        **{k:v for k,v in scored.items() if k not in ("cells","paired_comparisons","generated_structure")}}
