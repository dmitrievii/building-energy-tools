"""Historical same-source climate anomalies, R2.21 D.

Monthly state means and extensive totals have distinct aggregation semantics.
A reference uses equal-weighted valid year-month aggregates; annual reference
statistics use complete annual aggregates. No TMY/calendar pooling, temporal
gap filling, or extrapolation. P05/P95 describe empirical interannual spread.
"""
from __future__ import annotations
from dataclasses import dataclass
import calendar
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours

MIN_REFERENCE_YEARS=3
MIN_ENVELOPE_YEARS=5
MAX_YEARS=150
VIEWS=("Monthly anomaly bars","Reference envelope","Year × month anomaly heat map","Annual anomaly series")

@dataclass(frozen=True)
class Quantity:
    label:str
    unit:str
    anomaly_unit:str
    total:bool=False
    scale:float=1.
    nonnegative:bool=False

QUANTITIES={
    "dry_bulb_temperature_c":Quantity("Dry-bulb temperature","°C","K"),
    "dew_point_temperature_c":Quantity("Dew-point temperature","°C","K"),
    "relative_humidity_pct":Quantity("Relative humidity","%","percentage points",nonnegative=True),
    "humidity_ratio_g_kg":Quantity("Humidity ratio","g/kg dry air","g/kg dry air",nonnegative=True),
    "wind_speed_m_s":Quantity("Wind speed","m/s","m/s",nonnegative=True),
    "liquid_precipitation_depth_mm":Quantity("Liquid precipitation","mm","mm",True,1.,True),
    "global_horizontal_radiation_wh_m2":Quantity("Global horizontal irradiation","kWh/m²","kWh/m²",True,.001,True),
    "direct_normal_radiation_wh_m2":Quantity("Direct normal irradiation","kWh/m²","kWh/m²",True,.001,True),
    "diffuse_horizontal_radiation_wh_m2":Quantity("Diffuse horizontal irradiation","kWh/m²","kWh/m²",True,.001,True),
    "sunshine_duration_s":Quantity("Sunshine duration","h","h",True,1/3600.,True),
}

def is_historical(df):
    return isinstance(df.index,pd.DatetimeIndex) and df.attrs.get("canonical_calendar_mode")=="historical" and not df.attrs.get("typical_year") and not df.attrs.get("anomaly_generated_source")

def available(df):
    if not is_historical(df):return []
    return [c for c in QUANTITIES if c in df and pd.to_numeric(df[c],errors="coerce").notna().any()]

def monthly_values(df,column):
    if not is_historical(df):raise ValueError("A real historical observation archive is required.")
    if df.empty or df.index.has_duplicates:raise ValueError("Historical observations must have unique timestamps.")
    if int(df.index.year.max())-int(df.index.year.min())+1>MAX_YEARS:raise ValueError("Select at most 150 calendar years.")
    q=QUANTITIES[column]
    if column not in df:raise ValueError("The selected source quantity is unavailable.")
    s=pd.to_numeric(df[column],errors="coerce").astype(float).sort_index()
    s=s.where(np.isfinite(s))
    if q.nonnegative:s=s.where(s>=0)
    if column=="relative_humidity_pct":s=s.where(s<=100)
    s=s*q.scale
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    idx=s.index
    key=pd.MultiIndex.from_arrays([idx.year,idx.month],names=["year","month"])
    g=s.groupby(key)
    # Construct explicit full month coordinates, including wholly absent months.
    years=range(int(idx.year.min()),int(idx.year.max())+1)
    all_months=pd.MultiIndex.from_product([years,range(1,13)],names=["year","month"])
    n=g.count().reindex(all_months,fill_value=0)
    rows=g.size().reindex(all_months,fill_value=0)
    if monthly:
        if (rows>1).any():raise ValueError("Multiple native records represent one calendar month.")
        value=g.first().reindex(all_months)
        expected=pd.Series(1.,index=all_months)
        # Native monthly state means use calendar-day weights for annual means.
        weights=pd.Series([calendar.monthrange(y,m)[1]*24. for y,m in all_months],index=all_months)
        observed=n.astype(float)
    else:
        dt=native_interval_hours(df)
        if not np.isfinite(dt) or not 0<dt<=1:raise ValueError("Historical anomalies require hourly/finer or native monthly records.")
        weights=pd.Series([(pd.Timestamp(year=y,month=m,day=1,tz=idx.tz)+pd.DateOffset(months=1)-pd.Timestamp(year=y,month=m,day=1,tz=idx.tz)).total_seconds()/3600 for y,m in all_months],index=all_months)
        expected=weights
        observed=n.astype(float)*dt
        # Reject malformed cadence, including duplicated interval slots.
        delta=np.diff(idx.as_unit('ns').asi8)
        native_ns=int(round(dt*3600*1e9))
        if np.any(delta % native_ns !=0):raise ValueError("Irregular source cadence; normalize observations before anomaly analysis.")
        value=(g.sum(min_count=1) if q.total else g.mean()).reindex(all_months)
    complete=pd.Series(np.isclose(observed,expected,rtol=0,atol=1e-7),index=all_months)
    return pd.DataFrame({"value":value.where(complete),"coverage":observed/expected,
                         "weight_hours":weights,"complete":complete},index=all_months)

