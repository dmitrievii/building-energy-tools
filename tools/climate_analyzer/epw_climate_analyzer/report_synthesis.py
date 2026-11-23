"""R2.11 source-bound, low-memory cross-chapter report synthesis.

Computed from the selected observations at capture time. Both HTML and PDF
consume this same small frozen evidence record, keeping saved-source scopes
distinct after the active climate changes.
"""
from __future__ import annotations

import math
import pandas as pd

from .aggregations import native_interval_hours

T="dry_bulb_temperature_c"
W="humidity_ratio_g_kg"
V="wind_speed_m_s"
G="global_horizontal_radiation_wh_m2"
P="liquid_precipitation_depth_mm"
H="moist_air_enthalpy_kj_kg"


def _numeric(df,column):
    if column not in df:
        return pd.Series(float("nan"),index=df.index)
    return pd.to_numeric(df[column],errors="coerce").replace(
        [float("inf"),-float("inf")],float("nan"),
    )


def cross_chapter_synthesis(df):
    """Return compact observed metrics and affirmative, quantified design findings.

    No model is inferred when required columns or native hourly resolution are
    absent. Every duration uses the declared source cadence.
    """
    if df is None or df.empty:
        return {"rows":[],"interpretation":""}
    dt=native_interval_hours(df)
    n=len(df)
    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
    rows=[]
    findings=[]
    def add(name,value,valid):
        rows.append([str(name),str(value),f"{int(valid):,} / {n:,}"])
    t=_numeric(df,T)
    if t.notna().any():
        add("Outdoor temperature",f"Mean {t.mean():.1f} °C; {t.min():.1f} to {t.max():.1f} °C",t.count())
        if not monthly:
            cold=int(t.lt(18).sum())*dt
            warm=int(t.gt(26).sum())*dt
            add("Temperature screening","Below 18 °C: "+f"{cold:,.1f} h; above 26 °C: {warm:,.1f} h",t.count())
            if cold>warm:
                findings.append(f"{cold:,.0f} observed hours have outdoor air below 18 °C, compared with {warm:,.0f} above 26 °C. The climatic frequency favours evaluating supply-air heat recovery and seasonal heating control.")
            elif warm>cold:
                findings.append(f"{warm:,.0f} observed hours have outdoor air above 26 °C, compared with {cold:,.0f} below 18 °C. The climatic frequency favours evaluating solar protection, cooling operation and summer air movement.")
            else:
                findings.append(f"Outdoor conditions spend {cold:,.0f} hours below 18 °C and {warm:,.0f} hours above 26 °C across the selected records.")
    w=_numeric(df,W)
    if w.ge(0).any():
        valid=w.where(w.ge(0))
        add("Outdoor humidity ratio",f"Mean {valid.mean():.1f} g/kg dry air",valid.count())
        if not monthly:
            damp=float(valid.gt(10).sum())*dt
            add("Moisture screening",f"Above 10 g/kg: {damp:,.1f} h",valid.count())
            if damp:
                findings.append(f"Outdoor humidity ratio exceeds 10 g/kg for {damp:,.0f} observed hours. This identifies periods relevant to supply-air moisture treatment and condensation control.")
    v=_numeric(df,V).where(lambda x:x.ge(0))
    if v.notna().any():
        add("Observed wind speed",f"Mean {v.mean():.2f} m/s",v.count())
    g=_numeric(df,G).where(lambda x:x.ge(0))
    if g.notna().any():
        add("Horizontal irradiation",f"{g.sum()/1000:,.1f} kWh/m² selected-period total",g.count())
    p=_numeric(df,P).where(lambda x:x.ge(0))
    if p.notna().any():
        add("Precipitation",f"{p.sum():,.1f} mm selected-period total",p.count())
    if not monthly and t.notna().any() and w.ge(0).any():
        valid=t.notna()&w.ge(0)
        eligible=t.between(16,26)&w.between(0,9)
        hours=float(eligible.sum())*dt
        add("Outdoor-air ventilation screen",f"{hours:,.1f} h (16–26 °C, ≤9 g/kg)",valid.sum())
        findings.append(f"The reference outdoor-air ventilation screen admits {hours:,.0f} hours under the stated temperature and moisture conditions. Operable-opening schedules can be compared against this seasonal window.")
    h=_numeric(df,H)
    if not monthly and t.notna().any() and h.notna().any():
        valid=t.notna()&h.notna()
        eligible=t.between(5,24)&h.lt(50)
        hours=float(eligible.sum())*dt
        add("Economizer weather screen",f"{hours:,.1f} h (5–24 °C, enthalpy <50 kJ/kg)",valid.sum())
    if g.notna().any() and p.notna().any():
        findings.append("Solar irradiation and precipitation provide complementary evidence for façade shading, exposed circulation, drainage and weather-protected outdoor space.")
    return {"rows":rows,"interpretation":"\n\n".join(findings[:5]),
            "observed_records":n,"interval_hours":dt,"basis":"Monthly" if monthly else "Source subdaily"}


def synthesis_rows(context):
    synth=context.get("cross-chapter synthesis",{})
    return synth.get("rows",[]) if isinstance(synth,dict) else []


def synthesis_interpretation(context):
    synth=context.get("cross-chapter synthesis",{})
    return str(synth.get("interpretation","")) if isinstance(synth,dict) else ""
