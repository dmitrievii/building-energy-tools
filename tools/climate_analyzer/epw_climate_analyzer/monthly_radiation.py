"""Monthly source and plane-of-array irradiation with common period semantics.

Climate quantities are independent reference-plane observations (DNI is normal
to the solar beam). Surface quantities are additive POA contributions computed
by the established interval-level isotropic transposition kernel. No total is
ever stacked on its constituents. Missing observations remain missing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .aggregations import period_total_series
from .temporal_filtering import CALENDAR_PROFILE, time_basis
from .chart_theme import ORIENTATION_COLORS, SOLAR_COMPONENT_COLORS
from .facade_orientation import ORIENTATIONS

SOURCE_FIELDS = {
    "GHI": "global_horizontal_radiation_wh_m2",
    "DHI": "diffuse_horizontal_radiation_wh_m2",
    "DNI": "direct_normal_radiation_wh_m2",
}
SURFACE_FIELDS = {
    "Total POA": "poa_global_wh_m2",
    "Direct": "poa_direct_wh_m2",
    "Sky diffuse": "poa_sky_diffuse_wh_m2",
    "Ground-reflected": "poa_ground_diffuse_wh_m2",
}
SURFACE_COLORS = {
    "Total POA": SOLAR_COMPONENT_COLORS["GHI"],
    "Direct": SOLAR_COMPONENT_COLORS["DNI"],
    "Sky diffuse": SOLAR_COMPONENT_COLORS["DHI"],
    "Ground-reflected": "#7493AA",
}
SURFACE_NAMES = {name: angle for name, _, angle in ORIENTATIONS}
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _numeric(df, column):
    return column in df and pd.to_numeric(df[column], errors="coerce").notna().any()


def available_source_quantities(df):
    return [name for name, column in SOURCE_FIELDS.items() if _numeric(df, column)]


def surface_available(df):
    cols = (*SOURCE_FIELDS.values(), "solar_apparent_zenith_deg", "solar_azimuth_deg")
    if not all(_numeric(df, column) for column in cols):
        return False
    return bool(pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce").notna()
                              for c in cols}).all(axis=1).any())


def _period_index(df):
    if time_basis(df) == CALENDAR_PROFILE:
        return pd.Index(range(1, 13), name="Month")
    idx = pd.DatetimeIndex(df.index)
    if not len(idx):
        return pd.DatetimeIndex([], name="Month")
    # Single-year files keep all Jan-Dec slots; chronological multi-year
    # histories keep the year and month instead of adding different years.
    start, end = idx.min(), idx.max()
    if start.year == end.year:
        first = pd.Timestamp(year=start.year, month=1, day=1, tz=idx.tz)
        last = pd.Timestamp(year=start.year, month=12, day=1, tz=idx.tz)
    else:
        first = pd.Timestamp(year=start.year, month=start.month, day=1, tz=idx.tz)
        last = pd.Timestamp(year=end.year, month=end.month, day=1, tz=idx.tz)
    return pd.date_range(first, last, freq="MS", name="Month")


def _sum(values, df, index):
    totals = period_total_series(values, df, "Monthly") / 1000.
    # Existing monthly aggregation uses month starts. Normalize both key
    # representations explicitly to avoid depending on month-end conventions.
    if isinstance(index, pd.DatetimeIndex) and isinstance(totals.index, pd.DatetimeIndex):
        totals.index = pd.DatetimeIndex([pd.Timestamp(year=t.year, month=t.month, day=1,
                                                       tz=index.tz) for t in totals.index])
    return totals.reindex(index)


def monthly_source_irradiation(df, selected):
    index = _period_index(df)
    table = pd.DataFrame(index=index)
    for name in selected:
        if name not in available_source_quantities(df):
            raise ValueError(f"Unavailable source radiation quantity: {name}")
        table[name] = _sum(pd.to_numeric(df[SOURCE_FIELDS[name]], errors="coerce").clip(lower=0), df, index)
    return table


def monthly_surface_irradiation(df, surfaces, tilt_deg, selected, *, albedo=None):
    from .runtime_module_guard import ensure_current_solar_runtime

    if not surface_available(df):
        raise ValueError("No coincident solar geometry and admitted GHI, DNI and DHI inputs.")
    if not np.isfinite(tilt_deg) or not 0. <= tilt_deg <= 90.:
        raise ValueError("Surface tilt must be between 0 and 90 degrees.")
    if any(q not in SURFACE_FIELDS for q in selected):
        raise ValueError("Unknown surface irradiation quantity.")
    index = _period_index(df)
    table = pd.DataFrame(index=index)
    for name, azimuth in surfaces:
        if not np.isfinite(azimuth) or not 0. <= azimuth < 360.:
            raise ValueError("Surface azimuth must be in [0, 360).")
        intervals = ensure_current_solar_runtime().surface_irradiance_components(
            df, tilt_deg, azimuth, albedo=albedo,
        )
        for quantity in selected:
            table[(name, quantity)] = _sum(intervals[SURFACE_FIELDS[quantity]], df, index)
    if len(table.columns):
        table.columns = pd.MultiIndex.from_tuples(table.columns, names=["Surface", "Quantity"])
    return table


def _axis_labels(index):
    if isinstance(index, pd.DatetimeIndex):
        multi = len(set(index.year)) > 1
        return list(index.strftime("%b %Y" if multi else "%b"))
    return [MONTH_NAMES[int(m)-1] for m in index]


def monthly_rose_years(table):
    """Calendar profiles have no selected year; chronology retains its years."""
    if isinstance(table.index, pd.DatetimeIndex):
        return sorted({int(year) for year in table.index.year})
    return []


def monthly_rose_table(table, *, year=None):
    """Exactly 12 ordered calendar sectors; never fold chronological years."""
    years = monthly_rose_years(table)
    if isinstance(table.index, pd.DatetimeIndex):
        if not years:
            raise ValueError("No monthly periods are available.")
        if year is None:
            if len(years) != 1:
                raise ValueError("Select one calendar year for the monthly rose.")
            year = years[0]
        if year not in years:
            raise ValueError("Selected rose year is unavailable.")
        idx = pd.date_range(pd.Timestamp(year=year, month=1, day=1, tz=table.index.tz),
                           periods=12, freq="MS", name=table.index.name)
        return table.reindex(idx)
    if year is not None:
        raise ValueError("Calendar-profile monthly rose does not use a year selector.")
    return table.reindex(pd.Index(range(1, 13), name=table.index.name))


def monthly_radiation_chart(table, *, style="Bar chart", tilt_deg=None, rose_year=None):
    if style not in {"Bar chart", "Line chart", "Monthly rose"}:
        raise ValueError(f"Unknown chart type: {style}")
    if style == "Monthly rose":
        table = monthly_rose_table(table, year=rose_year)
    surface_mode = isinstance(table.columns, pd.MultiIndex)
    surface_names = list(dict.fromkeys(c[0] for c in table.columns)) if surface_mode else []
    multiple = len(surface_names) > 1
    x = _axis_labels(table.index)
    fig = go.Figure()
    dash = {"Total POA":"solid", "Direct":"dash", "Sky diffuse":"dot", "Ground-reflected":"dashdot"}
    patterns = {"Total POA":"", "Direct":"/", "Sky diffuse":".", "Ground-reflected":"x"}
    for series_index, column in enumerate(table.columns):
        if surface_mode:
            surface, quantity = column
            name = f"{surface} · {quantity}" if multiple else f"{quantity} ({surface})"
            color = (ORIENTATION_COLORS.get(surface.lower(), "#475569")
                     if multiple else SURFACE_COLORS[quantity])
            pattern = patterns[quantity] if multiple else ""
            line_dash = dash[quantity] if multiple else "solid"
        else:
            name, color, pattern, line_dash = str(column), SOLAR_COMPONENT_COLORS[column], "", "solid"
        values = table[column].to_numpy(dtype=float)
        common = dict(name=name, hovertemplate="%{x}<br>%{y:,.1f} kWh/m²<extra>%{fullData.name}</extra>")
        if style == "Monthly rose":
            # Plotly polar barmode has only stack/overlay. Allocate fixed,
            # disjoint angular sub-sectors explicitly to obtain grouped bars.
            # The radial origin is zero for every series, so totals and
            # components are never added. All twelve slots persist if a
            # month is missing or a legend item is hidden.
            count = max(1, len(table.columns))
            slot = 26.0 / count  # leave 4 degrees between adjacent months
            center = np.arange(12, dtype=float) * 30.0
            theta = (center - 13.0 + (series_index + 0.5) * slot) % 360.0
            fig.add_trace(go.Barpolar(theta=theta, thetaunit="degrees", r=values,
                width=slot * 0.90, base=0, name=name,
                marker=dict(color=color, pattern=dict(shape=pattern),
                            line=dict(color="white", width=0.5)),
                customdata=list(MONTH_NAMES),
                hovertemplate="%{customdata}<br>%{r:,.1f} kWh/m²<extra>%{fullData.name}</extra>"))
        elif style == "Bar chart":
            fig.add_trace(go.Bar(x=x, y=values, marker=dict(color=color, pattern=dict(shape=pattern)), **common))
        else:
            fig.add_trace(go.Scatter(x=x, y=values, mode="lines+markers", connectgaps=False,
                                     line=dict(color=color, dash=line_dash, width=2.5), **common))
    title = ("Monthly surface irradiation" + (f" · tilt {tilt_deg:g}°" if tilt_deg is not None else "")
             if surface_mode else "Monthly source irradiation")
    if style == "Monthly rose":
        years = monthly_rose_years(table)
        if years:
            title += f" · {years[0]}"
        else:
            title += " · calendar profile"
        title += " [kWh/m²]"
        fig.update_layout(height=780,
            polar=dict(barmode="overlay", bgcolor="white",
                radialaxis=dict(rangemode="nonnegative", tickformat=",.0f",
                                tickangle=0, angle=105, gridcolor="#DDE3EA"),
                angularaxis=dict(type="linear", direction="clockwise", rotation=90,
                    tickmode="array", tickvals=list(range(0, 360, 30)),
                    ticktext=list(MONTH_NAMES), gridcolor="#E4E8ED")),
            margin=dict(l=70, r=70, t=80, b=145))
    else:
        fig.update_layout(xaxis=dict(title=dict(text="Month", standoff=18),
                                     automargin=True, categoryorder="array", categoryarray=x),
                          yaxis=dict(title="Irradiation [kWh/m²]", rangemode="tozero"),
                          margin=dict(l=65, r=30, t=75, b=145))
    fig.update_layout(template="plotly_white", title=title, barmode="group",
        legend=dict(orientation="h", y=0.01, yref="container", yanchor="bottom",
                    x=0.5, xanchor="center"),
        meta={"measurement_basis": "surface" if surface_mode else "source",
              "unit": "kWh/m²", "month_sectors": 12 if style == "Monthly rose" else None,
              "rose_grouping": "disjoint angular sub-sectors" if style == "Monthly rose" else None})
    return fig
