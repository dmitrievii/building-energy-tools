"""R2.2 figure-specific humidity and psychrometric interpretation.

These deterministic descriptions refer to the displayed statistic, the selected
source data, and explicitly stated screening assumptions. Outdoor climatic
potential is never promoted to indoor comfort, condensation, economizer hours,
or building energy demand without a building/plant model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from .aggregations import native_interval_hours
from .interpretations import _fmt, _fmt_hours, _duration_hours_from_count

RH = "relative_humidity_pct"
W = "humidity_ratio_g_kg"
T = "dry_bulb_temperature_c"
DP = "dew_point_temperature_c"
WB = "wet_bulb_temperature_c"
H = "moist_air_enthalpy_kj_kg"
SV = "specific_volume_m3_kg"
RHO = "moist_air_density_kg_m3"
P = "atmospheric_station_pressure_pa"

UNITS = {
    RH: "%", W: "g/kg dry air", DP: "°C", WB: "°C",
    H: "kJ/kg dry air", SV: "m³/kg dry air", RHO: "kg/m³", P: "Pa",
}
LABELS = {
    RH: "relative humidity", W: "humidity ratio", DP: "dew-point temperature",
    WB: "wet-bulb temperature", H: "moist-air enthalpy", SV: "specific volume",
    RHO: "moist-air density", P: "station pressure",
}


def numeric(df, column):
    if column not in df:
        return pd.Series(dtype=float, index=df.index)
    return pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _plotted_series(fig, preferred=None):
    """Find a plotted numeric ordinate; ignore auxiliary markers when possible."""
    if fig is None:
        return pd.Series(dtype=float), []
    for tr in getattr(fig, "data", ()):
        name = str(getattr(tr, "name", "") or "")
        if preferred is not None and preferred.lower() not in name.lower():
            continue
        if preferred is None and any(k in name.lower() for k in ("quantile marker", "threshold")):
            continue
        raw = getattr(tr, "y", None)
        if raw is None:
            continue
        arr = np.asarray(raw, dtype=object)
        if arr.ndim != 1 or not arr.size:
            continue
        values = pd.to_numeric(pd.Series(arr), errors="coerce")
        if not values.notna().any():
            continue
        xs = getattr(tr, "x", None)
        return values, list(xs) if xs is not None else []
    return pd.Series(dtype=float), []


def _coincident(df, *columns):
    if not all(c in df for c in columns):
        return pd.DataFrame(columns=columns)
    return pd.DataFrame({c: numeric(df, c) for c in columns}, index=df.index).dropna()


def _physical_context(df, column):
    """One physical implication specific to the measured quantity."""
    v = numeric(df, column).dropna()
    if v.empty:
        return ""
    if column == RH:
        both = _coincident(df, RH, W)
        if not both.empty:
            high_rh = both[RH] >= 80.
            low_w = both[W] < 9.
            n = _duration_hours_from_count(df, int((high_rh & low_w).sum()))
            return (f"{_fmt_hours(n)} h have RH ≥80% while absolute humidity ratio is below "
                    "the illustrative 9 g/kg threshold. Relative humidity must not be used "
                    "alone as a dehumidification or ventilation-load criterion.")
        return "Relative humidity depends on temperature; it is not absolute water-vapour content."
    if column == W:
        hours = _duration_hours_from_count(df, int((v > 10.).sum()))
        return (f"{_fmt_hours(hours)} h exceed the illustrative 10 g/kg moisture screen. "
                "The threshold is not a universal comfort limit and does not itself rule out "
                "natural ventilation; a conditioned indoor target is a separate requirement.")
    if column == DP:
        h = _duration_hours_from_count(df, int((v >= 15.).sum()))
        return (f"Outdoor dew point is at or above 15 °C for {_fmt_hours(h)} h. "
                "Air in contact with an assumed 15 °C surface could reach saturation; "
                "this is not an indoor or interstitial condensation prediction.")
    if column == WB:
        paired = _coincident(df, T, WB)
        if not paired.empty:
            depression = paired[T] - paired[WB]
            return (f"Median outdoor dry-bulb minus wet-bulb depression is "
                    f"{_fmt(depression.median())} K. It indicates evaporative cooling headroom "
                    "of the outdoor air, not achievable indoor cooling or comfort.")
        return "Wet-bulb depression is informative for evaporative cooling potential."
    if column == H:
        h = _duration_hours_from_count(df, int((v > 55.).sum()))
        return (f"{_fmt_hours(h)} h exceed the illustrative 55 kJ/kg dry-air reference. "
                "An economizer decision requires comparison with indoor/return-air enthalpy "
                "and moisture limits, not an outdoor enthalpy threshold alone.")
    if column == SV:
        return ("Specific volume is per kilogram of dry air; converting an outdoor-air "
                "volume flow to dry-air mass flow also requires the actual air state.")
    if column == RHO:
        return ("Moist-air density is total moist-air mass per actual air volume. "
                "It is not the inverse of the dry-air-specific volume unless humidity is zero.")
    if column == P:
        return ("Station pressure describes the outdoor thermodynamic reference state. "
                "It is not wind pressure or a façade pressure difference.")
    return ""


def humidity_figure_interpretation(
    df, fig, kind, *, column="", title="", args=(),
    surface_c=15., airflow_m3_h=1000., target_g_kg=9.,
):
    """Plot-aware interpretation shared by Streamlit, the atlas, and reports."""
    kind = str(kind).lower()
    label = str(title or getattr(getattr(getattr(fig, "layout", None), "title", None), "text", "") or "")
    caption = label.lower()
    args = tuple(args or ())

    if kind == "psychrometric":
        paired = _coincident(df, T, W, H)
        if paired.empty:
            return "No coincident temperature, humidity-ratio and enthalpy states are available."
        n = len(paired)
        high_w = _duration_hours_from_count(df, int((paired[W] > 10.).sum()))
        high_h = _duration_hours_from_count(df, int((paired[H] > 55.).sum()))
        axes = "moisture content versus enthalpy" if "i-d" in caption else "dry-bulb temperature versus moisture content"
        if "climate zone" in caption or "contour" in caption:
            view = ("The density contour encloses the selected fraction of a smoothed "
                    "joint occurrence distribution, not an exact subset of measured hourly points. ")
        elif "distribution grid" in caption:
            view = ("Grid-cell frequencies are conditional on the displayed temperature/RH bins; "
                    "they are not indoor psychrometric states. ")
        else:
            view = "Points represent paired outdoor weather observations. "
        return (
            f"Outdoor psychrometric state ({axes}; {n:,} valid intervals): humidity ratio "
            f"{_fmt(paired[W].min())}–{_fmt(paired[W].max())} g/kg dry air. "
            f"{_fmt_hours(high_w)} h exceed 10 g/kg and {_fmt_hours(high_h)} h exceed 55 kJ/kg dry air. "
            + view +
            "Bioclimatic overlays are reference strategy maps with overlapping regions, "
            "not validated indoor-comfort, cooling or ventilation hours. "
            "Actual strategies require occupancy, indoor state and airflow/plant assumptions."
        )

    if kind == "condensation":
        dew = numeric(df, DP).dropna()
        if dew.empty:
            return "No valid outdoor dew-point values for the selected interval."
        n = _duration_hours_from_count(df, int((dew >= float(surface_c)).sum()))
        return (
            f"With a hypothetical constant {surface_c:g} °C surface, outdoor air has "
            f"dew point at or above that temperature for {_fmt_hours(n)} h. "
            "Only if this air contacts that surface could surface saturation occur. "
            "Surface heat balance, indoor vapour conditions, contact and drainage are not modelled."
        )

    if kind == "moisture":
        paired = _coincident(df, W, SV)
        paired = paired.loc[paired[SV].gt(0) & paired[W].ge(0)]
        if paired.empty:
            return "Valid humidity ratio and dry-air specific volume are required."
        dt = native_interval_hours(df)
        m_dry = (float(airflow_m3_h) / paired[SV]) * dt
        high = float((m_dry * ((paired[W] - float(target_g_kg)).clip(lower=0)) / 1000.).sum())
        low = float((m_dry * ((float(target_g_kg) - paired[W]).clip(lower=0)) / 1000.).sum())
        return (
            f"At constant actual outdoor volume flow {airflow_m3_h:,.0f} m³/h and target "
            f"{target_g_kg:g} g/kg dry air, the weather-only water-mass differences are "
            f"{high:,.0f} kg removal and {low:,.0f} kg addition over the selected intervals. "
            "These are hypothetical outdoor-air mass-balance quantities, not installed plant "
            "capacity, latent cooling energy, room moisture balance or evidence that "
            "naturally ventilated spaces must be dehumidified."
        )

    if kind == "persistence":
        threshold, above, _ = (args + (80., True, ""))[:3] if args else (80., True, "")
        column = column or RH
        v = numeric(df, column).dropna()
        n = _duration_hours_from_count(
            df, int((v >= float(threshold) if above else v <= float(threshold)).sum()))
        return (
            f"{_fmt_hours(n)} observed hours meet the selected "
            f"{'≥' if above else '≤'} {threshold:g} {UNITS.get(column, '')} condition. "
            "The figure describes contiguous observed events, not a return period. "
            + _physical_context(df, column)
        )

    if not column:
        return "No physical quantity was selected for interpretation."
    v = numeric(df, column).dropna()
    if v.empty:
        return f"No valid {LABELS.get(column, column)} observations support this plot."
    unit = UNITS.get(column, "")
    name = LABELS.get(column, column)
    context = _physical_context(df, column)
    hours = _duration_hours_from_count(df, len(v))

    if kind in ("time_series", "native") or (
        kind == "time series / profile" and "observed values" in caption):
        return (
            f"{_fmt_hours(hours)} observed hours of {name}: "
            f"mean {_fmt(v.mean())} {unit}, range {_fmt(v.min())}–{_fmt(v.max())} {unit}. "
            + context
        )

    if kind in ("profile", "percentile", "time series / profile"):
        centre = "median" if kind == "percentile" or "median" in caption else "mean"
        plotted, x = _plotted_series(fig, centre)
        if plotted.empty:
            plotted, x = _plotted_series(fig)
        if plotted.empty:
            return f"Selected {name} profile contains no numeric plotted ordinates. " + context
        smallest, largest = int(plotted.idxmin()), int(plotted.idxmax())
        at = lambda idx: str(x[idx]) if idx < len(x) else f"plotted point {idx+1}"
        band = ("P05–P95 shows observed variability, not statistical confidence. "
                if kind == "percentile" or "p05" in caption else
                "Min–max shows observed period extrema. " if "min" in caption and "max" in caption else "")
        return (
            f"In this selected {name} profile, the plotted {centre} is lowest at "
            f"{at(smallest)} ({_fmt(plotted.iloc[smallest])} {unit}) and highest at "
            f"{at(largest)} ({_fmt(plotted.iloc[largest])} {unit}). "
            + band + context
        )

    if kind in ("heatmap", "heat map"):
        traces = [tr for tr in getattr(fig, "data", ()) if getattr(tr, "type", "") == "heatmap"]
        if not traces:
            return f"{name.capitalize()} heatmap is based on the selected cell statistic. " + context
        tr = traces[0]
        z = np.asarray(tr.z, dtype=float)
        if z.ndim != 2 or not np.isfinite(z).any():
            return "No finite heatmap cells are displayed."
        lo = np.unravel_index(np.nanargmin(z), z.shape)
        hi = np.unravel_index(np.nanargmax(z), z.shape)
        x, y = list(tr.x), list(tr.y)
        location = lambda p: (f"x={x[p[1]] if p[1] < len(x) else '?'}; "
                              f"y={y[p[0]] if p[0] < len(y) else '?'}")
        return (
            f"Selected {name} cell statistic ranges from {_fmt(z[lo])} {unit} "
            f"({location(lo)}) to {_fmt(z[hi])} {unit} ({location(hi)}). "
            "These are values of the displayed aggregation, not record extrema. " + context
        )

    if kind in ("duration", "duration curve"):
        return (
            f"The {name} duration curve ranks {_fmt_hours(hours)} observed hours "
            "without chronology. "
            f"P05 {_fmt(v.quantile(.05))}, median {_fmt(v.median())}, "
            f"P95 {_fmt(v.quantile(.95))} {unit}. " + context
        )

    if kind in ("histogram", "box", "violin", "monthly boxplot", "monthly violin plot"):
        sentence = (
            f"{name.capitalize()} P05–P95 interval is "
            f"{_fmt(v.quantile(.05))}–{_fmt(v.quantile(.95))} {unit}; "
            f"median {_fmt(v.median())} {unit}. "
        )
        if kind in ("box", "violin", "monthly boxplot", "monthly violin plot") and isinstance(v.index, pd.DatetimeIndex):
            monthly = v.groupby(v.index.month).median()
            if not monthly.empty:
                sentence += (
                    f"Highest monthly median occurs in month {int(monthly.idxmax())}; "
                    f"lowest in month {int(monthly.idxmin())}. "
                )
        return sentence + context

    if kind in ("diurnal", "typical daily profile"):
        if not isinstance(v.index, pd.DatetimeIndex):
            return "The selected diurnal profile needs an hourly time basis."
        centre = "median" if "median" in caption else "mean"
        grouped = v.groupby([v.index.month, v.index.hour])
        m = grouped.median() if centre == "median" else grouped.mean()
        if m.empty:
            return "No month–hour data are available."
        a, b = m.idxmin(), m.idxmax()
        return (
            f"The month–hour {centre} is lowest in month {a[0]} at {a[1]:02d}:00 "
            f"({_fmt(m.min())} {unit}) and highest in month {b[0]} at {b[1]:02d}:00 "
            f"({_fmt(m.max())} {unit}). " + context
        )

    if kind == "occurrence":
        basis = str(args[0]) if args else (
            "Days" if "days" in caption else "Percentage" if "percentage" in caption else "Hours")
        statistic = str(args[1]) if len(args) > 1 else "Mean"
        counts = []
        for tr in getattr(fig, "data", ()):
            raw = getattr(tr, "y", None)
            if raw is None:
                continue
            vals = pd.to_numeric(pd.Series(np.asarray(raw, dtype=object)), errors="coerce").dropna()
            if len(vals):
                amount = float(vals.mean() if basis.lower() == "percentage" else vals.sum())
                counts.append((amount, str(getattr(tr, "name", "") or "unlabelled")))
        dominant = max(counts, key=lambda pair: pair[0])[1] if counts else "not determined"
        detail = (
            f"Complete-day {statistic.lower()} values are classified."
            if basis.lower() == "days" else
            "Class percentages use valid observations per displayed period."
            if basis.lower() == "percentage" else
            "Classes represent disjoint observation-hour frequencies."
        )
        return f"Most frequent displayed {name} class: {dominant}. {detail} " + context

    return (
        f"Selected {name}: mean {_fmt(v.mean())} {unit}, "
        f"range {_fmt(v.min())}–{_fmt(v.max())} {unit}. " + context
    )
