"""Generic aggregation helpers for climate charts."""

from __future__ import annotations

import pandas as pd


RESAMPLE_RULES = {
    "Hourly": "h",
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
    "Seasonal": None,
}


SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]


def filter_by_months_and_hours(
    df: pd.DataFrame,
    months: list[int] | None = None,
    hours: list[int] | None = None,
) -> pd.DataFrame:
    """Filter a climate DataFrame by selected months and hours of day."""
    data = df.copy()
    if months:
        data = data[data["month_index"].isin(months)]
    if hours:
        data = data[data["hour_of_day"].isin(hours)]
    return data


def aggregate_summary(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Aggregate a continuous variable into mean, min, max, median and percentiles."""
    if aggregation == "Hourly":
        out = df[[column]].copy()
        out["mean"] = out[column]
        out["min"] = out[column]
        out["max"] = out[column]
        out["median"] = out[column]
        out["p05"] = out[column]
        out["p95"] = out[column]
        return out[["mean", "min", "max", "median", "p05", "p95"]]

    if aggregation == "Seasonal":
        grouped = df.groupby("season", observed=False)[column]
        out = grouped.agg(mean="mean", min="min", max="max", median="median")
        out["p05"] = grouped.quantile(0.05)
        out["p95"] = grouped.quantile(0.95)
        out = out.reindex(SEASON_ORDER).dropna(how="all")
        return out

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    grouped = df[column].resample(rule)
    out = grouped.agg(mean="mean", min="min", max="max", median="median")
    out["p05"] = grouped.quantile(0.05)
    out["p95"] = grouped.quantile(0.95)
    return out.dropna(how="all")


def aggregate_sum(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Aggregate an extensive variable into sum, mean, min and max."""
    if aggregation == "Hourly":
        out = df[[column]].copy()
        out["sum"] = out[column]
        out["mean"] = out[column]
        out["min"] = out[column]
        out["max"] = out[column]
        return out[["sum", "mean", "min", "max"]]

    if aggregation == "Seasonal":
        grouped = df.groupby("season", observed=False)[column]
        out = grouped.agg(sum="sum", mean="mean", min="min", max="max")
        return out.reindex(SEASON_ORDER).dropna(how="all")

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    grouped = df[column].resample(rule)
    return grouped.agg(sum="sum", mean="mean", min="min", max="max").dropna(how="all")


def calendar_matrix(df: pd.DataFrame, column: str, row_group: str = "day") -> pd.DataFrame:
    """Create a matrix for heatmaps with hour-of-day columns."""
    if row_group == "day":
        row_key = "day_of_year"
    elif row_group == "week":
        row_key = "week_of_year"
    elif row_group == "month":
        row_key = "month_index"
    else:
        raise ValueError("row_group must be 'day', 'week' or 'month'")
    matrix = df.pivot_table(values=column, index=row_key, columns="hour_of_day", aggfunc="mean")
    return matrix.sort_index()


def monthly_hour_matrix(df: pd.DataFrame, column: str, aggfunc: str = "mean") -> pd.DataFrame:
    """Create month-by-hour matrix for diurnal climate profiles."""
    matrix = df.pivot_table(values=column, index="month_index", columns="hour_of_day", aggfunc=aggfunc)
    return matrix.sort_index()


def duration_curve(df: pd.DataFrame, column: str, ascending: bool = False) -> pd.DataFrame:
    """Return a sorted duration curve for a continuous variable."""
    values = df[column].dropna().sort_values(ascending=ascending).reset_index(drop=True)
    out = pd.DataFrame({"rank_hour": range(1, len(values) + 1), column: values})
    out["exceedance_fraction"] = out["rank_hour"] / max(len(out), 1)
    return out


def threshold_count_by_period(
    df: pd.DataFrame,
    condition: pd.Series,
    aggregation: str,
    label: str = "hours",
) -> pd.DataFrame:
    """Count hours satisfying a Boolean condition by a selected aggregation."""
    indicator = condition.fillna(False).astype(int).rename(label)
    temp = df.copy()
    temp[label] = indicator.values

    if aggregation == "Hourly":
        return temp[[label]]
    if aggregation == "Seasonal":
        return temp.groupby("season", observed=False)[label].sum().reindex(SEASON_ORDER).dropna().to_frame()

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    return temp[label].resample(rule).sum().to_frame()


def monthly_box_data(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Return rows required by Plotly monthly box and violin plots."""
    return df[[column, "month_name", "month_index"]].dropna().sort_values("month_index")
