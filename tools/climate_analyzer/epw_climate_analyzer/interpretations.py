"""Automatic interpretation text for climate charts.

The functions in this module create short, calculation-based comments that are
shown below interactive charts. They are intentionally concise and deterministic
so that the site can be used in reports and design discussions.
"""

from __future__ import annotations

import pandas as pd


def _fmt(value: float, digits: int = 1) -> str:
    """Format a numeric value for compact chart interpretation."""
    if pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def variable_interpretation(
    df: pd.DataFrame,
    column: str,
    label: str,
    unit: str,
    high_threshold: float | None = None,
    low_threshold: float | None = None,
) -> str:
    """Return a short statistical interpretation for one climate variable."""
    values = df[column].dropna()
    if values.empty:
        return f"No valid {label} data are available for the selected filter."

    mean = values.mean()
    minimum = values.min()
    maximum = values.max()
    p05 = values.quantile(0.05)
    p95 = values.quantile(0.95)
    text = (
        f"The selected period contains {len(values):,} valid hourly values. "
        f"Mean {label} is {_fmt(mean)} {unit}; the range is {_fmt(minimum)}...{_fmt(maximum)} {unit}. "
        f"The 5th to 95th percentile interval is {_fmt(p05)}...{_fmt(p95)} {unit}."
    )
    if high_threshold is not None:
        high_hours = int((values > high_threshold).sum())
        text += f" {high_hours:,} hours exceed {high_threshold:g} {unit}."
    if low_threshold is not None:
        low_hours = int((values < low_threshold).sum())
        text += f" {low_hours:,} hours are below {low_threshold:g} {unit}."
    return text


def temperature_interpretation(df: pd.DataFrame, heat_threshold: float, cool_threshold: float) -> str:
    """Interpret outdoor dry-bulb temperature for HVAC and passive design."""
    t = df["dry_bulb_temperature_c"].dropna()
    if t.empty:
        return "No valid dry-bulb temperature data are available."
    cold_hours = int((t < heat_threshold).sum())
    hot_hours = int((t > cool_threshold).sum())
    tropical_nights = int((df.between_time("20:00", "06:00")["dry_bulb_temperature_c"].resample("D").min() > 20).sum())
    amplitude = df["dry_bulb_temperature_c"].resample("D").agg(lambda x: x.max() - x.min()).mean()
    return (
        f"Mean outdoor temperature is {_fmt(t.mean())} °C. "
        f"There are {cold_hours:,} hours below {heat_threshold:g} °C and {hot_hours:,} hours above {cool_threshold:g} °C. "
        f"The average daily temperature amplitude is {_fmt(amplitude)} K. "
        f"The file contains approximately {tropical_nights:,} tropical nights with night minimum above 20 °C."
    )


def degree_day_interpretation(df: pd.DataFrame) -> str:
    """Interpret heating and cooling degree-hour proxies."""
    hdh = df.get("heating_degree_hours_kh", pd.Series(dtype=float)).sum()
    cdh = df.get("cooling_degree_hours_kh", pd.Series(dtype=float)).sum()
    hdd = hdh / 24.0
    cdd = cdh / 24.0
    dominant = "heating-dominated" if hdd > cdd else "cooling-dominated"
    return (
        f"The selected thresholds produce {hdd:,.0f} heating degree-days and {cdd:,.0f} cooling degree-days. "
        f"On this simplified basis the climate is {dominant}."
    )


def natural_ventilation_interpretation(df: pd.DataFrame, mask: pd.Series) -> str:
    """Interpret natural ventilation availability from a Boolean suitability mask."""
    hours = int(mask.fillna(False).sum())
    share = hours / max(len(df), 1) * 100.0
    monthly = mask.fillna(False).astype(int).groupby(df["month_index"]).sum()
    if monthly.empty:
        best_month = "n/a"
        best_hours = 0
    else:
        best_month = int(monthly.idxmax())
        best_hours = int(monthly.max())
    return (
        f"Natural ventilation is suitable for {hours:,} hours ({share:.1f}% of the selected period). "
        f"The strongest month is {best_month} with {best_hours:,} suitable hours. "
        f"If this indicator is low during occupied hours, the design should rely on mechanical ventilation, night flushing or hybrid control rather than manual window opening alone."
    )


