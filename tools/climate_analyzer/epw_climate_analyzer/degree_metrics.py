"""Heating/cooling degree-hour and degree-day climate indicators.

The Austrian HGT/KGT notation contains two independent temperatures for each
indicator.  They must not be collapsed into one generic balance temperature:

* HGT_i/gr: the heating limit selects heating periods; the temperature
  difference is measured from the heating indoor-air reference temperature.
* KGT_i/gr: the cooling limit selects cooling periods; the temperature
  difference is measured from the cooling indoor-air reference temperature.

For example HGT20/12 uses 20 °C indoor air and a 12 °C heating limit, while
KGT20/18.3 uses 20 °C indoor air and an 18.3 °C cooling limit.

Degree-hours evaluate the native source intervals. Degree-days first calculate
one daily-mean outdoor temperature and then apply the same selection/difference
semantics. They are therefore not interchangeable through division by 24.
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


def _validate_parameters(
    heating_indoor_c: float,
    heating_limit_c: float,
    cooling_indoor_c: float,
    cooling_limit_c: float,
) -> None:
    values = {
        "heating indoor-air temperature": heating_indoor_c,
        "heating limit": heating_limit_c,
        "cooling indoor-air temperature": cooling_indoor_c,
        "cooling limit": cooling_limit_c,
    }
    for label, value in values.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {label}.") from exc
        if not -80.0 <= numeric <= 80.0:
            raise ValueError(f"{label.capitalize()} is outside the supported -80...80 °C range.")

    # HGT convention requires the heating limit to be below or equal to the
    # indoor-air reference.  The analogous restriction is deliberately NOT
    # imposed on cooling: KGT20/18.3 is a valid requested convention with the
    # cooling limit below the 20 °C indoor-air reference.
    if float(heating_limit_c) > float(heating_indoor_c):
        raise ValueError("Heating limit must not exceed heating indoor-air temperature.")


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


def _degree_contributions(
    temperature: pd.Series,
    *,
    heating_indoor_c: float,
    heating_limit_c: float,
    cooling_indoor_c: float,
    cooling_limit_c: float,
) -> tuple[pd.Series, pd.Series]:
    """Return HGT/KGT temperature differences on their selected periods.

    HGT contribution:
        ``T_i,H - T_e`` when ``T_e < T_limit,H``, otherwise 0.

    KGT contribution:
        ``T_e - T_i,C`` when ``T_e > T_limit,C``, otherwise 0.

    The KGT expression intentionally does not clip negative differences. With
    KGT20/18.3, an interval in the 18.3...20 °C band belongs to the selected
    cooling period but has a negative difference to the 20 °C indoor reference.
    This keeps the two-temperature KGT definition explicit instead of silently
    replacing it by a one-temperature CDD18.3 calculation.
    """
    valid = temperature.notna()
    heating_selected = valid & (temperature < float(heating_limit_c))
    cooling_selected = valid & (temperature > float(cooling_limit_c))

    heating = pd.Series(0.0, index=temperature.index, dtype=float)
    cooling = pd.Series(0.0, index=temperature.index, dtype=float)
    heating.loc[heating_selected] = float(heating_indoor_c) - temperature.loc[heating_selected]
    cooling.loc[cooling_selected] = temperature.loc[cooling_selected] - float(cooling_indoor_c)
    heating.loc[~valid] = float("nan")
    cooling.loc[~valid] = float("nan")
    return heating, cooling


def degree_metric_table(
    df: pd.DataFrame,
    *,
    heating_indoor_c: float = 20.0,
    heating_limit_c: float = 12.0,
    cooling_indoor_c: float = 20.0,
    cooling_limit_c: float = 18.3,
    metric: DegreeMetric = "Degree-days",
    aggregation: DegreeAggregation = "Monthly",
    interval_minutes: float | None = None,
) -> pd.DataFrame:
    """Calculate HGT/KGT with four explicit temperature inputs.

    ``heating_limit_c`` and ``cooling_limit_c`` decide which source intervals or
    days belong to the corresponding heating/cooling period. The accumulated
    temperature difference is measured to the separate indoor-air reference
    temperature for that indicator.

    Degree-hours use each native source interval and multiply the selected
    difference by its duration. Degree-days first form daily-mean outdoor
    temperatures and then evaluate the two selection rules once per day.
    """
    _validate_parameters(
        heating_indoor_c,
        heating_limit_c,
        cooling_indoor_c,
        cooling_limit_c,
    )
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Degree metrics require a pandas DatetimeIndex.")
    if "dry_bulb_temperature_c" not in df.columns:
        raise KeyError("dry_bulb_temperature_c")

    temperature = pd.to_numeric(df["dry_bulb_temperature_c"], errors="coerce")

    if metric == "Degree-hours":
        heating, cooling = _degree_contributions(
            temperature,
            heating_indoor_c=heating_indoor_c,
            heating_limit_c=heating_limit_c,
            cooling_indoor_c=cooling_indoor_c,
            cooling_limit_c=cooling_limit_c,
        )
        interval_hours = _native_interval_hours(df, interval_minutes)
        source = pd.DataFrame(index=df.index.copy())
        source["Heating degree-hours (HGT)"] = heating * interval_hours
        source["Cooling degree-hours (KGT)"] = cooling * interval_hours
        result = _aggregate_table(source, aggregation)
        result.attrs["unit"] = "K·h"
        result.attrs["method"] = "source-interval"
    elif metric == "Degree-days":
        daily_temperature = temperature.resample("D").mean()
        heating, cooling = _degree_contributions(
            daily_temperature,
            heating_indoor_c=heating_indoor_c,
            heating_limit_c=heating_limit_c,
            cooling_indoor_c=cooling_indoor_c,
            cooling_limit_c=cooling_limit_c,
        )
        daily = pd.DataFrame(index=daily_temperature.index)
        daily["Heating degree-days (HGT)"] = heating
        daily["Cooling degree-days (KGT)"] = cooling
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
    result.attrs["heating_indoor_c"] = float(heating_indoor_c)
    result.attrs["heating_limit_c"] = float(heating_limit_c)
    result.attrs["cooling_indoor_c"] = float(cooling_indoor_c)
    result.attrs["cooling_limit_c"] = float(cooling_limit_c)
    result.attrs["heating_notation"] = f"HGT {heating_indoor_c:g}/{heating_limit_c:g}"
    result.attrs["cooling_notation"] = f"KGT {cooling_indoor_c:g}/{cooling_limit_c:g}"
    return result


def degree_metric_interpretation(
    table: pd.DataFrame,
    *,
    heating_indoor_c: float,
    heating_limit_c: float,
    cooling_indoor_c: float,
    cooling_limit_c: float,
    metric: DegreeMetric,
) -> str:
    """Return a concise interpretation tied to all four actual inputs."""
    if table.empty:
        return "No valid temperature data are available for the selected degree-metric calculation."
    heating_column = next((name for name in table.columns if str(name).startswith("Heating")), None)
    cooling_column = next((name for name in table.columns if str(name).startswith("Cooling")), None)
    heating = float(table[heating_column].sum()) if heating_column else 0.0
    cooling = float(table[cooling_column].sum()) if cooling_column else 0.0
    unit = str(table.attrs.get("unit", "K·h" if metric == "Degree-hours" else "K·d"))
    heating_notation = f"HGT {heating_indoor_c:g}/{heating_limit_c:g}"
    cooling_notation = f"KGT {cooling_indoor_c:g}/{cooling_limit_c:g}"
    method = "native source intervals" if metric == "Degree-hours" else "daily mean outdoor temperatures"
    cooling_note = ""
    if float(cooling_limit_c) < float(cooling_indoor_c):
        cooling_note = (
            f" For {cooling_notation}, periods between {cooling_limit_c:g} and {cooling_indoor_c:g} °C are selected by the cooling-limit rule "
            "but contribute a negative difference to the indoor-air reference."
        )
    return (
        f"{heating_notation}: indoor air {heating_indoor_c:g} °C, heating limit {heating_limit_c:g} °C → {heating:,.1f} {unit}. "
        f"{cooling_notation}: indoor air {cooling_indoor_c:g} °C, cooling limit {cooling_limit_c:g} °C → {cooling:,.1f} {unit}. "
        f"{metric} are calculated from {method}.{cooling_note}"
    )
