"""Sealed D/V comparison, resumable candidates, explicit separate C evaluation."""
import copy
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from ige_auto.cases import Cases
from ige_auto.data import Cube
from ige_auto.fit import Unidentifiable,fit_cases,predict,kernel_parameters
from ige_local.common import InputError,digest,file_hash,log,new_run,now,peak_rss_bytes,write_csv,write_json,source_audit_failed
from . import VERSION
from .auxiliary import train_bundle,forecasts,refit_bundle
from .cases import HumidityCases
from .config import sealed,check_cohort
from .metrics import score,errors
from .optimize import optimize_chain
from .physics import restore,EPSILON


def implementation():
    root=Path(__file__).resolve().parents[1]
    paths=[root/"ige_humidity.py"]
    for name in ("ige_hum","ige_auto","ige_local"):paths+=sorted((root/name).glob("*.py"))
    return {str(p.relative_to(root)).replace(os.sep,"/"):file_hash(p) for p in paths}


def seal(path,data,key):
    data=dict(data);data[key]=digest(data);write_json(path,data);return data


def create_spec(cube,h,c,anchor,root):
    import importlib.metadata,platform
    check_cohort(cube,anchor)
    if cube.meta.get("source_errors") or cube.meta.get("notes") or source_audit_failed(cube.meta.get("source_audit") or {}):
        raise InputError("Source preparation has unresolved errors; see E0 and cube/metadata.json")
    spec={"schema":"IGE_HUMIDITY_RUN_v1","version":VERSION,"created_utc":now(),"configuration":h,"base_configuration":c,
          "cube_path":str(cube.path),"cube_id":cube.meta["cube_id"],"anchor":anchor,
          "implementation":implementation(),"phase_convention":"BUCK_LIQUID_WATER_EXPLICIT",
          "epsilon":EPSILON,"execution_workers":1,"default_run_opens_C":False,
          "environment":{"python":sys.version,"platform":platform.platform(),
             "numpy":importlib.metadata.version("numpy"),"scipy":importlib.metadata.version("scipy")},
          "protocol":{"primary":"V common RH country/station macro-MAE; failures cannot disappear from common cases",
             "outer_optimizer":"D nested-group CV MSE of final reconstructed RH",
             "coefficients":"Native-coordinate SVD regression inside continuous weight optimization",
             "auxiliaries":"Shared T/p height-IDW models, tuned on nested subsets excluding humidity check families",
             "native_donor_contract":"Same joint T/RH/p donors for paired scoring; own coverage separately reported",
             "refit":"D+V after V choice, weights frozen, no C response used",
             "C_exposure":"Computational withholding; native containers were parsed automatically; no blind-raw claim"}}
    return seal(Path(root)/"run_spec.sealed.json",spec,"spec_id")


def check_run(root):
    root=Path(root).resolve();spec=sealed(root/"run_spec.sealed.json","spec_id")
    if implementation()!=spec["implementation"]:raise InputError("Humidity implementation changed; preserve exact code or start a new run")
    cube=Cube(spec["cube_path"])
    if cube.meta["cube_id"]!=spec["cube_id"]:raise InputError("Humidity input cube changed")
    check_cohort(cube,spec["anchor"])
    return root,spec,cube


def checkpoint(root,spec,name,compute):
    path=Path(root)/"checkpoints"/(name+".json")
    if path.exists():
        cached=sealed(path,"checkpoint_id")
        if cached["spec_id"]!=spec["spec_id"]:raise InputError("Checkpoint belongs to another study")
        log("Resume: "+name);return cached["value"]
    value=compute();seal(path,{"spec_id":spec["spec_id"],"value":value},"checkpoint_id");return value


