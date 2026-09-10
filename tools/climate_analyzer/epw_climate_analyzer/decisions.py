"""Decision-support indicators for climate-responsive design."""

from __future__ import annotations

import pandas as pd


def add_degree_metrics(
    df: pd.DataFrame,
    heating_base_c: float = 18.0,
    cooling_base_c: float = 26.0,
) -> pd.DataFrame:
    """Add hourly heating and cooling degree-hour proxy columns."""
    data = df.copy()
    t = data["dry_bulb_temperature_c"]
    data["heating_degree_hours_kh"] = (heating_base_c - t).clip(lower=0)
    data["cooling_degree_hours_kh"] = (t - cooling_base_c).clip(lower=0)
    return data


def natural_ventilation_condition(
    df: pd.DataFrame,
    t_min_c: float = 16.0,
    t_max_c: float = 26.0,
    d_max_g_kg: float = 9.0,
    rh_max_pct: float | None = None,
    wind_min_m_s: float | None = None,
    wind_max_m_s: float | None = None,
    occupied_only: bool = False,
    occupied_start_hour: int = 8,
    occupied_end_hour: int = 18,
    weekdays_only: bool = False,
) -> pd.Series:
    """Return a Boolean mask for outdoor-air natural ventilation suitability.

    When ``occupied_only`` is true, the mask is additionally restricted to the
    user-defined occupied-hour interval. Intervals may cross midnight, for
    example 22...6. ``weekdays_only`` keeps Monday through Friday only.
    """
    condition = df["dry_bulb_temperature_c"].between(t_min_c, t_max_c)
    if "humidity_ratio_g_kg" in df.columns:
        condition &= df["humidity_ratio_g_kg"] <= d_max_g_kg
    if rh_max_pct is not None:
        condition &= df["relative_humidity_pct"] <= rh_max_pct
    if wind_min_m_s is not None:
        condition &= df["wind_speed_m_s"] >= wind_min_m_s
    if wind_max_m_s is not None:
        condition &= df["wind_speed_m_s"] <= wind_max_m_s
    if occupied_only:
        start = int(max(0, min(23, occupied_start_hour)))
        end = int(max(0, min(23, occupied_end_hour)))
        if start <= end:
            occupied_mask = df["hour_of_day"].between(start, end)
        else:
            occupied_mask = (df["hour_of_day"] >= start) | (df["hour_of_day"] <= end)
        if weekdays_only:
            occupied_mask &= pd.Series(df.index.weekday < 5, index=df.index)
        condition &= occupied_mask
    return condition.fillna(False)


def night_flushing_condition(
    df: pd.DataFrame,
    day_hot_threshold_c: float = 26.0,
    night_max_c: float = 20.0,
    night_start_hour: int = 22,
    night_end_hour: int = 6,
) -> pd.Series:
    """Return a Boolean mask for potential night-flushing hours.

    For the usual cross-midnight interval (for example 22...6), late-evening
    hours are evaluated against the maximum temperature of the same calendar
    day, while early-morning hours are evaluated against the preceding calendar
    day. This prevents 00...06 from using temperatures that occur later in the
    future day.
    """
    start = int(max(0, min(23, night_start_hour)))
    end = int(max(0, min(23, night_end_hour)))
    hour = df["hour_of_day"]

    crosses_midnight = start > end
    if crosses_midnight:
        is_night = (hour >= start) | (hour <= end)
    else:
        is_night = hour.between(start, end)

    cool_enough = df["dry_bulb_temperature_c"] <= night_max_c
    daily_max = df["dry_bulb_temperature_c"].resample("D").max()
    normalized_days = pd.DatetimeIndex(df.index).normalize()

    current_day_max = pd.Series(
        daily_max.reindex(normalized_days).to_numpy(),
        index=df.index,
        dtype=float,
    )
    previous_day_max = pd.Series(
        daily_max.shift(1).reindex(normalized_days).to_numpy(),
        index=df.index,
        dtype=float,
    )

    if crosses_midnight:
        hot_day_reference = current_day_max.copy()
        early_morning = hour <= end
        hot_day_reference.loc[early_morning] = previous_day_max.loc[early_morning]
    else:
        # A non-crossing night interval in the early half of the day belongs to
        # the preceding evening; an evening-only interval belongs to the same day.
        if end <= 12:
            hot_day_reference = previous_day_max
        else:
            hot_day_reference = current_day_max

    follows_hot_day = hot_day_reference >= day_hot_threshold_c
    return (is_night & cool_enough & follows_hot_day).fillna(False)


def economizer_condition(
    df: pd.DataFrame,
    return_air_enthalpy_kj_kg: float = 50.0,
    t_min_c: float = 5.0,
    t_max_c: float = 24.0,
) -> pd.Series:
    """Return a Boolean mask for simple air-side economizer availability."""
    condition = df["moist_air_enthalpy_kj_kg"] < return_air_enthalpy_kj_kg
    condition &= df["dry_bulb_temperature_c"].between(t_min_c, t_max_c)
    return condition.fillna(False)


