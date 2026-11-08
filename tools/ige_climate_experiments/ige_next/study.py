"""Read-only, D-trained exploratory expansion of the already inspected V cohort.

No C evaluation entry point exists in this package. Source and artifact hashes are
checked before/after a run, and a failed candidate stays in the denominator.
"""
import copy
import csv
import gc
import gzip
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import numpy as np
from ige_auto.data import Cube
from ige_auto.fit import Unidentifiable
from ige_hum.auxiliary import forecasts
from ige_hum.config import sealed,check_cohort
from ige_hum.metrics import errors,score
from ige_hum.study import seal
from ige_local.common import InputError,digest,file_hash,log,new_run,now,peak_rss_bytes,read_json,write_csv,write_json,source_audit_failed
from . import VERSION
from .cases import Moisture,meteo,pressure_physics,restore
from .config import matrix
from .engine import fit,predict,search


ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=ROOT/"INTERPOLATION_PROGRAM_v030_RU.md"
BLOCKED={"solar":"BLOCKED_INPUT_NOT_IN_CUBE","precipitation":"BLOCKED_INPUT_NOT_IN_CUBE",
         "wind":"BLOCKED_INPUT_NOT_IN_CUBE","longwave":"BLOCKED_INPUT_NOT_IN_CUBE",
         "snow":"BLOCKED_INPUT_NOT_IN_CUBE","terrain_and_grid_background":"BLOCKED_EXTERNAL_INPUTS_NOT_PREPARED"}


def implementation():
    paths=[ROOT/"ige_next_experiments.py",PROTOCOL]
    for name in ("ige_next","ige_hum","ige_auto","ige_local"):paths+=sorted((ROOT/name).glob("*.py"))
    return {str(p.relative_to(ROOT)).replace(os.sep,"/"):file_hash(p) for p in paths}


def guard_C(source,source_spec):
    paths=[Path(source)/"C_OPENED.json"]
    # Windows paths cannot be inspected on Linux; do not pretend this is a blind archive.
    raw=source_spec.get("configuration",{}).get("cohort_anchor","")
    accessible=bool(raw and (os.name=="nt" or ":\\" not in raw) and Path(raw).is_file())
    if accessible:paths.append(Path(raw).parent.parent/"C_OPENED.json")
    if any(p.exists() for p in paths):raise InputError("Source/anchor C is already exposed; this protocol must not continue")
    if source_spec.get("continuation"):
        p=source_spec["continuation"].get("parent_run","")
        if p and (os.name=="nt" or ":\\" not in p) and (Path(p)/"C_OPENED.json").exists():raise InputError("Parent C is exposed")
    summary=read_json(Path(source)/"summary.json")
    if summary.get("holdout_opened") or summary.get("source_data_errors"):raise InputError("Source summary reports C exposure or source errors")
    if summary.get("exit_code")!=0:raise InputError("Source run did not complete successfully; resolve its errors first")
    return {"source_marker_checked":True,"original_anchor_marker_checked":accessible,
            "scope":"COMPUTATIONAL_WITHHOLDING_ONLY" if accessible else "DETACHED_ARCHIVE_COPY_OR_UNAVAILABLE_ANCHOR",
            "native_containers_previously_parsed":True,"independent_raw_blinding_claimed":False}


def validate_bundle(value,cube,indices,c):
    families={cube.stations[i]["family"] for i in indices};years=set(c["years"]["D"])
    if set(value)!={"T","p"}:raise InputError("Expected a shared T/p bundle")
    for name,record in value.items():
        if set(record["training_families"])!=families or set(record["training_years"])!=years:raise InputError("Auxiliary training families/years differ: "+name)
        if record["optimization"]["status"]!="CONVERGED":raise InputError("Unresolved auxiliary optimization")