def annual_values(monthly,column):
    q=QUANTITIES[column]
    m=monthly["value"]
    complete=m.notna().groupby(level="year").sum().eq(12)
    if q.total:values=m.groupby(level="year").sum(min_count=12)
    else:
        w=monthly["weight_hours"]
        values=(m*w).groupby(level="year").sum(min_count=12)/w.groupby(level="year").sum()
    return values.where(complete)

def _reference_stats(samples):
    n=samples.count()
    return pd.DataFrame({"mean":samples.mean().where(n>=MIN_REFERENCE_YEARS),
                         "median":samples.median().where(n>=MIN_REFERENCE_YEARS),
                         "p05":samples.quantile(.05).where(n>=MIN_ENVELOPE_YEARS),
                         "p95":samples.quantile(.95).where(n>=MIN_ENVELOPE_YEARS),
                         "n":n})

def analyze(target,reference,column,start,end):
    """Same-source target and unfiltered reference, admitted independently."""
    if start>end or end-start+1<MIN_REFERENCE_YEARS:
        raise ValueError("Select a reference interval spanning at least three years.")
    if not is_historical(target) or not is_historical(reference):
        raise ValueError("Historical observations are required on both sides.")
    # The caller supplies one loaded archive and its filtered view. Guard
    # calendar, timezone and cadence contracts; never combine unlike climates.
    if str(target.index.tz)!=str(reference.index.tz):
        raise ValueError("Target and reference analysis clocks must match.")
    if target.attrs.get("canonical_native_resolution")!=reference.attrs.get("canonical_native_resolution"):
        raise ValueError("Target and reference source resolutions must match.")
    if column not in target or column not in reference or reference.index.has_duplicates or target.index.has_duplicates:
        raise ValueError("The historical quantity requires unique target and reference records.")
    if not target.index.isin(reference.index).all():
        raise ValueError("The target must be a filtered view of the same loaded archive.")
    if not np.array_equal(pd.to_numeric(target[column],errors="coerce").to_numpy(dtype=float),
                          pd.to_numeric(reference[column].reindex(target.index),errors="coerce").to_numpy(dtype=float),equal_nan=True):
        raise ValueError("Target and reference observations must come from the same loaded archive.")
    if str(reference.attrs.get("canonical_native_resolution","")).lower()!="monthly" and not np.isclose(native_interval_hours(target),native_interval_hours(reference)):
        raise ValueError("Target and reference native intervals must match.")
    if start<int(reference.index.year.min()) or end>int(reference.index.year.max()):
        raise ValueError("The reference interval must lie within the loaded archive.")
    a=monthly_values(target,column);r=monthly_values(reference,column)
    r=r.loc[(r.index.get_level_values("year")>=start)&(r.index.get_level_values("year")<=end)]
    ref=_reference_stats(r.value.unstack("month").reindex(columns=range(1,13)))
    if not ref["mean"].notna().any():raise ValueError("No reference month has at least three valid annual samples.")
    target_month=a.value.unstack("month").reindex(columns=range(1,13))
    anomalies=target_month.subtract(ref["mean"],axis=1)
    target_annual=annual_values(a,column);ra=annual_values(r,column).dropna()
    annual_ref=float(ra.mean()) if len(ra)>=MIN_REFERENCE_YEARS else np.nan
    return dict(monthly=target_month,anomalies=anomalies,reference=ref,annual=target_annual,
                annual_anomalies=target_annual-annual_ref,annual_reference=annual_ref,
                annual_n=len(ra),coverage=a.coverage.unstack("month"),
                native_monthly=str(reference.attrs.get("canonical_native_resolution","")).lower()=="monthly")

