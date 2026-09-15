"""Heating/cooling degree-hour and degree-day climate indicators.

Degree-hours and degree-days are deliberately treated as two distinct methods:

* degree-hours integrate temperature difference at the native source interval;
* degree-days first calculate daily mean outdoor temperature and then apply the
  heating/cooling base temperatures.

They are therefore not interchangeable through a simple division by 24 when a
threshold is crossed within a day.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd


DegreeMetric = Literal["Degree-hours", "Degree-days"]
DegreeAggregation = Literal["Daily", "Weekly", "Monthly", "Seasonal", "Annual"]

SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
RESAMPLE_RULES: dict[str, str] = {
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
    "Annual": "YE",
}


def _validate_bases(heating_base_c: float, cooling_base_c: float) -> None:
    if float(heating_base_c) > float(cooling_base_c):
        raise ValueError("Heating base temperature must not exceed cooling base temperature.")


def _native_interval_hours(df: pd.DataFrame, interval_minutes: float | None) -> float:
    """Return source-interval duration without inferring false gaps from filters."""
    if interval_minutes is None:
        interval_minutes = df.attrs.get("canonical_native_interval_minutes", 60.0)
    try:
        minutes = float(interval_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("Native interval must be a positive number of minutes.") from exc
    if minutes <= 0:
        raise ValueError("Native interval must be a positive number of minutes.")
    return minutes / 60.0


def _season_from_month(month: int) -> str:
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Spring"
    if month in (6, 7, 8):
        return "Summer"
    return "Autumn"


def _aggregate_table(table: pd.DataFrame, aggregation: DegreeAggregation) -> pd.DataFrame:
    if aggregation == "Daily":
        return table.resample("D").sum(min_count=1).dropna(how="all")
    if aggregation == "Seasonal":
        season = pd.Categorical(
            [_season_from_month(int(ts.month)) for ts in table.index],
            categories=SEASON_ORDER,
            ordered=True,
        )
        grouped = table.groupby(season, observed=False).sum(min_count=1)
        grouped.index.name = "Season"
        return grouped.reindex(SEASON_ORDER).dropna(how="all")
    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported degree-metric aggregation: {aggregation}")
    return table.resample(rule).sum(min_count=1).dropna(how="all")


def degree_metric_table(
    df: pd.DataFrame,
    *,
    heating_base_c: float = 18.0,
    cooling_base_c: float = 26.0,
    metric: DegreeMetric = "Degree-hours",
    aggregation: DegreeAggregation = "Monthly",
    interval_minutes: float | None = None,
) -> pd.DataFrame:
    """Calculate heating/cooling degree metrics with explicit reference bases.

    Parameters
    ----------
    df:
        Climate data containing ``dry_bulb_temperature_c`` on a DatetimeIndex.
    heating_base_c, cooling_base_c:
        User-selected climate balance/reference temperatures. They are not a
        building load model and should not be interpreted as automatically equal
        to indoor thermostat setpoints.
    metric:
        ``Degree-hours`` uses every source interval. ``Degree-days`` uses daily
        mean outdoor temperature before applying the temperature difference.
    aggregation:
        Display/summation period for the resulting extensive indicator.
    interval_minutes:
        Optional source cadence override for degree-hours. If omitted, the
        canonical dataframe attribute is used when present, otherwise 60 min.
    """
    _validate_bases(heating_base_c, cooling_base_c)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Degree metrics require a pandas DatetimeIndex.")
    if "dry_bulb_temperature_c" not in df.columns:
        raise KeyError("dry_bulb_temperature_c")

    temperature = pd.to_numeric(df["dry_bulb_temperature_c"], errors="coerce")

    if metric == "Degree-hours":
        interval_hours = _native_interval_hours(df, interval_minutes)
        source = pd.DataFrame(index=df.index.copy())
        source["Heating degree-hours"] = (float(heating_base_c) - temperature).clip(lower=0) * interval_hours
        source["Cooling degree-hours"] = (temperature - float(cooling_base_c)).clip(lower=0) * interval_hours
        result = _aggregate_table(source, aggregation)
        result.attrs["unit"] = "K·h"
        result.attrs["method"] = "source-interval"
    elif metric == "Degree-days":
        daily_temperature = temperature.resample("D").mean()
        daily = pd.DataFrame(index=daily_temperature.index)
        daily["Heating degree-days"] = (float(heating_base_c) - daily_temperature).clip(lower=0)
        daily["Cooling degree-days"] = (daily_temperature - float(cooling_base_c)).clip(lower=0)
        if aggregation == "Daily":
            result = daily.dropna(how="all")
        else:
            result = _aggregate_table(daily, aggregation)
        result.attrs["unit"] = "K·d"
        result.attrs["method"] = "daily-mean"
    else:
        raise ValueError(f"Unsupported degree metric: {metric}")

    result.attrs["metric"] = metric
    result.attrs["aggregation"] = aggregation
    result.attrs["heating_base_c"] = float(heating_base_c)
    result.attrs["cooling_base_c"] = float(cooling_base_c)
    return result


def degree_metric_interpretation(
    table: pd.DataFrame,
    *,
    heating_base_c: float,
    cooling_base_c: float,
    metric: DegreeMetric,
) -> str:
    """Return a concise explanation tied to the actual user-selected bases."""
    if table.empty:
        return "No valid temperature data are available for the selected degree-metric calculation."
    heating_column = next((name for name in table.columns if str(name).startswith("Heating")), None)
    cooling_column = next((name for name in table.columns if str(name).startswith("Cooling")), None)
    heating = float(table[heating_column].sum()) if heating_column else 0.0
    cooling = float(table[cooling_column].sum()) if cooling_column else 0.0
    unit = str(table.attrs.get("unit", "K·h" if metric == "Degree-hours" else "K·d"))
    dominant = "heating-dominated" if heating > cooling else "cooling-dominated" if cooling > heating else "balanced"
    method = (
        "each source interval"
        if metric == "Degree-hours"
        else "daily mean outdoor temperature"
    )
    return (
        f"Using a heating base/reference temperature of {heating_base_c:g} °C and a cooling base/reference temperature of "
        f"{cooling_base_c:g} °C, the selected data produce {heating:,.1f} {unit} heating and {cooling:,.1f} {unit} cooling. "
        f"{metric} are calculated from {method}; on this simplified climate-indicator basis the period is {dominant}. "
        "These base temperatures are user-defined balance/reference temperatures, not a complete building indoor-temperature or load model."
    )
