"""Canonical hourly analysis normalization for measured climate sources.

The application keeps provider-native observations intact for provenance,
export and explicitly native diagnostics. Ordinary scientific analysis uses a
single hourly representation produced here. The conversion is quantity-aware
and fail-closed on incomplete source intervals: a 10-minute source therefore
requires six physical source timestamps in the hour and six valid values for a
canonical variable before that variable receives an hourly value.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .climate_model import aggregation_semantics_for


CANONICAL_ANALYSIS_INTERVAL_MINUTES = 60
HOURLY_COMPLETENESS_POLICY = "strict-complete-native-intervals"


def _validated_source_interval_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Canonical hourly normalization requires a valid source interval in minutes.") from exc
    if minutes <= 0:
        raise ValueError("Canonical hourly source interval must be positive.")
    if minutes > CANONICAL_ANALYSIS_INTERVAL_MINUTES:
        raise ValueError("Canonical hourly normalization does not upsample source intervals longer than one hour.")
    if CANONICAL_ANALYSIS_INTERVAL_MINUTES % minutes != 0:
        raise ValueError(
            "Canonical hourly normalization requires the source interval to divide 60 minutes exactly."
        )
    return minutes


def _validate_hour_alignment(index: pd.DatetimeIndex, source_interval_minutes: int) -> None:
    """Reject timestamps that cannot represent regular sub-hourly clock slots."""
    if index.has_duplicates:
        raise ValueError("Canonical hourly normalization requires unique source timestamps.")
    if index.hasnans:
        raise ValueError("Canonical hourly normalization does not accept NaT source timestamps.")
    if not index.is_monotonic_increasing:
        raise ValueError("Canonical hourly normalization requires source timestamps in increasing order.")
    if len(index) == 0:
        raise ValueError("Canonical hourly normalization requires at least one source timestamp.")

    misaligned = (
        (index.minute % int(source_interval_minutes) != 0)
        | (index.second != 0)
        | (index.microsecond != 0)
        | (index.nanosecond != 0)
    )
    if bool(np.any(misaligned)):
        raise ValueError(
            f"Source timestamps are not aligned to the declared {source_interval_minutes}-minute clock grid."
        )


def _circular_hourly_mean(values: pd.Series) -> pd.Series:
    """Return vectorized hourly circular means in degrees.

    This is mathematically equivalent to applying
    ``atan2(mean(sin(theta)), mean(cos(theta)))`` to each hourly group, but
    avoids Python-level ``Resampler.apply`` calls for every hour. NaNs are
    ignored here exactly as by the former group function; strict valid-count
    masking is applied by the caller afterwards. A cancelling resultant vector
    remains undefined and is returned as NaN.
    """
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    radians = np.deg2rad(np.mod(numeric, 360.0))
    sin_values = pd.Series(np.sin(radians), index=numeric.index, dtype="float64")
    cos_values = pd.Series(np.cos(radians), index=numeric.index, dtype="float64")
    sin_mean = sin_values.resample("h", label="left", closed="left").mean()
    cos_mean = cos_values.resample("h", label="left", closed="left").mean()
    undefined = (sin_mean.abs() < 1e-12) & (cos_mean.abs() < 1e-12)
    angles = np.mod(np.rad2deg(np.arctan2(sin_mean, cos_mean)), 360.0)
    result = pd.Series(angles, index=sin_mean.index, dtype="float64")
    return result.mask(undefined)


def _hourly_reduce(values: pd.Series, semantics: str) -> pd.Series:
    if semantics == "circular mean":
        return _circular_hourly_mean(values)
    grouped = values.resample("h", label="left", closed="left")
    if semantics == "sum":
        return grouped.sum(min_count=1)
    return grouped.mean()


def canonical_hourly_analysis_frame(
    data: pd.DataFrame,
    *,
    source_interval_minutes: int | None = None,
) -> pd.DataFrame:
    """Return the canonical hourly representation of one canonical climate frame.

    The source dataframe is never overwritten. Hourly source data take a
    shallow-copy fast path. Sub-hourly data are reduced once by the canonical
    variable aggregation contract.

    A physical hour with a missing source timestamp is omitted completely from
    the hourly timeline. Within a physically complete hour, a variable is masked
    to NaN unless all expected native values for that variable are numeric. This
    separates source-timeline gaps from variable-local missing observations and
    prevents partial means or silent zero-fill.
    """
    if not isinstance(data.index, pd.DatetimeIndex):
        raise TypeError("Canonical hourly analysis requires a pandas DatetimeIndex.")

    declared = source_interval_minutes
    if declared is None:
        declared = data.attrs.get("canonical_native_interval_minutes")
    minutes = _validated_source_interval_minutes(declared)
    index = pd.DatetimeIndex(data.index)
    _validate_hour_alignment(index, minutes)

    # EPW and any other native-hourly source should not pay for a resampling
    # pass. The shallow frame shares data blocks but receives independent attrs.
    if minutes == CANONICAL_ANALYSIS_INTERVAL_MINUTES:
        hourly = data.copy(deep=False)
        hourly.attrs.update(dict(data.attrs))
        hourly.attrs["canonical_source_interval_minutes"] = minutes
        hourly.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
        hourly.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
        hourly.attrs["canonical_analysis_resolution"] = "hourly"
        hourly.attrs["canonical_hourly_expected_source_records"] = 1
        hourly.attrs["canonical_hourly_completeness_policy"] = HOURLY_COMPLETENESS_POLICY
        hourly.attrs["canonical_hourly_incomplete_source_hours"] = 0
        hourly.attrs["canonical_hourly_incomplete_hours_by_variable"] = {}
        hourly.attrs["canonical_hourly_source_rows"] = int(len(data))
        hourly.attrs["canonical_hourly_rows"] = int(len(hourly))
        return hourly

    expected = CANONICAL_ANALYSIS_INTERVAL_MINUTES // minutes
    first_hour = pd.Timestamp(index.min()).floor("h")
    last_hour = pd.Timestamp(index.max()).floor("h")
    hourly_index = pd.date_range(first_hour, last_hour, freq="h", tz=index.tz, name=index.name)

    # Count physical source timestamps independently of variable nullability.
    timestamp_indicator = pd.Series(1, index=index, dtype="int64")
    source_counts = timestamp_indicator.resample("h", label="left", closed="left").sum().reindex(hourly_index, fill_value=0)
    if bool((source_counts > expected).any()):
        raise ValueError("A source hour contains more timestamps than allowed by the declared native cadence.")
    complete_timeline = source_counts == expected

    hourly = pd.DataFrame(index=hourly_index)
    incomplete_by_variable: dict[str, int] = {}

    for column in data.columns:
        values = pd.to_numeric(data[column], errors="coerce")
        values.index = index
        semantics = aggregation_semantics_for(column)
        reduced = _hourly_reduce(values, semantics).reindex(hourly_index)
        valid_counts = values.resample("h", label="left", closed="left").count().reindex(hourly_index, fill_value=0)
        complete = complete_timeline & (valid_counts == expected)
        hourly[column] = reduced.where(complete)
        incomplete_by_variable[str(column)] = int((~complete).sum())

    # A missing physical source slot invalidates the complete hour itself. Keep
    # variable-local NaNs only for hours whose physical timestamp grid is whole.
    hourly = hourly.loc[complete_timeline].copy()

    hourly.attrs.update(dict(data.attrs))
    hourly.attrs["canonical_source_interval_minutes"] = minutes
    hourly.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    hourly.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    hourly.attrs["canonical_analysis_resolution"] = "hourly"
    hourly.attrs["canonical_hourly_expected_source_records"] = int(expected)
    hourly.attrs["canonical_hourly_completeness_policy"] = HOURLY_COMPLETENESS_POLICY
    hourly.attrs["canonical_hourly_incomplete_source_hours"] = int((~complete_timeline).sum())
    hourly.attrs["canonical_hourly_incomplete_hours_by_variable"] = incomplete_by_variable
    hourly.attrs["canonical_hourly_source_rows"] = int(len(data))
    hourly.attrs["canonical_hourly_rows"] = int(len(hourly))
    hourly.attrs["canonical_hourly_reduction_factor"] = (
        float(len(data) / len(hourly)) if len(hourly) else math.nan
    )
    return hourly