def prediction_rows(native,coordinate,view,pred,aux,weights,mask):
    b=native.base;cube=b.cube;books=cube.meta
    target_sources=np.asarray(cube.sources[b.s,b.t,:3])
    for i,rid in enumerate(b.row_id):
        finite=lambda x:float(x) if np.isfinite(x) else ""
        used=np.flatnonzero(weights[i]>1e-8)
        donors=[{"station":cube.stations[b.d[j]]["key"],"weight":float(weights[i,j]),
                 "source_ids":[int(x) for x in cube.sources[b.d[j],b.t[i],:3]],
                 "qc_ids_TRHp":[int(x) for x in native.donor_qc[i,j]]} for j in used]
        yield {"case_id":rid,"country":str(b.country[i]),"station":str(b.station[i]),"timestamp_utc":cube.times[b.t[i]],
            "coordinate":coordinate,"common_case":bool(mask[i]),"RH_observed":finite(native.values[i,1]),
            "RH_predicted":finite(pred["RH"][i]),"e_observed_hPa":finite(native.e[i]),"e_predicted_hPa":finite(pred["e_hPa"][i]),
            "q_observed_kgkg":finite(native.q[i]),"q_predicted_kgkg":finite(pred["q_kgkg"][i]),
            "T_predicted":finite(aux["T"][i]),"p_predicted_hPa":finite(aux["p"][i]),
            "independent_donors":int(view.n_donors[i]),
            "effective_donors":finite(1/np.sum(weights[i]**2)) if np.sum(weights[i]**2)>0 else 0,
            "supersaturated":bool(pred["supersaturated"][i]),"negative_RH":bool(pred["negative_RH"][i]),
            "vapour_ge_pressure":bool(pred["vapour_ge_pressure"][i]),"q_outside_0_1":bool(pred["q_outside_0_1"][i]),
            "target_QC_TRHp":json.dumps([books["qc_codebook"][int(x)] for x in native.target_qc[i]],ensure_ascii=False),
            "target_source_ids_TRHp":json.dumps(target_sources[i].tolist()),"donors":json.dumps(donors,ensure_ascii=False)}


FIELDS=["case_id","country","station","timestamp_utc","coordinate","common_case","RH_observed","RH_predicted",
        "e_observed_hPa","e_predicted_hPa","q_observed_kgkg","q_predicted_kgkg","T_predicted","p_predicted_hPa",
        "independent_donors","effective_donors","supersaturated","negative_RH","vapour_ge_pressure","q_outside_0_1",
        "target_QC_TRHp","target_source_ids_TRHp","donors"]


def predict_chain(native,coordinate,model,eta,fit,aux,paired=True):
    view=native.view(coordinate,paired)
    values,neff,weights=predict(view,model,eta,fit)
    return restore(coordinate,values,aux["T"],aux["p"]),view,weights


