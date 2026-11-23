"""R2.8 outdoor-air and passive-design screening diagnostics.

The diagnostic stages preserve the selected weather screen while making the
roles of temperature, moisture, wind and occupancy explicit. A weather screen
is an evidence layer for architecture, not an airflow network calculation.
"""
from __future__ import annotations

import pandas as pd

from .aggregations import native_interval_hours


T = "dry_bulb_temperature_c"
W = "humidity_ratio_g_kg"
V = "wind_speed_m_s"


def _numeric(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df:
        return pd.Series(float("nan"), index=df.index)
    return pd.to_numeric(df[name], errors="coerce")


def ventilation_screen_stages(
    df: pd.DataFrame,
    *,
    t_min_c: float = 16.0,
    t_max_c: float = 26.0,
    d_max_g_kg: float = 9.0,
    wind_min_m_s: float | None = None,
    wind_max_m_s: float | None = None,
    occupied_only: bool = False,
    occupied_start_hour: int = 8,
    occupied_end_hour: int = 18,
    weekdays_only: bool = False,
) -> pd.DataFrame:
    """Monotone screening stages, counted in physical observed hours.

    The temperature-only stage is useful for showing which active condition
    removes potential periods; it is not a separate comfort definition.
    Missing moisture or optionally required wind values never qualify.
    """
    t = _numeric(df, T)
    w = _numeric(df, W)
    stages = [("Temperature range", t.between(t_min_c, t_max_c))]
    eligible = stages[-1][1] & w.ge(0) & w.le(d_max_g_kg)
    stages.append(("Temperature + moisture", eligible.copy()))
    if wind_min_m_s is not None or wind_max_m_s is not None:
        v = _numeric(df, V)
        eligible = eligible & v.ge(0)
        if wind_min_m_s is not None:
            eligible = eligible & v.ge(wind_min_m_s)
        if wind_max_m_s is not None:
            eligible = eligible & v.le(wind_max_m_s)
        stages.append(("With wind-speed limits", eligible.copy()))
    if occupied_only:
        clock = pd.DatetimeIndex(df.index)
        hours = clock.hour
        if occupied_start_hour <= occupied_end_hour:
            schedule = (hours >= occupied_start_hour) & (hours <= occupied_end_hour)
        else:
            schedule = (hours >= occupied_start_hour) | (hours <= occupied_end_hour)
        if weekdays_only:
            schedule = schedule & (clock.weekday < 5)
        eligible = eligible & pd.Series(schedule, index=df.index)
        stages.append(("During selected occupancy", eligible.copy()))
    dt = native_interval_hours(df)
    total = len(df) * dt
    return pd.DataFrame(
        {
            "screen": [name for name, _ in stages],
            "hours": [float(mask.fillna(False).sum()) * dt for _, mask in stages],
            "share_pct": [
                100.0 * float(mask.fillna(False).sum()) * dt / total if total else 0.0
                for _, mask in stages
            ],
        }
    )


def ventilation_screen_interpretation(
    df: pd.DataFrame,
    stages: pd.DataFrame,
    *,
    t_min_c: float,
    t_max_c: float,
    d_max_g_kg: float,
) -> str:
    """Affirmative, metric-specific architectural finding."""
    first = float(stages["hours"].iloc[0]) if not stages.empty else 0.0
    thermal_moisture = float(stages["hours"].iloc[1]) if len(stages) > 1 else 0.0
    final = float(stages["hours"].iloc[-1]) if not stages.empty else 0.0
    removed = first - thermal_moisture
    text = (
        f"Outdoor temperature is within {t_min_c:g}–{t_max_c:g} °C for "
        f"{first:,.1f} observed hours. The {d_max_g_kg:g} g/kg moisture limit "
        f"retains {thermal_moisture:,.1f} hours and removes {removed:,.1f} "
        f"temperature-qualified hours. The complete selected screen admits "
        f"{final:,.1f} hours ({float(stages['share_pct'].iloc[-1]):.1f}% "
        "of the selected observation period)."
    )
    if first > 0 and thermal_moisture == 0:
        text += (
            " Moisture is the controlling condition for this screening result. "
            "Air-movement and adaptive-comfort assessments should be examined "
            "as distinct design strategies."
        )
    elif first > 0 and thermal_moisture / first < 0.5:
        text += (
            " Moisture removes more than half the temperature-qualified "
            "hours; controlled or hybrid ventilation merits separate assessment."
        )
    else:
        text += (
            " The retained hours indicate when outdoor air aligns with the "
            "selected supply-air criteria. Review their timing and persistence "
            "for window and control scheduling."
        )
    return text


def night_flushing_interpretation(
    df: pd.DataFrame,
    mask: pd.Series,
    *,
    hot_day_c: float,
    night_max_c: float,
    night_end_hour: int = 6,
) -> str:
    """Report eligible physical hours and qualifying overnight periods."""
    aligned = mask.reindex(df.index).fillna(False).astype(bool)
    dt = native_interval_hours(df)
    hours = float(aligned.sum()) * dt
    if aligned.any():
        idx = pd.DatetimeIndex(df.index[aligned])
        anchor = idx.normalize() - pd.to_timedelta((idx.hour <= night_end_hour).astype(int), unit="D")
        night_count = int(pd.Index(anchor).nunique())
        peak_month = int(
            pd.Series(dt, index=idx).groupby(idx.month).sum().idxmax()
        )
        month_text = f" The largest eligible duration occurs in month {peak_month}."
    else:
        night_count = 0
        month_text = ""
    return (
        f"The night-cooling screen identifies {hours:,.1f} eligible hours "
        f"across {night_count:,} overnight periods, following days reaching "
        f"{hot_day_c:g} °C with nighttime outdoor air at or below "
        f"{night_max_c:g} °C."
        + month_text
        + " These periods inform operable-opening schedules and the potential "
        "for precooling exposed thermal mass."
    )
