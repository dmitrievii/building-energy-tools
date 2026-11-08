"""Registered, small configuration surface. The frozen source defines the cohort."""
import copy
import math
from pathlib import Path
from ige_local.common import InputError,read_json


def model(name,basis,regression="ols",kernel="idw"):
    return dict(id=name,basis=basis,kernel=kernel,regression=regression)


TEMPERATURE=[model("nearest","nearest"),model("idw_uncorrected","none"),
    model("height_idw_ols","height"),model("seasonal_idw_ols","seasonal_height"),
    model("monthly_idw_ols","monthly_height"),model("diurnal_height_ridge","diurnal","ridge"),
    model("hinge_height_ridge","hinge","ridge"),model("local_height_shrinkage","local_height"),
    model("background_residual_idw","background","ridge")]
PRESSURE=[model("nearest","nearest"),model("height_idw_ols","height"),
    model("barometric_idw","barometric"),model("barometric_residual_idw","barometric_residual")]
MOISTURE=[model("height_idw_ols","height"),model("seasonal_idw_ols","seasonal_height"),
    model("monthly_idw_ols","monthly_height"),model("harmonic_idw_ridge","harmonic_height","ridge"),
    model("geo_gaussian_ols","height_geo",kernel="gaussian"),
    model("seasonal_geo_gaussian_huber","seasonal_geo","huber","gaussian")]


def load(path):
    path=Path(path).resolve()
    try:c=read_json(path)
    except ValueError as exc:raise InputError("Invalid JSON configuration; use / in Windows paths: "+str(exc)) from exc
    expected={"schema","source_run","results","coordinates","supports","optimizer","workers","stages"}
    if set(c)!=expected or c["schema"]!="IGE_INTERPOLATION_PROGRAM_v030":raise InputError("Unknown configuration schema or keys")
    if c["coordinates"]!=["RH","log_e","q","Td","D"] or c["supports"]!=["joint","own"]:
        raise InputError("Registered matrix is five coordinates and joint/own support")
    if type(c["workers"]) is not int or c["workers"]!=1:raise InputError("workers=1 required")
    if not c["stages"] or len(set(c["stages"]))!=len(c["stages"]) or any(x not in ("T","p","humidity") for x in c["stages"]):
        raise InputError("Stages must be a unique subset of T, p, humidity")
    for k in ("source_run","results"):
        if not isinstance(c[k],str) or not c[k].strip() or any(ord(x)<32 for x in c[k]):raise InputError("Invalid path "+k)
        c[k]=str((path.parent/c[k]).resolve())
    opt=c["optimizer"]
    expected_opt={"max_evaluations","max_iterations","wall_seconds_per_model","starts","min_fit_cases","rank_rcond","max_condition"}
    if not isinstance(opt,dict) or set(opt)!=expected_opt:raise InputError("Optimizer keys differ from the registered contract")
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in opt.values()):raise InputError("Optimizer values must be finite numbers")
    if any(type(opt[k]) is not int for k in ("max_evaluations","max_iterations","starts","min_fit_cases")):raise InputError("Optimizer counts must be integers")
    if not (opt["max_evaluations"]>=10 and opt["max_iterations"]>=1 and opt["wall_seconds_per_model"]>0 and
        1<=opt["starts"]<=3 and opt["min_fit_cases"]>=10 and 0<opt["rank_rcond"]<1 and opt["max_condition"]>1):raise InputError("Invalid optimizer limits")
    c["config_source_path"]=str(path)
    return c


def matrix(config):
    rows=[]
    if "T" in config["stages"]:rows += [{"stage":"T","coordinate":"T","support":"native","model":copy.deepcopy(m)} for m in TEMPERATURE]
    if "p" in config["stages"]:rows += [{"stage":"p","coordinate":"p","support":"native","model":copy.deepcopy(m)} for m in PRESSURE]
    if "humidity" in config["stages"]:
        rows += [{"stage":"humidity","coordinate":v,"support":s,"model":copy.deepcopy(m)}
            for s in config["supports"] for v in config["coordinates"] for m in MOISTURE]
    return rows
