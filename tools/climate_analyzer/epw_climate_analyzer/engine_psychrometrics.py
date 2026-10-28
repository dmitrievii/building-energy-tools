"""Liquid-water T/w view: original state points and labelled isobaric guides."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .engine_analysis import T, RH, P, Q, STATION_UI_CONTRACT
from .engine.thermodynamics import EPSILON, saturation_water_pa


def station_psychrometric_figure(data, reference_pressure_pa: float):
    if (data.empty or not np.isfinite(reference_pressure_pa) or not 31000 <= reference_pressure_pa <= 120000
            or data.attrs.get("ige_ui_analysis", {}).get("station_year_contract") != STATION_UI_CONTRACT):
        raise ValueError("IGE_A15_ANALYSED_STATION_STATES_AND_REFERENCE_PRESSURE_REQUIRED")
    t = data[T].to_numpy(dtype=float); q = data[Q].to_numpy(dtype=float)
    # Reference lines have their own declared constant pressure. Point values
    # always retain the original per-hour q/p/RH, even above an ice boundary.
    grid = np.linspace(max(-70., float(t.min())-2), min(58., float(t.max())+2), 160)
    sat = saturation_water_pa(grid)
    figure = go.Figure()
    for rh in (20, 40, 60, 80, 100):
        e = rh/100 * sat
        if np.any(e >= reference_pressure_pa):
            raise ValueError("IGE_A15_GUIDE_VAPOUR_EXCEEDS_REFERENCE_PRESSURE")
        w = 1000 * EPSILON * e/(reference_pressure_pa-e)
        figure.add_trace(go.Scatter(x=grid, y=w, mode="lines", name=f"{rh}% RH water guide",
            line={"width": 1, "color": "#a3adb8"}, hoverinfo="skip"))
    figure.add_trace(go.Scattergl(x=t, y=1000*q/(1-q), mode="markers", name="Saved hourly states",
        marker={"size": 4, "color": data[RH], "colorscale": "Viridis", "cmin": 0, "cmax": 100,
            "opacity": .55, "colorbar": {"title": "RH water [%]"}},
        customdata=np.column_stack([data[P], data[RH], 1000*q, data.index.astype(str).to_numpy(dtype=object)]),
        hovertemplate="%{customdata[3]}<br>T %{x:.2f} °C<br>w %{y:.3f} g/kg dry air<br>"
            "q %{customdata[2]:.3f} g/kg moist air<br>RH water %{customdata[1]:.2f}%<br>"
            "conditional p %{customdata[0]:.1f} Pa<extra></extra>"))
    figure.update_layout(title="Saved hourly states · Murphy–Koop liquid water",
        xaxis_title="Reconstructed endpoint temperature [°C]", yaxis_title="Humidity ratio w [g/kg dry air]",
        height=460, legend={"orientation": "h"},
        meta={"reference_pressure_pa": float(reference_pressure_pa), "points_recomputed_at_reference_pressure": False,
            "water_phase_below_zero": True, "point_count": len(data)})
    return figure