def solar_interpretation(df: pd.DataFrame) -> str:
    """Interpret solar radiation availability and cooling-risk coincidence."""
    ghi = df["global_horizontal_radiation_wh_m2"].dropna().clip(lower=0)
    if ghi.empty:
        return "No valid global horizontal radiation data are available."
    annual = ghi.sum() / 1000.0
    sunny_hot = int(((df["global_horizontal_radiation_wh_m2"] > 300) & (df["dry_bulb_temperature_c"] > 24)).sum())
    diffuse_share = df["diffuse_horizontal_radiation_wh_m2"].sum() / max(df["global_horizontal_radiation_wh_m2"].sum(), 1)
    return (
        f"Annual horizontal irradiation is approximately {annual:,.0f} kWh/m². "
        f"The diffuse fraction is about {diffuse_share * 100:.1f}% of GHI. "
        f"There are {sunny_hot:,} hours with GHI above 300 Wh/m² and outdoor temperature above 24 °C; these hours are relevant for solar shading and cooling-risk assessment."
    )


def wind_interpretation(df: pd.DataFrame) -> str:
    """Interpret wind-speed and wind-direction data."""
    speed = df["wind_speed_m_s"].dropna()
    if speed.empty:
        return "No valid wind data are available."
    calm = int((speed < 1.0).sum())
    strong = int((speed > 8.0).sum())
    mean = speed.mean()
    return (
        f"Mean wind speed is {_fmt(mean)} m/s. "
        f"There are {calm:,} calm hours below 1 m/s and {strong:,} strong-wind hours above 8 m/s. "
        f"The wind rose should be checked together with natural-ventilation eligibility, because frequent wind alone does not guarantee usable ventilation hours."
    )


def sky_interpretation(df: pd.DataFrame) -> str:
    """Interpret sky cover and daylight availability."""
    cover = df["total_sky_cover_tenths"].dropna()
    illum = df.get("global_horizontal_illuminance_lux", pd.Series(dtype=float)).dropna()
    if cover.empty and illum.empty:
        return "No valid sky cover or illuminance data are available."
    text = ""
    if not cover.empty:
        clear = int((cover <= 2).sum())
        overcast = int((cover >= 8).sum())
        text += f"The file contains {clear:,} clear-sky hours and {overcast:,} overcast hours based on total sky cover. "
    if not illum.empty:
        daylight = int((illum > 10000).sum())
        text += f"Global horizontal illuminance exceeds 10,000 lux for {daylight:,} hours, indicating useful daylight availability for façade and daylighting studies."
    return text


def psychrometric_interpretation(df: pd.DataFrame) -> str:
    """Interpret the psychrometric point cloud."""
    d = df["humidity_ratio_g_kg"].dropna()
    h = df["moist_air_enthalpy_kj_kg"].dropna()
    if d.empty or h.empty:
        return "No valid psychrometric data are available."
    dry = int((d < 3).sum())
    humid = int((d > 10).sum())
    high_enthalpy = int((h > 55).sum())
    return (
        f"The humidity-ratio range is {_fmt(d.min())}...{_fmt(d.max())} g/kg. "
        f"There are {dry:,} very dry hours below 3 g/kg and {humid:,} humid hours above 10 g/kg. "
        f"{high_enthalpy:,} hours exceed 55 kJ/kg moist-air enthalpy, which is relevant for economizer and cooling/dehumidification decisions."
    )


def hvac_interpretation(df: pd.DataFrame) -> str:
    """Interpret HVAC-oriented climate indicators."""
    heat_hours = int((df["dry_bulb_temperature_c"] < 18).sum())
    cool_hours = int((df["dry_bulb_temperature_c"] > 26).sum())
    dehum_hours = int((df["humidity_ratio_g_kg"] > 10).sum())
    humid_hours = int((df["humidity_ratio_g_kg"] < 3).sum())
    return (
        f"Using simple outdoor-air thresholds, heating is indicated for {heat_hours:,} hours and cooling for {cool_hours:,} hours. "
        f"Latent treatment is also relevant: {dehum_hours:,} hours exceed 10 g/kg and {humid_hours:,} hours are below 3 g/kg. "
        f"These indicators are climate proxies; actual plant sizing still requires building loads, internal gains, schedules and ventilation rates."
    )


def data_quality_interpretation(issue_count: int, error_count: int) -> str:
    """Interpret the EPW data-quality diagnostics table."""
    if issue_count == 0:
        return "No common EPW data-quality issues were detected by the built-in checks."
    return (
        f"The diagnostics found {issue_count} issue categories, including {error_count} error-level categories. "
        f"Review these items before using the file for design decisions, especially if solar radiation, humidity or wind fields are critical."
    )
