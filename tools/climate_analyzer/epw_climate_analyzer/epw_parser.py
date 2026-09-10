"""EPW parsing utilities.

This module reads EnergyPlus Weather files into a normalized pandas DataFrame.
The parser intentionally avoids heavy EPW-specific dependencies because the EPW
format is a fixed-width CSV-like structure after the header section.

Important typical-year handling
-------------------------------
EPW files are often assembled from different source years: for example, January
may come from one measured year and July from another. Those source years are
valid metadata, but they must not be used as the plotting calendar. If they are
used directly, monthly profiles, heatmaps and duration-by-calendar charts can be
misordered across several real years.

For this reason, this parser preserves the original EPW year in
``epw_source_year`` and rebuilds the DataFrame index as one continuous typical
calendar year. By default, the target typical year is the current runtime year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from typing import BinaryIO, TextIO

import pandas as pd


EPW_COLUMNS = [
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "data_source_uncertainty_flags",
    "dry_bulb_temperature_c",
    "dew_point_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
    "extraterrestrial_horizontal_radiation_wh_m2",
    "extraterrestrial_direct_normal_radiation_wh_m2",
    "horizontal_infrared_radiation_intensity_wh_m2",
    "global_horizontal_radiation_wh_m2",
    "direct_normal_radiation_wh_m2",
    "diffuse_horizontal_radiation_wh_m2",
    "global_horizontal_illuminance_lux",
    "direct_normal_illuminance_lux",
    "diffuse_horizontal_illuminance_lux",
    "zenith_luminance_cd_m2",
    "wind_direction_deg",
    "wind_speed_m_s",
    "total_sky_cover_tenths",
    "opaque_sky_cover_tenths",
    "visibility_km",
    "ceiling_height_m",
    "present_weather_observation",
    "present_weather_codes",
    "precipitable_water_mm",
    "aerosol_optical_depth_thousandths",
    "snow_depth_cm",
    "days_since_last_snowfall",
    "albedo",
    "liquid_precipitation_depth_mm",
    "liquid_precipitation_quantity_hr",
]

MISSING_VALUE_LIMITS = {
    "dry_bulb_temperature_c": 99.0,
    "dew_point_temperature_c": 99.0,
    "relative_humidity_pct": 999.0,
    "atmospheric_station_pressure_pa": 999999.0,
    "global_horizontal_radiation_wh_m2": 9999.0,
    "direct_normal_radiation_wh_m2": 9999.0,
    "diffuse_horizontal_radiation_wh_m2": 9999.0,
    "global_horizontal_illuminance_lux": 999999.0,
    "direct_normal_illuminance_lux": 999999.0,
    "diffuse_horizontal_illuminance_lux": 999999.0,
    "wind_direction_deg": 999.0,
    "wind_speed_m_s": 999.0,
    "total_sky_cover_tenths": 99.0,
    "opaque_sky_cover_tenths": 99.0,
    "visibility_km": 9999.0,
    "ceiling_height_m": 99999.0,
    "precipitable_water_mm": 999.0,
    "snow_depth_cm": 999.0,
    "albedo": 999.0,
    "liquid_precipitation_depth_mm": 999.0,
}

# The parser uses the current runtime year as the unified EPW typical year.
# Keeping this as a module-level constant makes the behavior explicit and easy
# to change later if a fixed reference year is preferred.
DEFAULT_TYPICAL_YEAR = date.today().year


@dataclass(frozen=True)
class EpwLocation:
    """Location metadata extracted from the EPW LOCATION header."""

    city: str
    state: str
    country: str
    source: str
    wmo: str
    latitude: float
    longitude: float
    utc_offset: float
    elevation_m: float


@dataclass(frozen=True)
class EpwFile:
    """Parsed EPW object containing metadata, raw header and hourly data."""

    location: EpwLocation
    header_lines: list[str]
    data: pd.DataFrame
    name: str


@dataclass(frozen=True)
class DataQualityIssue:
    """Simple data-quality issue used by the diagnostics page."""

    field: str
    issue: str
    count: int
    severity: str


def _read_text(file: str | Path | BinaryIO | TextIO) -> tuple[str, str]:
    """Read uploaded or path-based EPW content and return text plus a name."""
    if isinstance(file, (str, Path)):
        path = Path(file)
        return path.read_text(encoding="utf-8", errors="replace"), path.name

    name = getattr(file, "name", "uploaded.epw")
    raw = file.read()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace"), name
    return str(raw), name


def _parse_location(line: str) -> EpwLocation:
    """Parse the EPW LOCATION line into a typed dataclass."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 10 or parts[0].upper() != "LOCATION":
        raise ValueError("The EPW file does not contain a valid LOCATION header.")
    return EpwLocation(
        city=parts[1],
        state=parts[2],
        country=parts[3],
        source=parts[4],
        wmo=parts[5],
        latitude=float(parts[6]),
        longitude=float(parts[7]),
        utc_offset=float(parts[8]),
        elevation_m=float(parts[9]),
    )


