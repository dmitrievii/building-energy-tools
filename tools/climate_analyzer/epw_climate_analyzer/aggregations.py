"""Generic aggregation helpers for climate charts."""

from __future__ import annotations

import pandas as pd

from .temporal_filtering import (
    CALENDAR_PROFILE,
    CHRONOLOGICAL,
    SEASON_ORDER,
    TIME_BASIS_ATTR,
    calendar_profile_slot,
    chronological_season_start,
    is_multiyear,
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
        frame = pd.DataFrame({"season": df.get("season"), "_value": numeric}, index=df.index)
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
        grouped = df.groupby("season", observed=False)[column]
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


def calendar_matrix(df: pd.DataFrame, column: str, row_group: str = "day") -> pd.DataFrame:
    """Create a period-by-hour matrix honoring chronological vs calendar-profile basis."""
    basis = time_basis(df)
    data = df.copy()
    index = pd.DatetimeIndex(data.index)
    if basis == CHRONOLOGICAL and is_multiyear(data):
        if row_group == "day":
            data["_row_key"] = index.strftime("%Y-%m-%d")
        elif row_group == "week":
            iso = index.isocalendar()
            data["_row_key"] = [f"{int(y):04d}-W{int(w):02d}" for y, w in zip(iso.year, iso.week, strict=False)]
        elif row_group == "month":
            data["_row_key"] = index.strftime("%Y-%m")
        else:
            raise ValueError("row_group must be 'day', 'week' or 'month'")
        row_key = "_row_key"
    else:
        if row_group == "day":
            row_key = "day_of_year"
        elif row_group == "week":
            row_key = "week_of_year"
        elif row_group == "month":
            row_key = "month_index"
        else:
            raise ValueError("row_group must be 'day', 'week' or 'month'")
    matrix = data.pivot_table(values=column, index=row_key, columns="hour_of_day", aggfunc="mean")
    return matrix.sort_index()


def monthly_hour_matrix(df: pd.DataFrame, column: str, aggfunc: str = "mean") -> pd.DataFrame:
    """Create month-by-hour matrix, preserving year-month in chronological multiyear mode."""
    data = df.copy()
    if time_basis(data) == CHRONOLOGICAL and is_multiyear(data):
        data["_month_period"] = pd.DatetimeIndex(data.index).strftime("%Y-%m")
        row_key = "_month_period"
    else:
        row_key = "month_index"
    matrix = data.pivot_table(values=column, index=row_key, columns="hour_of_day", aggfunc=aggfunc)
    return matrix.sort_index()


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
