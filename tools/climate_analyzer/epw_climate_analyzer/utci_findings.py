"""R2.9 scientific outdoor thermal-comfort findings shared by UI and atlas.

Calculations use the already evaluated UTCI / MRT states; plotting and reporting
do not re-run the physical model. All percentages identify their denominator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import native_interval_hours
from .chart_theme import EXPOSURE_COLORS

THRESHOLDS = (26.0, 32.0, 38.0)
THRESHOLD_NAMES = ("Above 26 °C · heat stress", "Above 32 °C · strong or greater",
                   "Above 38 °C · very strong or greater")


def exposure_statistics(df: pd.DataFrame, values: pd.DataFrame) -> pd.DataFrame:
    """Valid physical hours, selected-period coverage and UTCI distribution."""
    dt = native_interval_hours(df)
    selected = len(df) * dt
    rows = []
    for name in values:
        x = pd.to_numeric(values[name], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        n = len(x)
        rows.append({
            "Exposure": str(name),
            "Valid hours": n * dt,
            "Period coverage [%]": 100 * n * dt / selected if selected else 0.0,
            "Mean UTCI [°C]": float(x.mean()) if n else np.nan,
            "95th percentile [°C]": float(x.quantile(.95)) if n else np.nan,
            "Hours >32 °C": int((x > 32.).sum()) * dt,
            "Hours >38 °C": int((x > 38.).sum()) * dt,
        })
    return pd.DataFrame(rows)


def paired_exposure_statistics(df: pd.DataFrame, values: pd.DataFrame) -> dict:
    """Common-hour difference and heat-stress threshold crossings."""
    columns = ["Open sun", "Direct-beam shade"]
    if not set(columns).issubset(values):
        raise ValueError("Paired UTCI requires Open sun and Direct-beam shade.")
    paired = values[columns].apply(pd.to_numeric, errors="coerce").replace(
        [np.inf, -np.inf], np.nan).dropna()
    dt = native_interval_hours(df)
    delta = paired["Open sun"] - paired["Direct-beam shade"]
    result = {
        "paired_hours": len(paired) * dt,
        "observed_hours": len(df) * dt,
        "coverage_pct": 100. * len(paired) / len(df) if len(df) else 0.,
        "mean_difference_c": float(delta.mean()) if len(delta) else np.nan,
        "median_difference_c": float(delta.median()) if len(delta) else np.nan,
        "p95_difference_c": float(delta.quantile(.95)) if len(delta) else np.nan,
        "hours_benefit_ge_2k": int((delta >= 2.).sum()) * dt,
        "hours_benefit_ge_5k": int((delta >= 5.).sum()) * dt,
    }
    for t in THRESHOLDS:
        label = int(t)
        result[f"sun_above_{label}_h"] = int((paired["Open sun"] > t).sum()) * dt
        result[f"shade_above_{label}_h"] = int((paired["Direct-beam shade"] > t).sum()) * dt
        result[f"downcross_{label}_h"] = int(((paired["Open sun"] > t) & (paired["Direct-beam shade"] <= t)).sum()) * dt
        result[f"upcross_{label}_h"] = int(((paired["Open sun"] <= t) & (paired["Direct-beam shade"] > t)).sum()) * dt
    result["monthly"] = delta.resample("MS").agg(
        mean="mean", median="median", p95=lambda x: x.quantile(.95),
        count="count",
    ).assign(hours=lambda d: d["count"] * dt)
    return result


def paired_exposure_interpretation(df: pd.DataFrame, values: pd.DataFrame) -> str:
    """Metric-specific seasonal findings suitable for reports and dashboards."""
    x = paired_exposure_statistics(df, values)
    if not x["paired_hours"]:
        return "The selected interval contains no paired UTCI observations for the two radiation scenarios."
    months = x["monthly"].loc[lambda a: a["count"] > 0]
    if len(months):
        peak_month = months["mean"].idxmax().strftime("%B %Y")
        peak = float(months["mean"].max())
        seasonal = f" The greatest monthly mean reduction occurs in {peak_month} ({peak:.2f} K)."
    else:
        seasonal = ""
    return (
        f"Across {x['paired_hours']:,.0f} coincident valid hours "
        f"({x['coverage_pct']:.1f}% of the selected period), suppressing direct-beam "
        f"radiation reduces mean UTCI by {x['mean_difference_c']:.2f} K; the "
        f"95th percentile of hourly reductions is {x['p95_difference_c']:.2f} K. "
        f"Strong-or-greater heat-stress exposure (>32 °C) decreases from "
        f"{x['sun_above_32_h']:,.0f} to {x['shade_above_32_h']:,.0f} hours; "
        f"{x['downcross_32_h']:,.0f} paired hours cross into a lower severity category. "
        f"Very-strong-or-greater heat-stress exposure (>38 °C) decreases from "
        f"{x['sun_above_38_h']:,.0f} to {x['shade_above_38_h']:,.0f} hours."
        + seasonal
        + " The comparison represents direct-beam shielding with the selected "
          "sky, ground and optical assumptions. It informs the seasonal value "
          "of external shade for pedestrian areas, courts and outdoor circulation."
    )


def utci_distribution_interpretation(df: pd.DataFrame, values: pd.DataFrame, exposure: str) -> str:
    """Describe coverage and heat-stress duration for a selected exposure."""
    if exposure not in values:
        raise KeyError(exposure)
    summary = exposure_statistics(df, values[[exposure]]).iloc[0]
    if not summary["Valid hours"]:
        return f"The selected {exposure} scenario contains no valid UTCI observations."
    return (
        f"{exposure}: {summary['Valid hours']:,.0f} physically observed hours "
        f"({summary['Period coverage [%]']:.1f}% coverage); mean UTCI "
        f"{summary['Mean UTCI [°C]']:.2f} °C and 95th percentile "
        f"{summary['95th percentile [°C]']:.2f} °C. "
        f"Strong-or-greater heat stress (>32 °C) occurs during "
        f"{summary['Hours >32 °C']:,.0f} hours; very-strong-or-greater "
        f"heat stress (>38 °C) during {summary['Hours >38 °C']:,.0f} hours. "
        "The distribution shows seasonal outdoor exposure relevant to shade, "
        "wind shelter, circulation placement and occupied outdoor spaces."
    )


def paired_monthly_figure(df: pd.DataFrame, values: pd.DataFrame, *, title: str = "Paired monthly mean UTCI"):
    paired = values[["Open sun", "Direct-beam shade"]].dropna()
    monthly = paired.resample("MS").mean()
    fig = go.Figure()
    for name in ["Direct-beam shade", "Open sun"]:
        fig.add_scatter(x=monthly.index, y=monthly[name], mode="lines+markers", name=name,line_color=EXPOSURE_COLORS[name])
    fig.update_layout(template="plotly_white", title=title, yaxis_title="UTCI [°C]",
                      legend=dict(orientation="h", x=0., y=-.22))
    return fig


def paired_delta_figure(df: pd.DataFrame, values: pd.DataFrame):
    stats = paired_exposure_statistics(df, values)
    monthly = stats["monthly"]
    fig = go.Figure()
    fig.add_bar(x=monthly.index, y=monthly["mean"], name="Mean UTCI reduction",
                customdata=monthly["hours"], marker_color="#D97706",
                hovertemplate="%{x|%B %Y}<br>Mean reduction: %{y:.2f} K<br>Paired: %{customdata:.0f} h<extra></extra>")
    fig.add_scatter(x=monthly.index, y=monthly["p95"], mode="lines+markers",
                    name="95th-percentile hourly reduction", line_color="#9A3412")
    fig.update_layout(template="plotly_white",
                      title="Monthly direct-beam shading effect on UTCI",
                      xaxis_title="Month",yaxis_title="Open sun minus shade [K]",
                      legend=dict(orientation="h",x=0.,y=-.22))
    return fig


def paired_threshold_figure(df: pd.DataFrame, values: pd.DataFrame):
    stats = paired_exposure_statistics(df, values)
    fig = go.Figure()
    labels=list(THRESHOLD_NAMES)
    sun=[stats[f"sun_above_{int(t)}_h"] for t in THRESHOLDS]
    shade=[stats[f"shade_above_{int(t)}_h"] for t in THRESHOLDS]
    fig.add_bar(x=labels,y=sun,name="Open sun",marker_color=EXPOSURE_COLORS["Open sun"])
    fig.add_bar(x=labels,y=shade,name="Direct-beam shade",marker_color=EXPOSURE_COLORS["Direct-beam shade"])
    fig.update_layout(template="plotly_white",barmode="group",
                      title="Paired heat-stress exposure by threshold",
                      xaxis_title="UTCI threshold",yaxis_title="Observed hours",
                      legend=dict(orientation="h",x=0.,y=-.25))
    return fig


def mrt_monthly_figure(tr: pd.DataFrame):
    paired=tr[["Open sun","Direct-beam shade"]].dropna().resample("MS").mean()
    fig=go.Figure()
    for name in ["Direct-beam shade","Open sun"]:
        fig.add_scatter(x=paired.index,y=paired[name],mode="lines+markers",name=name,line_color=EXPOSURE_COLORS[name])
    fig.update_layout(template="plotly_white",title="Mean radiant temperature · sun and beam shade",
                      xaxis_title="Month",yaxis_title="Equivalent MRT [°C]",
                      legend=dict(orientation="h",x=0.,y=-.22))
    return fig


def utci_view_interpretation(df,values,view,*,exposure=None):
    """Canonical narrative for one actual UTCI representation and source scope."""
    from .utci_presentation import STRESS_NOTE
    if view in ("heatmap","stress","duration"):
        columns=list(values) if exposure is None else [exposure]
        note=" ".join(utci_distribution_interpretation(df,values,c) for c in columns)
        method={
            "heatmap":" Each calendar cell presents its mean evaluated UTCI with categorical stress colouring. "+STRESS_NOTE,
            "stress":" Stacked monthly classes partition the valid observed UTCI duration.",
            "duration":" Background shading identifies UTCI stress categories; each selected exposure is independently ranked by evaluated UTCI.",
        }[view]
        return note+method
    extra={
        "utci_pair":" Background bands indicate the thermal-stress classification of the monthly mean UTCI.",
        "utci_pair_delta":" Monthly bars show mean hourly UTCI reduction; the line shows its 95th percentile.",
        "utci_pair_stress":" The thresholds are cumulative: hours above 38 °C also belong to the group above 32 °C.",
        "utci_pair_duration":" Each line is independently ranked across the same set of valid hours.",
        "utci_pair_mrt":" Monthly MRT curves use the paired UTCI evaluation hours and represent the selected shortwave and longwave radiation environments.",
    }
    if view not in extra:raise ValueError("Unknown UTCI view.")
    return paired_exposure_interpretation(df,values)+extra[view]


def utci_sensitivity_inputs(axis,*,temperature=30.,rh=50.,wind=1.,offset=0.):
    """One prescribed grid and parameter definition, independent of presentation."""
    ta=np.arange(-10.,46.);va=np.linspace(.5,17.,34);da=np.arange(-30.,71.,2.)
    if axis in ("Air temperature × radiant offset","Temperature–radiant offset"):
        x,y=ta,da;xx,yy=np.meshgrid(x,y)
        return x,y,(xx,xx+yy,wind,rh),"Air temperature [°C]","Radiant offset [K]"
    if axis in ("Wind speed × radiant offset","Wind–radiant offset"):
        x,y=va,da;xx,yy=np.meshgrid(x,y)
        return x,y,(temperature,temperature+yy,xx,rh),"10 m wind [m/s]","Radiant offset [K]"
    if axis in ("Air temperature × wind speed","Temperature–wind"):
        x,y=ta,va;xx,yy=np.meshgrid(x,y)
        return x,y,(xx,xx+offset,yy,rh),"Air temperature [°C]","10 m wind [m/s]"
    raise ValueError("Unknown UTCI sensitivity axes.")


def utci_sensitivity_interpretation(axis,*,temperature=30.,rh=50.,wind=1.,offset=0.):
    from .utci_presentation import STRESS_NOTE
    if axis in ("Air temperature × radiant offset","Temperature–radiant offset"):
        fixed=f"10 m wind {wind:g} m/s"
    elif axis in ("Wind speed × radiant offset","Wind–radiant offset"):
        fixed=f"air temperature {temperature:g} °C"
    elif axis in ("Air temperature × wind speed","Temperature–wind"):
        fixed=f"mean radiant temperature offset {offset:g} K"
    else:raise ValueError("Unknown UTCI sensitivity axes.")
    return (f"The controlled sensitivity grid compares UTCI across the two displayed environmental variables, "
            f"with relative humidity {rh:g}% and {fixed} held constant. Each cell represents one evaluated model state. "+STRESS_NOTE)