def figure(target,reference,column,start,end,view,*,year=None,relative=False):
    if view not in VIEWS:raise ValueError("Unknown anomaly representation.")
    q=QUANTITIES[column];a=analyze(target,reference,column,start,end)
    ref=a["reference"];an=a["anomalies"];unit=q.anomaly_unit
    if relative:
        if not q.total or view=="Reference envelope":raise ValueError("Relative anomalies are available for extensive totals only.")
        an=an.divide(ref["mean"].where(ref["mean"]>0),axis=1)*100
        unit="%"
    years=list(a["monthly"].index)
    if year is None:year=int(target.index.year.max())
    if year not in years:raise ValueError("Selected target year is outside the filtered observation period.")
    months=[calendar.month_abbr[m] for m in range(1,13)]
    f=go.Figure()
    def bars(x,s):
        f.add_bar(x=x,y=s,marker_color=["#C94D40" if v>0 else "#3979B7" if v<0 else "#999999" for v in s.fillna(0)],showlegend=False)
        f.add_hline(y=0,line_color="#666666",line_width=1)
    if view==VIEWS[0]:
        s=an.loc[year]
        if not s.notna().any():raise ValueError("No comparable complete target months in the selected year.")
        bars(months,s);f.update_layout(xaxis_title="Month",yaxis_title=f"Anomaly [{unit}]")
        note=f"In {year}, {s.notna().sum()} months have comparable values. The largest positive or negative departure by magnitude is {s.loc[s.abs().idxmax()]:+.2f} {unit} in {calendar.month_name[s.abs().idxmax()]}."
    elif view==VIEWS[1]:
        s=a["monthly"].loc[year].where(ref["mean"].notna())
        if not s.notna().any():raise ValueError("No comparable complete target months in the selected year.")
        # Separate contiguous reference-band segments so filled polygons
        # never bridge a calendar month without sufficient reference years.
        valid=np.flatnonzero(ref.p05.notna().to_numpy()&ref.p95.notna().to_numpy())
        groups=np.split(valid,np.where(np.diff(valid)>1)[0]+1) if len(valid) else []
        for i,g in enumerate(groups):
            xx=[months[k] for k in g]
            if len(g)==1:
                lo,hi=float(ref.p05.iloc[g[0]]),float(ref.p95.iloc[g[0]])
                f.add_scatter(x=xx*2,y=[lo,hi],mode="lines+markers",line_color="#94A3B8",name="Reference P05–P95",showlegend=i==0,legendgroup="reference_band")
            else:
                f.add_scatter(x=xx,y=ref.p95.iloc[g],mode="lines",line_width=0,showlegend=False,connectgaps=False,legendgroup="reference_band")
                f.add_scatter(x=xx,y=ref.p05.iloc[g],mode="lines",line_width=0,fill="tonexty",fillcolor="rgba(100,116,139,.23)",name="Reference P05–P95",showlegend=i==0,legendgroup="reference_band",connectgaps=False)
        f.add_scatter(x=months,y=ref["median"],mode="lines+markers",line=dict(color="#64748B",dash="dash"),name="Reference median",connectgaps=False)
        f.add_scatter(x=months,y=ref["mean"],mode="lines",line=dict(color="#303030",dash="dot"),name="Reference mean",connectgaps=False)
        f.add_scatter(x=months,y=s,mode="lines+markers",line_color="#C94D40",name=str(year),connectgaps=False)
        f.update_layout(xaxis_title="Month",yaxis_title=f"{q.label} [{q.unit}]")
        note=f"The {year} monthly observations are compared with reference-year means and medians. {int(ref.p05.notna().sum())} calendar months support empirical P05–P95 bands."
    elif view==VIEWS[2]:
        z=an.to_numpy(dtype=float)
        if not np.isfinite(z).any():raise ValueError("No comparable target months.")
        limit=max(1e-9,float(np.nanmax(np.abs(z))))
        f.add_heatmap(x=months,y=[str(v) for v in an.index],z=z,zmin=-limit,zmax=limit,zmid=0,
                      colorscale=[[0,"#2865A8"],[.5,"#F7F7F7"],[1,"#C54736"]],
                      colorbar=dict(title=f"Anomaly [{unit}]"),hoverongaps=False,
                      meta={"heatmap_semantics":"categorical","heatmap_quantity":"interannual anomalies"})
        f.update_layout(xaxis_title="Month",yaxis_title="Year",plot_bgcolor="#D1D5DB",
                        height=max(450,min(1100,24*len(an)+150)))
        note=f"The matrix contains {np.isfinite(z).sum()} comparable year–month departures across {len(an)} calendar years. Grey cells lack comparable complete observations or an admitted reference."
    else:
        s=a["annual_anomalies"]
        if relative:s=s/a["annual_reference"]*100 if a["annual_reference"]>0 else s*np.nan
        if not s.notna().any():raise ValueError("Annual anomalies require 12 valid months in each target year and at least three complete reference years.")
        bars([str(v) for v in s.index],s);f.update_layout(xaxis_title="Year",yaxis_title=f"Annual anomaly [{unit}]")
        note=f"{s.notna().sum()} complete target years are compared with {a['annual_n']} complete reference years. Annual departures span {s.min():+.2f} to {s.max():+.2f} {unit}."
    f.update_layout(template="plotly_white",title=f"{q.label} · {view.lower()} · reference {start}–{end}",
                    meta={"layout_kind":"climate_anomaly","reference_start":int(start),"reference_end":int(end),
                          "quantity":column,"reference_sample_counts":ref.n.astype(int).tolist(),
                          "annual_reference_years":int(a["annual_n"])})
    note+=f" Reference interval: {start}–{end}; monthly departures use the arithmetic mean of valid reference-year monthly values. At least {MIN_REFERENCE_YEARS} reference samples per month are required."
    note+=" Provider-native monthly values retain their published semantics." if a["native_monthly"] else " Hourly months require full valid observation coverage, including leap days and the analysis clock."
    if view==VIEWS[1]:note+=f" P05–P95 describes interannual variation, with at least {MIN_ENVELOPE_YEARS} valid reference years per month."
    if relative:note+=" Relative departure is 100 × (target − reference)/reference for positive reference totals."
    if end-start+1<30:note+=" This is a selected short-period reference climatology."
    else:note+=" Reference sample counts are retained for each calendar month; the selected interval does not by itself establish a certified standard climatological normal."
    if view==VIEWS[3]:note+=" Annual departures use the mean of complete annual reference aggregates; state means are weighted by calendar duration and totals are summed."
    note+=" Target years within the reference interval contribute to that reference."
    return f,note,a