def _timezone_name_from_offset(utc_offset: float) -> str:
    """Return an Etc/GMT timezone name from an EPW UTC offset.

    IANA Etc/GMT signs are reversed: UTC+1 is represented as Etc/GMT-1.
    The app only needs a fixed-offset timezone for solar-position calculations.
    """
    rounded = int(round(utc_offset))
    if abs(utc_offset - rounded) > 1e-6:
        return "UTC"
    if rounded == 0:
        return "UTC"
    sign = "-" if rounded > 0 else "+"
    return f"Etc/GMT{sign}{abs(rounded)}"


def _is_leap_year(year: int) -> bool:
    """Return True when the supplied Gregorian year contains February 29."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _next_leap_year(year: int) -> int:
    """Return the nearest leap year greater than or equal to ``year``."""
    candidate = year
    while not _is_leap_year(candidate):
        candidate += 1
    return candidate


def _has_february_29(df: pd.DataFrame) -> bool:
    """Return True if the EPW data contains leap-day rows."""
    return bool(((df["month"].astype("Int64") == 2) & (df["day"].astype("Int64") == 29)).any())


def _resolve_typical_year(df: pd.DataFrame, target_year: int | None = None) -> int:
    """Resolve the unified typical year used for the DataFrame index.

    The default is the current runtime year. If a rare leap-year EPW contains
    February 29 and the current year is not a leap year, the nearest future leap
    year is used to preserve all records without dropping or duplicating hours.
    Standard 8760-hour EPW files still use the current runtime year.
    """
    year = int(target_year or DEFAULT_TYPICAL_YEAR)
    if _has_february_29(df) and not _is_leap_year(year):
        return _next_leap_year(year)
    return year


def build_datetime_index(df: pd.DataFrame, target_year: int | None = None) -> pd.DatetimeIndex:
    """Build a typical-year DatetimeIndex from EPW month, day and hour fields.

    EPW files often store a different source year for each month because they
    are assembled from measured periods. Those years are intentionally ignored
    for plotting and aggregation. The returned index uses one unified typical
    year while preserving the EPW month/day/hour calendar.

    EPW hours are usually 1...24 and represent the end of the interval. For
    plotting and aggregation, the timestamp is shifted to hour-1 on the same
    calendar day, so EPW hour 1 becomes 00:00 and EPW hour 24 becomes 23:00.
    """
    typical_year = _resolve_typical_year(df, target_year)
    hours_zero_based = df["hour"].astype(int).clip(lower=1, upper=24) - 1
    dt_frame = pd.DataFrame(
        {
            "year": typical_year,
            "month": df["month"].astype(int),
            "day": df["day"].astype(int),
            "hour": hours_zero_based,
        }
    )
    index = pd.to_datetime(dt_frame, errors="coerce")

    if index.isna().any():
        # Fall back to a continuous hourly typical-year sequence only for files
        # with invalid calendar fields. This keeps the application usable while
        # preserving the record count.
        safe = pd.date_range(f"{typical_year}-01-01 00:00:00", periods=len(df), freq="h")
        index = pd.DatetimeIndex(safe)

    return pd.DatetimeIndex(index)


def clean_epw_dataframe(df: pd.DataFrame, target_year: int | None = None) -> pd.DataFrame:
    """Normalize numeric columns, replace EPW missing markers and add time fields.

    The original EPW year column is copied to ``epw_source_year`` before the
    typical-year index is created. The public ``year`` column is then replaced
    by the unified plotting year, which prevents all downstream charts from
    accidentally sorting EPW months by their measured source years.
    """
    df = df.copy()
    for column in EPW_COLUMNS:
        if column == "data_source_uncertainty_flags":
            continue
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["epw_source_year"] = df["year"]

    for column, limit in MISSING_VALUE_LIMITS.items():
        if column in df.columns:
            df.loc[df[column] >= limit, column] = pd.NA

    df.index = build_datetime_index(df, target_year=target_year)
    df.index.name = "timestamp"
    df = df.sort_index(kind="mergesort")

    # Keep the user-facing time fields consistent with the rebuilt typical-year
    # index. The original source years remain available in epw_source_year.
    df["year"] = df.index.year
    df["typical_year"] = df.index.year
    df["date"] = df.index.date
    df["month_index"] = df.index.month
    df["month_name"] = df.index.month_name().str.slice(stop=3)
    df["day_of_year"] = df.index.dayofyear
    df["week_of_year"] = df.index.isocalendar().week.astype(int)
    df["hour_of_day"] = df.index.hour
    df["season"] = df["month_index"].map(
        {
            12: "Winter",
            1: "Winter",
            2: "Winter",
            3: "Spring",
            4: "Spring",
            5: "Spring",
            6: "Summer",
            7: "Summer",
            8: "Summer",
            9: "Autumn",
            10: "Autumn",
            11: "Autumn",
        }
    )
    return df


def parse_epw(file: str | Path | BinaryIO | TextIO) -> EpwFile:
    """Parse an EPW file and return metadata plus a normalized DataFrame."""
    text, name = _read_text(file)
    lines = text.splitlines()
    if len(lines) < 10:
        raise ValueError("The uploaded file is too short to be a valid EPW file.")

    header_lines = lines[:8]
    location = _parse_location(header_lines[0])
    data_text = "\n".join(lines[8:])
    df = pd.read_csv(StringIO(data_text), header=None, names=EPW_COLUMNS)
    df = clean_epw_dataframe(df)
    df.attrs["timezone_name"] = _timezone_name_from_offset(location.utc_offset)
    df.attrs["typical_year"] = int(df["typical_year"].iloc[0]) if not df.empty else DEFAULT_TYPICAL_YEAR
    df.attrs["source_years"] = sorted(int(y) for y in df["epw_source_year"].dropna().unique())
    return EpwFile(location=location, header_lines=header_lines, data=df, name=name)


def quality_issues(df: pd.DataFrame) -> list[DataQualityIssue]:
    """Return a compact list of common EPW data-quality issues."""
    issues: list[DataQualityIssue] = []

    for column in df.columns:
        missing = int(df[column].isna().sum())
        if missing > 0 and column not in {"date", "month_name", "season"}:
            issues.append(DataQualityIssue(column, "Missing or EPW sentinel values", missing, "warning"))

    if "dew_point_temperature_c" in df and "dry_bulb_temperature_c" in df:
        count = int((df["dew_point_temperature_c"] > df["dry_bulb_temperature_c"]).sum())
        if count:
            issues.append(DataQualityIssue("dew_point_temperature_c", "Dew point above dry-bulb temperature", count, "error"))

    if "relative_humidity_pct" in df:
        count = int(((df["relative_humidity_pct"] < 0) | (df["relative_humidity_pct"] > 100)).sum())
        if count:
            issues.append(DataQualityIssue("relative_humidity_pct", "Relative humidity outside 0...100%", count, "error"))

    if "wind_direction_deg" in df:
        count = int(((df["wind_direction_deg"] < 0) | (df["wind_direction_deg"] > 360)).sum())
        if count:
            issues.append(DataQualityIssue("wind_direction_deg", "Wind direction outside 0...360 degrees", count, "error"))

    if "global_horizontal_radiation_wh_m2" in df:
        night_like = (df["hour_of_day"] < 4) | (df["hour_of_day"] > 22)
        count = int((night_like & (df["global_horizontal_radiation_wh_m2"] > 20)).sum())
        if count:
            issues.append(DataQualityIssue("global_horizontal_radiation_wh_m2", "Positive night-time GHI proxy check", count, "warning"))

    return issues


def location_summary(location: EpwLocation) -> dict[str, object]:
    """Return location metadata formatted for display in the UI."""
    return {
        "City": location.city,
        "State": location.state,
        "Country": location.country,
        "Source": location.source,
        "WMO": location.wmo,
        "Latitude": location.latitude,
        "Longitude": location.longitude,
        "UTC offset": location.utc_offset,
        "Elevation [m]": location.elevation_m,
    }
