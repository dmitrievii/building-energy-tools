"""Calculated EPW statistics for climate-summary UI panels.

This module derives compact annual, seasonal and monthly statistics directly
from the active EPW hourly data table. It does not read companion weather files;
all indicators are calculated from EPW fields and from already derived columns
such as humidity ratio, moist-air enthalpy, solar position and degree hours.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .decisions import (
    comfort_condition,
    dehumidification_condition,
    economizer_condition,
    humidification_condition,
    natural_ventilation_condition,
    night_flushing_condition,
    shading_condition,
)


MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]


@dataclass(frozen=True)
class MetricDefinition:
    """Definition of a statistic shown in the summary UI."""

    category: str
    metric: str
    value: object
    unit: str
    note: str


def _fmt_number(value: float | int | None, digits: int = 1) -> str:
    """Return a compact string for numeric metric values."""
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}"


def _safe_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric series for a column or an empty series if absent."""
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _safe_mean(df: pd.DataFrame, column: str) -> float:
    """Return the column mean or NaN when the column has no valid values."""
    values = _safe_series(df, column)
    return float(values.mean()) if not values.empty else float("nan")


def _safe_sum(df: pd.DataFrame, column: str) -> float:
    """Return the column sum or NaN when the column has no valid values."""
    values = _safe_series(df, column)
    return float(values.sum()) if not values.empty else float("nan")


def _safe_quantile(df: pd.DataFrame, column: str, q: float) -> float:
    """Return a column quantile or NaN when the column has no valid values."""
    values = _safe_series(df, column)
    return float(values.quantile(q)) if not values.empty else float("nan")


def _safe_min(df: pd.DataFrame, column: str) -> float:
    """Return the column minimum or NaN when the column has no valid values."""
    values = _safe_series(df, column)
    return float(values.min()) if not values.empty else float("nan")


def _safe_max(df: pd.DataFrame, column: str) -> float:
    """Return the column maximum or NaN when the column has no valid values."""
    values = _safe_series(df, column)
    return float(values.max()) if not values.empty else float("nan")


def _timestamp_at_extreme(df: pd.DataFrame, column: str, mode: str) -> str:
    """Return the timestamp for the minimum or maximum value in a column."""
    values = _safe_series(df, column)
    if values.empty:
        return "n/a"
    index = values.idxmin() if mode == "min" else values.idxmax()
    return pd.Timestamp(index).strftime("%Y-%m-%d %H:%M")


def _count(df: pd.DataFrame, condition: pd.Series | np.ndarray | list[bool]) -> int:
    """Return the number of true hours in a Boolean condition."""
    series = pd.Series(condition, index=df.index).fillna(False)
    return int(series.sum())


def _share(hours: int, total_hours: int) -> float:
    """Return a percentage share of hours."""
    return hours / max(total_hours, 1) * 100.0


def _hour_metric(metric: str, hours: int, total_hours: int, note: str) -> MetricDefinition:
    """Create a metric row for a Boolean hourly indicator."""
    return MetricDefinition(
        category="Decision indicators",
        metric=metric,
        value=f"{hours:,} ({_share(hours, total_hours):.1f}%)",
        unit="h",
        note=note,
    )


def _dominant_direction_sector(df: pd.DataFrame, sector_width_deg: int = 30) -> str:
    """Return the most frequent wind-direction sector for non-calm hours."""
    required = {"wind_direction_deg", "wind_speed_m_s"}
    if not required.issubset(df.columns):
        return "n/a"
    data = df[list(required)].dropna()
    data = data[data["wind_speed_m_s"] >= 0.5]
    if data.empty:
        return "n/a"
    sectors = (np.floor(((data["wind_direction_deg"] % 360) + sector_width_deg / 2) / sector_width_deg) * sector_width_deg) % 360
    dominant = int(sectors.value_counts().idxmax())
    return f"{dominant:03d}° ± {sector_width_deg // 2}°"


