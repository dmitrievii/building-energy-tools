"""P3 source-neutral thermal and passive-design screening calculations."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .aggregations import native_interval_hours, period_total_series
from .temporal_filtering import display_period_labels,time_basis

T="dry_bulb_temperature_c"
RH="relative_humidity_pct"
W="humidity_ratio_g_kg"
V="wind_speed_m_s"
SV="specific_volume_m3_kg"
DEW="dew_point_temperature_c"
GHI="global_horizontal_radiation_wh_m2"
DHI="diffuse_horizontal_radiation_wh_m2"
DNI="direct_normal_radiation_wh_m2"
LW="horizontal_infrared_radiation_intensity_wh_m2"
ZEN="solar_apparent_zenith_deg"
SIGMA=5.670374419e-8
EDGES=(-40,-27,-13,0,9,26,32,38,46)
CLASSES=("Extreme cold","Very strong cold","Strong cold","Moderate cold","Slight cold","No thermal stress","Moderate heat","Strong heat","Very strong heat","Extreme heat")
COLORS=("#312E81","#4338CA","#2563EB","#60A5FA","#B9D9F3","#8BCB88","#F6D365","#F39A40","#D94738","#8B1A28")

def numeric(df,c):
    if c not in df:
        return pd.Series(np.nan,index=df.index,dtype=float)
    return pd.to_numeric(df[c],errors="coerce").replace([np.inf,-np.inf],np.nan)

def complete(df,*columns):
    return bool(pd.concat([numeric(df,c).notna() for c in columns],axis=1).all(axis=1).any())

def utci_values(t,tr,v,rh):
    """Published UTCI polynomial via pinned library; reject out-of-range inputs."""
    from pythermalcomfort.models import utci
    t,tr,v,rh=np.broadcast_arrays(*[np.asarray(x,dtype=float) for x in (t,tr,v,rh)])
    good=np.isfinite(t)&np.isfinite(tr)&np.isfinite(v)&np.isfinite(rh)&(rh>=0)&(rh<=100)&(v>=.5)&(v<=17)&(t>=-50)&(t<=50)&(tr-t>=-30)&(tr-t<=70)
    out=np.full(t.shape,np.nan)
    if good.any():
        out[good]=utci(tdb=t[good],tr=tr[good],v=v[good],rh=rh[good],limit_inputs=True,round_output=False).utci
    return out

def radiant_scenarios(df,*,albedo=.2,absorptivity=.7,emissivity=.95,projected_factor=.25,ground_delta=0.):
    """Spherical-equivalent radiation screening, not a human-shaped site model.
    Shade removes beam only; isotropic sky/ground diffuse and LW unchanged.
    Ground assumed blackbody at Ta+offset. All input energies are interval Wh/m².
    """
    if not (0<=albedo<=1 and 0<=absorptivity<=1 and 0<emissivity<=1 and 0<=projected_factor<=1):
        raise ValueError("Invalid optical coefficients.")
    dt=native_interval_hours(df)
    t=numeric(df,T);g=numeric(df,GHI)/dt;d=numeric(df,DHI)/dt
    n=numeric(df,DNI)/dt;lw=numeric(df,LW)/dt;z=numeric(df,ZEN)
    valid=(t+ground_delta>-273.15)&g.ge(0)&d.ge(0)&n.ge(0)&lw.gt(0)&z.between(0,180)
    base=.5*(lw+SIGMA*(t+ground_delta+273.15)**4)+(absorptivity/emissivity)*.5*(d+albedo*g)
    beam=(absorptivity/emissivity)*projected_factor*n.where(z<90,0.)
    return pd.DataFrame({"Direct-beam shade":((base/SIGMA)**.25-273.15).where(valid),
                         "Open sun":(((base+beam)/SIGMA)**.25-273.15).where(valid)},index=df.index)

def utci_frame(df,*,model="Uniform radiant offset",offset=0.,wind_factor=1.,**radiation):
    if not np.isfinite(wind_factor) or wind_factor<=0:
        raise ValueError("Wind factor must be positive.")
    t=numeric(df,T);rh=numeric(df,RH);v=numeric(df,V)*wind_factor
    if model=="Uniform radiant offset":
        tr=pd.DataFrame({"Uniform radiant offset":t+offset},index=df.index)
    elif model=="Open-sky screening":
        tr=radiant_scenarios(df,**radiation)
    else:
        raise ValueError("Unknown radiation scenario.")
    out=pd.DataFrame({c:utci_values(t,tr[c],v,rh) for c in tr},index=df.index)
    out.attrs.update(df.attrs)
    return out,tr

def monthly_totals(df,ledger):
    out=pd.DataFrame({c:period_total_series(ledger[c],df,"Monthly") for c in ledger})
    out.index=display_period_labels(out.index,"Monthly",time_basis(df))
    return out

def utci_class_hours(df,values):
    bins=pd.cut(values,[-np.inf,*EDGES,np.inf],labels=CLASSES,right=True)
    dt=native_interval_hours(df)
    return monthly_totals(df,pd.DataFrame({c:bins.eq(c).astype(float).where(values.notna())*dt for c in CLASSES}))

def ventilation_loads(df,*,airflow,heat,cool,w_low,w_high):
    """Actual outdoor volume flow; dry-air mass; separate positive interval kWh."""
    if not np.isfinite([airflow,heat,cool,w_low,w_high]).all() or airflow<0 or heat>cool or not 0<=w_low<=w_high:
        raise ValueError("Invalid airflow or target deadbands.")
    t=numeric(df,T);w=numeric(df,W)/1000;sv=numeric(df,SV)
    m=(airflow/3600/sv).where(t.notna()&w.ge(0)&sv.gt(0))
    cp=1.006+1.86*w
    dt=native_interval_hours(df)
    return pd.DataFrame({"Sensible heating":m*cp*(heat-t).clip(lower=0)*dt,
        "Sensible cooling":m*cp*(t-cool).clip(lower=0)*dt,
        "Latent humidification":m*2501*(w_low/1000-w).clip(lower=0)*dt,
        "Latent dehumidification":m*2501*(w-w_high/1000).clip(lower=0)*dt},index=df.index)

def moisture_loads(df,*,airflow,target):
    if not np.isfinite([airflow,target]).all() or airflow<0 or target<0:
        raise ValueError("Invalid flow or target.")
    w=numeric(df,W);sv=numeric(df,SV)
    m=(airflow/sv).where(w.ge(0)&sv.gt(0))*native_interval_hours(df)
    return pd.DataFrame({"Humidification":m*(target-w).clip(lower=0)/1000,
                         "Dehumidification":m*(w-target).clip(lower=0)/1000},index=df.index)

def condensation_margin(df,surface_c):
    return surface_c-numeric(df,DEW)

def full_daily_temperature(df):
    t=numeric(df,T).sort_index()
    dt=native_interval_hours(df)
    daily=t.resample("D").mean()
    observed=t.resample("D").count()*dt
    expected=pd.Series([(d+pd.DateOffset(days=1)-d).total_seconds()/3600 for d in daily.index],index=daily.index)
    return daily.where(np.isclose(observed,expected,atol=1e-8,rtol=0))

def adaptive_bands(df):
    """Seven previous complete daily means; normalized alpha=.8; no lookahead.
    EN 16798-1 screening on 10..30 C only; not indoor compliance.
    """
    daily=full_daily_temperature(df)
    weights=.8**np.arange(7);weights/=weights.sum()
    previous=pd.concat([daily.shift(i+1) for i in range(7)],axis=1)
    rm=previous.mul(weights,axis=1).sum(axis=1,min_count=7)
    neutral=(.33*rm+18.8).where(rm.between(10,30))
    out=pd.DataFrame({"Running mean":rm,"Neutral":neutral})
    for cat,up,lo in (("I",2,3),("II",3,4),("III",4,5)):
        out[cat+" lower"]=neutral-lo
        out[cat+" upper"]=neutral+up
    return out

def attach_adaptive(df):
    if df.empty:return df
    bands=adaptive_bands(df).reindex(pd.DatetimeIndex(df.index).normalize())
    out=df.copy()
    for c in bands:
        out["p3_adaptive_"+c]=bands[c].to_numpy()
    out.attrs.update(df.attrs)
    return out

def eligibility_mask(df,mask,*,wind=False):
    valid=numeric(df,T).notna()&numeric(df,W).ge(0)
    if wind:valid&=numeric(df,V).ge(0)
    return mask.astype(float).where(valid)

def suitability_grid(df,mask,*,axis):
    x=numeric(df,T);y=numeric(df,axis).where(numeric(df,axis).ge(0))
    sy=1. if axis==W else .5
    raw=pd.DataFrame({"x":np.floor(x/2)*2+1,"y":np.floor(y/sy)*sy+sy/2,
                      "suitable":mask.astype(float)},index=df.index).dropna()
    if raw.empty:return pd.DataFrame(),pd.DataFrame()
    g=raw.groupby(["y","x"]).suitable.agg(["mean","count"])
    # Fixed-width bins must retain empty intervening cells; otherwise Plotly
    # stretches adjacent occupied cells across unobserved temperature/wind.
    nx=int(round((raw.x.max()-raw.x.min())/2))+1
    ny=int(round((raw.y.max()-raw.y.min())/sy))+1
    if nx*ny>200000 or nx>2000 or ny>2000:
        raise ValueError("Observed ranges are too large for a fixed-bin suitability grid. Inspect source data quality.")
    xs=raw.x.min()+2*np.arange(nx)
    ys=raw.y.min()+sy*np.arange(ny)
    return g["mean"].unstack().reindex(index=ys,columns=xs)*100,g["count"].unstack().reindex(index=ys,columns=xs)*native_interval_hours(df)

def persistence(df,mask,*,night=False,end_hour=6):
    """Longest uninterrupted eligible run per date or night-start date."""
    dt=native_interval_hours(df);idx=pd.DatetimeIndex(df.index)
    if not idx.is_monotonic_increasing or idx.has_duplicates:
        raise ValueError("Persistence requires sorted unique timestamps.")
    days=idx.normalize()
    if night:days=days.where(idx.hour>end_hour,days-pd.DateOffset(days=1))
    records={};previous=None;last_day=None;run=0.
    for stamp,day,ok,known in zip(idx,days,mask.fillna(False).astype(bool),mask.notna()):
        row=records.setdefault(day,[0.,0.,0.])
        if known:row[2]+=dt
        if not ok:run=0.
        else:
            if previous is None or day!=last_day or stamp-previous!=pd.Timedelta(hours=dt):run=0.
            run+=dt;row[0]=max(row[0],run);row[1]+=dt
        previous=stamp;last_day=day
    out=pd.DataFrame.from_dict(records,orient="index",columns=["Longest run [h]","Suitable hours [h]","Valid hours [h]"])
    out.loc[out["Valid hours [h]"]==0,["Longest run [h]","Suitable hours [h]"]]=np.nan
    return out

def persistence_monthly(table,threshold):
    """Count observed days/nights meeting a minimum uninterrupted duration.

    A day with at least one known state is represented; an all-unknown day is
    excluded. Partial days count as observed only, never as complete days.
    """
    if not np.isfinite(threshold) or threshold<=0:
        raise ValueError("Minimum continuous duration must be positive.")
    run=table["Longest run [h]"]
    valid=run.notna()
    met=run.ge(threshold)&valid
    counts=pd.DataFrame({"Meets minimum":met.astype(int),
                         "Below minimum":(valid&~met).astype(int),
                         "Observed days":valid.astype(int)},index=table.index)
    return counts.resample("MS").sum().where(counts.resample("MS")["Observed days"].sum().gt(0),axis=0)


def annual_hour_grid(df,values):
    idx=pd.DatetimeIndex(df.index)
    raw=pd.DataFrame({"day":idx.normalize(),"hour":idx.hour,"value":np.asarray(values,dtype=float)})
    grid=raw.groupby(["hour","day"]).value.mean().unstack()
    days=pd.date_range(pd.Timestamp(year=idx[0].year,month=1,day=1,tz=idx.tz),pd.Timestamp(year=idx[0].year,month=12,day=31,tz=idx.tz),freq="D")
    return grid.reindex(index=range(24),columns=days)
