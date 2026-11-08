"""Explicit liquid-water convention; no clipping or hidden humidity repair."""
import numpy as np
from ige_auto.data import buck_water

EPSILON = 0.621945  # Molecular mass ratio, explicit PsychroLib/ASHRAE convention.


def q_from_e(e, p):
    e,p=np.broadcast_arrays(np.asarray(e,dtype=float),np.asarray(p,dtype=float))
    den=p-(1-EPSILON)*e
    with np.errstate(divide="ignore",invalid="ignore",over="ignore"):
        return np.where((p>0)&(den>0),EPSILON*e/den,np.nan)


def e_from_q(q,p):
    q,p=np.broadcast_arrays(np.asarray(q,dtype=float),np.asarray(p,dtype=float))
    den=EPSILON+(1-EPSILON)*q
    with np.errstate(divide="ignore",invalid="ignore",over="ignore"):
        return np.where((p>0)&(den>0),q*p/den,np.nan)


def dewpoint_water(e):
    """Invert the SAME Buck-water curve only within declared [-80, 50] degC."""
    e=np.asarray(e,dtype=float);lo=np.full(e.shape,-80.);hi=np.full(e.shape,50.)
    valid=np.isfinite(e)&(e>0)&(e>=buck_water(-80.))&(e<=buck_water(50.))
    for _ in range(48):
        mid=(lo+hi)/2;lower=buck_water(mid)<e
        lo=np.where(lower,mid,lo);hi=np.where(lower,hi,mid)
    return np.where(valid,(lo+hi)/2,np.nan)


def restore(coordinate,value,t_pred,p_pred,with_dewpoint=True):
    value=np.asarray(value,dtype=float);es=buck_water(t_pred)
    with np.errstate(over="ignore",invalid="ignore",divide="ignore"):
        if coordinate=="RH":
            rh=value;e=rh*es/100;q=q_from_e(e,p_pred)
        elif coordinate=="log_e":
            e=np.exp(value);rh=100*e/es;q=q_from_e(e,p_pred)
        elif coordinate=="q":
            q=value;e=e_from_q(q,p_pred);rh=100*e/es
        else:
            raise ValueError("Unknown humidity coordinate")
    result={"RH":rh,"e_hPa":e,"q_kgkg":q,
            "supersaturated":np.isfinite(rh)&(rh>100),
            "negative_RH":np.isfinite(rh)&(rh<0),
            "vapour_ge_pressure":np.isfinite(e)&np.isfinite(p_pred)&(e>=p_pred),
            "q_outside_0_1":np.isfinite(q)&((q<0)|(q>=1))}
    if with_dewpoint:result["Td_water"]=dewpoint_water(e)
    return result
