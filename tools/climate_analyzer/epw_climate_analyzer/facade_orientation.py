"""Façade orientation chart data and interchangeable Cartesian/polar views.

Every surface is evaluated by the existing source-neutral POA kernel. The
chart controls select presentation components only; the physical calculation,
input mask, time period and albedo are common to both chart styles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .chart_theme import ORIENTATION_COLORS, POA_COMPONENT_COLORS

ORIENTATIONS = (
    ("North", "N", 0.0), ("North-East", "NE", 45.0),
    ("East", "E", 90.0), ("South-East", "SE", 135.0),
    ("South", "S", 180.0), ("South-West", "SW", 225.0),
    ("West", "W", 270.0), ("North-West", "NW", 315.0),
)
COMPONENTS = (
    ("direct_kwh_m2", "Direct", POA_COMPONENT_COLORS["poa_direct_wh_m2"], "poa_direct_wh_m2"),
    ("sky_diffuse_kwh_m2", "Sky diffuse", POA_COMPONENT_COLORS["poa_sky_diffuse_wh_m2"], "poa_sky_diffuse_wh_m2"),
    ("ground_reflected_kwh_m2", "Ground-reflected", POA_COMPONENT_COLORS["poa_ground_diffuse_wh_m2"], "poa_ground_diffuse_wh_m2"),
)
TOTAL = "total_kwh_m2"


def surface_period_summary(df, tilt_deg: float, azimuth_deg: float, *, albedo=None):
    from .runtime_module_guard import ensure_current_solar_runtime

    poa = ensure_current_solar_runtime().surface_irradiance_components(
        df, tilt_deg, azimuth_deg, albedo=albedo,
    )
    sums = poa.sum(min_count=1) / 1000.0
    result = {key: float(sums[source]) for key, _, _, source in COMPONENTS}
    result[TOTAL] = float(sums["poa_global_wh_m2"])
    result["valid_intervals"] = int(poa["poa_global_wh_m2"].notna().sum())
    result["selected_intervals"] = len(df)
    return result


def orientation_period_components(df, tilt_deg: float = 90.0, *, albedo=None):
    """Eight directional sums and an independent horizontal reference.

    NaN is preserved when no complete coincident source interval is available.
    The flat-roof value uses the identical POA kernel at zero tilt, not a
    separately substituted GHI sum.
    """
    rows = []
    for name, short, azimuth in ORIENTATIONS:
        rows.append({"orientation": name, "direction": short, "azimuth_deg": azimuth,
                     **surface_period_summary(df, tilt_deg, azimuth, albedo=albedo)})
    flat = surface_period_summary(df, 0.0, 0.0, albedo=albedo)
    return pd.DataFrame(rows), flat


def _segments(data, selected):
    selected = set(selected)
    active = [(key, label, color) for key, label, color, _ in COMPONENTS if key in selected]
    return active or [(TOTAL, "Total POA", [ORIENTATION_COLORS[name.lower()]
                                             for name in data["orientation"]])]


def _label_values(values):
    return [f"{v:,.0f}" if np.isfinite(v) else "" for v in values]


def _axis_upper(data):
    finite = pd.to_numeric(data[TOTAL], errors="coerce").dropna()
    return max(1.0, float(finite.max()) * 1.22) if not finite.empty else 1.0


def _flat_label(flat):
    value = float(flat[TOTAL])
    return f"{value:,.0f}" if np.isfinite(value) else "No data"


def orientation_components_chart(data: pd.DataFrame, flat: dict, *, tilt_deg: float,
                                 style: str = "Bar chart", selected=()) -> go.Figure:
    """Plot the total or selected additive components, without double counting.

    Total POA is never stacked alongside its components. Both chart styles use
    the same values and a stable range based on the complete directional totals.
    """
    segments = _segments(data, selected)
    decomposed = any(key != TOTAL for key, _, _ in segments)
    total = data[TOTAL].to_numpy(dtype=float)
    shown = data[[key for key, _, _ in segments]].sum(axis=1, min_count=len(segments)).to_numpy(dtype=float)
    upper = _axis_upper(data)
    title = f"Irradiation by orientation · tilt {tilt_deg:g}°"
    fig = go.Figure()
    if style not in {"Bar chart", "Solar rose"}:
        raise ValueError(f"Unknown façade chart style: {style}")
    for key, label, color in segments:
        common = dict(
            name=label, marker=dict(color=color, line=dict(color="white", width=1)),
            customdata=np.column_stack((data["orientation"], total)),
            showlegend=decomposed,
        )
        if style == "Solar rose":
            fig.add_trace(go.Barpolar(
                theta=data["azimuth_deg"], r=data[key], width=40,
                hovertemplate="%{customdata[0]}<br>" + label +
                    ": %{r:,.1f} kWh/m²<br>Total POA: %{customdata[1]:,.1f} kWh/m²<extra></extra>",
                **common,
            ))
        else:
            fig.add_trace(go.Bar(
                x=data["direction"], y=data[key],
                hovertemplate="%{customdata[0]}<br>" + label +
                    ": %{y:,.1f} kWh/m²<br>Total POA: %{customdata[1]:,.1f} kWh/m²<extra></extra>",
                **common,
            ))
    if style == "Solar rose":
        # The polar hole has zero data radius at its inner edge. The roof
        # reference occupies the hole, never changes or offsets the bar values.
        fig.add_trace(go.Scatterpolar(
            theta=data["azimuth_deg"], r=np.where(np.isfinite(shown), shown + upper * .055, np.nan),
            text=_label_values(shown), mode="text", textfont=dict(color="#263444"),
            name="Displayed irradiation labels", showlegend=False, hoverinfo="skip",
        ))
        fig.update_layout(
            polar=dict(hole=0.26, barmode="stack", bgcolor="#FFFFFF",
                radialaxis=dict(range=[0, upper], angle=90, gridcolor="#D9E0E7",
                    linecolor="#D9E0E7", tickformat=",.0f"),
                angularaxis=dict(direction="clockwise", rotation=90, tickmode="array",
                    tickvals=[row[2] for row in ORIENTATIONS],
                    ticktext=[row[1] for row in ORIENTATIONS], gridcolor="#E5E9EE")),
            height=760, margin=dict(l=65,r=65,t=85,b=90),
        )
        fig.add_annotation(x=0.5,y=0.5,xref="paper",yref="paper",showarrow=False,
            text=f"Flat roof<br><b>{_flat_label(flat)}</b><br>kWh/m²",
            align="center", bgcolor="#F4E7C6", bordercolor="#D6BB7C", borderpad=6)
    else:
        fig.add_trace(go.Scatter(
            x=data["direction"], y=np.where(np.isfinite(shown), shown+upper*.035,np.nan),
            mode="text", text=_label_values(shown), textfont=dict(color="#263444"),
            showlegend=False, hoverinfo="skip", name="Displayed irradiation labels",
        ))
        fig.update_layout(barmode="stack", height=560, margin=dict(l=75,r=30,t=85,b=80),
            xaxis=dict(title="Surface orientation", categoryorder="array",
                       categoryarray=[row[1] for row in ORIENTATIONS]),
            yaxis=dict(title="Irradiation [kWh/m²]", range=[0,upper], gridcolor="#E5E9EE"))
    fig.update_layout(template="plotly_white", title=title,
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.10),
        meta={"unit":"kWh/m²", "tilt_deg":float(tilt_deg),
              "compass_polar": style == "Solar rose",
              "displayed_components":[key for key,_,_ in segments],
              "flat_roof_total_kwh_m2": float(flat[TOTAL]) if np.isfinite(flat[TOTAL]) else None})
    return fig
