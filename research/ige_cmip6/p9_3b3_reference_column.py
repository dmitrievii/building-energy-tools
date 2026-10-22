"""P2 hybrid columns and pressure transfer, without observational calibration.

Full-level geopotential follows the published ECMWF alpha construction; pressure
at a specified geopotential instead integrates the positive layer Tv exactly.
The arithmetic full-level p and ECMWF layer-mean geopotential are NOT silently
treated as an exact hydrostatic point pair. Condensate loading is excluded.
"""
from __future__ import annotations

from dataclasses import asdict,dataclass
import datetime as dt
import math

import numpy as np

from p9_3b3_compare_vertical_frame import G0,SourceBlocked,VerticalCoordinate,fingerprint
from p9_3b3_thermodynamics import RD,RV


GASES={"B3_GAS_CONSISTENT":(RD,RV/RD-1),
       "ECMWF_PUBLISHED_APPROXIMATION":(287.06,.609133)}


@dataclass(frozen=True)
class HybridColumn:
    timestamp_UTC: str
    latitude: float
    longitude: float
    first_level: int
    gas: str
    half_pressure_Pa: tuple
    integration_half_pressure_Pa: tuple
    half_geopotential_m2s2: tuple
    full_pressure_Pa: tuple
    full_geopotential_ECMWF_alpha_m2s2: tuple
    temperature_K: tuple
    specific_humidity_kgkg: tuple
    source: str
    source_sha256: str

    @property
    def fingerprint(self):return fingerprint(asdict(self))

    @property
    def domain(self):return self.half_geopotential_m2s2[-1],self.half_geopotential_m2s2[0]

    def layer(self,phi):
        if not math.isfinite(phi) or not self.domain[0]<=phi<=self.domain[1]:
            raise SourceBlocked("P93REF_OUTSIDE_AIR_COLUMN_NO_UNDERGROUND_OR_TOP_EXTRAPOLATION")
        return min(len(self.temperature_K)-1,max(0,
            int(np.searchsorted(-np.array(self.half_geopotential_m2s2),-phi,side="right")-1)))

    def state(self,phi):
        j=self.layer(phi)
        return self.temperature_K[j],self.specific_humidity_kgkg[j]

    def log_pressure(self,phi):
        j=self.layer(phi);rd,c=GASES[self.gas]
        tv=self.temperature_K[j]*(1+c*self.specific_humidity_kgkg[j])
        return math.log(self.integration_half_pressure_Pa[j+1])-(phi-self.half_geopotential_m2s2[j+1])/(rd*tv)


