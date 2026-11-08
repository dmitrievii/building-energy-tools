"""Fit shared T/p without the humidity validation families, including tuning."""
import copy
import numpy as np
from ige_auto.cases import Cases
from ige_auto.data import rank_key
from ige_auto.fit import optimize,fit_cases,predict
from ige_local.common import InputError,log,write_json
from .solver import recover_native

MODEL={"id":"shared_height_idw_ols","basis":"height","kernel":"idw","regression":"ols"}


def training_folds(cube,c,train,n=3):
    train=np.asarray(train,dtype=int);mapping={}
    for country in sorted({cube.stations[s]["country"] for s in train}):
        families=sorted({cube.stations[s]["family"] for s in train if cube.stations[s]["country"]==country},
                        key=lambda f:rank_key(c["split_seed"],"aux",country,f))
        if len(families)<n+2:raise InputError("Too few auxiliary training families for nested checks: "+country)
        for i,f in enumerate(families):mapping[f]=i%n
    return [np.array([s for s in train if mapping[cube.stations[s]["family"]]!=i]) for i in range(n)],mapping


def train_bundle(cube,c,train,times,optimizer,diagnostics=None):
    train=np.asarray(train,dtype=int);times=np.asarray(times,dtype=int)
    subsets,mapping=training_folds(cube,c,train)
    conf=copy.deepcopy(c);conf["optimizer"]=optimizer;conf["workers"]=1
    fitted={}
    for variable in ("T","p"):
        log("  shared auxiliary "+variable+": "+str(len(train))+" training sites; nested tuning")
        folds=[]
        for i,part in enumerate(subsets):
            check=np.array([s for s in train if mapping[cube.stations[s]["family"]]==i])
            folds.append((Cases(cube,[(part,times)],part,variable,conf,"aux_nested_%s_fit"%i),
                          Cases(cube,[(check,times)],part,variable,conf,"aux_nested_%s_check"%i)))
        search=optimize(folds,MODEL,conf)
        if search["status"]=="UNRESOLVED_OPTIMIZATION":
            log("  shared auxiliary "+variable+": retrying continuous optimization")
            search=recover_native(search,folds,MODEL,conf)
        if diagnostics is not None:
            from pathlib import Path
            write_json(Path(diagnostics)/(variable+"_optimization.json"),search)
        if search["status"]!="CONVERGED":raise InputError("Auxiliary "+variable+": "+search["status"])
        log("  shared auxiliary "+variable+": CONVERGED")
        del folds
        a=Cases(cube,[(train,times)],train,variable,conf,"aux_outer_fit")
        fit=fit_cases(a,MODEL,search["eta"],optimizer)
        fitted[variable]={"model":MODEL,"optimization":search,"fit":fit,
                          "training_families":sorted({cube.stations[s]["family"] for s in train}),
                          "training_years":sorted(set(cube.years[times].tolist()))}
    return fitted


def forecasts(cube,c,panels,donors,bundle,label):
    result={}
    for variable in ("T","p"):
        b=Cases(cube,panels,donors,variable,c,label)
        record=bundle[variable]
        p,_,_=predict(b,record["model"],record["optimization"]["eta"],record["fit"])
        result[variable]=p
    return result


def refit_bundle(cube,c,panels,donors,bundle,optimizer):
    fitted=copy.deepcopy(bundle)
    for variable in ("T","p"):
        b=Cases(cube,panels,donors,variable,c,"aux_final_D_plus_V")
        fitted[variable]["fit"]=fit_cases(b,MODEL,bundle[variable]["optimization"]["eta"],optimizer)
        fitted[variable]["training_families"]=b.ledger["target_families"]
        fitted[variable]["training_years"]=b.ledger["target_years"]
    return fitted
