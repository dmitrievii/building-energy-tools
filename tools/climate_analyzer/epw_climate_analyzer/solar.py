"""Solar-position and surface-irradiance helpers.

The module uses pvlib for solar-position and plane-of-array irradiance
calculations. These functions support early-stage solar, shading and PV-oriented
climate analysis from EPW data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .epw_parser import EpwLocation


def fixed_offset_timezone_name(utc_offset: float) -> str:
    """Return an IANA fixed-offset timezone name from an EPW UTC offset."""
    rounded = int(round(utc_offset))
    if rounded == 0:
        return "UTC"
    sign = "-" if rounded > 0 else "+"
    return f"Etc/GMT{sign}{abs(rounded)}"


def localized_times(df: pd.DataFrame, location: EpwLocation) -> pd.DatetimeIndex:
    """Return the DataFrame index localized to the EPW fixed UTC offset."""
    tz_name = fixed_offset_timezone_name(location.utc_offset)
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        return index.tz_convert(tz_name)
    return index.tz_localize(tz_name, ambiguous="NaT", nonexistent="shift_forward")


def add_solar_position(df: pd.DataFrame, location: EpwLocation) -> pd.DataFrame:
    """Add apparent zenith, elevation and azimuth columns using pvlib."""
    import pvlib

    data = df.copy()
    times = localized_times(data, location)
    solpos = pvlib.solarposition.get_solarposition(
        time=times,
        latitude=location.latitude,
        longitude=location.longitude,
        altitude=location.elevation_m,
    )
    data["solar_apparent_zenith_deg"] = solpos["apparent_zenith"].to_numpy()
    data["solar_elevation_deg"] = solpos["apparent_elevation"].to_numpy()
    data["solar_azimuth_deg"] = solpos["azimuth"].to_numpy()
    data["is_daylight"] = data["solar_elevation_deg"] > 0
    return data


def surface_irradiance_series(
    df: pd.DataFrame,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    albedo: float = 0.2,
) -> pd.Series:
    """Calculate total plane-of-array irradiance for a tilted surface."""
    import pvlib

    required = [
        "solar_apparent_zenith_deg",
        "solar_azimuth_deg",
        "direct_normal_radiation_wh_m2",
        "global_horizontal_radiation_wh_m2",
        "diffuse_horizontal_radiation_wh_m2",
    ]
    for column in required:
        if column not in df.columns:
            raise ValueError(f"Missing required column for irradiance calculation: {column}")

    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=surface_tilt_deg,
        surface_azimuth=surface_azimuth_deg,
        solar_zenith=df["solar_apparent_zenith_deg"].clip(lower=0, upper=180),
        solar_azimuth=df["solar_azimuth_deg"],
        dni=df["direct_normal_radiation_wh_m2"].fillna(0).clip(lower=0),
        ghi=df["global_horizontal_radiation_wh_m2"].fillna(0).clip(lower=0),
        dhi=df["diffuse_horizontal_radiation_wh_m2"].fillna(0).clip(lower=0),
        albedo=albedo,
    )
    return pd.Series(poa["poa_global"].to_numpy(), index=df.index, name="poa_global_wh_m2")


def orientation_annual_radiation(df: pd.DataFrame, tilt_deg: float = 90.0) -> pd.DataFrame:
    """Return annual radiation sums for façade orientations."""
    orientations = {
        "North": 0.0,
        "North-East": 45.0,
        "East": 90.0,
        "South-East": 135.0,
        "South": 180.0,
        "South-West": 225.0,
        "West": 270.0,
        "North-West": 315.0,
    }
    rows = []
    for label, azimuth in orientations.items():
        poa = surface_irradiance_series(df, tilt_deg, azimuth)
        rows.append({"orientation": label, "azimuth_deg": azimuth, "annual_kwh_m2": poa.sum() / 1000.0})
    return pd.DataFrame(rows)


def orientation_tilt_matrix(
    df: pd.DataFrame,
    tilt_values: list[float] | None = None,
    azimuth_values: list[float] | None = None,
) -> pd.DataFrame:
    """Calculate an annual kWh/m² matrix for orientation and tilt combinations."""
    if tilt_values is None:
        tilt_values = list(np.arange(0, 91, 10))
    if azimuth_values is None:
        azimuth_values = list(np.arange(0, 360, 15))

    rows = []
    for tilt in tilt_values:
        for azimuth in azimuth_values:
            poa = surface_irradiance_series(df, float(tilt), float(azimuth))
            rows.append(
                {
                    "tilt_deg": float(tilt),
                    "azimuth_deg": float(azimuth),
                    "annual_kwh_m2": poa.sum() / 1000.0,
                }
            )
    return pd.DataFrame(rows).pivot(index="tilt_deg", columns="azimuth_deg", values="annual_kwh_m2")


def monthly_orientation_radiation(df: pd.DataFrame, tilt_deg: float = 90.0) -> pd.DataFrame:
    """Return monthly radiation sums for main façade orientations."""
    orientations = {"North": 0.0, "East": 90.0, "South": 180.0, "West": 270.0}
    result = pd.DataFrame(index=range(1, 13))
    for label, azimuth in orientations.items():
        poa = surface_irradiance_series(df, tilt_deg, azimuth)
        result[label] = poa.groupby(df["month_index"]).sum() / 1000.0
    result.index.name = "month"
    return result