def candidate(root,spec,c,coordinate,model,folds,train,valid,aux):
    path=Path(root)/"models"/coordinate/model["id"];result_path=path/"result.sealed.json"
    if result_path.exists():
        cached=sealed(result_path,"result_id")
        if cached["spec_id"]!=spec["spec_id"]:raise InputError("Candidate specification mismatch")
        if cached.get("prediction_sha256") and file_hash(path/"V_predictions.csv")!=cached["prediction_sha256"]:
            raise InputError("Candidate predictions changed; checkpoint cannot be resumed")
        if cached.get("trace_sha256") and file_hash(path/"optimization_trace.json")!=cached["trace_sha256"]:
            raise InputError("Candidate optimization trace changed")
        if cached.get("own_prediction_sha256") and file_hash(path/"V_own_predictions.csv")!=cached["own_prediction_sha256"]:
            raise InputError("Candidate own-coverage predictions changed")
        log("Resume candidate: "+coordinate+" / "+model["id"]);return cached
    log("Humidity "+coordinate+" / "+model["id"])
    begin=time.monotonic();result={"spec_id":spec["spec_id"],"coordinate":coordinate,"model":model,"status":"STARTED"}
    try:
        search=optimize_chain(folds,coordinate,model,c);trace=search.pop("trace",[])
        write_json(path/"optimization_trace.json",trace);result["optimization"]=search
        result["trace_sha256"]=file_hash(path/"optimization_trace.json")
        if search["status"]!="CONVERGED":result["status"]=search["status"]
        else:
            fit=fit_cases(train.view(coordinate),model,search["eta"],c["optimizer"])
            pred,view,weights=predict_chain(valid,coordinate,model,search["eta"],fit,aux)
            mask=valid.common_mask(aux);n=int(mask.sum());result["fit_D"]=fit
            result["common_case_id"]=digest({"cohort":valid.cohort_id,"mask_sha256":digest(np.packbits(mask).tobytes())})
            result["common"]=score(valid,pred,mask);result["common_calendar_cases"]=n
            own,ov,ow=predict_chain(valid,coordinate,model,search["eta"],fit,aux,False)
            result["own_coverage"]=score(valid,own,ov.obs)
            result["own_coverage"]["N_predicted_calendar"]=int(np.isfinite(own["RH"]).sum())
            result["own_coverage"]["N_reference_coordinate"]=int(ov.obs.sum())
            required=all(result["common"]["RH"]["by_country"].get(co,{}).get("N",0)>0 for co in c["countries"])
            result["status"]="ELIGIBLE" if n>=c["optimizer"]["min_fit_cases"] and result["common"]["RH"]["N_scored"]==n and required else "INCOMPLETE_COMMON_V"
            write_csv(path/"V_predictions.csv",prediction_rows(valid,coordinate,view,pred,aux,weights,mask),FIELDS)
            result["prediction_sha256"]=file_hash(path/"V_predictions.csv")
            write_csv(path/"V_own_predictions.csv",prediction_rows(valid,coordinate,ov,own,aux,ow,mask),FIELDS)
            result["own_prediction_sha256"]=file_hash(path/"V_own_predictions.csv")
            result["kernel_parameters"]=kernel_parameters(model,search["eta"])
    except (Unidentifiable,ValueError,np.linalg.LinAlgError) as exc:
        result["status"]="UNIDENTIFIABLE_OR_UNSUPPORTED";result["reason"]=str(exc)
    result["wall_seconds"]=time.monotonic()-begin
    log("  "+result["status"])
    return seal(result_path,result,"result_id")