def _daily_temperature_amplitude(df: pd.DataFrame) -> pd.Series:
    """Return daily dry-bulb temperature amplitudes in Kelvin."""
    if "dry_bulb_temperature_c" not in df.columns:
        return pd.Series(dtype=float)
    return df["dry_bulb_temperature_c"].resample("D").agg(lambda values: values.max() - values.min()).dropna()


def calculated_statistics_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return calculated EPW statistics grouped into UI-ready tables."""
    total_hours = len(df)
    leap_day_hours = int(((df.index.month == 2) & (df.index.day == 29)).sum()) if isinstance(df.index, pd.DatetimeIndex) else 0
    expected_hours = 8784 if leap_day_hours else 8760
    valid_temperature_hours = int(_safe_series(df, "dry_bulb_temperature_c").count())
    missing_values = int(df.isna().sum(numeric_only=False).sum())
    daily_amp = _daily_temperature_amplitude(df)
    tropical_nights = 0
    if "dry_bulb_temperature_c" in df.columns:
        night = df[(df["hour_of_day"] >= 20) | (df["hour_of_day"] <= 6)]
        tropical_nights = int((night["dry_bulb_temperature_c"].resample("D").min() > 20.0).sum())

    tables: dict[str, list[MetricDefinition]] = {
        "Dataset": [
            MetricDefinition("Dataset", "Hourly records", f"{total_hours:,}", "h", "Number of rows used for the current statistics scope."),
            MetricDefinition("Dataset", "Expected typical-year coverage", f"{_share(total_hours, expected_hours):.1f}", "%", "Reference denominator is 8,760 h or 8,784 h when leap-day records exist."),
            MetricDefinition("Dataset", "First timestamp", df.index.min().strftime("%Y-%m-%d %H:%M") if total_hours else "n/a", "", "Start of the active EPW time axis."),
            MetricDefinition("Dataset", "Last timestamp", df.index.max().strftime("%Y-%m-%d %H:%M") if total_hours else "n/a", "", "End of the active EPW time axis."),
            MetricDefinition("Dataset", "Leap-day records", f"{leap_day_hours:,}", "h", "EPW files are usually typical years without leap day, but measured files may include it."),
            MetricDefinition("Dataset", "Valid dry-bulb coverage", f"{_share(valid_temperature_hours, total_hours):.1f}", "%", "Share of rows with usable outdoor dry-bulb temperature."),
            MetricDefinition("Dataset", "Missing values after EPW sentinel cleanup", f"{missing_values:,}", "cells", "Missing-value count after replacing standard EPW sentinel values."),
        ],
        "Temperature": [
            MetricDefinition("Temperature", "Mean dry-bulb temperature", _fmt_number(_safe_mean(df, "dry_bulb_temperature_c")), "°C", "Annual or filtered-period average outdoor temperature."),
            MetricDefinition("Temperature", "Minimum dry-bulb temperature", _fmt_number(_safe_min(df, "dry_bulb_temperature_c")), "°C", f"Timestamp: {_timestamp_at_extreme(df, 'dry_bulb_temperature_c', 'min')}."),
            MetricDefinition("Temperature", "Maximum dry-bulb temperature", _fmt_number(_safe_max(df, "dry_bulb_temperature_c")), "°C", f"Timestamp: {_timestamp_at_extreme(df, 'dry_bulb_temperature_c', 'max')}."),
            MetricDefinition("Temperature", "Dry-bulb P01 / P99", f"{_fmt_number(_safe_quantile(df, 'dry_bulb_temperature_c', 0.01))} / {_fmt_number(_safe_quantile(df, 'dry_bulb_temperature_c', 0.99))}", "°C", "Extreme but less noise-sensitive temperature bounds."),
            MetricDefinition("Temperature", "Dry-bulb P05 / P95", f"{_fmt_number(_safe_quantile(df, 'dry_bulb_temperature_c', 0.05))} / {_fmt_number(_safe_quantile(df, 'dry_bulb_temperature_c', 0.95))}", "°C", "Useful climate envelope for early HVAC and passive-design screening."),
            MetricDefinition("Temperature", "Mean daily temperature amplitude", _fmt_number(float(daily_amp.mean()) if not daily_amp.empty else float('nan')), "K", "Average daily max-min spread; high values indicate night-cooling and thermal-mass potential."),
            MetricDefinition("Temperature", "Maximum daily temperature amplitude", _fmt_number(float(daily_amp.max()) if not daily_amp.empty else float('nan')), "K", "Largest daily outdoor temperature swing."),
            MetricDefinition("Temperature", "Frost hours", f"{_count(df, df['dry_bulb_temperature_c'] < 0.0):,}" if "dry_bulb_temperature_c" in df else "n/a", "h", "Hours with outdoor temperature below 0 °C."),
            MetricDefinition("Temperature", "Very hot hours above 30 °C", f"{_count(df, df['dry_bulb_temperature_c'] > 30.0):,}" if "dry_bulb_temperature_c" in df else "n/a", "h", "Outdoor overheating severity indicator."),
            MetricDefinition("Temperature", "Tropical nights", f"{tropical_nights:,}", "d", "Days where the night-time minimum remains above 20 °C."),
        ],
        "Humidity and psychrometrics": [
            MetricDefinition("Humidity and psychrometrics", "Mean relative humidity", _fmt_number(_safe_mean(df, "relative_humidity_pct")), "%", "Average outdoor relative humidity."),
            MetricDefinition("Humidity and psychrometrics", "Relative humidity P05 / P95", f"{_fmt_number(_safe_quantile(df, 'relative_humidity_pct', 0.05))} / {_fmt_number(_safe_quantile(df, 'relative_humidity_pct', 0.95))}", "%", "Humidity range excluding the most extreme 10% of hours."),
            MetricDefinition("Humidity and psychrometrics", "Mean humidity ratio", _fmt_number(_safe_mean(df, "humidity_ratio_g_kg")), "g/kg dry air", "Psychrometric moisture content calculated from EPW temperature, RH and pressure."),
            MetricDefinition("Humidity and psychrometrics", "Humidity ratio P95", _fmt_number(_safe_quantile(df, "humidity_ratio_g_kg", 0.95)), "g/kg dry air", "Useful indicator for latent-load and dehumidification screening."),
            MetricDefinition("Humidity and psychrometrics", "Maximum dew-point temperature", _fmt_number(_safe_max(df, "dew_point_temperature_c")), "°C", f"Timestamp: {_timestamp_at_extreme(df, 'dew_point_temperature_c', 'max')}."),
            MetricDefinition("Humidity and psychrometrics", "Maximum wet-bulb temperature", _fmt_number(_safe_max(df, "wet_bulb_temperature_c")), "°C", "Relevant for evaporative cooling and heat-rejection concepts."),
            MetricDefinition("Humidity and psychrometrics", "Moist-air enthalpy P95", _fmt_number(_safe_quantile(df, "moist_air_enthalpy_kj_kg", 0.95)), "kJ/kg dry air", "Outdoor-air total heat indicator for economizer and cooling analysis."),
            MetricDefinition("Humidity and psychrometrics", "Dry-air hours below 3 g/kg", f"{_count(df, df['humidity_ratio_g_kg'] < 3.0):,}" if "humidity_ratio_g_kg" in df else "n/a", "h", "Potential humidification or very dry outdoor-air periods."),
            MetricDefinition("Humidity and psychrometrics", "Humid-air hours above 10 g/kg", f"{_count(df, df['humidity_ratio_g_kg'] > 10.0):,}" if "humidity_ratio_g_kg" in df else "n/a", "h", "Potential dehumidification or latent-load periods."),
            MetricDefinition("Humidity and psychrometrics", "High-enthalpy hours above 55 kJ/kg", f"{_count(df, df['moist_air_enthalpy_kj_kg'] > 55.0):,}" if "moist_air_enthalpy_kj_kg" in df else "n/a", "h", "Outdoor-air hours where air-side economizer use is usually limited."),
        ],
        "Solar and daylight": [
            MetricDefinition("Solar and daylight", "Annual GHI", _fmt_number(_safe_sum(df, "global_horizontal_radiation_wh_m2") / 1000.0, 0), "kWh/m²", "Global horizontal irradiation summed from EPW hourly radiation."),
            MetricDefinition("Solar and daylight", "Annual DNI", _fmt_number(_safe_sum(df, "direct_normal_radiation_wh_m2") / 1000.0, 0), "kWh/m²", "Direct-normal irradiation summed from EPW hourly radiation."),
            MetricDefinition("Solar and daylight", "Annual DHI", _fmt_number(_safe_sum(df, "diffuse_horizontal_radiation_wh_m2") / 1000.0, 0), "kWh/m²", "Diffuse-horizontal irradiation summed from EPW hourly radiation."),
            MetricDefinition("Solar and daylight", "Diffuse share of GHI", _fmt_number((_safe_sum(df, "diffuse_horizontal_radiation_wh_m2") / max(_safe_sum(df, "global_horizontal_radiation_wh_m2"), 1.0)) * 100.0), "%", "High values indicate a cloudier/diffuse-light-dominated solar climate."),
            MetricDefinition("Solar and daylight", "Peak GHI", _fmt_number(_safe_max(df, "global_horizontal_radiation_wh_m2"), 0), "Wh/m²", f"Timestamp: {_timestamp_at_extreme(df, 'global_horizontal_radiation_wh_m2', 'max')}."),
            MetricDefinition("Solar and daylight", "Solar hours above 300 Wh/m²", f"{_count(df, df['global_horizontal_radiation_wh_m2'] > 300.0):,}" if "global_horizontal_radiation_wh_m2" in df else "n/a", "h", "Hours relevant for shading, PV and solar-gain assessment."),
            MetricDefinition("Solar and daylight", "Daylight hours above 10,000 lux", f"{_count(df, df['global_horizontal_illuminance_lux'] > 10000.0):,}" if "global_horizontal_illuminance_lux" in df else "n/a", "h", "Simple daylight-availability indicator from EPW illuminance."),
        ],
        "Wind": [
            MetricDefinition("Wind", "Mean wind speed", _fmt_number(_safe_mean(df, "wind_speed_m_s")), "m/s", "Average wind speed from EPW."),
            MetricDefinition("Wind", "Wind speed P95", _fmt_number(_safe_quantile(df, "wind_speed_m_s", 0.95)), "m/s", "High but non-maximum wind-speed indicator."),
            MetricDefinition("Wind", "Maximum wind speed", _fmt_number(_safe_max(df, "wind_speed_m_s")), "m/s", f"Timestamp: {_timestamp_at_extreme(df, 'wind_speed_m_s', 'max')}."),
            MetricDefinition("Wind", "Calm hours below 1 m/s", f"{_count(df, df['wind_speed_m_s'] < 1.0):,}" if "wind_speed_m_s" in df else "n/a", "h", "Low wind-speed hours; relevant for natural ventilation and outdoor comfort."),
            MetricDefinition("Wind", "Strong-wind hours above 8 m/s", f"{_count(df, df['wind_speed_m_s'] > 8.0):,}" if "wind_speed_m_s" in df else "n/a", "h", "Potential wind discomfort or façade-exposure periods."),
            MetricDefinition("Wind", "Dominant wind-direction sector", _dominant_direction_sector(df), "deg", "Most frequent direction sector for hours with wind speed at least 0.5 m/s."),
        ],
        "Sky, precipitation and snow": [
            MetricDefinition("Sky, precipitation and snow", "Mean total sky cover", _fmt_number(_safe_mean(df, "total_sky_cover_tenths")), "tenths", "Average EPW total sky-cover value."),
            MetricDefinition("Sky, precipitation and snow", "Clear-sky hours", f"{_count(df, df['total_sky_cover_tenths'] <= 2.0):,}" if "total_sky_cover_tenths" in df else "n/a", "h", "Hours with total sky cover at or below 2 tenths."),
            MetricDefinition("Sky, precipitation and snow", "Overcast hours", f"{_count(df, df['total_sky_cover_tenths'] >= 8.0):,}" if "total_sky_cover_tenths" in df else "n/a", "h", "Hours with total sky cover at or above 8 tenths."),
            MetricDefinition("Sky, precipitation and snow", "Liquid precipitation depth", _fmt_number(_safe_sum(df, "liquid_precipitation_depth_mm")), "mm", "Total precipitation depth from EPW when the field is available."),
            MetricDefinition("Sky, precipitation and snow", "Wet hours", f"{_count(df, df['liquid_precipitation_depth_mm'] > 0.0):,}" if "liquid_precipitation_depth_mm" in df else "n/a", "h", "Hours with positive liquid precipitation depth."),
            MetricDefinition("Sky, precipitation and snow", "Maximum hourly precipitation", _fmt_number(_safe_max(df, "liquid_precipitation_depth_mm")), "mm/h", "Peak hourly precipitation depth in the EPW field."),
            MetricDefinition("Sky, precipitation and snow", "Maximum snow depth", _fmt_number(_safe_max(df, "snow_depth_cm")), "cm", "Maximum EPW snow-depth field value."),
        ],
        "Decision indicators": [],
    }

    decision_rows = tables["Decision indicators"]
    if "dry_bulb_temperature_c" in df.columns:
        hdd = _safe_sum(df, "heating_degree_hours_kh") / 24.0
        cdd = _safe_sum(df, "cooling_degree_hours_kh") / 24.0
        decision_rows.extend(
            [
                MetricDefinition("Decision indicators", "Heating degree-days, base 18 °C", _fmt_number(hdd, 0), "K·d", "Outdoor-air severity proxy; not a building load."),
                MetricDefinition("Decision indicators", "Cooling degree-days, base 26 °C", _fmt_number(cdd, 0), "K·d", "Outdoor-air cooling severity proxy; not a building load."),
            ]
        )
        decision_rows.append(_hour_metric("Heating-indicated hours below 18 °C", _count(df, df["dry_bulb_temperature_c"] < 18.0), total_hours, "Simple outdoor-air threshold."))
        decision_rows.append(_hour_metric("Cooling-indicated hours above 26 °C", _count(df, df["dry_bulb_temperature_c"] > 26.0), total_hours, "Simple outdoor-air threshold."))

    strategy_conditions: dict[str, tuple[Callable[[pd.DataFrame], pd.Series], str]] = {
        "Comfort-zone outdoor-air hours": (comfort_condition, "T between 20...26 °C and humidity ratio not above 12 g/kg."),
        "Natural-ventilation default hours": (natural_ventilation_condition, "Default limits: 16...26 °C and humidity ratio ≤ 9 g/kg."),
        "Night-flushing default hours": (night_flushing_condition, "Default indicator: hot day followed by cool night hours."),
        "Solar-shading indicator hours": (shading_condition, "Default indicator: outdoor temperature ≥ 24 °C and GHI ≥ 250 Wh/m²."),
        "Air-side economizer default hours": (economizer_condition, "Default indicator: outdoor enthalpy below 50 kJ/kg and dry-bulb within 5...24 °C."),
        "Dehumidification indicator hours": (dehumidification_condition, "Default indicator: humidity ratio above 10 g/kg."),
        "Humidification indicator hours": (humidification_condition, "Default indicator: humidity ratio below 3 g/kg."),
    }
    for metric, (func, note) in strategy_conditions.items():
        try:
            hours = _count(df, func(df))
        except Exception:
            hours = 0
        decision_rows.append(_hour_metric(metric, hours, total_hours, note))

    return {name: _metric_table(rows) for name, rows in tables.items()}


def _metric_table(rows: list[MetricDefinition]) -> pd.DataFrame:
    """Convert metric rows into a display-ready DataFrame."""
    return pd.DataFrame(
        {
            "Metric": [row.metric for row in rows],
            "Value": [row.value for row in rows],
            "Unit": [row.unit for row in rows],
            "Interpretation": [row.note for row in rows],
        }
    )


def monthly_climate_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return a compact monthly climate-summary table calculated from EPW data."""
    rows: list[dict[str, object]] = []
    for month_index, month_name in enumerate(MONTH_ORDER, start=1):
        subset = df[df["month_index"] == month_index]
        if subset.empty:
            continue
        amplitude = _daily_temperature_amplitude(subset)
        rows.append(
            {
                "Month": month_name,
                "Hours": len(subset),
                "Mean dry-bulb [°C]": round(_safe_mean(subset, "dry_bulb_temperature_c"), 1),
                "Min dry-bulb [°C]": round(_safe_min(subset, "dry_bulb_temperature_c"), 1),
                "Max dry-bulb [°C]": round(_safe_max(subset, "dry_bulb_temperature_c"), 1),
                "Mean daily amplitude [K]": round(float(amplitude.mean()) if not amplitude.empty else float("nan"), 1),
                "Mean RH [%]": round(_safe_mean(subset, "relative_humidity_pct"), 1),
                "Mean humidity ratio [g/kg]": round(_safe_mean(subset, "humidity_ratio_g_kg"), 1),
                "Mean enthalpy [kJ/kg]": round(_safe_mean(subset, "moist_air_enthalpy_kj_kg"), 1),
                "GHI [kWh/m²]": round(_safe_sum(subset, "global_horizontal_radiation_wh_m2") / 1000.0, 1),
                "DNI [kWh/m²]": round(_safe_sum(subset, "direct_normal_radiation_wh_m2") / 1000.0, 1),
                "DHI [kWh/m²]": round(_safe_sum(subset, "diffuse_horizontal_radiation_wh_m2") / 1000.0, 1),
                "Mean wind speed [m/s]": round(_safe_mean(subset, "wind_speed_m_s"), 1),
                "HDD18 [K·d]": round(_safe_sum(subset, "heating_degree_hours_kh") / 24.0, 0),
                "CDD26 [K·d]": round(_safe_sum(subset, "cooling_degree_hours_kh") / 24.0, 0),
                "Precipitation [mm]": round(_safe_sum(subset, "liquid_precipitation_depth_mm"), 1),
                "Clear-sky hours": _count(subset, subset["total_sky_cover_tenths"] <= 2.0) if "total_sky_cover_tenths" in subset else 0,
                "Overcast hours": _count(subset, subset["total_sky_cover_tenths"] >= 8.0) if "total_sky_cover_tenths" in subset else 0,
                "Natural-ventilation hours": _count(subset, natural_ventilation_condition(subset)),
            }
        )
    return pd.DataFrame(rows)


