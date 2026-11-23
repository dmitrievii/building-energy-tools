"""Figure-specific, source/plot-bound temperature interpretation (R2.1).

This module does not estimate indoor comfort, energy demand, HVAC capacity, or
night-ventilation performance from outdoor temperature alone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from .interpretations import _fmt, _fmt_hours, _duration_hours_from_count


def _temperature_plot_series(fig, name=None):
    """Finite ordinates actually plotted; omit reference-quantile overlays."""
    for trace in getattr(fig, "data", ()):
        trace_name = str(getattr(trace, "name", "") or "")
        if name is not None and name.lower() not in trace_name.lower():
            continue
        if name is None and ("quantiles" in trace_name.lower() or "threshold" in trace_name.lower()):
            continue
        raw_y = getattr(trace, "y", None)
        values = np.asarray(() if raw_y is None else raw_y, dtype=object)
        if values.ndim != 1 or not len(values):
            continue
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        if numeric.notna().any():
            raw_x = getattr(trace, "x", None)
            xs = list(() if raw_x is None else raw_x)
            return numeric, xs
    return pd.Series(dtype=float), []


def temperature_figure_interpretation(df, fig, kind, *, column="dry_bulb_temperature_c", title="", thresholds=(18., 26.)):
    """Interpret the *selected figure*, not an unrelated annual summary.

    Plot values reflect actual figure aggregations; source counts reflect valid
    records in the active selection. Temperature thresholds are outdoor screens.
    """
    data = pd.to_numeric(df.get(column, pd.Series(dtype=float)), errors="coerce").dropna()
    if data.empty:
        return "No valid temperature observations support the selected figure."
    name = title or getattr(getattr(fig.layout, "title", None), "text", "") or ""
    lower_name = name.lower()
    kind = str(kind).lower()
    hours = _duration_hours_from_count(df, len(data))
    total = f"{_fmt_hours(hours)} observed hours"
    if column == "dry_bulb_temperature_c":
        low, high = map(float, thresholds)
        h_low = _duration_hours_from_count(df, int(data.lt(low).sum()))
        h_high = _duration_hours_from_count(df, int(data.gt(high).sum()))
        climate = (f"Outdoor exposure: {_fmt_hours(h_low)} h below {low:g} °C and "
                   f"{_fmt_hours(h_high)} h above {high:g} °C. "
                   "These are not building heating or cooling loads.")
    else:
        climate = "This temperature quantity alone does not establish building heating/cooling loads or indoor comfort."

    if kind in ("time_series", "native") or (kind == "time series / profile" and "observed values" in lower_name):
        return (f"Observed temperatures over {total} range from {_fmt(data.min())} to "
                f"{_fmt(data.max())} °C (mean {_fmt(data.mean())} °C). " + climate)

    if kind in ("profile", "percentile", "time series / profile"):
        metric = "Median" if kind == "percentile" or "median" in lower_name else "Mean"
        series, x = _temperature_plot_series(fig, metric)
        if series.empty:
            series, x = _temperature_plot_series(fig)
        if series.empty:
            return "Selected temperature profile reflects only valid observations. " + climate
        lo, hi = int(series.idxmin()), int(series.idxmax())
        at = lambda idx: str(x[idx]) if idx < len(x) else f"point {idx+1}"
        envelope = ("The P05–P95 band describes source variability, not a confidence interval. "
                    if kind == "percentile" or "p05" in lower_name else
                    "The min–max band describes observed extremes within each plotted period. "
                    if "max" in lower_name else "")
        return (f"In this selected profile, the plotted {metric.lower()} is lowest at "
                f"{at(lo)} ({_fmt(series.iloc[lo])} °C) and highest at "
                f"{at(hi)} ({_fmt(series.iloc[hi])} °C). {envelope}" + climate)

    if kind in ("heatmap", "heat map"):
        traces = [t for t in getattr(fig, "data", ()) if getattr(t, "type", "") == "heatmap"]
        if not traces:
            return "Temperature heatmap represents the selected cell statistic. " + climate
        trace = traces[0]
        z = np.asarray(trace.z, dtype=float)
        if z.ndim != 2 or not np.isfinite(z).any():
            return "No valid temperature cells are plotted."
        lo, hi = np.unravel_index(np.nanargmin(z), z.shape), np.unravel_index(np.nanargmax(z), z.shape)
        x, y = list(trace.x), list(trace.y)
        cell = lambda pos: f'{str(x[pos[1]]) if pos[1]<len(x) else "?"}, hour {str(y[pos[0]]) if pos[0]<len(y) else "?"}'
        return (f"For the selected heatmap statistic, the lowest displayed cell is "
                f"{_fmt(z[lo])} °C ({cell(lo)}) and the highest is {_fmt(z[hi])} °C ({cell(hi)}). "
                "The common absolute colour scale indicates outdoor temperature, not indoor comfort. " + climate)

    if kind in ("duration", "duration curve"):
        return (f"The temperature duration curve ranks {total} without preserving chronology. "
                f"P05 = {_fmt(data.quantile(.05))} °C, median = {_fmt(data.median())} °C, "
                f"P95 = {_fmt(data.quantile(.95))} °C. " + climate)

    if kind in ("histogram", "box", "violin", "monthly boxplot", "monthly violin plot"):
        base = (f"The observed distribution spans {_fmt(data.quantile(.05))}–"
                f"{_fmt(data.quantile(.95))} °C from P05 to P95; median {_fmt(data.median())} °C. ")
        if kind in ("box", "violin", "monthly boxplot", "monthly violin plot") and isinstance(data.index, pd.DatetimeIndex):
            monthly = data.groupby(data.index.month).median()
            if not monthly.empty:
                base += (f"Highest monthly median: month {int(monthly.idxmax())} "
                         f"({_fmt(monthly.max())} °C); lowest: month {int(monthly.idxmin())} "
                         f"({_fmt(monthly.min())} °C). ")
        return base + "Distribution indicates outdoor exposure, not indoor comfort or equipment capacity."

    if kind in ("diurnal", "typical daily profile"):
        if not isinstance(data.index, pd.DatetimeIndex):
            return "The plotted daily profile describes outdoor clock-hour variability."
        statistic = "median" if "median" in lower_name else "mean"
        pooled = data.groupby([data.index.month, data.index.hour])
        series = pooled.median() if statistic == "median" else pooled.mean()
        if series.empty:
            return "No selected month-hour profiles are available."
        low_at, high_at = series.idxmin(), series.idxmax()
        return (f"Pooled month–hour {statistic} reaches {_fmt(series.min())} °C "
                f"(month {low_at[0]}, {low_at[1]:02d}:00) and {_fmt(series.max())} °C "
                f"(month {high_at[0]}, {high_at[1]:02d}:00). "
                "Use the seasonal day–night contrast to screen passive control; night-cooling viability also depends on indoor temperature, humidity and airflow.")

    if kind == "amplitude":
        series, x = _temperature_plot_series(fig)
        if series.empty:
            return "Amplitude is max minus min for each selected period; it is not necessarily the daily range."
        max_at = int(series.idxmax())
        label = str(x[max_at]) if max_at < len(x) else "selected period"
        scale = ("daily" if "daily" in lower_name else "weekly" if "weekly" in lower_name else
                 "monthly" if "monthly" in lower_name else "seasonal" if "seasonal" in lower_name else
                 "annual" if "annual" in lower_name else "selected-period")
        return (f"The mean plotted {scale} amplitude is {_fmt(series.mean())} K; "
                f"maximum {_fmt(series.max())} K at {label}. "
                "Amplitude is the within-period outdoor maximum minus minimum. "
                "Weekly, monthly and annual ranges are not diurnal swings; none independently demonstrates night-flushing potential.")

    if kind == "occurrence":
        basis = "percentage" if "percentage" in lower_name else "days" if "days" in lower_name else "hours"
        if basis == "days":
            detail = "Each day is classified by the selected complete-day statistic, not hourly temperature."
        elif basis == "percentage":
            detail = "Percentages use valid source observations as the denominator within each reported period."
        else:
            detail = "Classes count observed source intervals and are mutually exclusive."
        classes = []
        for trace in getattr(fig, "data", ()):
            ys = pd.to_numeric(pd.Series(list(getattr(trace, "y", ()))), errors="coerce").dropna()
            if not ys.empty:
                amount = float(ys.mean() if basis == "percentage" else ys.sum())
                classes.append((amount, str(getattr(trace, "name", "") or "unnamed class")))
        dominant = max(classes)[1] if classes else "n/a"
        return (f"The most frequent plotted temperature class is {dominant} "
                f"(based on {basis} for the selected periods). " + detail + " " + climate)

    if kind == "degree":
        values = []
        for trace in getattr(fig, "data", ()):
            nm = str(getattr(trace, "name", "") or "")
            ys = pd.to_numeric(pd.Series(list(getattr(trace, "y", ()))), errors="coerce").dropna()
            if not ys.empty:
                values.append((nm, float(ys.sum())))
        metric = "degree-hours" if "degree-hours" in lower_name else "degree-days"
        unit = "K·h" if metric == "degree-hours" else "K·d"
        result = ", ".join(f"{nm}: {_fmt(v)} {unit}" for nm, v in values)
        method = ("Source-interval temperature differences are integrated." if metric == "degree-hours"
                  else "Complete daily mean outdoor temperatures are evaluated before applying the base.")
        return f"{result}. {method} These are climatic exposure indicators, not building energy demand."

    if kind == "temp_threshold":
        counts = []
        for trace in getattr(fig, "data", ()):
            ys = pd.to_numeric(pd.Series(list(getattr(trace, "y", ()))), errors="coerce").dropna()
            if not ys.empty:
                counts.append(f'{str(getattr(trace, "name", "") or "Condition")}: {_fmt_hours(ys.sum())} h')
        return ("; ".join(counts) + ". " if counts else "") + "Strict outdoor thresholds describe climatic exposure, not actual building heating/cooling demand."

    if kind == "day_indicators":
        return ("Frost days use daily minimum below 0 °C. Tropical nights use daily minimum "
                "at or above 20 °C for complete calendar days; this is not an occupied-night comfort assessment.")
    if kind == "temp_events":
        return ("An event requires at least three consecutive complete qualifying days. "
                "Daily maximum, mean and minimum criteria are different; event counts and durations must not be interchanged.")
    return climate
