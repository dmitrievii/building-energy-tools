"""Pressure-conditioned joint T/q solve with explicit source operators.

Only new P9.3B3 modules are used. Legacy weather solvers remain immutable.
Pressure is never a free optimizer variable. Local failure means UNRESOLVED.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import warnings
import numpy as np
from scipy.optimize import minimize

from p9_3b3_daily_feasibility import (fixed_profile_feasibility, weights_for,
                                    bounded_mean_profile, RH_TOL)
from p9_3b3_thermodynamics import (MK, epsilon_for, saturation, q_saturation,
                                  qsat_derivative, relative_humidity, state_diagnostics)
from p9_3b3_state_validation import validate_state


@dataclass(frozen=True)
class SolverPolicy:
    formulation: str = MK
    max_temperature_change_K: float = 2.
    minimum_slope_K_per_hour: float = 6.
    max_iterations: int = 180
    lower_bound_seconds: float = 5.
    quadrature: str = "REPRESENTATIVE_NODES_NOT_HOURLY_MEANS"

    def __post_init__(self):
        if (self.formulation not in (MK, "BUCK_WATER_LEGACY") or
                self.max_temperature_change_K != 2. or self.minimum_slope_K_per_hour != 6. or
                not 1 <= self.max_iterations <= 180 or not 0 <= self.lower_bound_seconds <= 5):
            raise ValueError("P93B3_UNREGISTERED_SOLVER_POLICY")

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def affine_temperature(donor_T_K, target):
    t = np.asarray(donor_T_K, float)
    if t.ndim != 1 or not len(t) or not np.all(np.isfinite(t)):
        raise ValueError("P93B3_INVALID_DONOR_TEMPERATURE")
    if target.Tmax_K == target.Tmin_K:
        return np.full(len(t), target.Tmin_K)
    if np.ptp(t) < 1e-12:
        raise ValueError("P93B3_FLAT_DONOR_CANNOT_SUPPLY_NONFLAT_EXTREMA")
    return target.Tmin_K + (target.Tmax_K-target.Tmin_K) * (t-t.min())/np.ptp(t)


class JointProblem:
    """Shared constrained problem; x=[free T in K, all q in g/kg]."""

    def __init__(self, donor_T, donor_q, target, pressure, weights=None, policy=None):
        self.target, self.pressure = target, pressure
        self.policy = policy or SolverPolicy()
        self.T0 = affine_temperature(donor_T, target)
        self.P = np.asarray(pressure.values_Pa)
        self.q0 = np.asarray(donor_q, float)
        n = len(self.T0)
        self.n = n
        self.w = weights_for(n, weights)
        if (self.P.shape != (n,) or self.q0.shape != (n,) or not np.all(np.isfinite(self.q0))
                or np.any(self.q0 < 0) or np.any(self.q0 >= 1)):
            raise ValueError("P93B3_DONOR_STATE_ALIGNMENT")
        if pressure.mode == "OBSERVED_SITE_VALIDATION_ONLY":
            raise ValueError("P93B3_OBSERVATIONS_FORBIDDEN_IN_GENERATION")
        self.phase = target.semantics.rh_phase
        if self.phase == "UNKNOWN":
            raise ValueError("P93B3_SOURCE_PHASE_UNKNOWN")
        if self.policy.formulation == "BUCK_WATER_LEGACY" and self.phase != "WATER":
            raise ValueError("P93B3_BUCK_PHASE_MISMATCH")
        self.low = np.maximum(target.Tmin_K, self.T0-2.)
        self.high = np.minimum(target.Tmax_K, self.T0+2.)
        self.extrema = {int(np.argmin(self.T0)), int(np.argmax(self.T0))}
        if target.Tmin_K == target.Tmax_K:
            self.extrema = set(range(n))
        for i in self.extrema:
            self.low[i] = self.high[i] = self.T0[i]
        self.free = np.asarray([i for i in range(n) if i not in self.extrema], int)
        self.k = len(self.free)
        self.slope = max(6., float(np.max(np.abs(np.diff(self.T0)))*n/24) if n > 1 else 6.)
        self.sq = max(1e-9, float(np.sqrt(self.w @ self.q0**2)))
        self.bounds = list(zip(self.low[self.free], self.high[self.free])) + [
            (0., float(v)*1000) for v in q_saturation(self.high, self.P, self.policy.formulation)]
        caps = q_saturation(self.T0, self.P, self.policy.formulation)
        qstart = bounded_mean_profile(self.q0, caps, min(target.q_mean_kgkg, float(self.w@caps)), self.w)
        self.x0 = self.pack(self.T0, qstart)

    def pack(self, T, q):
        return np.r_[np.asarray(T)[self.free], np.asarray(q)*1000]

    def unpack(self, x):
        t = self.T0.copy()
        t[self.free] = x[:self.k]
        return t, np.asarray(x[self.k:])/1000

    def humidity(self, x):
        t, q = self.unpack(x)
        r = relative_humidity(t, self.P, q, self.phase, self.policy.formulation)
        a = 100 * self.P / saturation(t, self.phase, self.policy.formulation)
        eps = epsilon_for(self.policy.formulation)
        dq = a*eps/(eps+(1-eps)*q)**2/1000
        dt = -r*saturation(t, self.phase, self.policy.formulation, True)/saturation(t, self.phase, self.policy.formulation)
        jac = np.r_[(self.w*dt)[self.free], self.w*dq]
        return float(self.w @ r), jac

    def shape(self, x):
        t, q = self.unpack(x)
        a, b = (t-self.T0)/2, (q-self.q0)/self.sq
        value = np.dot(a,a)+np.dot(b,b)+.25*(np.dot(np.diff(a),np.diff(a))+np.dot(np.diff(b),np.diff(b)))
        def smooth_grad(v):
            out = 2*v.copy()
            d = np.diff(v)
            out[:-1] -= .5*d
            out[1:] += .5*d
            return out
        grad = np.r_[smooth_grad(a)[self.free]/2, smooth_grad(b)/self.sq/1000]
        return float(value), grad

    def constraints(self, Q=None, RH=None):
        cons = []
        def cap(x):
            t,q = self.unpack(x)
            return 1000*(q_saturation(t,self.P,self.policy.formulation)-q)
        def cap_jac(x):
            t,_ = self.unpack(x)
            j = np.zeros((self.n,self.k+self.n))
            j[self.free, np.arange(self.k)] = 1000*qsat_derivative(t,self.P,self.policy.formulation)[self.free]
            j[:,self.k:] = -np.eye(self.n)
            return j
        cons.append({"type":"ineq", "fun":cap, "jac":cap_jac})
        if self.n > 1:
            a = np.zeros((self.n-1,self.k+self.n))
            for col,i in enumerate(self.free):
                if i > 0: a[i-1,col] += self.n/24
                if i < self.n-1: a[i,col] -= self.n/24
            def slope(x):
                t,_=self.unpack(x)
                d=np.diff(t)*self.n/24
                return np.r_[self.slope-d,self.slope+d]
            cons.append({"type":"ineq","fun":slope,"jac":lambda x:np.vstack([-a,a])})
        if self.target.semantics.temperature_operator == "TIME_MEAN_TAS":
            j = np.r_[self.w[self.free], np.zeros(self.n)]
            cons.append({"type":"eq", "fun":lambda x:float(self.w@self.unpack(x)[0]-self.target.tas_K), "jac":lambda x,j=j:j})
        if Q is not None:
            j = np.r_[np.zeros(self.k),self.w]
            cons.append({"type":"eq","fun":lambda x:float(self.w@x[self.k:]-Q*1000),"jac":lambda x,j=j:j})
        if RH is not None:
            cons.append({"type":"eq","fun":lambda x:(self.humidity(x)[0]-RH)/100,
                         "jac":lambda x:self.humidity(x)[1]/100})
        return cons

    def optimize(self, objective=None, Q=None, RH=None, start=None):
        fun = objective or self.shape
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sol = minimize(fun, self.x0 if start is None else start, jac=True, method="SLSQP",
                           bounds=self.bounds, constraints=self.constraints(Q,RH),
                           options={"maxiter":self.policy.max_iterations,"ftol":1e-11,"disp":False})
        return sol

    def validate_profile(self, T):
        if np.any(T < self.low-1e-7) or np.any(T > self.high+1e-7):
            raise ValueError("P93B3_T_BOUND_EXCEEDED")
        if len(T)>1 and np.any(np.abs(np.diff(T))*self.n/24 > self.slope+1e-7):
            raise ValueError("P93B3_SLOPE_BOUND_EXCEEDED")

    def package(self, T, q, strict=True):
        self.validate_profile(T)
        valid = validate_state(T.tolist(), self.P.tolist(), q.tolist(), self.target,
                               self.w.tolist(), self.policy.formulation, strict)
        return {"T_K":T.tolist(),"p_Pa":self.P.tolist(),"q_kgkg":q.tolist(),
                "weights":self.w.tolist(),"validation":valid,
                "diagnostics":state_diagnostics(T,self.P,q,self.phase,self.policy.formulation),
                "pressure_reference":self.pressure.metadata(),"policy_sha256":self.policy.fingerprint,
                "quadrature":self.policy.quadrature,"source_modified":not strict,
                "source_semantics":asdict(self.target.semantics),
                "pressure_model_qualified":False,"operational_ready":False,"production_epw_ready":False}


def solve_day(donor_T, donor_q, target, pressure, weights=None, policy=None):
    if target.semantics.rh_phase == "UNKNOWN":
        return {"status":"SOURCE_BLOCKED","reason":"SOURCE_PHASE_UNKNOWN","date":target.date}
    problem = JointProblem(donor_T,donor_q,target,pressure,weights,policy)
    base = {"date":target.date,"source_modified":False,"pressure_model_qualified":False,
            "production_epw_ready":False,"operational_ready":False}
    fixed = fixed_profile_feasibility(problem.T0,problem.P,target.q_mean_kgkg,target.RH_mean_pct,
        problem.phase,problem.policy.formulation,problem.w,problem.policy.lower_bound_seconds)
    if fixed["status"] == "FEASIBLE":
        try:
            output=problem.package(problem.T0,np.asarray(fixed["witness_q"]))
            return {**base,**output,"status":"EXACT_DEFINED_OPERATORS",
                    "method":"FIXED_PROFILE_Q_RH_WITNESS","fixed_profile_diagnosis":fixed}
        except ValueError:
            # E.g. TIME_MEAN_TAS: affine profile is not the prescribed mean.
            pass
    upper = float(problem.w @ q_saturation(problem.high,problem.P,problem.policy.formulation))
    if np.all(problem.low == problem.high) and fixed["status"] == "CERTIFIED_INFEASIBLE":
        return {**base,"status":"CERTIFIED_INFEASIBLE","reason":fixed["reason"],
                "certificate":{**fixed,"scope":"FULL_DECLARED_T_DOMAIN_IS_FIXED"}}
    if target.q_mean_kgkg > upper + 1e-12:
        return {**base,"status":"CERTIFIED_INFEASIBLE","reason":"Q_ABOVE_MONOTONE_BOX_CAPACITY_UPPER",
                "certificate":{"domain":"DECLARED_T_BOUNDS_FIXED_P_RELAXING_SLOPE_AND_MEAN",
                    "upper_q_mean":upper,"source_q_mean":target.q_mean_kgkg,
                    "scope":"THIS_DONOR_AND_POLICY_ONLY","pressure_fingerprint":pressure.fingerprint},
                "fixed_profile_diagnosis":fixed}
    starts=[problem.x0]
    if "witness_q" in fixed:
        starts.append(problem.pack(problem.T0,np.asarray(fixed["witness_q"])))
    else:
        # Deterministic second start, never selected from station errors.
        t=(problem.low+problem.high)/2
        c=q_saturation(t,problem.P,problem.policy.formulation)
        starts.append(problem.pack(t,bounded_mean_profile(problem.q0,c,min(target.q_mean_kgkg,float(problem.w@c)),problem.w)))
    trials=[]
    for start in starts[:2]:
        sol=problem.optimize(Q=target.q_mean_kgkg,RH=target.RH_mean_pct,start=start)
        trials.append({"success":bool(sol.success),"iterations":int(sol.nit),"message":str(sol.message)})
        t,q=problem.unpack(sol.x)
        # Numerical validity is independently checked even if optimizer status is false.
        try:
            output=problem.package(t,q)
        except ValueError:
            continue
        return {**base,**output,"status":"EXACT_DEFINED_OPERATORS","method":"JOINT_T_Q_SLSQP_VALIDATED",
                "optimizer_trials":trials,"fixed_profile_diagnosis":fixed,
                "global_shape_optimum_certified":False}
    return {**base,"status":"UNRESOLVED","reason":"LOCAL_JOINT_SOLVER_DID_NOT_ESTABLISH_FEASIBILITY",
            "optimizer_trials":trials,"fixed_profile_diagnosis":fixed,
            "certificate":{"scope":"NO_GLOBAL_INFEASIBILITY_CLAIM","box_capacity_upper_q":upper}}