def seasonal_climate_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return a seasonal climate-summary table calculated from EPW data."""
    rows: list[dict[str, object]] = []
    for season in SEASON_ORDER:
        subset = df[df["season"] == season]
        if subset.empty:
            continue
        rows.append(
            {
                "Season": season,
                "Hours": len(subset),
                "Mean dry-bulb [°C]": round(_safe_mean(subset, "dry_bulb_temperature_c"), 1),
                "Min dry-bulb [°C]": round(_safe_min(subset, "dry_bulb_temperature_c"), 1),
                "Max dry-bulb [°C]": round(_safe_max(subset, "dry_bulb_temperature_c"), 1),
                "Mean humidity ratio [g/kg]": round(_safe_mean(subset, "humidity_ratio_g_kg"), 1),
                "GHI [kWh/m²]": round(_safe_sum(subset, "global_horizontal_radiation_wh_m2") / 1000.0, 1),
                "Mean wind speed [m/s]": round(_safe_mean(subset, "wind_speed_m_s"), 1),
                "HDD18 [K·d]": round(_safe_sum(subset, "heating_degree_hours_kh") / 24.0, 0),
                "CDD26 [K·d]": round(_safe_sum(subset, "cooling_degree_hours_kh") / 24.0, 0),
                "Precipitation [mm]": round(_safe_sum(subset, "liquid_precipitation_depth_mm"), 1),
                "Natural-ventilation hours": _count(subset, natural_ventilation_condition(subset)),
            }
        )
    return pd.DataFrame(rows)


def extreme_day_summary(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return ranked daily extremes calculated from EPW hourly data."""
    daily = df.resample("D").agg(
        mean_dry_bulb_c=("dry_bulb_temperature_c", "mean"),
        min_dry_bulb_c=("dry_bulb_temperature_c", "min"),
        max_dry_bulb_c=("dry_bulb_temperature_c", "max"),
        max_dew_point_c=("dew_point_temperature_c", "max"),
        max_humidity_ratio_g_kg=("humidity_ratio_g_kg", "max"),
        max_enthalpy_kj_kg=("moist_air_enthalpy_kj_kg", "max"),
        ghi_kwh_m2=("global_horizontal_radiation_wh_m2", lambda values: values.clip(lower=0).sum() / 1000.0),
        max_wind_speed_m_s=("wind_speed_m_s", "max"),
        precipitation_mm=("liquid_precipitation_depth_mm", "sum"),
    ).dropna(how="all")
    daily.index = daily.index.strftime("%Y-%m-%d")
    return {
        "Coldest days": daily.sort_values("min_dry_bulb_c", ascending=True).head(10).round(2),
        "Hottest days": daily.sort_values("max_dry_bulb_c", ascending=False).head(10).round(2),
        "Highest-enthalpy days": daily.sort_values("max_enthalpy_kj_kg", ascending=False).head(10).round(2),
        "Most humid days": daily.sort_values("max_humidity_ratio_g_kg", ascending=False).head(10).round(2),
        "Highest-radiation days": daily.sort_values("ghi_kwh_m2", ascending=False).head(10).round(2),
        "Windiest days": daily.sort_values("max_wind_speed_m_s", ascending=False).head(10).round(2),
        "Wettest days": daily.sort_values("precipitation_mm", ascending=False).head(10).round(2),
    }


