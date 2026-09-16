"""Canonical hourly analysis normalization for measured climate sources.

The application keeps provider-native observations intact for provenance,
export and explicitly native diagnostics.  Ordinary scientific analysis uses a
single hourly representation produced here.  The conversion is quantity-aware
and fail-closed on incomplete source intervals: a 10-minute source therefore
requires six valid values for a canonical variable before that hourly value is
considered valid.
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


def _hourly_reduce(values: pd.Series, semantics: str) -> pd.Series:
    grouped = values.resample("h", label="left", closed="left")
    if semantics == "sum":
        return grouped.sum(min_count=1)
    if semantics == "circular mean":
        return grouped.apply(_circular_mean_degrees)
    return grouped.mean()


def canonical_hourly_analysis_frame(
    data: pd.DataFrame,
    *,
    source_interval_minutes: int | None = None,
) -> pd.DataFrame:
    """Return the canonical hourly representation of one canonical climate frame.

    The source dataframe is never overwritten.  Hourly source data take a
    shallow-copy fast path.  Sub-hourly data are reduced once by the canonical
    variable aggregation contract and then masked per variable unless every
    expected native observation in that hour is present and numeric.

    Missing timestamps and missing values are therefore never silently converted
    to zero or hidden inside a partial hourly mean.  Coverage is variable-local:
    if temperature is missing in one native slot but precipitation is complete,
    the temperature hour is invalid while the precipitation total remains valid.
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
    # pass.  The shallow frame shares data blocks but receives independent attrs.
    if minutes == CANONICAL_ANALYSIS_INTERVAL_MINUTES:
        hourly = data.copy(deep=False)
        hourly.attrs.update(dict(data.attrs))
        hourly.attrs["canonical_source_interval_minutes"] = minutes
        hourly.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
        hourly.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
        hourly.attrs["canonical_analysis_resolution"] = "hourly"
        hourly.attrs["canonical_hourly_expected_source_records"] = 1
        hourly.attrs["canonical_hourly_completeness_policy"] = HOURLY_COMPLETENESS_POLICY
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

    hourly = pd.DataFrame(index=hourly_index)
    incomplete_by_variable: dict[str, int] = {}

    for column in data.columns:
        values = pd.to_numeric(data[column], errors="coerce")
        values.index = index
        semantics = aggregation_semantics_for(column)
        reduced = _hourly_reduce(values, semantics).reindex(hourly_index)
        valid_counts = values.resample("h", label="left", closed="left").count().reindex(hourly_index, fill_value=0)
        complete = (source_counts == expected) & (valid_counts == expected)
        reduced = reduced.where(complete)
        hourly[column] = reduced
        incomplete_by_variable[str(column)] = int((~complete).sum())

    hourly.attrs.update(dict(data.attrs))
    hourly.attrs["canonical_source_interval_minutes"] = minutes
    hourly.attrs["canonical_native_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    hourly.attrs["canonical_analysis_interval_minutes"] = CANONICAL_ANALYSIS_INTERVAL_MINUTES
    hourly.attrs["canonical_analysis_resolution"] = "hourly"
    hourly.attrs["canonical_hourly_expected_source_records"] = int(expected)
    hourly.attrs["canonical_hourly_completeness_policy"] = HOURLY_COMPLETENESS_POLICY
    hourly.attrs["canonical_hourly_incomplete_hours_by_variable"] = incomplete_by_variable
    hourly.attrs["canonical_hourly_source_rows"] = int(len(data))
    hourly.attrs["canonical_hourly_rows"] = int(len(hourly))
    hourly.attrs["canonical_hourly_reduction_factor"] = (
        float(len(data) / len(hourly)) if len(hourly) else math.nan
    )
    return hourly
