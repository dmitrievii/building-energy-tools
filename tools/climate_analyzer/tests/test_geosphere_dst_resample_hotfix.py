from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from epw_climate_analyzer.aggregations import aggregate_summary, period_total_series
from epw_climate_analyzer.analysis_clock import LOCAL_CIVIL_TIME, analysis_index
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, TIME_BASIS_ATTR


def _vienna_local_frame() -> pd.DataFrame:
    # Use UTC source instants so both DST transitions are physically unambiguous.
    utc = pd.date_range("2024-03-01 00:00", "2024-11-02 23:00", freq="h", tz="UTC")
    local = analysis_index(
        utc,
        mode=LOCAL_CIVIL_TIME,
        local_timezone_name="Europe/Vienna",
        source_timezone_name="UTC",
    )
    frame = pd.DataFrame({"dry_bulb_temperature_c": range(len(local))}, index=local)
    frame.attrs[TIME_BASIS_ATTR] = CHRONOLOGICAL
    return frame


def test_local_civil_analysis_clock_uses_zoneinfo_and_preserves_fall_back_hours() -> None:
    frame = _vienna_local_frame()
    index = pd.DatetimeIndex(frame.index)

    assert isinstance(index.tz, ZoneInfo)
    repeated = index[(index.year == 2024) & (index.month == 10) & (index.day == 27) & (index.hour == 2)]
    assert len(repeated) == 2
    assert repeated[0].utcoffset() != repeated[1].utcoffset()


def test_monthly_summary_resamples_across_vienna_dst_without_nonexistent_time_error() -> None:
    frame = _vienna_local_frame()

    summary = aggregate_summary(frame, "dry_bulb_temperature_c", "Monthly")

    assert not summary.empty
    assert summary.index.tz is not None
    assert {3, 4, 5, 6, 7, 8, 9, 10, 11}.issubset(set(pd.DatetimeIndex(summary.index).month))


def test_monthly_extensive_resample_uses_same_dst_safe_clock() -> None:
    frame = _vienna_local_frame()
    values = pd.Series(1.0, index=frame.index)

    totals = period_total_series(values, frame, "Monthly")

    assert not totals.empty
    assert totals.index.tz is not None
    # October contains the repeated civil hour; both physical observations must
    # survive the local-civil analysis clock and contribute to the monthly total.
    october = totals[pd.DatetimeIndex(totals.index).month == 10]
    assert len(october) == 1
    assert float(october.iloc[0]) == 745.0