def climate_statistics_interpretation(df: pd.DataFrame) -> str:
    """Return a concise interpretation for the calculated EPW statistics section."""
    if df.empty:
        return "No EPW rows are available for the selected statistics scope."
    mean_t = _safe_mean(df, "dry_bulb_temperature_c")
    hdd = _safe_sum(df, "heating_degree_hours_kh") / 24.0
    cdd = _safe_sum(df, "cooling_degree_hours_kh") / 24.0
    ghi = _safe_sum(df, "global_horizontal_radiation_wh_m2") / 1000.0
    nv_hours = _count(df, natural_ventilation_condition(df))
    dehum_hours = _count(df, dehumidification_condition(df))
    dominant = "heating-dominated" if hdd > cdd else "cooling-dominated"
    return (
        f"The selected EPW scope contains {len(df):,} hourly records. Mean outdoor temperature is {_fmt_number(mean_t)} °C. "
        f"With default bases, the climate is {dominant}: HDD18 = {_fmt_number(hdd, 0)} K·d and CDD26 = {_fmt_number(cdd, 0)} K·d. "
        f"Summed GHI is {_fmt_number(ghi, 0)} kWh/m². Default natural-ventilation criteria are met for {nv_hours:,} h, "
        f"while humidity ratio above 10 g/kg occurs for {dehum_hours:,} h. These values are climate indicators only; building-specific loads still require a building model."
    )
