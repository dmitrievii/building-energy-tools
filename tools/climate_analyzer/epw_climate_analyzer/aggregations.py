"""Generic aggregation helpers for climate charts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .climate_model import aggregation_semantics_for
from .temporal_filtering import (
    CALENDAR_PROFILE,
    CHRONOLOGICAL,
    SEASON_ORDER,
    TIME_BASIS_ATTR,
    calendar_profile_slot,
    chronological_season_start,
    is_multiyear,
    season_name,
    time_basis,
)


RESAMPLE_RULES = {
    "Hourly": "h",
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
    "Annual": "YE",
    "Seasonal": None,
}


def _attach_temporal_attrs(out: pd.DataFrame, source: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    out.attrs.update(dict(source.attrs))
    out.attrs[TIME_BASIS_ATTR] = time_basis(source)
    out.attrs["aggregation"] = aggregation
    return out


def filter_by_months_and_hours(
    df: pd.DataFrame,
    months: list[int] | None = None,
    hours: list[int] | None = None,
) -> pd.DataFrame:
    """Filter a climate DataFrame by selected months and hours of day."""
    attrs = dict(df.attrs)
    data = df.copy()
    if months:
        data = data[data["month_index"].isin(months)]
    if hours:
        data = data[data["hour_of_day"].isin(hours)]
    data.attrs.update(attrs)
    return data


def _calendar_summary(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    slot = calendar_profile_slot(pd.DatetimeIndex(df.index), aggregation)
    values = pd.to_numeric(df[column], errors="coerce")
    temp = pd.DataFrame({"_value": values.to_numpy()}, index=df.index)
    temp["_slot"] = slot
    grouped = temp.groupby("_slot", observed=False, sort=True)["_value"]
    out = grouped.agg(mean="mean", min="min", max="max", median="median")
    out["p05"] = grouped.quantile(0.05)
    out["p95"] = grouped.quantile(0.95)
    return out.dropna(how="all")


def _chronological_season_summary(df: pd.DataFrame, column: str) -> pd.DataFrame:
    starts = chronological_season_start(pd.DatetimeIndex(df.index))
    values = pd.to_numeric(df[column], errors="coerce")
    temp = pd.DataFrame({"_value": values.to_numpy(), "_season_start": starts}, index=df.index)
    grouped = temp.groupby("_season_start", sort=True)["_value"]
    out = grouped.agg(mean="mean", min="min", max="max", median="median")
    out["p05"] = grouped.quantile(0.05)
    out["p95"] = grouped.quantile(0.95)
    out.index = pd.DatetimeIndex(out.index, name="Season start")
    return out.dropna(how="all")


def aggregate_summary(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Aggregate a continuous variable into mean, min, max, median and percentiles.

    ``Chronological`` keeps real years distinct. ``Calendar profile`` removes the
    year only from the grouping key so equivalent calendar positions from all
    selected years form one climatological bucket.
    """
    basis = time_basis(df)
    if basis == CALENDAR_PROFILE:
        return _attach_temporal_attrs(_calendar_summary(df, column, aggregation), df, aggregation)

    if aggregation == "Hourly":
        grouped = pd.to_numeric(df[column], errors="coerce").resample("h")
        out = grouped.agg(mean="mean", min="min", max="max", median="median")
        out["p05"] = grouped.quantile(0.05)
        out["p95"] = grouped.quantile(0.95)
        return _attach_temporal_attrs(out.dropna(how="all"), df, aggregation)

    if aggregation == "Seasonal":
        if is_multiyear(df):
            out = _chronological_season_summary(df, column)
        else:
            grouped = df.groupby("season", observed=False)[column]
            out = grouped.agg(mean="mean", min="min", max="max", median="median")
            out["p05"] = grouped.quantile(0.05)
            out["p95"] = grouped.quantile(0.95)
            out = out.reindex(list(SEASON_ORDER)).dropna(how="all")
        return _attach_temporal_attrs(out, df, aggregation)

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    grouped = pd.to_numeric(df[column], errors="coerce").resample(rule)
    out = grouped.agg(mean="mean", min="min", max="max", median="median")
    out["p05"] = grouped.quantile(0.05)
    out["p95"] = grouped.quantile(0.95)
    return _attach_temporal_attrs(out.dropna(how="all"), df, aggregation)


