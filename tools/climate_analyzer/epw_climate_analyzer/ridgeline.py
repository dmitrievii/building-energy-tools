"""Shared monthly/seasonal ridgeline distributions for climate observations.

Use a common histogram grid and probability density (area integrates to one
for each represented group). No KDE extrapolation, synthetic samples, or
independent peak normalization. Native record values and their units remain
unchanged. The display is offset vertically, never interpreted as a time series.
"""
from __future__ import annotations

import calendar
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .chart_theme import metric_color, rgba
from .climate_model import aggregation_semantics_for


def ridgeline_figure(df, column, unit, label, *, grouping="Monthly",
                     bins=40, quantiles=True, wet_only=False, latitude=None):
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Dated source observations are required.")
    if aggregation_semantics_for(column) == "circular mean" or "direction" in column:
        raise ValueError("Circular directions require directional statistics.")
    if grouping not in ("Monthly", "Seasonal"):
        raise ValueError("Unsupported ridgeline grouping.")
    if not 10 <= int(bins) <= 100:
        raise ValueError("Choose 10–100 common distribution bins.")
    values = pd.to_numeric(df[column], errors="coerce")
    valid = np.isfinite(values.to_numpy(dtype=float))
    if wet_only:
        valid &= values.to_numpy(dtype=float) > 0
    values = values.loc[valid]
    if values.empty:
        raise ValueError("No valid observations in the selected distribution scope.")
    month = values.index.month
    if grouping == "Monthly":
        groups = [(calendar.month_name[m], values.loc[month == m])
                  for m in range(1, 13)]
    else:
        try:
            lat = float(latitude)
            known_hemisphere = np.isfinite(lat) and -90 <= lat <= 90 and lat != 0
        except (TypeError, ValueError):
            lat, known_hemisphere = 0., False
        names = (("Summer", "Autumn", "Winter", "Spring") if lat < 0
                 else ("Winter", "Spring", "Summer", "Autumn"))
        if not known_hemisphere:
            names = ("Dec–Feb", "Mar–May", "Jun–Aug", "Sep–Nov")
        groups = [(name, values.loc[month.isin(months)])
                  for name, months in zip(names, ((12, 1, 2), (3, 4, 5),
                                                   (6, 7, 8), (9, 10, 11)))]
    groups = [(name, s.to_numpy(dtype=float)) for name, s in groups if len(s)]
    lo, hi = float(values.min()), float(values.max())
    if lo == hi:
        edges = None
    else:
        edges = np.linspace(lo, hi, int(bins) + 1)
    profiles = []
    for name, data in groups:
        if edges is None:
            profiles.append((name, data, None))
        else:
            counts, _ = np.histogram(data, bins=edges)
            density = counts / (len(data) * np.diff(edges))
            profiles.append((name, data, density))
    peak = max((float(d.max()) for _, _, d in profiles if d is not None), default=1.)
    scale = 1.65 / peak
    color = metric_color(column)
    f = go.Figure()
    # Highest baseline first (Jan at top); draw lower ridges later so their
    # outlines and shared-baseline statistics remain visible.
    ticks, ticktext, summaries = [], [], []
    for i, (name, data, density) in enumerate(profiles):
        baseline = len(profiles) - 1 - i
        ticks.append(baseline)
        ticktext.append(name)
        p05, median, p95 = np.quantile(data, [.05, .5, .95])
        summaries.append((name, len(data), float(p05), float(median), float(p95)))
        if density is None or float(data.min()) == float(data.max()):
            f.add_scatter(x=[median], y=[baseline], mode="markers",
                          marker=dict(color=color, size=8),
                          name=name, showlegend=False,
                          hovertemplate=f"{name}<br>Constant value %{{x:.3g}} {unit}<br>n={len(data)}<extra></extra>")
        else:
            # Closed polygon along the actual common-bin edges. A step plot
            # preserves the probability mass of each bin, including zeros.
            x = np.concatenate(([edges[0]], np.repeat(edges, 2)[1:-1], [edges[-1]]))
            yy = np.concatenate(([baseline], baseline + np.repeat(density, 2)*scale, [baseline]))
            f.add_scatter(x=x, y=yy, mode="lines", fill="toself",
                          line=dict(color=color, width=1.2), fillcolor=rgba(color, .32),
                          name=name, showlegend=False, hoverinfo="skip")
            centers = (edges[:-1] + edges[1:]) / 2
            f.add_scatter(x=centers, y=baseline+density*scale, mode="markers",
                          marker=dict(size=9, opacity=0), customdata=density,
                          name=name, showlegend=False,
                          hovertemplate=f"{name}<br>Bin centre %{{x:.3g}} {unit}<br>Probability density %{{customdata:.3g}}<br>n={len(data)}<extra></extra>")
        if quantiles:
            f.add_scatter(x=[p05, p95], y=[baseline, baseline], mode="lines",
                          line=dict(color="#404040", width=2), hoverinfo="skip",
                          showlegend=False)
            f.add_scatter(x=[median], y=[baseline], mode="markers",
                          marker=dict(color="#202020", size=6),
                          name=name, showlegend=False,
                          hovertemplate=f"{name}<br>Median %{{x:.3g}} {unit}<extra></extra>")
    f.update_layout(template="plotly_white", title=f"{label} · {grouping.lower()} ridgeline",
                    xaxis_title=f"{label} [{unit}]", yaxis=dict(tickmode="array",
                    tickvals=ticks,ticktext=ticktext,showgrid=False,zeroline=False,
                    range=[-.35, len(profiles)+.9]),
                    height=max(360, 48*len(profiles)+110),
                    meta={"layout_kind":"ridgeline","ridgeline_grouping":grouping,
                          "ridgeline_bins":int(bins),"ridgeline_quantiles":bool(quantiles)})
    low = min(summaries, key=lambda a:a[3])
    high = max(summaries, key=lambda a:a[3])
    broad = max(summaries, key=lambda a:a[4]-a[2])
    scope = " Positive precipitation observations only." if wet_only else ""
    note = (f"The {grouping.lower()} ridgeline shows distributions of {label.lower()} "
            f"across {len(profiles)} represented groups ({len(values):,} valid source observations). "
            f"The lowest group median is {low[3]:.2f} {unit} in {low[0]}; "
            f"the highest is {high[3]:.2f} {unit} in {high[0]}. "
            f"The widest P05–P95 interval occurs in {broad[0]} "
            f"({broad[2]:.2f}–{broad[4]:.2f} {unit}). "
            "Ridges share one physical value axis and a common probability-density scale; "
            "each binned distribution has unit probability area. Constant groups are shown as points. "
            "Equivalent calendar groups pool selected source years."
            + (" Baseline segments mark P05–P95 and points mark medians." if quantiles else "") + scope)
    return f, note