def hybrid_column(lnsp,surface_phi,T,q,A,B,*,first_level,timestamp_UTC,latitude,longitude,
                  source,source_sha256,gas="B3_GAS_CONSISTENT"):
    """Consecutive complete bottom levels ending at 137, with source GRIB pv."""
    parsed=dt.datetime.fromisoformat(timestamp_UTC.replace("Z","+00:00"))
    if parsed.utcoffset() is not None and parsed.utcoffset()!=dt.timedelta(0):
        raise ValueError("P93REF_TIMESTAMP_MUST_BE_UTC")
    if gas not in GASES or type(first_level) is not int or not 1<=first_level<=137:
        raise ValueError("P93REF_GAS_OR_FIRST_LEVEL")
    t,z,a,b=(np.asarray(x,float) for x in (T,q,A,B))
    n=138-first_level
    if t.shape!=(n,) or z.shape!=(n,) or a.shape!=(138,) or b.shape!=(138,):
        raise ValueError("P93REF_MISSING_OR_NONCONTIGUOUS_BOTTOM_LEVELS")
    if (not np.isfinite(np.r_[t,z,a,b,lnsp,surface_phi,latitude,longitude]).all() or
            np.any(t<=100) or np.any(t>=360) or np.any(z<0) or np.any(z>=.1) or
            np.any(a<0) or np.any(b<0) or np.any(b>1) or a[0]!=0 or b[0]!=0 or a[-1]!=0 or b[-1]!=1 or
            not -90<=latitude<=90 or not 0<=longitude<360 or not -20000<surface_phi<100000):
        raise ValueError("P93REF_INPUT_DOMAIN")
    if not source or len(source_sha256)!=64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("P93REF_SOURCE_PROVENANCE_REQUIRED")
    if not math.log(30000)<lnsp<math.log(115000):raise ValueError("P93REF_SURFACE_PRESSURE_PA_DOMAIN")
    all_p=a+b*math.exp(lnsp)
    if np.any(np.diff(all_p)<=0):raise ValueError("P93REF_HYBRID_PRESSURE_ORDER")
    p=all_p[first_level-1:].copy();ip=p.copy()
    if first_level==1:ip[0]=.1  # published finite top integration convention
    rd,c=GASES[gas];tv=t*(1+c*z)
    phi=np.empty(n+1);phi[-1]=surface_phi;full=np.empty(n)
    for i in range(n-1,-1,-1):
        ratio=(ip[i+1]-ip[i])/ip[i]
        dlog=math.log1p(ratio)
        alpha=(math.log(2) if first_level+i==1 else
            ratio/2-ratio**2/3+ratio**3/4-ratio**4/5 if ratio<1e-4 else 1-dlog/ratio)
        full[i]=phi[i+1]+rd*tv[i]*alpha
        phi[i]=phi[i+1]+rd*tv[i]*dlog
    if not np.isfinite(phi).all() or np.any(np.diff(phi)>=0):raise ValueError("P93REF_NONMONOTONIC_COLUMN")
    return HybridColumn(timestamp_UTC,float(latitude),float(longitude),first_level,gas,
        tuple(p),tuple(ip),tuple(phi),tuple((p[:-1]+p[1:])/2),tuple(full),tuple(t),tuple(z),source,source_sha256)


def target_geopotential(target,*,allow_constant_g_geometric=False):
    if not isinstance(target,VerticalCoordinate) or not target.verified:
        raise SourceBlocked("P93REF_VERIFIED_SOURCE_COORDINATE_REQUIRED")
    if target.kind=="GEOPOTENTIAL_M2_S2" and target.datum in ("GEOPOTENTIAL_ZERO","MSL_GEOID"):
        return target.value,"SOURCE_GEOPOTENTIAL"
    if target.kind=="GEOPOTENTIAL_HEIGHT_M" and target.datum in ("GEOPOTENTIAL_ZERO","MSL_GEOID"):
        return G0*target.value,"SOURCE_GEOPOTENTIAL_HEIGHT"
    if target.kind=="GEOMETRIC_M" and target.datum=="MSL_GEOID" and allow_constant_g_geometric:
        return G0*target.value,"DECLARED_CONSTANT_G_HEIGHT_APPROXIMATION_NOT_DATUM_TRANSFORMATION"
    raise SourceBlocked("P93REF_GEOMETRIC_OR_DATUM_ADAPTER_NOT_ESTABLISHED")