def _calendar_period_totals(values: pd.Series, df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Return one extensive period total per year and calendar slot."""
    idx = pd.DatetimeIndex(df.index)
    slot = calendar_profile_slot(idx, aggregation)
    temp = pd.DataFrame({"_value": pd.to_numeric(values, errors="coerce").to_numpy()}, index=idx)
    temp["_year"] = idx.year.astype(int)
    temp["_slot"] = slot
    yearly = temp.groupby(["_year", "_slot"], observed=False, sort=True)["_value"].sum(min_count=1)
    return yearly.rename("_sum").reset_index()


def period_total_series(values: pd.Series, df: pd.DataFrame, aggregation: str) -> pd.Series:
    """Aggregate an extensive/occurrence series by the active temporal basis.

    In calendar-profile mode, totals are first calculated independently for each
    year and equivalent calendar buckets are then averaged. This prevents a
    five-year dataset from being misreported as a five-times-larger typical
    January, while still preserving all years in chronological mode.
    """
    basis = time_basis(df)
    numeric = pd.to_numeric(values, errors="coerce")
    numeric.index = df.index

    if basis == CALENDAR_PROFILE:
        yearly = _calendar_period_totals(numeric, df, aggregation)
        result = yearly.groupby("_slot", observed=False, sort=True)["_sum"].mean()
        result.index.name = "Calendar period"
        return result.dropna()

    if aggregation == "Hourly":
        return numeric.resample("h").sum(min_count=1).dropna()
    if aggregation == "Seasonal":
        if is_multiyear(df):
            starts = chronological_season_start(pd.DatetimeIndex(df.index))
            temp = pd.DataFrame({"_value": numeric.to_numpy(), "_season_start": starts}, index=df.index)
            result = temp.groupby("_season_start", sort=True)["_value"].sum(min_count=1)
            result.index = pd.DatetimeIndex(result.index, name="Season start")
            return result.dropna()
        if "season" in df.columns:
            season_values = df["season"]
        else:
            season_values = pd.Categorical(
                [season_name(month) for month in pd.DatetimeIndex(df.index).month],
                categories=list(SEASON_ORDER),
                ordered=True,
            )
        frame = pd.DataFrame({"season": season_values, "_value": numeric.to_numpy()}, index=df.index)
        return frame.groupby("season", observed=False)["_value"].sum(min_count=1).reindex(list(SEASON_ORDER)).dropna()

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    return numeric.resample(rule).sum(min_count=1).dropna()


def aggregate_sum(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Aggregate an extensive variable into sum, mean, min and max.

    For calendar profiles, the centre ``sum`` is the mean per-year period total;
    ``min``/``max`` are the range of per-year period totals. This keeps units and
    climatological meaning intact instead of summing several years together.
    """
    basis = time_basis(df)
    values = pd.to_numeric(df[column], errors="coerce")

    if basis == CALENDAR_PROFILE:
        yearly = _calendar_period_totals(values, df, aggregation)
        grouped = yearly.groupby("_slot", observed=False, sort=True)["_sum"]
        out = grouped.agg(sum="mean", mean="mean", min="min", max="max").dropna(how="all")
        out.index.name = "Calendar period"
        return _attach_temporal_attrs(out, df, aggregation)

    totals = period_total_series(values, df, aggregation)
    if aggregation == "Hourly":
        # State the per-hour extensive total consistently in all four columns.
        out = pd.DataFrame({"sum": totals, "mean": totals, "min": totals, "max": totals})
        return _attach_temporal_attrs(out, df, aggregation)

    if aggregation == "Seasonal" and not is_multiyear(df):
        if "season" in df.columns:
            season_values = df["season"]
        else:
            season_values = pd.Categorical(
                [season_name(month) for month in pd.DatetimeIndex(df.index).month],
                categories=list(SEASON_ORDER),
                ordered=True,
            )
        temp = pd.DataFrame({"season": season_values, "_value": values.to_numpy()}, index=df.index)
        grouped = temp.groupby("season", observed=False)["_value"]
        out = grouped.agg(sum="sum", mean="mean", min="min", max="max").reindex(list(SEASON_ORDER)).dropna(how="all")
        return _attach_temporal_attrs(out, df, aggregation)

    rule = RESAMPLE_RULES.get(aggregation)
    if aggregation == "Seasonal" and is_multiyear(df):
        starts = chronological_season_start(pd.DatetimeIndex(df.index))
        temp = pd.DataFrame({"_value": values.to_numpy(), "_season_start": starts}, index=df.index)
        grouped = temp.groupby("_season_start", sort=True)["_value"]
        out = grouped.agg(sum="sum", mean="mean", min="min", max="max").dropna(how="all")
        out.index = pd.DatetimeIndex(out.index, name="Season start")
        return _attach_temporal_attrs(out, df, aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    grouped = values.resample(rule)
    out = grouped.agg(sum="sum", mean="mean", min="min", max="max").dropna(how="all")
    return _attach_temporal_attrs(out, df, aggregation)


HEATMAP_COMPARE_HOUR = "Hour of day"
HEATMAP_COMPARE_YEAR = "Year"
HEATMAP_COMPARISON_DIMENSIONS = (HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR)
HEATMAP_INTENSIVE_STATISTICS = ("Mean", "Minimum", "Maximum", "Median", "P05", "P95")
HEATMAP_EXTENSIVE_STATISTICS = ("Total",) + HEATMAP_INTENSIVE_STATISTICS
HEATMAP_CIRCULAR_STATISTICS = ("Circular mean",)


def heatmap_statistic_options(column: str) -> tuple[str, ...]:
    """Return quantity-aware statistics that are meaningful for a heat-map cell."""
    semantics = aggregation_semantics_for(column)
    if semantics == "sum":
        return HEATMAP_EXTENSIVE_STATISTICS
    if semantics == "circular mean":
        return HEATMAP_CIRCULAR_STATISTICS
    return HEATMAP_INTENSIVE_STATISTICS


def heatmap_default_statistic(column: str) -> str:
    """Return the physically preferred default statistic for a canonical variable."""
    semantics = aggregation_semantics_for(column)
    if semantics == "sum":
        return "Total"
    if semantics == "circular mean":
        return "Circular mean"
    return "Mean"


def _normalise_heatmap_statistic(column: str, statistic: str) -> str:
    requested = str(statistic).strip()
    semantics = aggregation_semantics_for(column)
    if semantics == "circular mean" and requested == "Mean":
        requested = "Circular mean"
    options = heatmap_statistic_options(column)
    if requested not in options:
        raise ValueError(f"Unsupported heat-map statistic '{requested}' for {column}; choose one of {options}.")
    return requested


def _circular_mean_degrees(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return float("nan")
    radians = np.deg2rad(np.mod(numeric.to_numpy(), 360.0))
    sin_mean = float(np.sin(radians).mean())
    cos_mean = float(np.cos(radians).mean())
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return float("nan")
    return float(np.mod(np.rad2deg(np.arctan2(sin_mean, cos_mean)), 360.0))


def _heatmap_reduce(grouped, statistic: str) -> pd.Series:
    if statistic == "Mean":
        return grouped.mean()
    if statistic == "Minimum":
        return grouped.min()
    if statistic == "Maximum":
        return grouped.max()
    if statistic == "Median":
        return grouped.median()
    if statistic == "P05":
        return grouped.quantile(0.05)
    if statistic == "P95":
        return grouped.quantile(0.95)
    if statistic == "Total":
        return grouped.sum(min_count=1)
    if statistic == "Circular mean":
        return grouped.apply(_circular_mean_degrees)
    raise ValueError(f"Unsupported heat-map statistic: {statistic}")


def _calendar_day_slot(index: pd.DatetimeIndex) -> pd.Index:
    """Return leap-neutral calendar-day numbers on a fixed 366-day reference year.

    Using a leap reference year keeps the same month/day at the same coordinate
    in leap and non-leap source years. Feb 29 is slot 60; Mar 1 is slot 61 in
    every year, so an absent leap day becomes a real gap rather than shifting all
    later dates by one column.
    """
    reference = pd.DatetimeIndex(
        pd.to_datetime(
            {
                "year": np.full(len(index), 2000, dtype=int),
                "month": index.month.astype(int),
                "day": index.day.astype(int),
            }
        )
    )
    return pd.Index(reference.dayofyear.astype(int), name="Day")


def _heatmap_period_key(index: pd.DatetimeIndex, row_group: str) -> pd.Index:
    """Return numeric calendar coordinates that Plotly cannot reinterpret as dates."""
    group = str(row_group).strip().lower()
    if group == "day":
        return _calendar_day_slot(index)
    if group == "week":
        iso = index.isocalendar()
        return pd.Index(iso.week.astype(int).to_numpy(), name="Week")
    if group == "month":
        return pd.Index(index.month.astype(int), name="Month")
    raise ValueError("row_group must be 'day', 'week' or 'month'")


def temporal_heatmap_matrix(
    df: pd.DataFrame,
    column: str,
    row_group: str = "day",
    compare_across: str = HEATMAP_COMPARE_HOUR,
    statistic: str = "Mean",
) -> pd.DataFrame:
    """Create a generic heat-map matrix from calendar period and comparison dimension.

    Heat-map period axes are always calendar coordinates: day 1...366 on a
    leap-neutral reference year, ISO week 1...53, or month 1...12. This prevents
    multi-year chronological data from expanding a day×hour chart into thousands
    of columns and prevents Plotly from parsing ``MM-DD`` labels as dates.

    ``Hour of day`` aligns equivalent calendar slots across all selected years.
    ``Year`` is the explicit interannual view and preserves the real calendar
    year (ISO week-year for weekly heat maps) on the Y axis regardless of the
    global time-basis selection.

    For extensive quantities in a multi-year hour-of-day heat map, ``Total`` is
    first calculated independently for each source year/cell and then averaged
    across years. This avoids totals that scale merely with the number of years
    loaded while retaining one comparable calendar heat map.
    """
    if column not in df.columns:
        raise KeyError(f"Heat-map column is missing: {column}")
    if compare_across not in HEATMAP_COMPARISON_DIMENSIONS:
        raise ValueError(f"Unsupported heat-map comparison dimension: {compare_across}")

    statistic = _normalise_heatmap_statistic(column, statistic)
    index = pd.DatetimeIndex(df.index)
    values = pd.to_numeric(df[column], errors="coerce")
    temp = pd.DataFrame({"_value": values.to_numpy()}, index=index)
    group = str(row_group).strip().lower()

    if compare_across == HEATMAP_COMPARE_YEAR:
        if group == "week":
            iso = index.isocalendar()
            temp["_y"] = iso.year.astype(int).to_numpy()
            temp["_x"] = iso.week.astype(int).to_numpy()
        else:
            temp["_y"] = index.year.astype(int)
            temp["_x"] = _heatmap_period_key(index, row_group).to_numpy()
    else:
        temp["_y"] = (
            pd.to_numeric(df["hour_of_day"], errors="coerce").to_numpy()
            if "hour_of_day" in df.columns
            else index.hour.astype(int)
        )
        temp["_x"] = _heatmap_period_key(index, row_group).to_numpy()

    temp = temp.dropna(subset=["_value", "_y", "_x"])
    if temp.empty:
        return pd.DataFrame()

    if statistic == "Total" and compare_across == HEATMAP_COMPARE_HOUR and is_multiyear(df):
        if group == "week":
            temp["_year"] = pd.DatetimeIndex(temp.index).isocalendar().year.astype(int).to_numpy()
        else:
            temp["_year"] = temp.index.year.astype(int)
        per_year = temp.groupby(["_year", "_y", "_x"], observed=False, sort=True)["_value"].sum(min_count=1)
        reduced = per_year.groupby(["_y", "_x"], observed=False, sort=True).mean()
    else:
        grouped = temp.groupby(["_y", "_x"], observed=False, sort=True)["_value"]
        reduced = _heatmap_reduce(grouped, statistic)

    matrix = reduced.unstack("_x").sort_index()
    if group == "month" and all(isinstance(value, (int, np.integer)) for value in matrix.columns):
        matrix = matrix.reindex(columns=list(range(1, 13)))
    elif group in {"day", "week"} and len(matrix.columns):
        numeric_columns = [int(value) for value in matrix.columns]
        matrix = matrix.reindex(columns=list(range(min(numeric_columns), max(numeric_columns) + 1)))
    return matrix


def calendar_matrix(df: pd.DataFrame, column: str, row_group: str = "day") -> pd.DataFrame:
    """Backward-compatible period-by-hour matrix using mean cell values."""
    return temporal_heatmap_matrix(
        df,
        column,
        row_group=row_group,
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic="Mean",
    ).T


def monthly_hour_matrix(df: pd.DataFrame, column: str, aggfunc: str = "mean") -> pd.DataFrame:
    """Backward-compatible month-by-hour matrix on calendar month coordinates."""
    statistic = {
        "mean": "Mean",
        "min": "Minimum",
        "max": "Maximum",
        "median": "Median",
        "sum": "Total",
    }.get(str(aggfunc).strip().lower())
    if statistic is None:
        raise ValueError(f"Unsupported monthly-hour aggregation: {aggfunc}")
    return temporal_heatmap_matrix(
        df,
        column,
        row_group="month",
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic=statistic,
    ).T


def duration_curve(df: pd.DataFrame, column: str, ascending: bool = False) -> pd.DataFrame:
    """Return a sorted duration curve with both record rank and physical duration."""
    values = df[column].dropna().sort_values(ascending=ascending).reset_index(drop=True)
    out = pd.DataFrame({"rank_hour": range(1, len(values) + 1), column: values})
    out["duration_hours"] = out["rank_hour"].astype(float) * native_interval_hours(df)
    out["exceedance_fraction"] = out["rank_hour"] / max(len(out), 1)
    return out


def native_interval_hours(df: pd.DataFrame) -> float:
    """Return one source record's declared physical duration in hours.

    Canonical datasets carry ``canonical_native_interval_minutes`` as source
    metadata. Historical gaps must not be interpreted as longer observations,
    so a present record always contributes only the declared native interval.
    Legacy frames without that attribute fall back to the median positive
    timestamp spacing, then to one hour when no cadence can be inferred.
    """
    declared = df.attrs.get("canonical_native_interval_minutes")
    try:
        minutes = float(declared)
    except (TypeError, ValueError):
        minutes = float("nan")

    if not pd.notna(minutes) or minutes <= 0.0:
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
            index = pd.DatetimeIndex(df.index).sort_values().unique()
            deltas = pd.Series(index[1:] - index[:-1]).dt.total_seconds().div(60.0)
            positive = deltas[deltas > 0.0]
            minutes = float(positive.median()) if not positive.empty else 60.0
        else:
            minutes = 60.0

    return minutes / 60.0


def threshold_count_by_period(
    df: pd.DataFrame,
    condition: pd.Series,
    aggregation: str,
    label: str = "hours",
) -> pd.DataFrame:
    """Integrate condition duration in physical hours by aggregation period."""
    hours_per_record = native_interval_hours(df)
    aligned = condition.reindex(df.index).fillna(False).astype(float)
    values = aligned * hours_per_record
    values.name = label
    result = period_total_series(values, df, aggregation).rename(label).to_frame()
    return _attach_temporal_attrs(result, df, aggregation)


def monthly_box_data(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Return rows required by Plotly monthly box and violin plots."""
    data = df[[column, "month_name", "month_index"]].dropna().copy()
    if time_basis(df) == CHRONOLOGICAL and is_multiyear(df):
        data["period_name"] = pd.DatetimeIndex(data.index).strftime("%b %Y")
        data["period_order"] = pd.DatetimeIndex(data.index).to_period("M").astype(str)
    else:
        data["period_name"] = data["month_name"]
        data["period_order"] = data["month_index"]
    data.attrs.update(dict(df.attrs))
    return data.sort_values("period_order")