def dehumidification_condition(df: pd.DataFrame, d_target_g_kg: float = 10.0) -> pd.Series:
    """Return a Boolean mask for hours exceeding a target outdoor humidity ratio."""
    return (df["humidity_ratio_g_kg"] > d_target_g_kg).fillna(False)


def humidification_condition(df: pd.DataFrame, d_target_g_kg: float = 3.0) -> pd.Series:
    """Return a Boolean mask for hours below a target outdoor humidity ratio."""
    return (df["humidity_ratio_g_kg"] < d_target_g_kg).fillna(False)


def shading_condition(
    df: pd.DataFrame,
    t_threshold_c: float = 24.0,
    ghi_threshold_wh_m2: float = 250.0,
) -> pd.Series:
    """Return a Boolean mask for hours where solar shading is likely useful."""
    condition = df["dry_bulb_temperature_c"] >= t_threshold_c
    condition &= df["global_horizontal_radiation_wh_m2"] >= ghi_threshold_wh_m2
    return condition.fillna(False)


def comfort_condition(
    df: pd.DataFrame,
    t_min_c: float = 20.0,
    t_max_c: float = 26.0,
    d_min_g_kg: float | None = None,
    d_max_g_kg: float | None = 12.0,
) -> pd.Series:
    """Return a Boolean mask for a simple outdoor-air comfort zone."""
    condition = df["dry_bulb_temperature_c"].between(t_min_c, t_max_c)
    if d_min_g_kg is not None:
        condition &= df["humidity_ratio_g_kg"] >= d_min_g_kg
    if d_max_g_kg is not None:
        condition &= df["humidity_ratio_g_kg"] <= d_max_g_kg
    return condition.fillna(False)


def passive_strategy_table(df: pd.DataFrame) -> pd.DataFrame:
    """Classify climate hours into simple passive/HVAC strategy buckets."""
    strategies = {
        "Comfort without conditioning": comfort_condition(df),
        "Natural ventilation": natural_ventilation_condition(df),
        "Night flushing": night_flushing_condition(df),
        "Solar shading likely useful": shading_condition(df),
        "Air-side economizer": economizer_condition(df),
        "Dehumidification likely useful": dehumidification_condition(df),
        "Humidification likely useful": humidification_condition(df),
        "Heating likely required": df["dry_bulb_temperature_c"] < 18.0,
        "Cooling likely required": df["dry_bulb_temperature_c"] > 26.0,
    }
    rows = []
    for strategy, mask in strategies.items():
        hours = int(mask.fillna(False).sum())
        rows.append({"strategy": strategy, "hours": hours, "share_pct": hours / max(len(df), 1) * 100.0})
    return pd.DataFrame(rows).sort_values("hours", ascending=False)


def passive_strategy_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Return monthly hours for selected passive and HVAC strategy indicators."""
    masks = {
        "Comfort": comfort_condition(df),
        "Natural ventilation": natural_ventilation_condition(df),
        "Night flushing": night_flushing_condition(df),
        "Shading": shading_condition(df),
        "Economizer": economizer_condition(df),
        "Dehumidification": dehumidification_condition(df),
        "Humidification": humidification_condition(df),
        "Heating": df["dry_bulb_temperature_c"] < 18.0,
        "Cooling": df["dry_bulb_temperature_c"] > 26.0,
    }
    out = pd.DataFrame(index=range(1, 13))
    for label, mask in masks.items():
        temp = pd.Series(mask.fillna(False).astype(int).values, index=df.index)
        out[label] = temp.groupby(df["month_index"]).sum()
    out.index.name = "month"
    return out.fillna(0)


def rejection_reasons_for_nv(
    df: pd.DataFrame,
    t_min_c: float,
    t_max_c: float,
    d_max_g_kg: float,
    wind_min_m_s: float | None = None,
    wind_max_m_s: float | None = None,
) -> pd.DataFrame:
    """Return a table explaining why hours are rejected for natural ventilation.

    Missing-data diagnostics are handled by the Data Quality page, so this chart
    only reports active design-limit reasons. Wind-speed reasons are included
    only when the corresponding wind limits are enabled by the user.
    """
    reasons = {
        "Too cold": df["dry_bulb_temperature_c"] < t_min_c,
        "Too hot": df["dry_bulb_temperature_c"] > t_max_c,
        "Too humid": df["humidity_ratio_g_kg"] > d_max_g_kg,
    }
    if wind_min_m_s is not None:
        reasons["Wind too weak"] = df["wind_speed_m_s"] < wind_min_m_s
    if wind_max_m_s is not None:
        reasons["Wind too strong"] = df["wind_speed_m_s"] > wind_max_m_s

    rows = []
    for reason, mask in reasons.items():
        hours = int(mask.fillna(False).sum())
        rows.append({"reason": reason, "hours": hours, "share_pct": hours / max(len(df), 1) * 100.0})
    return pd.DataFrame(rows).sort_values("hours", ascending=False)
