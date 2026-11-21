"""One site-based astronomical reference shared by Cartesian, polar (with optional radiation) and 3D views.

Monthly curves use the 21st of each month at five-minute resolution. Hour lines
use a fixed-offset clock and daily geometric positions, forming analemmas.
Weather samples are never used to reconstruct missing astronomical paths.
All positions use the existing pvlib apparent-elevation/azimuth convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from .solar import add_solar_position_for_site, fixed_offset_timezone, fixed_offset_timezone_name

# A seasonal gradient: blue winter, green shoulder season, orange summer,
# with distinct shades for the rising and falling branches of the year.
MONTH_COLORS = (
    "#2563EB", "#0E7490", "#059669", "#429322", "#8A9700", "#DE8A00",
    "#D14E17", "#A96E00", "#287742", "#0D8B91", "#3559A0", "#6343A5",
)


def _month_dash(month: int) -> str:
    # Similar solar declinations on either side of June can nearly coincide.
    # Two line patterns make the two seasonal branches distinguishable.
    return "solid" if month <= 6 else "dash"


def _month_legend(**kwargs):
    return dict(orientation="h", x=0.5, xanchor="center",
                groupclick="togglegroup", itemclick="toggle",
                itemdoubleclick="toggleothers", traceorder="normal", **kwargs)
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
RADIATION_COLORSCALE = [[0.0, "#4c1d95"], [0.45, "#f97316"], [1.0, "#fef08a"]]
RADIATION_FIELDS = (
    ("direct_normal_radiation_wh_m2", "DNI"),
    ("global_horizontal_radiation_wh_m2", "GHI"),
    ("diffuse_horizontal_radiation_wh_m2", "DHI"),
)


@dataclass(frozen=True)
class SolarReference:
    latitude: float
    longitude: float
    elevation_m: float
    utc_offset_hours: float
    year: int
    # Each pair contains azimuth and apparent elevation in degrees. NaNs
    # separate paths that cross below the astronomical horizon.
    months: tuple[tuple[np.ndarray, np.ndarray], ...]
    hours: tuple[tuple[np.ndarray, np.ndarray], ...]

    @property
    def description(self) -> str:
        return (f"21st of each month · astronomical reference {self.year} · "
                f"hour curves use fixed {fixed_offset_timezone_name(self.utc_offset_hours)}")


def _visible_path(azimuth, elevation):
    """Clip a sampled curve to elevation >= 0, including horizon crossings."""
    azimuth = np.asarray(azimuth, dtype=float)
    elevation = np.asarray(elevation, dtype=float)
    az, el = [], []
    for i, (a, h) in enumerate(zip(azimuth, elevation)):
        valid = np.isfinite(a) and np.isfinite(h)
        above = valid and h >= 0.0
        if i:
            a0, h0 = azimuth[i - 1], elevation[i - 1]
            prev_valid = np.isfinite(a0) and np.isfinite(h0)
            prev_above = prev_valid and h0 >= 0.0
            if valid and prev_valid and prev_above != above:
                f = -h0 / (h - h0)
                da = (a - a0 + 180.0) % 360.0 - 180.0
                az.append((a0 + f * da) % 360.0)
                el.append(0.0)
            if prev_above and not above:
                az.append(np.nan)
                el.append(np.nan)
        if above:
            az.append(a % 360.0)
            el.append(min(float(h), 90.0))
    return np.asarray(az, dtype=float), np.asarray(el, dtype=float)


@lru_cache(maxsize=32)
def _reference(latitude: float, longitude: float, elevation_m: float,
               utc_offset_hours: float, year: int) -> SolarReference:
    clock = fixed_offset_timezone(utc_offset_hours)
    monthly_times = [
        pd.date_range(pd.Timestamp(year=year, month=m, day=21, tz=clock),
                      periods=289, freq="5min")
        for m in range(1, 13)
    ]
    annual_hours = pd.date_range(f"{year}-01-01", f"{year+1}-01-01",
                                 freq="h", inclusive="left", tz=clock)
    times = monthly_times[0].append(monthly_times[1:]).append(annual_hours)
    # Reuse the established astronomical engine, rather than introduce a
    # second approximation or interpolate missing measurement rows.
    positions = add_solar_position_for_site(
        pd.DataFrame(index=times), latitude=latitude, longitude=longitude,
        elevation_m=elevation_m,
    )
    az = positions["solar_azimuth_deg"].to_numpy()
    el = positions["solar_elevation_deg"].to_numpy()
    count = len(monthly_times[0])
    months = tuple(_visible_path(az[m*count:(m+1)*count], el[m*count:(m+1)*count])
                   for m in range(12))
    offset = 12 * count
    hours = tuple(_visible_path(az[offset+h::24], el[offset+h::24]) for h in range(24))
    return SolarReference(latitude, longitude, elevation_m, utc_offset_hours, year, months, hours)


def solar_reference(df: pd.DataFrame) -> SolarReference | None:
    """Resolve the immutable site provenance carried by the analysis frame."""
    site = df.attrs.get("solar_geometry_site")
    if not isinstance(site, dict):
        return None
    try:
        lat, lon = float(site["latitude"]), float(site["longitude"])
        elev = float(site["elevation_m"])
        offset = float(site["utc_offset_hours"])
        year = int(site["reference_year"])
        if not (np.isfinite([lat, lon, elev, offset]).all() and -90 <= lat <= 90
                and -180 <= lon <= 180 and -24 < offset < 24 and 1678 <= year <= 2261):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return _reference(lat, lon, elev, offset, year)


def available_radiation_fields(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [(column, label) for column, label in RADIATION_FIELDS
            if column in df and pd.to_numeric(df[column], errors="coerce").notna().any()]


def _polar_layout(fig, title: str, *, invert_zenith_axis: bool = False,
                  zenith_labels: bool = False):
    ticks = [0, 15, 30, 45, 60, 75, 90]
    radial_labels = [f"{v if zenith_labels else 90-v}°" for v in ticks]
    fig.update_layout(
        template="plotly_white", title=title, height=760,
        margin=dict(l=40, r=40, t=75, b=70),
        showlegend=True, legend=_month_legend(y=-0.08),
        polar=dict(
            bgcolor="white",
            radialaxis=dict(range=[90, 0] if invert_zenith_axis else [0, 90],
                            tickmode="array", tickvals=ticks, ticktext=radial_labels,
                            angle=90, gridcolor="#E3E7EB", linecolor="#D0D5DB"),
            angularaxis=dict(direction="clockwise", rotation=90, tickmode="array",
                             tickvals=[0, 45, 90, 135, 180, 225, 270, 315],
                             ticktext=["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                             gridcolor="#E3E7EB", linecolor="#D0D5DB"),
        ),
    )
    if zenith_labels:
        fig.update_layout(polar_radialaxis_title="Zenith angle [deg]")
    return fig


def _monthly_label(az, el, month):
    indices = np.flatnonzero(np.isfinite(az) & np.isfinite(el))
    if not len(indices):
        return None
    # The two half-year branches can lie nearly on top of one another.
    # Place their labels at different relative positions along the path.
    fraction = 0.31 if month <= 6 else 0.69
    i = indices[int(round((len(indices) - 1) * fraction))]
    return float(az[i]), float(el[i])


def _add_polar_months(fig, reference: SolarReference):
    # Draw all halos before all visible coloured lines. A later month's
    # white outline must not paint over a neighbouring month's coloured path.

    for month, (az, el) in enumerate(reference.months, 1):
        if not len(az):
            continue
        fig.add_trace(go.Scatterpolar(theta=az, r=90-el, mode="lines",
            line=dict(color="rgba(255,255,255,0.85)", width=4, dash=_month_dash(month)),
            showlegend=False, hoverinfo="skip", connectgaps=False,
            legendgroup=f"month-{month}", name=f"{MONTH_NAMES[month-1]} guide halo",
            uid=f"polar-month-{month}-halo"))
    for month, (az, el) in enumerate(reference.months, 1):
        if not len(az):
            continue  # polar night: no above-horizon path exists
        color = MONTH_COLORS[month-1]
        fig.add_trace(go.Scatterpolar(theta=az, r=90-el, mode="lines",
            line=dict(color=color, width=2.8, dash=_month_dash(month)),
            name=f"{MONTH_NAMES[month-1]} 21", legendgroup=f"month-{month}",
            uid=f"polar-month-{month}-line",
            connectgaps=False, showlegend=True, customdata=el,
            hovertemplate=f"{MONTH_NAMES[month-1]} 21<br>Azimuth %{{theta:.1f}}°"
                          "<br>Elevation %{customdata:.1f}°<extra></extra>"))
        label = _monthly_label(az, el, month)
        if label is not None:
            a, h = label
            fig.add_trace(go.Scatterpolar(theta=[a], r=[90-h], mode="text",
                text=[MONTH_NAMES[month-1]], textposition="top center",
                textfont=dict(color=color, size=12), showlegend=False,
                hoverinfo="skip", legendgroup=f"month-{month}", name=f"{MONTH_NAMES[month-1]} label",
                uid=f"polar-month-{month}-label"))

def _add_polar_hours(fig, reference: SolarReference):
    first = True
    for hour, (az, el) in enumerate(reference.hours):
        if not len(az) or not np.isfinite(el).any() or np.nanmax(el) < 2.0:
            continue
        fig.add_trace(go.Scatterpolar(theta=az, r=90-el, mode="lines",
            line=dict(color="#AAB4C2", width=1, dash="dot"),
            name="Hour curves" if first else f"{hour:02d}:00", showlegend=first,
            legendgroup="hour-curves", hoverinfo="skip", connectgaps=False))
        first = False
        i = int(np.nanargmax(el))
        fig.add_trace(go.Scatterpolar(theta=[az[i]], r=[90-el[i]], mode="text",
            text=[f"{hour:02d}"], textposition="top center",
            textfont=dict(size=10, color="#64748B"), name=f"{hour:02d}:00 label",
            showlegend=False, legendgroup="hour-curves", hoverinfo="skip"))


def _missing_reference(fig):
    fig.add_annotation(x=0.5, y=1.04, xref="paper", yref="paper", showarrow=False,
        text="Astronomical reference unavailable: site coordinates and clock are required.")
    return fig


def classic_sun_path(df: pd.DataFrame, title: str = "2D sun-path diagram", *,
                     radiation_field: str | None = None,
                     invert_zenith_axis: bool = False,
                     hide_zero_radiation: bool = False) -> go.Figure:
    """The single polar chart; only an explicit quantity enables radiation.

    Monthly curves, hour curves, projection and axis labels are identical
    with or without the measured irradiation overlay. None is deliberately
    different from an unavailable or empty selected quantity.
    """
    fields = dict(available_radiation_fields(df))
    field = radiation_field
    label = fields.get(field, "")
    fig = go.Figure()
    if field is None:
        pass
    elif field in fields and {"solar_azimuth_deg", "solar_elevation_deg"}.issubset(df):
        values = pd.to_numeric(df[field], errors="coerce")
        az = pd.to_numeric(df["solar_azimuth_deg"], errors="coerce")
        el = pd.to_numeric(df["solar_elevation_deg"], errors="coerce")
        keep = values.notna() & az.notna() & el.gt(0)
        if hide_zero_radiation:
            keep &= values.gt(0)
        filtered = df.loc[keep].copy()
        if not filtered.empty:
            fig = px.scatter_polar(
                filtered.assign(zenith_angle_deg=90-el.loc[keep]),
                theta="solar_azimuth_deg", r="zenith_angle_deg", color=field,
                hover_data={c: True for c in ("month_index", "hour_of_day", "solar_elevation_deg") if c in filtered},
                labels={field: f"{label} [Wh/m²]", "solar_azimuth_deg": "Solar azimuth [deg]",
                        "zenith_angle_deg": "Zenith angle [deg]"},
                render_mode="webgl", color_continuous_scale=RADIATION_COLORSCALE,
            )
            fig.update_traces(marker=dict(size=5, opacity=0.85),
                              name=f"{label} irradiation", uid="polar-radiation",
                              legendgroup="radiation-overlay", showlegend=False)
            fig.update_layout(coloraxis_colorbar=dict(title=f"{label} [Wh/m²]", len=0.76))
        else:
            fig.add_annotation(x=0.5, y=1.02, xref="paper", yref="paper",
                text="No radiation samples remain in the active filter.", showarrow=False)
    else:
        fig.add_annotation(x=0.5, y=1.02, xref="paper", yref="paper",
            text="No measured or admitted radiation quantity is available.", showarrow=False)
    reference = solar_reference(df)
    _polar_layout(fig, title, invert_zenith_axis=invert_zenith_axis)
    fig.update_layout(meta={"radiation_field": field or ""})
    if reference is None:
        return _missing_reference(fig)
    _add_polar_hours(fig, reference)
    _add_polar_months(fig, reference)
    fig.update_layout(meta={"solar_reference": reference.description,
                            "radiation_field": field or ""})
    return fig


def radiation_sun_path(df: pd.DataFrame, title: str | None = None,
                       invert_zenith_axis: bool = False, hide_zero_radiation: bool = False,
                       radiation_field: str | None = None) -> go.Figure:
    """Compatibility entry point for earlier programmatic radiation charts."""
    fields = dict(available_radiation_fields(df))
    field = radiation_field or next(iter(fields), None)
    label = fields.get(field, "")
    return classic_sun_path(df, title or (f"Sun path with {label}" if label else "2D sun-path diagram"),
                            radiation_field=field, invert_zenith_axis=invert_zenith_axis,
                            hide_zero_radiation=hide_zero_radiation)


def _cartesian_path(azimuth, elevation):
    """Split the N/0° seam instead of drawing a line across the entire plot."""
    xs, ys = [], []
    for a, h in zip(azimuth, elevation):
        if xs and np.isfinite(a) and np.isfinite(xs[-1]) and abs(a-xs[-1]) > 180:
            xs.append(np.nan)
            ys.append(np.nan)
        xs.append(a)
        ys.append(h)
    return xs, ys


def technical_sun_path(df: pd.DataFrame, title: str = "Technical sun-path diagram") -> go.Figure:
    """Restore the original Cartesian engineering representation.

    The earlier chart's azimuth/elevation axes are retained, but its
    first-available-day sampling is replaced by the common astronomical 21st
    reference used by the other views. This works for incomplete weather years.
    """
    fig = go.Figure()
    reference = solar_reference(df)
    axes = [55., 305.]
    ymax = 85.
    if reference is not None:
        finite_az = [a[np.isfinite(a)] for a, _ in reference.months if np.isfinite(a).any()]
        finite_el = [h[np.isfinite(h)] for _, h in reference.months if np.isfinite(h).any()]
        if finite_az:
            low = min(float(np.min(a)) for a in finite_az)
            high = max(float(np.max(a)) for a in finite_az)
            axes = [max(0., min(55., 10*np.floor(low/10)-5)),
                    min(360., max(305., 10*np.ceil(high/10)+5))]
        if finite_el:
            ymax = max(85., min(90., float(np.ceil(max(np.max(h) for h in finite_el)/5)*5)))
        first = True
        for hour, (az, el) in enumerate(reference.hours):
            if not len(el) or not np.isfinite(el).any() or np.nanmax(el) < 2.0:
                continue
            x, y = _cartesian_path(az, el)
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", connectgaps=False,
                line=dict(color="#AAB4C2", width=1, dash="dot"),
                name="Hour curves" if first else f"{hour:02d}:00", legendgroup="hour-curves",
                showlegend=first, hoverinfo="skip"))
            first = False
            idx = int(np.nanargmax(el))
            fig.add_trace(go.Scatter(x=[az[idx]], y=[el[idx]], mode="text",
                text=[f"{hour:02d}:00"], textposition="top center",
                textfont=dict(color="#64748B", size=10),
                legendgroup="hour-curves", showlegend=False, hoverinfo="skip"))
        for month, (az, el) in enumerate(reference.months, 1):
            if not len(az):
                continue
            x,y = _cartesian_path(az, el)
            color = MONTH_COLORS[month-1]
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", connectgaps=False,
                line=dict(color=color, width=2.8, dash=_month_dash(month)),
                name=f"{MONTH_NAMES[month-1]} 21", legendgroup=f"month-{month}",
                uid=f"technical-month-{month}-line", showlegend=True,
                hovertemplate=f"{MONTH_NAMES[month-1]} 21<br>Azimuth %{{x:.1f}}°"
                              "<br>Elevation %{y:.1f}°<extra></extra>"))
            label = _monthly_label(az, el, month)
            if label is not None:
                a,h = label
                fig.add_trace(go.Scatter(x=[a], y=[h], mode="text",
                    text=[f"21 {MONTH_NAMES[month-1]}"], textposition="top center",
                    textfont=dict(color=color, size=12), legendgroup=f"month-{month}",
                    uid=f"technical-month-{month}-label", showlegend=False, hoverinfo="skip"))
        fig.update_layout(meta={"solar_reference": reference.description})
    else:
        _missing_reference(fig)
    # Put compass bearings into the axis tick text itself. Plotly lays out
    # the two-line tick labels before the axis title, including after a
    # change of the global font, avoiding independent overlapping annotations.
    cardinal = {0: "North", 90: "East", 180: "South", 270: "West", 360: "North"}
    ticks = list(range(0, 361, 10))
    labels = [f"{a}°<br>{cardinal[a]}" if a in cardinal else f"{a}°" for a in ticks]
    fig.update_layout(template="plotly_white", title=title, height=900,
        margin=dict(l=65,r=40,t=80,b=175), showlegend=True,
        legend=_month_legend(y=0.01, yref="container", yanchor="bottom"),
        xaxis=dict(title=dict(text="Solar azimuth [deg]", standoff=18),
                   range=axes, tickmode="array", tickvals=ticks, ticktext=labels,
                   automargin=True, gridcolor="rgba(107,114,128,0.25)", zeroline=False),
        yaxis=dict(title="Solar elevation [deg]", range=[0,ymax], dtick=10,
                   ticksuffix="°", gridcolor="rgba(107,114,128,0.25)", zeroline=False))
    return fig


def sun_direction_xyz(azimuth, elevation):
    """Unit sphere: +X East, +Y North, +Z up; azimuth clockwise from North."""
    a, h = np.deg2rad(azimuth), np.deg2rad(elevation)
    return np.cos(h)*np.sin(a), np.cos(h)*np.cos(a), np.sin(h)


def _dome_grid():
    x, y, z = [], [], []
    def add(az, el):
        for target, values in zip((x, y, z), sun_direction_xyz(az, el)):
            target.extend(np.asarray(values).tolist())
            target.append(None)
    for altitude in range(0, 90, 15):
        add(np.linspace(0, 360, 145), np.full(145, altitude))
    for azimuth in range(0, 360, 30):
        add(np.full(61, azimuth), np.linspace(0, 90, 61))
    return go.Scatter3d(x=x, y=y, z=z, mode="lines",
        line=dict(color="#DCE2E8", width=2), name="Sky dome grid", showlegend=False, hoverinfo="skip")


def _cube_traces(show_cube: bool):
    half = 0.15
    x = [-half, half, half, -half, -half, half, half, -half]
    y = [-half, -half, half, half, -half, -half, half, half]
    z = [0, 0, 0, 0, 0.30, 0.30, 0.30, 0.30]
    mesh = go.Mesh3d(x=x, y=y, z=z, i=[0,0,4,4,0,0,1,1,2,2,3,3],
        j=[1,2,5,6,1,5,2,6,3,7,0,4], k=[2,3,6,7,5,4,6,5,7,6,4,7],
        facecolor=["#C8D0D9"]*2+["#E3E8EF"]*2+["#C8D0D9"]*2+["#B8C3CF"]*2+
                  ["#C8D0D9"]*2+["#B8C3CF"]*2,
        flatshading=True, lighting=dict(ambient=0.8, diffuse=0.35),
        visible=show_cube, name="Illustrative cube", showlegend=False, hoverinfo="skip")
    ex, ey, ez = [], [], []
    for i, j in ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)):
        ex.extend([x[i], x[j], None]); ey.extend([y[i], y[j], None]); ez.extend([z[i], z[j], None])
    edges = go.Scatter3d(x=ex, y=ey, z=ez, mode="lines", line=dict(color="#8793A2", width=3),
        visible=show_cube, name="Cube edges", showlegend=False, hoverinfo="skip")
    return mesh, edges


def sun_path_3d(df: pd.DataFrame, *, show_cube: bool = True, title: str = "3D sun-path diagram") -> go.Figure:
    fig = go.Figure()
    reference = solar_reference(df)
    if reference is None:
        return fig.update_layout(title="Astronomical reference unavailable")
    fig.add_trace(_dome_grid())
    # Thin neutral hour curves add spatial context without obscuring paths.
    first_hour = True
    for hour, (az, el) in enumerate(reference.hours):
        if not len(az):
            continue
        x, y, z = sun_direction_xyz(az, el)
        fig.add_trace(go.Scatter3d(x=x, y=y, z=z, mode="lines",
            line=dict(color="#C6CDD7", width=1, dash="dot"),
            name="Hour curves" if first_hour else f"{hour:02d}:00",
            legendgroup="hour-curves", showlegend=first_hour, hoverinfo="skip", connectgaps=False))
        first_hour = False
    for month, (az, el) in enumerate(reference.months, 1):
        if not len(az):
            continue
        x, y, z = sun_direction_xyz(az, el)
        fig.add_trace(go.Scatter3d(x=x, y=y, z=z, mode="lines", connectgaps=False,
            line=dict(color=MONTH_COLORS[month-1], width=5, dash=_month_dash(month)),
            name=f"{MONTH_NAMES[month-1]} 21", legendgroup=f"month-{month}",
            uid=f"dome-month-{month}-line", showlegend=True, customdata=np.column_stack((az, el)),
            hovertemplate=f"{MONTH_NAMES[month-1]} 21<br>Azimuth %{{customdata[0]:.1f}}°"
                          "<br>Elevation %{customdata[1]:.1f}°<extra></extra>"))
    compass_x, compass_y, compass_z = sun_direction_xyz(np.array([0.,90.,180.,270.]), np.zeros(4))
    fig.add_trace(go.Scatter3d(x=1.08*compass_x, y=1.08*compass_y, z=compass_z,
        mode="text", text=["N","E","S","W"], textfont=dict(size=14,color="#263444"),
        name="Compass", showlegend=False, hoverinfo="skip"))
    fig.add_traces(_cube_traces(show_cube))
    axis = dict(visible=False, showgrid=False, zeroline=False, showbackground=False)
    revision = (f"sun-dome-turntable:{reference.latitude:.6f}:{reference.longitude:.6f}:"
                f"{reference.year}:{reference.utc_offset_hours:g}")
    fig.update_layout(template="plotly_white", title=title, height=760,
        margin=dict(l=0,r=0,t=70,b=50),
        showlegend=True, legend=_month_legend(y=-0.02),
        uirevision=revision, meta={"solar_reference": reference.description,
            "cube_is_illustrative": True, "coordinate_system":"east,north,up"},
        scene=dict(xaxis=dict(**axis,range=[-1.15,1.15]),
            yaxis=dict(**axis,range=[-1.15,1.15]), zaxis=dict(**axis,range=[-0.05,1.10]),
            aspectmode="manual", aspectratio=dict(x=1,y=1,z=0.5),
            dragmode="turntable", uirevision=revision,
            camera=dict(eye=dict(x=1.45,y=-1.65,z=1.08),up=dict(x=0,y=0,z=1),
                        projection=dict(type="orthographic"))))
    return fig