def prepare(config):
    source=Path(config["source_run"]);source_spec=sealed(source/"run_spec.sealed.json","spec_id")
    exposure=guard_C(source,source_spec)
    cube=Cube(source/"cube");check_cohort(cube,source_spec["anchor"])
    if cube.meta["cube_id"]!=source_spec["cube_id"]:raise InputError("Source cube differs from its run spec")
    if cube.meta.get("source_errors") or cube.meta.get("notes") or source_audit_failed(cube.meta.get("source_audit") or {}):raise InputError("Source cube has unresolved preparation/audit errors")
    c=copy.deepcopy(source_spec["base_configuration"]);c["optimizer"]=config["optimizer"];c["workers"]=1
    destination=Path(config["results"]).resolve();db=Path(c["database"]).resolve()
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):raise InputError("Outputs must be separate from the source run")
    if os.name=="nt" or ":\\" not in c["database"]:
        if destination.is_relative_to(db) or db.is_relative_to(destination):raise InputError("Outputs must be disjoint from Database")
    d=np.flatnonzero(cube.roles=="D");checkpoints={};source_files={}
    for name in ["aux_full_D"]+["aux_inner_"+str(f) for f in range(c["inner_folds"])]:
        p=source/"checkpoints"/(name+".json");record=sealed(p,"checkpoint_id")
        if record["spec_id"]!=source_spec["spec_id"]:raise InputError("Auxiliary belongs to another source run")
        ix=d if name=="aux_full_D" else np.flatnonzero((cube.roles=="D")&(cube.folds!=int(name.rsplit("_",1)[1])))
        validate_bundle(record["value"],cube,ix,c);checkpoints[name]=record
        source_files[str(p.resolve())]=file_hash(p)
    for p in (source/"run_spec.sealed.json",source/"summary.json",source/"cube"/"metadata.json"):
        source_files[str(p.resolve())]=file_hash(p)
    out=new_run(destination)
    shutil.copytree(source/"cube",out/"cube")
    for name,record in checkpoints.items():write_json(out/"auxiliary"/(name+".json"),record)
    inventory=matrix(config)
    spec={"schema":"IGE_INTERPOLATION_RUN_v030","version":VERSION,"created_utc":now(),"configuration":config,
        "base_configuration":c,"source_run":str(source.resolve()),"source_spec_id":source_spec["spec_id"],
        "source_files":source_files,"auxiliary_hashes":{p.name:file_hash(p) for p in sorted((out/"auxiliary").glob("*.json"))},
        "cube_id":cube.meta["cube_id"],"anchor":source_spec["anchor"],
        "C_exposure":exposure,"implementation":implementation(),"candidate_matrix":inventory,"blocked_stages":BLOCKED,
        "environment":{"python":sys.version,"platform":platform.platform(),"numpy":importlib.metadata.version("numpy"),
            "scipy":importlib.metadata.version("scipy"),"thread_limits":{k:os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS")}},
        "protocol":{"status":"EXPLORATORY_SEQUENTIAL_V_AFTER_PRIOR_INSPECTION","cohort_reassigned":False,
            "search_data":"D only; family-grouped inner CV; native coefficients by SVD; continuous donor weights",
            "humidity_inner_objective":"reconstructed RH macro country/station/month MSE on fixed common D folds",
            "humidity_auxiliaries":"unchanged sealed D-only/cross-fitted T/p from the parent; D+V bundles excluded",
            "selection":"V country/station macro MAE; all requested candidates and numerical failures reported",
            "C_evaluation_implemented":False,"full_year_gate_applied":False,"clipping_applied":False,
            "QC_policy":"source eligibility inherited; no additional rejection of automatic/unreviewed observations",
            "coupling":"V diagnostic only, replace auxiliary forecasts without retuning humidity fits",
            "background":"learned country/month seasonal-diurnal height background; no DEM/reanalysis supplied"}}
    seal(out/"run_spec.sealed.json",spec,"spec_id");write_json(out/"candidate_matrix.json",inventory)
    log("New interpolation run: "+str(out));return out


def check_run(out):
    out=Path(out).resolve();s=sealed(out/"run_spec.sealed.json","spec_id")
    if s["implementation"]!=implementation():raise InputError("Implementation/protocol changed; start a new run, do not reuse its scores")
    for raw,expected in s["source_files"].items():
        if file_hash(raw)!=expected:raise InputError("Source artifact changed: "+raw)
    for name,expected in s["auxiliary_hashes"].items():
        if file_hash(out/"auxiliary"/name)!=expected:raise InputError("Copied auxiliary changed: "+name)
    guard_C(s["source_run"],sealed(Path(s["source_run"])/"run_spec.sealed.json","spec_id"))
    if (out/"C_OPENED.json").exists():raise InputError("C exposure marker found")
    cube=Cube(out/"cube");check_cohort(cube,s["anchor"])
    if cube.meta["cube_id"]!=s["cube_id"]:raise InputError("Input cube changed")
    return out,s,cube


def bundle(out,name,cube,indices,c):
    x=sealed(out/"auxiliary"/(name+".json"),"checkpoint_id")
    validate_bundle(x["value"],cube,indices,c);return x["value"]


def splits(cube,c):
    dt=np.flatnonzero(cube.time_roles=="D");vt=np.flatnonzero(cube.time_roles=="V")
    d=np.flatnonzero(cube.roles=="D");v=np.flatnonzero(cube.roles=="V")
    folds=[(np.flatnonzero((cube.roles=="D")&(cube.folds!=f)),np.flatnonzero((cube.roles=="D")&(cube.folds==f))) for f in range(c["inner_folds"])]
    return d,v,dt,vt,folds


def fixed_auxiliaries(out,cube,c):
    d,v,dt,vt,folds=splits(cube,c);full=bundle(out,"aux_full_D",cube,d,c)
    av=forecasts(cube,c,[(v,vt)],d,full,"V_fixed_auxiliary")
    ad=forecasts(cube,c,[(d,dt)],d,full,"D_fixed_auxiliary")
    inner=[]
    for f,(train,check) in enumerate(folds):
        b=bundle(out,"aux_inner_"+str(f),cube,train,c)
        inner.append((forecasts(cube,c,[(train,dt)],train,b,"D_inner_fit_aux"),
                      forecasts(cube,c,[(check,dt)],train,b,"D_inner_check_aux")))
    return ad,av,inner


def memory_check(owners,c):
    seen=set();total=0
    for owner in owners:
        for obj in (owner,getattr(owner,"base",None)):
            if obj is None:continue
            for a in vars(obj).values():
                if isinstance(a,np.ndarray) and id(a) not in seen:seen.add(id(a));total+=a.nbytes
    if total*2>c["memory_budget_bytes"]:raise InputError("Case matrices plus optimizer workspace exceed the memory budget")
    return total


def path_for(out,item):return out/"models"/item["stage"]/item["support"]/item["coordinate"]/item["model"]["id"]


def resume(out,spec,item):
    path=path_for(out,item);rp=path/"result.sealed.json"
    if not rp.exists():return None
    r=sealed(rp,"result_id")
    if r["spec_id"]!=spec["spec_id"] or r["candidate"]!=item:raise InputError("Candidate spec mismatch")
    for name,sha in r.get("artifacts",{}).items():
        if file_hash(path/name)!=sha:raise InputError("Candidate artifact changed: "+str(path/name))
    log("Resume "+r["key"]+": "+r["status"]);return r


def extra_diagnostics(y,p,b,mask):
    use=mask&np.isfinite(y)&np.isfinite(p);err=np.abs(p-y)
    local=(b.ht*24/(2*np.pi))%24 if hasattr(b,"ht") else np.array([(int(b.cube.times[t][11:13])+b.cube.stations[s]["lon"]/15)%24 for s,t in zip(b.s,b.t)])
    z=np.array([b.cube.stations[s]["height_m"] for s in b.s])
    min_distance=np.min(np.where(b.mask,b.dist,np.inf),axis=1)
    def group(values,edges):
        return [{"from":lo,"to":hi,"N":int((use&(values>=lo)&(values<hi)).sum()),
            "MAE":float(np.mean(err[use&(values>=lo)&(values<hi)])) if np.any(use&(values>=lo)&(values<hi)) else None} for lo,hi in zip(edges[:-1],edges[1:])]
    return {"mean_solar_hour":group(local,list(range(0,25,3))),"target_height_m":group(z,[-500,300,700,1200,2000,10000]),
        "nearest_eligible_donor_km":group(min_distance,[0,25,50,100,200,500,5000]),
        "P95_absolute_error":float(np.quantile(err[use],.95)) if use.any() else None}


def write_predictions(path,b,arrays,mask,weights):
    path.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(path/"V_predictions.npz",**arrays,common_mask=mask,station_index=b.s,time_index=b.t,
        donor_indices=b.d,donor_weights=weights,target_qc=np.asarray(b.cube.qc[b.s,b.t,:3]),
        target_sources=np.asarray(b.cube.sources[b.s,b.t,:3]))
    # NPZ keeps exact arrays and donor weights; CSV is a compact review/export view.
    fields=["case_id","country","station","timestamp_utc","common_case"]+list(arrays)
    with (path/"V_predictions.csv.gz").open("wb") as raw:
        with gzip.GzipFile(fileobj=raw,mode="wb",mtime=0,filename="") as gz:
            with io.TextIOWrapper(gz,encoding="utf-8",newline="") as stream:
                w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
                for i,rid in enumerate(b.row_id):
                    row={"case_id":rid,"country":str(b.country[i]),"station":str(b.station[i]),"timestamp_utc":b.cube.times[b.t[i]],"common_case":int(mask[i])}
                    row.update({k:float(v[i]) if np.isfinite(v[i]) else "" for k,v in arrays.items()});w.writerow(row)


def candidate(out,spec,c,item,folds,training,validation,fixed,aux=None,knot_bounds=None,native=None):
    cached=resume(out,spec,item)
    if cached is not None:return cached
    path=path_for(out,item);begin=time.monotonic();cpu=time.process_time();model=item["model"]
    key="/".join((item["stage"],item["support"],item["coordinate"],model["id"]))
    log("Interpolation "+key+"; fixed V cases="+str(int(fixed.sum())))
    r={"spec_id":spec["spec_id"],"candidate":item,"key":key,"status":"STARTED","artifacts":{},
       "common_case_id":digest({"rows":validation.row_id,"mask":np.packbits(fixed).tolist()}),"common_calendar_cases":int(fixed.sum())}
    try:
        opt=search(folds,model,c,"RH" if native is not None else "native",item["coordinate"],knot_bounds)
        trace=opt.pop("trace",[]);write_json(path/"optimization_trace.json",trace);r["optimization"]=opt
        r["artifacts"]["optimization_trace.json"]=file_hash(path/"optimization_trace.json")
        if opt["status"]!="CONVERGED":r["status"]=opt["status"]
        else:
            fitted=fit(training,model,opt["eta"],c["optimizer"]);pv,w=predict(validation,model,opt["eta"],fitted)
            r["fit_D"]=fitted;r["training_ledger"]=training.ledger;r["validation_ledger"]=validation.ledger
            if native is None:
                reference=np.where(validation.obs,validation.y,np.nan)
                r["common"]=errors(reference,pv,validation,fixed);r["own_coverage"]=errors(reference,pv,validation,validation.obs)
                r["diagnostics"]=extra_diagnostics(reference,pv,validation,fixed)
                arrays={"observed":reference,"predicted":pv,"native_prediction":pv}
                r["own_coverage"]["N_predicted_calendar"]=int(np.isfinite(pv).sum())
            else:
                pred=restore(item["coordinate"],pv,aux)
                r["common"]=score(native,pred,fixed)
                # Crucial: RH reference does not require observed target p or T.
                r["own_coverage"]=score(native,pred,native.eligible[:,1])
                r["own_coverage"]["N_predicted_calendar"]=int(np.isfinite(pred["RH"]).sum())
                r["own_coverage"]["N_native_coordinate_reference"]=int(validation.obs.sum())
                r["diagnostics"]=extra_diagnostics(native.values[:,1],pred["RH"],validation,fixed)
                arrays={"observed":np.where(native.eligible[:,1],native.values[:,1],np.nan),"predicted":pred["RH"],"native_prediction":pv,
                    "T_aux_predicted":aux["T"],"p_aux_predicted":aux["p"],"e_predicted_hPa":pred["e_hPa"],
                    "q_predicted_kgkg":pred["q_kgkg"],"Td_predicted_water":pred["Td_water"]}
            metric=r["common"]["RH"] if native is not None else r["common"]
            countries=all(metric["by_country"].get(co,{}).get("N",0)>0 for co in c["countries"])
            r["status"]="ELIGIBLE" if int(fixed.sum())>=c["optimizer"]["min_fit_cases"] and metric["N_scored"]==int(fixed.sum()) and countries else "INCOMPLETE_COMMON_V"
            r["primary_macro_MAE"]=metric["macro_MAE"]
            write_predictions(path,validation,arrays,fixed,w)
            for n in ("V_predictions.npz","V_predictions.csv.gz"):r["artifacts"][n]=file_hash(path/n)
    except (Unidentifiable,ValueError,np.linalg.LinAlgError,FloatingPointError) as exc:
        r["status"]="UNIDENTIFIABLE_OR_UNSUPPORTED";r["reason"]=str(exc)
    r.update(wall_seconds=time.monotonic()-begin,cpu_seconds=time.process_time()-cpu)
    log("  "+r["status"]+("; macro MAE="+str(round(r["primary_macro_MAE"],6)) if r.get("primary_macro_MAE") is not None else ""))
    return seal(path/"result.sealed.json",r,"result_id")


def run_temperature(out,spec,cube,c,items):
    d,v,dt,vt,groups=splits(cube,c)
    train=meteo(cube,c,[(d,dt)],d,"T","T_D");valid=meteo(cube,c,[(v,vt)],d,"T","T_V")
    folds=[]
    for f,(a,b) in enumerate(groups):
        tr=meteo(cube,c,[(a,dt)],a,"T","T_inner_fit_"+str(f));ck=meteo(cube,c,[(b,dt)],a,"T","T_inner_check_"+str(f))
        folds.append((tr,ck,ck.fit_mask.copy(),None))
    memory_check([train,valid]+[x for a,b,_,_ in folds for x in (a,b)],c)
    heights=np.array([cube.stations[i]["height_m"]/1000 for i in d]);bounds=np.quantile(heights,[.2,.8]).tolist()
    return [candidate(out,spec,c,item,folds,train,valid,valid.fit_mask.copy(),knot_bounds=bounds) for item in items]


def run_pressure(out,spec,cube,c,items):
    d,v,dt,vt,groups=splits(cube,c);ad,av,inner=fixed_auxiliaries(out,cube,c)
    train=meteo(cube,c,[(d,dt)],d,"p","p_D");valid=meteo(cube,c,[(v,vt)],d,"p","p_V")
    tp=pressure_physics(cube,c,[(d,dt)],d,ad,"p_D");vp=pressure_physics(cube,c,[(v,vt)],d,av,"p_V")
    plain=[];physical=[]
    for f,((a,b),(at,ac)) in enumerate(zip(groups,inner)):
        tr=meteo(cube,c,[(a,dt)],a,"p","p_inner_fit_"+str(f));ck=meteo(cube,c,[(b,dt)],a,"p","p_inner_check_"+str(f))
        trp=pressure_physics(cube,c,[(a,dt)],a,at,"p_inner_physical_fit_"+str(f));ckp=pressure_physics(cube,c,[(b,dt)],a,ac,"p_inner_physical_check_"+str(f))
        mask=ckp.fit_mask&ck.fit_mask;plain.append((tr,ck,mask.copy(),None));physical.append((trp,ckp,mask.copy(),None))
    fixed=vp.fit_mask&valid.fit_mask
    memory_check([train,valid,tp,vp]+[x for fs in (plain,physical) for a,b,_,_ in fs for x in (a,b)],c)
    return [candidate(out,spec,c,item,physical if item["model"]["basis"].startswith("barometric") else plain,
        tp if item["model"]["basis"].startswith("barometric") else train,
        vp if item["model"]["basis"].startswith("barometric") else valid,fixed.copy()) for item in items]


def run_humidity(out,spec,cube,c,items):
    d,v,dt,vt,groups=splits(cube,c);ad,av,inner=fixed_auxiliaries(out,cube,c)
    train=Moisture(cube,c,[(d,dt)],d,"humidity_D","joint");valid=Moisture(cube,c,[(v,vt)],d,"humidity_V","joint")
    natives=[]
    for f,((a,b),(at,ac)) in enumerate(zip(groups,inner)):
        tr=Moisture(cube,c,[(a,dt)],a,"humidity_inner_fit_"+str(f),"joint")
        ck=Moisture(cube,c,[(b,dt)],a,"humidity_inner_check_"+str(f),"joint")
        ac={**ac,"RH_reference":ck.values[:,1]}
        natives.append((tr,ck,ck.common_mask(ac),ac))
    estimated=memory_check([train,valid]+[x for a,b,_,_ in natives for x in (a,b)],c)
    write_json(out/"memory_case_estimate.json",{"humidity_case_arrays_bytes":estimated,"workspace_multiplier":2})
    fixed=valid.common_mask(av);results=[]
    for item in items:
        co=item["coordinate"];paired=item["support"]=="joint"
        folds=[(a.view(co,paired),b.view(co,paired),mask.copy(),ac) for a,b,mask,ac in natives]
        results.append(candidate(out,spec,c,item,folds,train.view(co,paired),valid.view(co,paired),fixed.copy(),av,native=valid))
    return results


def selected(results):
    groups={}
    for r in results:
        if r["status"]!="ELIGIBLE":continue
        item=r["candidate"];key="/".join((item["stage"],item["support"],item["coordinate"]))
        groups.setdefault(key,[]).append(r)
    return {k:min(pool,key=lambda r:(r["primary_macro_MAE"],len(r["fit_D"]["coefficients"]),r["key"])) for k,pool in groups.items()}


def coupling(out,spec,cube,c,chosen):
    if "T/native/T" not in chosen or "p/native/p" not in chosen:return {"status":"SKIPPED_MISSING_T_OR_P_STAGE"}
    d,v,dt,vt,_=splits(cube,c);_,av,_=fixed_auxiliaries(out,cube,c)
    native=Moisture(cube,c,[(v,vt)],d,"humidity_V","joint");fixed=native.common_mask(av)
    def load_result(r):return np.load(path_for(out,r["candidate"])/"V_predictions.npz",allow_pickle=False)
    with load_result(chosen["T/native/T"]) as a:pt=a["predicted"].copy()
    with load_result(chosen["p/native/p"]) as a:pp=a["predicted"].copy()
    reports={}
    for key,r in chosen.items():
        if r["candidate"]["stage"]!="humidity":continue
        with load_result(r) as a:pv=a["native_prediction"].copy()
        co=r["candidate"]["coordinate"]
        reports[key]={}
        for name,ax in (("replace_T_only",{"T":pt,"p":av["p"]}),("replace_p_only",{"T":av["T"],"p":pp}),
                        ("replace_T_and_p",{"T":pt,"p":pp})):
            pred=restore(co,pv,ax);sc=score(native,pred,fixed)
            reports[key][name]={"RH":sc["RH"],"physical_flags":sc["physical_flags"],"complete_on_fixed_cases":sc["RH"]["N_scored"]==int(fixed.sum())}
    value={"status":"DIAGNOSTIC_ONLY_NO_HUMIDITY_RETUNING","selected_T":chosen["T/native/T"]["result_id"],
        "selected_p":chosen["p/native/p"]["result_id"],"fixed_calendar_cases":int(fixed.sum()),"results":reports}
    write_json(out/"coupling_diagnostic.json",value);return value


def paired_interval(out,cube,a,b,repeats=2000):
    """Exploratory, conditional on inspected V and selected models, NOT a test-set CI."""
    with np.load(path_for(out,a["candidate"])/"V_predictions.npz",allow_pickle=False) as x:
        mask=x["common_mask"];pa=x["predicted"];y=x["observed"];s=x["station_index"]
    with np.load(path_for(out,b["candidate"])/"V_predictions.npz",allow_pickle=False) as x:
        if not np.array_equal(mask,x["common_mask"]) or not np.array_equal(s,x["station_index"]):raise InputError("Paired bootstrap grids differ")
        pb=x["predicted"]
    by_country={}
    for st in sorted(set(s[mask])):
        use=mask&(s==st);delta=float(np.mean(np.abs(pa[use]-y[use])-np.abs(pb[use]-y[use])))
        by_country.setdefault(cube.stations[st]["country"],[]).append(delta)
    rng=np.random.default_rng(20261108);draws=np.zeros(repeats)
    for values in by_country.values():draws+=np.mean(rng.choice(values,(repeats,len(values)),replace=True),axis=1)/len(by_country)
    return {"difference_A_minus_B":float(np.mean([np.mean(v) for v in by_country.values()])),
        "conditional_percentile_95":np.quantile(draws,[.025,.975]).tolist(),"station_counts":{k:len(v) for k,v in by_country.items()},
        "resampling":"country-stratified stations; all sampled hours travel with a station","repeats":repeats,
        "interpretation":"EXPLORATORY_POST_SELECTION_CONDITIONAL_V_ONLY; no independent significance or year-generalization claim"}


def summarize(out,spec,cube,results,begin,cpu):
    c=spec["base_configuration"];chosen=selected(results);diagnostic=coupling(out,spec,cube,c,chosen)
    rows=[]
    for r in results:
        item=r["candidate"];own=r.get("own_coverage",{});own=own.get("RH",own)
        rows.append({"stage":item["stage"],"support":item["support"],"coordinate":item["coordinate"],"model":item["model"]["id"],
            "status":r["status"],"common_macro_MAE":r.get("primary_macro_MAE"),"common_N":r["common_calendar_cases"],
            "own_scored_N":own.get("N_scored"),"own_macro_MAE":own.get("macro_MAE"),
            "wall_seconds":r["wall_seconds"],"cpu_seconds":r["cpu_seconds"],"result_id":r["result_id"]})
    write_csv(out/"comparison.csv",rows,list(rows[0]) if rows else ["status"])
    comparisons={}
    if "T/native/T" in chosen:
        ref=next((r for r in results if r["key"]=="T/native/T/height_idw_ols" and r["status"]=="ELIGIBLE"),None)
        if ref:comparisons["selected_T_minus_height"]=paired_interval(out,cube,chosen["T/native/T"],ref)
    for co in ("RH","log_e","q","Td","D"):
        a=chosen.get("humidity/own/"+co);b=chosen.get("humidity/joint/"+co)
        if a and b:comparisons["own_minus_joint_"+co]=paired_interval(out,cube,a,b)
    compact={k:{"key":r["key"],"result_id":r["result_id"],"macro_MAE":r["primary_macro_MAE"],
        "N":r["common_calendar_cases"],"fit_D":r["fit_D"],"eta":r["optimization"]["eta"]} for k,r in chosen.items()}
    summary={"version":VERSION,"finished_utc":now(),"spec_id":spec["spec_id"],"cube_id":spec["cube_id"],
        "models_requested":len(spec["candidate_matrix"]),"models_recorded":len(results),"models_eligible":sum(r["status"]=="ELIGIBLE" for r in results),
        "failures":[{"key":r["key"],"status":r["status"],"reason":r.get("reason")} for r in results if r["status"]!="ELIGIBLE"],
        "best_per_group":compact,"blocked_stages":BLOCKED,"paired_exploratory_comparisons":comparisons,
        "coupling_status":diagnostic["status"],"holdout_opened":False,"C_exposure_scope":spec["C_exposure"],
        "validation_status":"EXPLORATORY_SEQUENTIAL_V_AFTER_PRIOR_INSPECTION","scientific_accuracy_qualified":False,
        "clipping_applied":False,"full_year_gate_applied":False,"source_data_modified":False,"network_requests":0,
        "wall_seconds_this_invocation":time.monotonic()-begin,"cpu_seconds_this_invocation":time.process_time()-cpu,"peak_rss_bytes":peak_rss_bytes()}
    summary["exit_code"]=0 if summary["models_eligible"]==summary["models_requested"] else 2
    write_json(out/"summary.json",summary)
    lines=["# IGE — новая программа интерполяционных экспериментов, 0.3.0","",
        "Статус: исследовательское расширение после предыдущего просмотра V. Контрольная C не вычислялась; независимая валидация ещё предстоит.","",
        "Запрошено моделей: %d; записано: %d; пригодно на всех общих часах: %d."%(summary["models_requested"],len(results),summary["models_eligible"]),"",
        "| Величина / доноры | Выбранная на V модель | Macro MAE | Общие часы |","|---|---|---:|---:|"]
    lines += ["| "+k+" | "+r["key"].split("/")[-1]+" | "+str(round(r["macro_MAE"],6))+" | "+str(r["N"])+" |" for k,r in compact.items()]
    lines += ["","Единицы: T — °C, p — hPa, ошибка восстановленной RH — процентные пункты, не относительные проценты.",
        "Влажность сравнивается с теми же общими T/p; own и joint заново обучаются раздельно. Собственное покрытие приведено отдельно в comparison.csv.",
        "Все коэффициенты оценены на D, веса оптимизированы непрерывно внутри D. Глобальная оптимальность не заявляется. Модели D+V для этой новой программы не обучались.",
        "Подстановка новых T/p в coupling_diagnostic.json — диагностическая проверка без переобучения коэффициентов влажности.",
        "CSV и NPZ каждого кандидата содержат прогнозы V; NPZ также содержит точные веса доноров, индексы, QC и ссылки на источники внутри запечатанного куба.",
        "Флаги ручной/автоматической проверки сохраняются; дополнительного исключения непроверенных вручную часов нет. RH не обрезается.",
        "Невычисленные блоки: солнце, осадки, ветер, длинноволновое излучение, снег и внешняя топография/сетка — отсутствуют необходимые входы в этом кубе."]
    if summary["failures"]:lines += ["","Незавершённые кандидаты:"]+["- "+x["key"]+": "+x["status"]+" "+str(x["reason"] or "") for x in summary["failures"]]
    (out/"REPORT_RU.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def train(out):
    begin=time.monotonic();cpu=time.process_time();out,spec,cube=check_run(out);c=spec["base_configuration"]
    write_json(out/"input_codebooks.json",{k:cube.meta[k] for k in ("stations","times","qc_codebook","source_codebook","operator_codebook")})
    results=[]
    for stage,runner in (("T",run_temperature),("p",run_pressure),("humidity",run_humidity)):
        items=[i for i in spec["candidate_matrix"] if i["stage"]==stage]
        if items:results+=runner(out,spec,cube,c,items)
        gc.collect()
    # Verify immutability again before accepting the summary.
    check_run(out)
    summary=summarize(out,spec,cube,results,begin,cpu)
    log("REPORT: "+str(out/"REPORT_RU.md"));log("SUMMARY: "+str(out/"summary.json"));return summary
