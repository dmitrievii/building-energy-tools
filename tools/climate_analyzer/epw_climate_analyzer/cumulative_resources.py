"""Calendar-year cumulative profiles of physically additive observed contributions.

Monthly steps are summed from native interval contributions; no averaging of
year totals, gap filling, or annualization. Each year starts from zero and
retains separate coverage. A gap does not erase the preceding observed total.
"""
from __future__ import annotations
import calendar
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .aggregations import native_interval_hours
from .chart_theme import metric_color, series_color
from .residual_findings import TOTAL_FIELDS, _numeric

def _monthly_source(df):
    return str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"

def _admit(df):
    if df.empty or not isinstance(df.index,pd.DatetimeIndex) or df.index.has_duplicates:
        raise ValueError("A nonempty source with unique dated observations is required.")
    if _monthly_source(df):return None
    dt=native_interval_hours(df)
    if not np.isfinite(dt) or not 0<dt<=1:raise ValueError("Hourly/finer or native monthly records are required.")
    return dt

def monthly_accumulation(df,values):
    """Sum observed contributions, retain missing months and expected coverage."""
    dt=_admit(df)
    if not values.index.equals(df.index):raise ValueError("Contribution timestamps must match source observations.")
    v=pd.to_numeric(values,errors="coerce").replace([np.inf,-np.inf],np.nan)
    years=sorted(set(df.index.year))
    if len(years)>150:raise ValueError("Select at most 150 calendar years.")
    key=pd.MultiIndex.from_arrays([v.index.year,v.index.month],names=["year","month"])
    grid=pd.MultiIndex.from_product([years,range(1,13)],names=["year","month"])
    g=v.groupby(key)
    counts=g.count().reindex(grid,fill_value=0)
    if dt is None:
        if (g.size()>1).any():raise ValueError("Duplicate native monthly records.")
        coverage=counts.astype(float)
    else:
        expected=[]
        for y,m in grid:
            start=pd.Timestamp(year=y,month=m,day=1,tz=v.index.tz)
            expected.append((start+pd.DateOffset(months=1)-start).total_seconds()/3600)
        coverage=counts*dt/np.asarray(expected)
    totals=g.sum(min_count=1).reindex(grid)
    cumulative=totals.groupby(level="year").cumsum(skipna=True)
    return pd.DataFrame({"monthly":totals,"cumulative":cumulative,"coverage":coverage},index=grid)

def profile_figure(df,contributions,*,title,unit,detail="",colors=None):
    """One trace per quantity/year. A partial-month marker flags incomplete scope."""
    f=go.Figure()
    months=list(calendar.month_abbr)[1:]
    tables={}
    for label,values in contributions.items():
        table=monthly_accumulation(df,values)
        if table.monthly.notna().any():tables[label]=table
    if not tables:raise ValueError("No valid observed contributions remain.")
    years=sorted(set(df.index.year))
    summaries=[]
    for label,table in tables.items():
        for year in years:
            t=table.loc[year]
            if not t.monthly.notna().any():continue
            name=label if len(years)==1 else f"{label} · {year}"
            color=(colors or {}).get(label,metric_color(label)) if len(years)==1 else series_color(name,title)
            complete=np.isclose(t.coverage,1.,atol=1e-8,rtol=0)
            custom=[[int(year),float(m) if pd.notna(m) else None,float(c)*100] for m,c in zip(t.monthly,t.coverage)]
            f.add_scatter(x=months,y=t.cumulative,mode="lines+markers",name=name,
                connectgaps=False,line=dict(color=color),marker=dict(color=color,size=6,
                    symbol=["circle" if ok else "circle-open" for ok in complete]),
                customdata=custom,hovertemplate="%{customdata[0]} · %{x}<br>Accumulated: %{y:,.2f} "+unit+
                "<br>Monthly contribution: %{customdata[1]:,.2f}<br>Calendar coverage: %{customdata[2]:.1f}%<extra></extra>")
            summaries.append((name,float(t.monthly.sum()),int(t.monthly.notna().sum()),int(complete.sum())))
    f.update_layout(title=title,template="plotly_white",xaxis_title="Calendar month",
        yaxis_title=f"Cumulative observed contribution [{unit}]",legend=dict(orientation="h",y=-.2),
        meta={"layout_kind":"cumulative_resource","source_scope":"observed year-to-date"})
    low=min(summaries,key=lambda a:a[1]);high=max(summaries,key=lambda a:a[1])
    note=(f"Each curve accumulates the observed monthly contributions within its own calendar year, resetting at January. "
          f"The final observed totals range from {low[1]:,.2f} {unit} ({low[0]}) to {high[1]:,.2f} {unit} ({high[0]}). "
          "Missing months appear as gaps; open markers identify partially covered months. "
          "Later cumulative values retain earlier observed contributions, while excluded or missing observations contribute no estimated amount. "
          "A partial-year curve describes the selected observation scope. ")
    if _monthly_source(df):note+="Native monthly coverage counts published valid monthly records. "
    if detail:note+=detail
    return f,note

def extensive_profile(df,column):
    label,unit,factor=TOTAL_FIELDS[column]
    v=_numeric(df,column).where(lambda x:x>=0)
    dt=_admit(df)
    if dt is not None and column in ("precipitation_duration_min","sunshine_duration_s"):
        v=v.where(v<=dt*(60 if column=="precipitation_duration_min" else 3600)+1e-6)
    return profile_figure(df,{label:v*factor},title=f"{label} · cumulative annual profile",unit=unit,
        colors={label:metric_color(column)},detail="Source interval totals are summed in their physical units.")

def degree_profile(df,*,heating_indoor_c=20.,heating_limit_c=12.,cooling_indoor_c=26.,cooling_limit_c=26.):
    from .degree_metrics import _validate_parameters,_degree_contributions
    dt=_admit(df)
    if dt is None:raise ValueError("Degree-hours require hourly or finer source observations.")
    args=dict(heating_indoor_c=heating_indoor_c,heating_limit_c=heating_limit_c,
              cooling_indoor_c=cooling_indoor_c,cooling_limit_c=cooling_limit_c)
    _validate_parameters(**args)
    t=_numeric(df,"dry_bulb_temperature_c")
    h,c=_degree_contributions(t,**args)
    return profile_figure(df,{"Heating degree-hours (HGT)":h*dt,"Cooling degree-hours (KGT)":c*dt},
        title=f"Cumulative degree-hours · HGT {heating_indoor_c:g}/{heating_limit_c:g}; KGT {cooling_indoor_c:g}/{cooling_limit_c:g}",
        unit="K·h",detail="The existing two-temperature HGT/KGT selection and signed differences are retained; KGT may decrease when the cooling limit lies below the indoor reference.")

def ventilation_profile(df,*,fixed=None):
    from .decisions import natural_ventilation_condition
    from .p3_comfort import eligibility_mask
    dt=_admit(df)
    if dt is None:raise ValueError("Ventilation suitability requires hourly or finer source observations.")
    args=dict(fixed or {})
    wind=args.get("wind_min_m_s") is not None or args.get("wind_max_m_s") is not None
    mask=natural_ventilation_condition(df,**args)
    v=eligibility_mask(df,mask,wind=wind)*dt
    return profile_figure(df,{"Natural ventilation suitable hours":v},title="Natural ventilation · cumulative suitable hours",
        unit="h",detail=f"Active screen: outdoor temperature {args.get('t_min_c',16.):g}–{args.get('t_max_c',26.):g} °C, humidity ratio ≤ {args.get('d_max_g_kg',9.):g} g/kg; active wind and occupancy conditions remain in the eligibility mask.")