def train(root):
    root,spec,cube=check_run(root);c=spec["base_configuration"];h=spec["configuration"];begin=time.monotonic()
    if (root/"C_OPENED.json").exists():raise InputError("Cannot resume training after C exposure")
    if (Path(h["cohort_anchor"]).parent.parent/"C_OPENED.json").exists():raise InputError("Anchor C exposed; training cannot be resumed as confirmatory development")
    d=np.flatnonzero(cube.roles=="D");dt=np.flatnonzero(cube.time_roles=="D")
    v=np.flatnonzero(cube.roles=="V");vt=np.flatnonzero(cube.time_roles=="V")
    auxiliary=checkpoint(root,spec,"aux_full_D",lambda:train_bundle(cube,c,d,dt,h["auxiliary_optimizer"]))
    valid=HumidityCases(cube,c,[(v,vt)],d,"V_common_selection")
    aux_v=forecasts(cube,c,[(v,vt)],d,auxiliary,"V_shared_auxiliary")
    training=HumidityCases(cube,c,[(d,dt)],d,"D_humidity_fit")
    folds=[]
    for fold in range(c["inner_folds"]):
        fit=np.flatnonzero((cube.roles=="D")&(cube.folds!=fold));check=np.flatnonzero((cube.roles=="D")&(cube.folds==fold))
        bundle=checkpoint(root,spec,"aux_inner_"+str(fold),lambda fit=fit:train_bundle(cube,c,fit,dt,h["auxiliary_optimizer"]))
        held={cube.stations[s]["family"] for s in check}
        if any(held&set(x["training_families"]) for x in bundle.values()):raise InputError("Auxiliary family leakage")
        folds.append((HumidityCases(cube,c,[(fit,dt)],fit,"humidity_inner_fit_"+str(fold)),
                      HumidityCases(cube,c,[(check,dt)],fit,"humidity_inner_check_"+str(fold)),
                      forecasts(cube,c,[(check,dt)],fit,bundle,"inner_shared_auxiliary")))
    # Conservative aggregate estimate, including simultaneously resident folds.
    # Base/Cube maps are excluded; array views may be counted twice deliberately.
    natives=[training,valid]+[n for a,b,_ in folds for n in (a,b)]
    matrix_bytes=sum(x.nbytes for native in natives for owner in (native,native.base)
                     for x in vars(owner).values() if isinstance(x,np.ndarray))
    del natives
    if matrix_bytes*3>c["memory_budget_bytes"]:
        raise InputError("Humidity case matrices and optimizer workspace exceed memory budget; reduce cases_per_partition")
    results=[candidate(root,spec,c,coordinate,model,folds,training,valid,aux_v)
             for coordinate in h["coordinates"] for model in c["models"]]
    del folds,training
    chosen={};failures={}
    for coordinate in h["coordinates"]:
        pool=[r for r in results if r["coordinate"]==coordinate and r["status"]=="ELIGIBLE"]
        if pool:chosen[coordinate]=min(pool,key=lambda r:(r["common"]["RH"]["macro_MAE"],len(r["fit_D"]["coefficients"]),r["model"]["id"]))
        else:failures[coordinate]="NO_ELIGIBLE_COMMON_RH_MODEL"
    if len({r["common_case_id"] for r in results if r["status"]=="ELIGIBLE"})>1:raise InputError("Common V case sets differ")
    winner=min(chosen,key=lambda k:chosen[k]["common"]["RH"]["macro_MAE"]) if chosen else None
    panels=[(d,dt),(v,vt)];dv=np.flatnonzero(np.isin(cube.roles,["D","V"]))
    final_aux=checkpoint(root,spec,"aux_final_D_plus_V",lambda:refit_bundle(cube,c,panels,dv,auxiliary,h["auxiliary_optimizer"]))
    final_cases=HumidityCases(cube,c,panels,dv,"final_humidity_D_plus_V")
    final={}
    for coordinate,r in chosen.items():
        try:
            final[coordinate]={"model":r["model"],"eta":r["optimization"]["eta"],
                "fit":fit_cases(final_cases.view(coordinate),r["model"],r["optimization"]["eta"],c["optimizer"]),
                "selection_result_id":r["result_id"],"V_score_RH":r["common"]["RH"]["macro_MAE"]}
        except (Unidentifiable,ValueError) as exc:failures[coordinate]="FINAL_REFIT: "+str(exc)
    selected=seal(root/"selected_chains.sealed.json",{"spec_id":spec["spec_id"],"cube_id":cube.meta["cube_id"],
        "models":final,"shared_auxiliary_models":final_aux,"primary_chain_selected_on_V":winner,
        "selection_failures":failures,"final_refit":"D_PLUS_V","weights_frozen":True},"selected_id")
    rows=[]
    for r in results:
        row={"coordinate":r["coordinate"],"model":r["model"]["id"],"status":r["status"],
             "selected_structure":chosen.get(r["coordinate"],{}).get("model",{}).get("id")==r["model"]["id"]}
        if "common" in r:
            row.update(common_RH_macro_MAE=r["common"]["RH"]["macro_MAE"],common_RH_MAE=r["common"]["RH"]["MAE"],
                common_RH_RMSE=r["common"]["RH"]["RMSE"],common_e_MAE_hPa=r["common"]["e_hPa"]["MAE"],
                common_q_MAE_kgkg=r["common"]["q_kgkg"]["MAE"],common_N=r["common_calendar_cases"],
                own_RH_N=r["own_coverage"]["RH"]["N_scored"],own_RH_MAE=r["own_coverage"]["RH"]["MAE"],
                supersaturated=r["common"]["physical_flags"]["supersaturated"])
        rows.append(row)
    write_csv(root/"chain_comparison.csv",rows,["coordinate","model","status","selected_structure","common_RH_macro_MAE","common_RH_MAE", "common_RH_RMSE","common_e_MAE_hPa","common_q_MAE_kgkg","common_N","own_RH_N","own_RH_MAE","supersaturated"])
    common=valid.common_mask(aux_v);reference=valid.view("RH")
    coverage={"sampled_calendar_cases":len(common),"joint_target_reference":int(valid.joint_reference.sum()),
              "joint_donor_ready":int(reference.ready.sum()),"joint_reference_and_donors":int(reference.fit_mask.sum()),
              "common_after_shared_auxiliary":int(common.sum())}
    auxiliary_validation={name:errors(np.where(valid.eligible[:,j],valid.values[:,j],np.nan),aux_v[name],valid.base,common)
                          for name,j in (("T",0),("p",2))}
    summary={"version":VERSION,"finished_utc":now(),"spec_id":spec["spec_id"],"selected_id":selected["selected_id"],
        "models_requested":len(results),"models_eligible":sum(r["status"]=="ELIGIBLE" for r in results),
        "best_structures":{k:r["model"]["id"] for k,r in chosen.items()},"primary_chain_selected_on_V":winner,
        "selection_scores_V_RH":{k:r["common"]["RH"]["macro_MAE"] for k,r in chosen.items()},
        "common_calendar_cases":int(common.sum()),"common_coverage":coverage,"shared_auxiliary_validation":auxiliary_validation,
        "estimated_resident_case_matrices_bytes":matrix_bytes,"selection_failures":failures,
        "holdout_opened":False,"scientific_accuracy_qualified":False,"clipping_applied":False,
        "wall_seconds_this_invocation":time.monotonic()-begin,"peak_process_rss_bytes":peak_rss_bytes(),
        "exit_code":2 if failures else 0}
    if implementation()!=spec["implementation"]:raise InputError("Implementation changed during comparison")
    if (Path(h["cohort_anchor"]).parent.parent/"C_OPENED.json").exists():raise InputError("Anchor C exposed during training")
    Cube(cube.path)
    write_json(root/"summary.json",summary)
    lines=["# IGE — сравнение полных цепочек влажности", "", "Версия "+VERSION+". Код завершения: "+str(summary["exit_code"])+".", "",
           "Первичный критерий: ошибка восстановленной RH на общих часах V с равными весами стран и станций.",
           "T/p предсказаны моделями без проверяемых семейств; внутренние T/p веса также настроены без этих семейств.",
           "Нативные коэффициенты найдены регрессией; веса — непрерывной оптимизацией D. C не открыта.", "",
           "| Цепочка | Структура | MAE RH, п.п. |", "|---|---|---:|"]
    lines += ["| "+k+" | "+r["model"]["id"]+" | "+str(round(r["common"]["RH"]["macro_MAE"],6))+" |" for k,r in chosen.items()]
    lines += ["", "Лучший численный вариант V: "+str(winner)+". Это не независимое подтверждение и не допуск в эксплуатацию.",
              "Общих часов: "+str(coverage["common_after_shared_auxiliary"])+" из "+str(coverage["sampled_calendar_cases"])+" календарных случаев; причины потери покрытия и ошибки общих T/p приведены в summary.json.",
              "`chain_comparison.csv` содержит общее качество и собственное покрытие; `models/` — прогнозы, флаги, коэффициенты и трассы.",
              "Общие метрики V относятся к D-fit. Запечатанные итоговые модели дополнительно обучены на D+V; их ошибка C ещё не оценена.",
              "Все преобразования используют Buck над водой, в том числе при отрицательной T. Насыщение над льдом не сравнивалось.",
              "RH выше 100% и отрицательные значения отмечены и не обрезаются; q не отождествляется с влагосодержанием сухого воздуха.",
              "Величины e/q/Td производны от T/RH/p, а не независимые измерения. Прямая абсолютная влажность в г/м³ не является кандидатом."]
    (root/"REPORT_RU.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def evaluate(root,repeat=False):
    """Explicit only: compare frozen chains on three registered C panels."""
    root,spec,cube=check_run(root);c=spec["base_configuration"]
    selected=sealed(root/"selected_chains.sealed.json","selected_id")
    if selected["spec_id"]!=spec["spec_id"] or selected["cube_id"]!=cube.meta["cube_id"]:
        raise InputError("Selected chains belong to other inputs")
    if selected["selection_failures"] or set(selected["models"])!={"RH","log_e","q"}:
        raise InputError("Cannot open C for an incomplete comparison")
    anchor=Path(spec["configuration"]["cohort_anchor"]).parent.parent
    markers=[root/"C_OPENED.json",anchor/"C_OPENED.json"]
    exposed=any(p.exists() for p in markers)
    if exposed and not repeat:raise InputError("This cohort C was already exposed; --repeat records a repeated evaluation")
    # Anchor marker is shared with the original automatic-regression evaluator.
    for path in reversed(markers):
        if not path.exists():
            try:
                with path.open("x",encoding="utf-8") as f:
                    json.dump({"opened_utc":now(),"study":str(root),"selected_id":selected["selected_id"]},f)
            except FileExistsError as exc:
                raise InputError("Another process opened C concurrently") from exc
    output=new_run(root/"holdout_evaluations")
    report={"selected_id":selected["selected_id"],"opened_utc":now(),"repeated_exposure":exposed,
            "primary_chain_frozen_on_V":selected["primary_chain_selected_on_V"],"panels":{},"scientific_accuracy_qualified":False}
    donors=np.flatnonzero(np.isin(cube.roles,["D","V"]))
    for name,station_role,time_role in (("joint_C_sites_C_years","C","C"),
        ("spatial_C_sites_D_years","C","D"),("temporal_D_sites_C_years","D","C")):
        panels=[(np.flatnonzero(cube.roles==station_role),np.flatnonzero(cube.time_roles==time_role))]
        native=HumidityCases(cube,c,panels,donors,name)
        aux=forecasts(cube,c,panels,donors,selected["shared_auxiliary_models"],name+"_aux")
        mask=native.common_mask(aux);records={}
        for coordinate,r in selected["models"].items():
            pred,view,weights=predict_chain(native,coordinate,r["model"],r["eta"],r["fit"],aux)
            own,ov,_=predict_chain(native,coordinate,r["model"],r["eta"],r["fit"],aux,False)
            records[coordinate]={"common":score(native,pred,mask),"own":score(native,own,ov.obs),
                                 "common_calendar_cases":int(mask.sum())}
            write_csv(output/(name+"_"+coordinate+".csv"),prediction_rows(native,coordinate,view,pred,aux,weights,mask),FIELDS)
        report["panels"][name]=records
    complete=all(r["common_calendar_cases"]>0 and r["common"]["RH"]["N_scored"]==r["common_calendar_cases"]
                 and all(r["common"]["RH"]["by_country"].get(co,{}).get("N",0)>0 for co in c["countries"])
                 for panel in report["panels"].values() for r in panel.values())
    report["exit_code"]=0 if complete else 2
    report["evaluation_directory"]=str(output)
    Cube(cube.path)
    if implementation()!=spec["implementation"]:raise InputError("Implementation changed during C evaluation")
    write_json(output/"summary.json",report)
    summary=json.loads((root/"summary.json").read_bytes())
    summary.update(holdout_opened=True,latest_C_evaluation=str(output),latest_C_exit_code=report["exit_code"])
    write_json(root/"summary.json",summary)
    return report