def transfer_pressure(columns,distances_km,target,*,timestamp_UTC,allow_ground_diagnostic=False,
                      allow_constant_g_geometric=False):
    """Blend T/q on a common AIR interval and integrate from ONE log-p anchor.

    Source-only suitability filtering is based on geometry, never station p,
    RH error, or closure success. Under-ground extrapolation is forbidden.
    """
    if not isinstance(target,VerticalCoordinate):raise SourceBlocked("P93REF_TYPED_TARGET_COORDINATE_REQUIRED")
    if target.role not in ("BAROMETER","THERMO_SENSOR"):
        if target.role!="STATION_GROUND" or not allow_ground_diagnostic:
            raise SourceBlocked("P93REF_TARGET_MUST_BE_SENSOR_NOT_GROUND")
    if not 1<=len(columns)<=4 or len(columns)!=len(distances_km):
        raise ValueError("P93REF_ONE_TO_FOUR_ALIGNED_COLUMNS_REQUIRED")
    if any(c.timestamp_UTC!=timestamp_UTC for c in columns):raise ValueError("P93REF_PROFILE_TIME_MISMATCH")
    if len({c.gas for c in columns})!=1:raise ValueError("P93REF_MIXED_GAS_FORMULATIONS")
    if len({(c.latitude,c.longitude) for c in columns})!=len(columns):raise ValueError("P93REF_DUPLICATE_COLUMN")
    if any(not math.isfinite(d) or d<0 for d in distances_km):raise ValueError("P93REF_DISTANCE_DOMAIN")
    phi,approx=target_geopotential(target,allow_constant_g_geometric=allow_constant_g_geometric)
    eligible=[(c,d) for c,d in zip(columns,distances_km) if c.domain[0]<=phi<=c.domain[1]]
    if not eligible:raise SourceBlocked("P93REF_NO_COLUMN_AIR_DOMAIN_COVERS_TARGET")
    cs,dist=zip(*eligible)
    exact=[i for i,d in enumerate(dist) if d==0]
    weights=np.zeros(len(cs))
    if exact:weights[exact[0]]=1
    else:
        # Scaling avoids overflow for very small positive distances.
        weights=np.array([(min(dist)/d)**2 for d in dist]);weights/=weights.sum()
    active=[(c,float(w)) for c,w in zip(cs,weights) if w>0]
    lo=max(c.domain[0] for c,w in active);hi=min(c.domain[1] for c,w in active)
    if not lo<=phi<=hi:raise SourceBlocked("P93REF_NO_COMMON_AIR_INTERVAL")
    anchor=sum(w*c.log_pressure(hi) for c,w in active)
    boundaries=sorted({phi,hi,*[x for c,w in active for x in c.half_geopotential_m2s2 if phi<x<hi]})
    rd,coef=GASES[cs[0].gas];integral=0.;segments=[]
    for lower,upper in zip(boundaries,boundaries[1:]):
        values=[(c.state((lower+upper)/2),w) for c,w in active]
        t=sum(state[0]*w for state,w in values);q=sum(state[1]*w for state,w in values)
        tv=t*(1+coef*q)
        delta=(upper-lower)/(rd*tv);integral+=delta
        segments.append({"lower_phi":lower,"upper_phi":upper,"T_K":t,"q_kgkg":q,"delta_log_p":delta})
    result=math.exp(anchor+integral)
    if not 30000<result<115000:raise SourceBlocked("P93REF_TARGET_PRESSURE_OUTSIDE_TERRESTRIAL_DOMAIN")
    target_T=(segments[0]['T_K'] if segments else sum(w*c.state(phi)[0] for c,w in active))
    target_q=(segments[0]['q_kgkg'] if segments else sum(w*c.state(phi)[1] for c,w in active))
    return {"pressure_Pa":result,"timestamp_UTC":timestamp_UTC,"target":asdict(target),
        "target_layer_T_K":target_T,"target_layer_q_kgkg":target_q,
        "target_state_support":"AIR_SIDE_PIECEWISE_CONSTANT_LAYER_NOT_A_2M_OBSERVATION_OPERATOR",
        "water_saturation_admissibility":"NOT_CHECKED_BY_VERTICAL_TRANSFER",
        "height_approximation":approx,"target_phi_m2s2":phi,"common_air_interval_m2s2":[lo,hi],
        "eligible_columns":len(eligible),"rejected_columns":len(columns)-len(eligible),
        "active_columns":[{"latitude":c.latitude,"longitude":c.longitude,"weight":w,"fingerprint":c.fingerprint} for c,w in active],
        "gas_formulation":cs[0].gas,"anchor_phi_m2s2":hi,"anchor_log_pressure":anchor,
        "integrated_log_pressure_increment":integral,"segments":segments,
        "physical_scope":"PIECEWISE_CONSTANT_LAYER_T_Q_HYDROSTATIC_GAS_NO_CONDENSATE",
        "surface_layer_status":"LOWEST_MODEL_LAYER_CONSTANT_EXTENSION_NOT_2M_SIMILARITY_ADAPTER",
        "target_role":"GROUND_SENSITIVITY_NOT_SENSOR" if target.role=="STATION_GROUND" else target.role,
        "sensor_height_history_qualified":False,"independent_accuracy":"NOT_TESTED",
        "pressure_model_qualified":False,"production_epw_ready":False,"operational_ready":False,
        "B4_negative_result_retained":True}
