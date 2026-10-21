"""C2 strict-first physical projection with immutable source and fixed pressure.

An exact witness is preserved BEFORE minimizing a soft-data objective. This is
an explicit source-preservation policy, not a claim that an exact witness is a
MAP optimum. Modified results minimize a specified sensitivity metric plus a
discrete donor prior; neither a calibrated error covariance nor globally nearest
climate is claimed by default. Every source diagnostic has a correction ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
import json
import math
import warnings

import numpy as np
from scipy.optimize import linprog, minimize

from p9_3b3_compare_identified_set import MeanInterval, PressureBox, identified_bounds
from p9_3b3_compare_operators import normalized_weights
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_c2_validation import validate_projection
from p9_3b3_daily_feasibility import bounded_mean_profile, fixed_profile_feasibility
from p9_3b3_joint_solver import JointProblem, SolverPolicy
from p9_3b3_thermodynamics import (MK, epsilon_for, q_saturation, qsat_derivative,
                                  relative_humidity, saturation)


MODES = ("HARD_Q_SOFT_RH", "HARD_RH_SOFT_Q", "BOTH_SOFT")


@dataclass(frozen=True)
class ProjectionMetric:
    q_scale_gkg: float = 1.
    RH_scale_pp: float = 5.
    correlation: float = 0.
    interpretation: str = "SENSITIVITY_METRIC_NOT_ERROR_COVARIANCE"
    evidence: str = "PREREGISTERED_DIMENSIONAL_SCALES_NO_NEX_ERROR_CALIBRATION"

    def __post_init__(self):
        if (not all(math.isfinite(x) for x in (self.q_scale_gkg,self.RH_scale_pp,self.correlation)) or
                self.q_scale_gkg <= 0 or self.RH_scale_pp <= 0 or abs(self.correlation) >= 1 or
                not self.evidence or self.interpretation not in
                ("SENSITIVITY_METRIC_NOT_ERROR_COVARIANCE", "EXTERNALLY_SUPPORTED_SAME_PRODUCT_ERROR_COVARIANCE")):
            raise ValueError("P93C2_INVALID_POSITIVE_DEFINITE_METRIC")
        with np.errstate(over="ignore",divide="ignore",invalid="ignore"):
            matrix=self.matrix
            if not np.all(np.isfinite(matrix)):
                raise ValueError("P93C2_METRIC_FLOAT_DOMAIN")
            try:
                np.linalg.cholesky(matrix)
                inverse=np.linalg.inv(matrix)
            except np.linalg.LinAlgError as exc:
                raise ValueError("P93C2_METRIC_FLOAT_SINGULAR") from exc
            if not np.all(np.isfinite(inverse)):
                raise ValueError("P93C2_METRIC_PRECISION_NONFINITE")

    @property
    def matrix(self):
        q,r,c = self.q_scale_gkg,self.RH_scale_pp,self.correlation
        return np.array([[q*q,c*q*r],[c*q*r,r*r]])

    @property
    def precision(self):
        return np.linalg.inv(self.matrix)


@dataclass(frozen=True)
class CorrectionBudget:
    q_limit_gkg: float | None = None
    RH_limit_pp: float | None = None
    interpretation: str = "NOT_ESTABLISHED"
    evidence: str = "NO_INDEPENDENT_NEX_PROCESSING_ERROR_BUDGET"

    def __post_init__(self):
        if not self.evidence or self.interpretation not in (
                "NOT_ESTABLISHED", "RESEARCH_GUARD_NOT_SCIENTIFIC_ACCEPTANCE",
                "EXTERNALLY_JUSTIFIED_SAME_PRODUCT_BUDGET"):
            raise ValueError("P93C2_INVALID_BUDGET_EVIDENCE")
        values = (self.q_limit_gkg,self.RH_limit_pp)
        if self.interpretation == "NOT_ESTABLISHED":
            if any(x is not None for x in values):
                raise ValueError("P93C2_UNESTABLISHED_BUDGET_CANNOT_CONTAIN_LIMITS")
        elif any(x is None or not math.isfinite(x) or x < 0 for x in values):
            raise ValueError("P93C2_BOTH_EXPLICIT_NONNEGATIVE_BUDGETS_REQUIRED")

    def classify(self, dq_gkg, dr_pp, unchanged):
        if unchanged:
            return "NO_SOURCE_CORRECTION_NEEDED"
        if self.interpretation == "NOT_ESTABLISHED":
            return "PROVISIONAL_CORRECTION_BUDGET_NOT_ESTABLISHED"
        if abs(dq_gkg) > self.q_limit_gkg+1e-6 or abs(dr_pp) > self.RH_limit_pp+1e-4:
            return "REJECTED_CORRECTION_BUDGET"
        return ("WITHIN_DECLARED_EXTERNAL_BUDGET" if self.interpretation.startswith("EXTERNALLY")
                else "WITHIN_RESEARCH_GUARD_NOT_SCIENTIFIC_ACCEPTANCE")


@dataclass(frozen=True)
class ProjectionPolicy:
    lambda_shape: float = .01
    temperature_scale_K: float = 2.
    q_scale_floor_gkg: float = 1.
    roughness_hours: float = 1.
    max_iterations: int = 180
    strict_starts: int = 2
    projection_starts: int = 3

    def __post_init__(self):
        if (not all(math.isfinite(x) for x in (self.lambda_shape,self.temperature_scale_K,
                 self.q_scale_floor_gkg,self.roughness_hours)) or self.lambda_shape < 0 or
                self.temperature_scale_K != 2 or self.q_scale_floor_gkg <= 0 or self.roughness_hours < 0 or
                any(type(v) is not int for v in (self.max_iterations,self.strict_starts,self.projection_starts)) or
                not 1 <= self.max_iterations <= 180 or not 1 <= self.strict_starts <= 2 or
                not 1 <= self.projection_starts <= 3):
            raise ValueError("P93C2_INVALID_POLICY")


class ProjectionProblem:
    def __init__(self, donor_T, donor_q, target, pressure, q_weights=None, RH_weights=None,
                 T_weights=None, policy=None):
        self.policy = policy or ProjectionPolicy()
        self.donor_T = tuple(float(x) for x in donor_T)
        self.donor_q = tuple(float(x) for x in donor_q)
        self.base = JointProblem(self.donor_T,self.donor_q,target,pressure,
            policy=SolverPolicy(formulation=MK,max_iterations=self.policy.max_iterations,lower_bound_seconds=0))
        self.target,self.pressure = target,pressure
        self.n,self.k = self.base.n,self.base.k
        self.free = self.base.free
        self.T0,self.P,self.q0 = self.base.T0.copy(),self.base.P.copy(),self.base.q0.copy()
        uniform = np.full(self.n,1/self.n)
        self.u = normalized_weights(uniform if q_weights is None else q_weights,self.n)
        self.v = normalized_weights(uniform if RH_weights is None else RH_weights,self.n)
        self.wT = normalized_weights(uniform if T_weights is None else T_weights,self.n)
        self.qscale = max(self.policy.q_scale_floor_gkg/1000,float(np.sqrt(np.mean(self.q0**2))))

    def diagnostics(self, x):
        t,q = self.base.unpack(x)
        rh = relative_humidity(t,self.P,q,self.base.phase,MK)
        es = saturation(t,self.base.phase,MK)
        eps = epsilon_for(MK)
        jq = np.r_[np.zeros(self.k),self.u]
        dt_rh = -rh*saturation(t,self.base.phase,MK,derivative=True)/es
        dq_rh = 100*self.P/es*eps/(eps+(1-eps)*q)**2/1000
        jr = np.r_[(self.v*dt_rh)[self.free],self.v*dq_rh]
        return np.array([1000*(float(self.u@q)-self.target.q_mean_kgkg),
                         float(self.v@rh)-self.target.RH_mean_pct]), np.vstack([jq,jr])

    def shape(self, x):
        t,q = self.base.unpack(x)
        a,b = (t-self.T0)/self.policy.temperature_scale_K,(q-self.q0)/self.qscale
        value = float((a@a+b@b)/self.n)
        ga,gb = 2*a/self.n,2*b/self.n
        if self.n > 1:
            scale = self.policy.roughness_hours**2/((self.n-1)*(24/self.n)**2)
            for vec,grad in ((a,ga),(b,gb)):
                diff = np.diff(vec)
                value += float(scale*(diff@diff))
                grad[:-1] -= 2*scale*diff
                grad[1:] += 2*scale*diff
        return value,np.r_[ga[self.free]/self.policy.temperature_scale_K,gb/self.qscale/1000]

    def objective(self, x, metric):
        residual,jac = self.diagnostics(x)
        precision = metric.precision
        shape,gradient = self.shape(x)
        data = .5*float(residual@precision@residual)
        return data+self.policy.lambda_shape*shape, jac.T@precision@residual+self.policy.lambda_shape*gradient

    def constraints(self, hard_q=False, hard_RH=False):
        # Reuse only the frozen physical box/cap/slope geometry. Replace its
        # uniform T-mean equation with the explicitly declared T operator.
        constraints = [c for c in self.base.constraints() if c["type"] != "eq"]
        if self.target.semantics.temperature_operator == "TIME_MEAN_TAS" and np.any(self.wT[self.free]>0):
            jac = np.r_[self.wT[self.free],np.zeros(self.n)]
            constraints.append({"type":"eq","fun":lambda x:float(self.wT@self.base.unpack(x)[0]-self.target.tas_K),
                                "jac":lambda x,j=jac:j})
        if hard_q:
            j = np.r_[np.zeros(self.k),self.u]
            constraints.append({"type":"eq","fun":lambda x:float(self.diagnostics(x)[0][0]),"jac":lambda x,j=j:j})
        if hard_RH:
            constraints.append({"type":"eq","fun":lambda x:float(self.diagnostics(x)[0][1])/100,
                                "jac":lambda x:self.diagnostics(x)[1][1]/100})
        return constraints

    def validate(self, x, hard_q=False, hard_RH=False):
        t,q = self.base.unpack(x)
        return validate_projection(t.tolist(),self.P.tolist(),q.tolist(),self.target,
            self.pressure.values_Pa,self.donor_T,self.u.tolist(),self.v.tolist(),self.wT.tolist(),
            hard_q=hard_q,hard_RH=hard_RH)

    def starts(self):
        starts = []
        for t in (self.T0,(self.base.low+self.base.high)/2):
            caps = q_saturation(t,self.P)
            q = np.clip(self.q0,0,caps)
            starts.append(self.base.pack(t,q))
        caps = q_saturation(self.T0,self.P)
        # Frozen helper requires positive weights. For zero-support operators,
        # construct a mass-compatible profile with a direct bounded multiplier.
        mean = min(self.target.q_mean_kgkg,float(self.u@caps))
        q = np.minimum(caps,mean/(float(self.u@caps) or 1)*caps)
        if np.all(self.u > 0):
            q = bounded_mean_profile(self.q0,caps,mean,self.u)
        starts.append(self.base.pack(self.T0,q))
        return starts

    def temperature_feasibility(self):
        if self.target.semantics.temperature_operator != "TIME_MEAN_TAS":
            return {"status":"T_GEOMETRY_HAS_AFFINE_WITNESS"}
        if not self.k:
            return {"status":("T_GEOMETRY_HAS_AFFINE_WITNESS" if abs(self.wT@self.T0-self.target.tas_K)<=1e-6
                              else "CERTIFIED_T_DOMAIN_INFEASIBLE")}
        n = self.n
        D = np.zeros((max(0,n-1),n))
        for i in range(n-1):D[i,i]=-n/24;D[i,i+1]=n/24
        sol = linprog(np.zeros(n),A_ub=np.vstack([D,-D]) if n>1 else None,
            b_ub=np.full(2*(n-1),self.base.slope) if n>1 else None,
            A_eq=self.wT[None,:],b_eq=[self.target.tas_K],
            bounds=list(zip(self.base.low,self.base.high)),method="highs")
        if sol.status == 2:return {"status":"CERTIFIED_T_DOMAIN_INFEASIBLE","method":"BOUNDED_LINEAR_T_MEAN_AND_SLOPE_LP"}
        if sol.status != 0:return {"status":"T_DOMAIN_NUMERICALLY_UNRESOLVED","solver_status":int(sol.status)}
        self._T_lp = np.asarray(sol.x)
        return {"status":"T_LP_WITNESS_FOUND"}


def _base_report(target,pressure,mode,metric,budget,policy,donor_date,pressure_alignment):
    return {"date":target.date,"donor_date":donor_date,"mode":mode,
        "pressure_alignment":pressure_alignment,"pressure_reference":pressure.metadata(),
        "metric":{**asdict(metric),"matrix_gkg_pp":metric.matrix.tolist()},
        "correction_budget":asdict(budget),"projection_policy":asdict(policy),
        "source_target_sha256":fingerprint(target.to_dict()),
        "source_semantics":asdict(target.semantics),
        "source_diagnostics":{"q_mean_kgkg":target.q_mean_kgkg,"RH_mean_pp":target.RH_mean_pct,
            "Tmin_K":target.Tmin_K,"Tmax_K":target.Tmax_K,"tas_K":target.tas_K,
            "temperature_operator":target.semantics.temperature_operator},
        "source_inputs_mutated":False,"source_modified":False,
        "journal":[{"variable":field,"source_value":value,"achieved_value":None,"delta":None,"unit":unit,
                    "delta_unit":"percentage_point" if field=="hurs" else "kg/kg",
                    "correction_applied":False,"reason":"NO_VALIDATED_CANDIDATE_AVAILABLE"}
                   for field,value,unit in (("huss",target.q_mean_kgkg,"kg/kg"),("hurs",target.RH_mean_pct,"%"))],
        "global_optimality_certified":False,"optimality_gap":None,
        "reconciliation_science_qualified":False,"independent_accuracy":"NOT_TESTED",
        "pressure_model_qualified":False,"operational_ready":False,"production_epw_ready":False,
        "production_eligible":False,"research_only":True}


def _package(problem,x,base,metric,budget,method,trials,strict_status):
    mode=base["mode"]
    valid=problem.validate(x,mode=="HARD_Q_SOFT_RH",mode=="HARD_RH_SOFT_Q")
    t,q=problem.base.unpack(x)
    unchanged=valid["source_diagnostics_unchanged_within_numerical_tolerance"]
    residual,jac=problem.diagnostics(x)
    shape,_=problem.shape(x)
    data=.5*float(residual@metric.precision@residual)
    acceptance=budget.classify(float(residual[0]),float(residual[1]),unchanged)
    journal=[]
    for field,src,achieved,delta,unit,hard,scale in (
        ("huss",problem.target.q_mean_kgkg,valid["q_mean_kgkg"],valid["daily_residuals"]["q_mean_kgkg"],"kg/kg",mode=="HARD_Q_SOFT_RH",metric.q_scale_gkg/1000),
        ("hurs",problem.target.RH_mean_pct,valid["RH_source_mean_pct"],valid["daily_residuals"]["RH_mean_pp"],"%",mode=="HARD_RH_SOFT_Q",metric.RH_scale_pp)):
        weights=problem.u if field=="huss" else problem.v
        journal.append({"variable":field,"operator":"DECLARED_DISCRETE_WEIGHTED_MEAN",
            "operator_weights_sha256":fingerprint(weights.tolist()),"phase":problem.base.phase if field=="hurs" else None,
            "source_value":src,"achieved_value":achieved,"delta":delta,"unit":unit,
            "delta_unit":"percentage_point" if field=="hurs" else "kg/kg",
            "correction_applied":abs(delta)>(1e-9 if field=="huss" else 1e-4),
            "hard_constraint":hard,"delta_divided_by_design_scale":delta/scale,
            "design_scale_is_not_measurement_uncertainty":metric.interpretation.startswith("SENSITIVITY"),
            "strict_stage_status":strict_status,"correction_acceptance":acceptance,
            "pressure_fingerprint":problem.pressure.fingerprint})
    status=("REJECTED_CORRECTION_BUDGET" if acceptance=="REJECTED_CORRECTION_BUDGET" else
            "EXACT_SOURCE_PRESERVED" if unchanged else "LOCAL_PHYSICAL_PROJECTION_RESEARCH_ONLY")
    return {**base,"status":status,"method":method,"source_modified":not unchanged,
        "T_K":t.tolist(),"p_Pa":problem.P.tolist(),"q_kgkg":q.tolist(),
        "q_weights":problem.u.tolist(),"RH_weights":problem.v.tolist(),"T_weights":problem.wT.tolist(),
        "validation":valid,"diagnostics":valid["diagnostics"],"journal":journal,
        "correction_acceptance":acceptance,"strict_stage_status":strict_status,"optimizer_trials":trials,
        "objective":{"data_metric":data,"shape_unweighted":shape,
                     "shape_weighted":problem.policy.lambda_shape*shape,"total":data+problem.policy.lambda_shape*shape},
        "hourly_adjustment_summary":{"max_T_delta_from_affine_donor_K":float(np.max(abs(t-problem.T0))),
            "rms_T_delta_from_affine_donor_K":float(np.sqrt(np.mean((t-problem.T0)**2))),
            "max_q_delta_from_raw_donor_gkg":float(np.max(abs(q-problem.q0))*1000)},
        "pressure_unchanged":True,"source_temperature_constraints_changed":False,
        "temperature_operator":problem.target.semantics.temperature_operator,
        "source_semantics":asdict(problem.target.semantics)}


def project_day(donor_T,donor_q,target,pressure,*,mode="BOTH_SOFT",donor_date,
                pressure_alignment="TARGET_DAY_EXTERNAL_FIXED",metric=None,budget=None,policy=None,
                q_weights=None,RH_weights=None,T_weights=None,strict_witness=None):
    if mode not in MODES:raise ValueError("P93C2_UNKNOWN_MODE")
    dt.date.fromisoformat(donor_date)
    if pressure.mode=="OBSERVED_SITE_VALIDATION_ONLY":raise ValueError("P93C2_OBSERVED_PRESSURE_FORBIDDEN")
    if pressure_alignment=="TARGET_DAY_EXTERNAL_FIXED":
        if pressure.reference_date!=target.date:raise ValueError("P93C2_TARGET_DAY_PRESSURE_DATE_MISMATCH")
    elif pressure_alignment=="REGISTERED_DONOR_PRESSURE_SENSITIVITY":
        if pressure.reference_date!=donor_date:raise ValueError("P93C2_DONOR_PRESSURE_DATE_MISMATCH")
    else:raise ValueError("P93C2_PRESSURE_ALIGNMENT_MUST_BE_EXPLICIT")
    metric,budget,policy=metric or ProjectionMetric(),budget or CorrectionBudget(),policy or ProjectionPolicy()
    before=fingerprint(target.to_dict());p_before=pressure.fingerprint
    original=(tuple(donor_T),tuple(donor_q))
    report=_base_report(target,pressure,mode,metric,budget,policy,donor_date,pressure_alignment)
    report["donor_state_sha256"]=fingerprint({"date":donor_date,"T_K":list(donor_T),
        "q_kgkg":list(donor_q),"pressure_fingerprint":p_before})
    if target.semantics.rh_phase=="UNKNOWN":
        return {**report,"status":"SOURCE_BLOCKED","reason":"SOURCE_PHASE_UNKNOWN"}
    problem=ProjectionProblem(donor_T,donor_q,target,pressure,q_weights,RH_weights,T_weights,policy)
    report["operator_weights_sha256"]={name:fingerprint(w.tolist()) for name,w in
        (("huss",problem.u),("hurs",problem.v),("tas_time_mean",problem.wT))}
    tcheck=problem.temperature_feasibility()
    if tcheck["status"] in ("CERTIFIED_T_DOMAIN_INFEASIBLE","T_DOMAIN_NUMERICALLY_UNRESOLVED"):
        return {**report,"status":tcheck["status"],"certificate":tcheck,"scope":"THIS_DONOR_T_PRIOR_ONLY"}
    trials=[]
    def finish(x,method,strict_status):
        out=_package(problem,x,report,metric,budget,method,trials,strict_status)
        if fingerprint(target.to_dict())!=before or pressure.fingerprint!=p_before or original!=(tuple(donor_T),tuple(donor_q)):
            raise AssertionError("P93C2_IMMUTABLE_INPUT_CHANGED")
        return out
    if strict_witness is not None and strict_witness.get("status")=="EXACT_DEFINED_OPERATORS":
        if strict_witness.get("p_Pa")!=list(pressure.values_Pa):
            raise ValueError("P93C2_SUPPLIED_WITNESS_PRESSURE_MISMATCH")
        validate_projection(strict_witness["T_K"],strict_witness["p_Pa"],strict_witness["q_kgkg"],
            target,pressure.values_Pa,problem.donor_T,problem.u.tolist(),problem.v.tolist(),problem.wT.tolist(),
            hard_q=True,hard_RH=True)
        x=problem.base.pack(strict_witness["T_K"],strict_witness["q_kgkg"])
        # Never trust cached residuals or a caller's claimed success.
        problem.validate(x,True,True)
        return finish(x,"STRICT_WITNESS_PRESERVED_BEFORE_SOFT_OBJECTIVE","EXACT_VALIDATED")
    starts=problem.starts()
    if hasattr(problem,"_T_lp"):
        t=problem._T_lp;caps=q_saturation(t,problem.P)
        starts[1]=problem.base.pack(t,np.minimum(problem.q0,caps))
    for x in starts:
        try:problem.validate(x,True,True)
        except ValueError:continue
        return finish(x,"EXACT_START_PRESERVED_BEFORE_SOFT_OBJECTIVE","EXACT_VALIDATED")
    box=PressureBox(tuple(problem.P),tuple(problem.P),pressure.frame,pressure.fingerprint)
    outer=identified_bounds(problem.base.low,problem.base.high,box,
        MeanInterval(target.q_mean_kgkg,target.q_mean_kgkg,"kg/kg","IMMUTABLE_DAILY_SOURCE"),
        MeanInterval(target.RH_mean_pct,target.RH_mean_pct,"%","IMMUTABLE_DAILY_SOURCE"),
        problem.u,problem.v,phase=problem.base.phase)
    report["strict_outer_bound"]=outer
    strict_status=outer["status"]
    # Fixed-T exact witnesses are cheap and avoid numerical optimization on the
    # majority of already compatible days. Unequal operators use the joint NLP.
    if outer["status"]!="CERTIFIED_INFEASIBLE" and np.array_equal(problem.u,problem.v) and np.all(problem.u>0):
        f=fixed_profile_feasibility(problem.T0,problem.P,target.q_mean_kgkg,target.RH_mean_pct,
                                    problem.base.phase,MK,problem.u,lower_time_limit=0)
        if f["status"]=="FEASIBLE":
            x=problem.base.pack(problem.T0,np.asarray(f["witness_q"]))
            try:problem.validate(x,True,True)
            except ValueError:pass
            else:return finish(x,"FIXED_T_EXACT_WITNESS_PRESERVED","EXACT_VALIDATED")
    def optimize(start,objective,hq,hr,stage):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore",RuntimeWarning)
            sol=minimize(objective,start,jac=True,method="SLSQP",bounds=problem.base.bounds,
                constraints=problem.constraints(hq,hr),
                options={"maxiter":policy.max_iterations,"ftol":1e-11,"disp":False})
        trials.append({"stage":stage,"solver_success":bool(sol.success),"iterations":int(sol.nit),"message":str(sol.message)})
        return sol
    if outer["status"]!="CERTIFIED_INFEASIBLE":
        for x in starts[:policy.strict_starts]:
            sol=optimize(x,problem.shape,True,True,"STRICT_SOURCE_SEARCH")
            try:problem.validate(sol.x,True,True)
            except ValueError:continue
            return finish(sol.x,"STRICT_SEARCH_WITNESS_PRESERVED","EXACT_VALIDATED")
        strict_status="STRICT_SEARCH_UNRESOLVED_COMPATIBILITY_NOT_DISPROVED"
    hq,hr=mode=="HARD_Q_SOFT_RH",mode=="HARD_RH_SOFT_Q"
    capacity=float(problem.u@q_saturation(problem.base.high,problem.P))
    if hq and target.q_mean_kgkg>capacity+1e-9:
        return {**report,"status":"CERTIFIED_HARD_CONSTRAINTS_INFEASIBLE",
                "reason":"HARD_Q_ABOVE_DONOR_T_DOMAIN_CAPACITY","q_capacity_upper":capacity,
                "strict_stage_status":strict_status,"optimizer_trials":trials,"scope":"THIS_DONOR_PRIOR_ONLY"}
    if hr and (problem.base.phase=="WATER" or
               (problem.base.phase=="WATER_ICE" and np.min(problem.base.low)>=273.15)) and target.RH_mean_pct>100+1e-4:
        return {**report,"status":"CERTIFIED_HARD_CONSTRAINTS_INFEASIBLE",
                "reason":"HARD_RH_ABOVE_WATER_SATURATION_BOUND","strict_stage_status":strict_status}
    candidates=[]
    for x in starts[:policy.projection_starts]:
        sol=optimize(x,lambda x:problem.objective(x,metric),hq,hr,"SOFT_SOURCE_PROJECTION")
        try:problem.validate(sol.x,hq,hr)
        except ValueError:continue
        candidates.append((problem.objective(sol.x,metric)[0],sol.x.copy(),len(trials)-1,bool(sol.success)))
    if not candidates:
        return {**report,"status":"UNRESOLVED","reason":"NO_PHYSICALLY_VALID_HARD_CONSTRAINT_WITNESS",
                "strict_stage_status":strict_status,"optimizer_trials":trials,
                "scope":"LOCAL_SEARCH_FAILURE_IS_NOT_INFEASIBILITY"}
    selected=min(candidates,key=lambda x:x[0])
    report["selected_optimizer_trial"]=selected[2]
    report["selected_solver_reported_success"]=selected[3]
    report["local_optimality_status"]="SOLVER_STOPPING_CRITERION_ONLY" if selected[3] else "OPTIMALITY_UNRESOLVED_VALIDATED_FEASIBLE_CANDIDATE"
    return finish(selected[1],"LOCAL_WEIGHTED_PROJECTION_VALIDATED_NOT_GLOBAL",strict_status)
