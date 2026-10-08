"""Source-neutral solar-position and surface-irradiance helpers.

The module uses pvlib for solar position and plane-of-array irradiance.  Source
adapters are responsible only for exposing timestamped physical quantities and
location metadata; all solar geometry and derived-radiation calculations live
here and operate on ordinary pandas DataFrames.

When measured GHI and DHI are available but DNI is not, direct normal
irradiation can be reconstructed from the horizontal radiation balance

    GHI = DHI + DNI * cos(theta_z)

at the same interval.  The reconstruction is deliberately disabled very close
to the horizon where division by a small cosine would amplify measurement
noise.  Existing measured DNI is never overwritten.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_ALBEDO = 0.20
DEFAULT_DNI_MIN_COS_ZENITH = 0.065
VARIABLE_ORIGIN_ATTR = "canonical_variable_origin"

# Streamlit can retain this module after app.py has been hot-updated on disk.
# A source fingerprint lets runtime_module_guard reload only on deploy changes.
_RUNTIME_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def fixed_offset_timezone_name(utc_offset: float) -> str:
    """Return an exact human-readable fixed UTC-offset label."""
    total_minutes = int(round(float(utc_offset) * 60.0))
    if total_minutes == 0:
        return "UTC"
    sign = "+" if total_minutes > 0 else "-"
    absolute = abs(total_minutes)
    hours, minutes = divmod(absolute, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def fixed_offset_timezone(utc_offset: float) -> timezone:
    """Return a ``datetime.timezone`` preserving an offset to the minute."""
    total_minutes = int(round(float(utc_offset) * 60.0))
    return timezone(timedelta(minutes=total_minutes), name=fixed_offset_timezone_name(utc_offset))


def _copy_attrs(source: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    target.attrs.update(dict(source.attrs))
    return target


def _record_variable_origin(df: pd.DataFrame, column: str, description: str) -> None:
    origins = dict(df.attrs.get(VARIABLE_ORIGIN_ATTR, {}))
    origins[str(column)] = str(description)
    df.attrs[VARIABLE_ORIGIN_ATTR] = origins


def variable_origin(df: pd.DataFrame, column: str) -> str:
    """Return a human-readable measured/calculated provenance label."""
    origins = df.attrs.get(VARIABLE_ORIGIN_ATTR, {})
    if isinstance(origins, dict) and column in origins:
        return str(origins[column])
    return "source / measured when supplied by provider"


def localized_times(df: pd.DataFrame, location: Any) -> pd.DatetimeIndex:
    """Return timestamps appropriate for an EPW-style fixed-offset location.

    This compatibility helper retains the original EPW behaviour.  For real
    historical sources with timezone-aware timestamps use
    :func:`solar_position_times` directly; physical solar geometry is invariant
    to whether the same instant is represented in UTC or local civil time.
    """
    utc_offset = float(getattr(location, "utc_offset"))
    tz_info = fixed_offset_timezone(utc_offset)
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        return index.tz_convert(tz_info)
    return index.tz_localize(tz_info)


def solar_position_times(
    df: pd.DataFrame,
    *,
    timezone_name: str | None = None,
    utc_offset_hours: float | None = None,
) -> pd.DatetimeIndex:
    """Return timezone-aware instants for source-neutral solar calculations.

    Historical provider data normally arrive timezone-aware (GeoSphere is UTC),
    so those instants are used unchanged.  A naive EPW plotting calendar needs
    its documented fixed standard-time offset attached before pvlib is called.
    ``timezone_name`` is used only for naive historical/custom frames.
    """
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        return index
    if utc_offset_hours is not None:
        return index.tz_localize(fixed_offset_timezone(float(utc_offset_hours)))
    if timezone_name:
        return index.tz_localize(str(timezone_name), ambiguous="infer", nonexistent="shift_forward")
    return index.tz_localize("UTC")


def add_solar_position_for_site(
    df: pd.DataFrame,
    *,
    latitude: float,
    longitude: float,
    elevation_m: float | None = None,
    timezone_name: str | None = None,
    utc_offset_hours: float | None = None,
) -> pd.DataFrame:
    """Add apparent zenith/elevation/azimuth for an abstract climate site."""
    import pvlib

    data = _copy_attrs(df, df.copy())
    times = solar_position_times(
        data,
        timezone_name=timezone_name,
        utc_offset_hours=utc_offset_hours,
    )
    solpos = pvlib.solarposition.get_solarposition(
        time=times,
        latitude=float(latitude),
        longitude=float(longitude),
        altitude=float(elevation_m or 0.0),
    )
    data["solar_apparent_zenith_deg"] = solpos["apparent_zenith"].to_numpy()
    data["solar_elevation_deg"] = solpos["apparent_elevation"].to_numpy()
    data["solar_azimuth_deg"] = solpos["azimuth"].to_numpy()
    data["is_daylight"] = data["solar_elevation_deg"] > 0.0
    _record_variable_origin(data, "solar_apparent_zenith_deg", "calculated from timestamp and site coordinates (pvlib)")
    _record_variable_origin(data, "solar_elevation_deg", "calculated from timestamp and site coordinates (pvlib)")
    _record_variable_origin(data, "solar_azimuth_deg", "calculated from timestamp and site coordinates (pvlib)")
    return data


def add_solar_position(df: pd.DataFrame, location: Any) -> pd.DataFrame:
    """Backward-compatible wrapper accepting an EPW location-like object."""
    return add_solar_position_for_site(
        df,
        latitude=float(getattr(location, "latitude")),
        longitude=float(getattr(location, "longitude")),
        elevation_m=float(getattr(location, "elevation_m", 0.0) or 0.0),
        utc_offset_hours=float(getattr(location, "utc_offset")),
    )


def derive_direct_normal_radiation(
    df: pd.DataFrame,
    *,
    overwrite: bool = False,
    min_cos_zenith: float = DEFAULT_DNI_MIN_COS_ZENITH,
) -> pd.DataFrame:
    """Derive interval DNI from coincident GHI, DHI and solar geometry.

    GHI, DHI and the resulting DNI are all interval irradiation quantities in
    Wh/m², so the interval duration cancels from the horizontal-balance equation.
    Existing numeric DNI is retained by default.  Night-time values are set to
    zero; daylight values too close to the horizon are left missing because the
    inverse cosine becomes ill-conditioned there.
    """
    data = _copy_attrs(df, df.copy())
    required = {
        "global_horizontal_radiation_wh_m2",
        "diffuse_horizontal_radiation_wh_m2",
        "solar_apparent_zenith_deg",
    }
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError("DNI derivation requires canonical columns: " + ", ".join(missing))

    if not overwrite and "direct_normal_radiation_wh_m2" in data.columns:
        existing = pd.to_numeric(data["direct_normal_radiation_wh_m2"], errors="coerce")
        if existing.notna().any():
            return data

    ghi = pd.to_numeric(data["global_horizontal_radiation_wh_m2"], errors="coerce")
    dhi = pd.to_numeric(data["diffuse_horizontal_radiation_wh_m2"], errors="coerce")
    zenith = pd.to_numeric(data["solar_apparent_zenith_deg"], errors="coerce")
    cos_zenith = np.cos(np.deg2rad(zenith.astype(float)))
    direct_horizontal = (ghi - dhi).clip(lower=0.0)

    result = pd.Series(np.nan, index=data.index, dtype="float64")
    night = cos_zenith <= 0.0
    stable_daylight = cos_zenith >= float(min_cos_zenith)
    valid = stable_daylight & direct_horizontal.notna() & np.isfinite(cos_zenith)
    result.loc[night & ghi.notna() & dhi.notna()] = 0.0
    result.loc[valid] = direct_horizontal.loc[valid] / cos_zenith[valid]
    result = result.clip(lower=0.0)
    data["direct_normal_radiation_wh_m2"] = result
    data["direct_normal_radiation_is_calculated"] = result.notna()
    _record_variable_origin(
        data,
        "direct_normal_radiation_wh_m2",
        "calculated from measured/available GHI and DHI using GHI = DHI + DNI·cos(zenith); horizon-guarded",
    )
    return data


def ensure_solar_radiation_components(
    df: pd.DataFrame,
    *,
    latitude: float,
    longitude: float,
    elevation_m: float | None = None,
    timezone_name: str | None = None,
    utc_offset_hours: float | None = None,
) -> pd.DataFrame:
    """Return a frame with solar geometry and calculable DNI added.

    This is the canonical source-neutral entry point used by EPW, measured
    historical datasets and comparison.  It never fabricates a missing DHI; DNI
    is derived only when both horizontal components are physically available.
    """
    data = add_solar_position_for_site(
        df,
        latitude=latitude,
        longitude=longitude,
        elevation_m=elevation_m,
        timezone_name=timezone_name,
        utc_offset_hours=utc_offset_hours,
    )
    has_ghi = "global_horizontal_radiation_wh_m2" in data.columns and pd.to_numeric(
        data["global_horizontal_radiation_wh_m2"], errors="coerce"
    ).notna().any()
    has_dhi = "diffuse_horizontal_radiation_wh_m2" in data.columns and pd.to_numeric(
        data["diffuse_horizontal_radiation_wh_m2"], errors="coerce"
    ).notna().any()
    has_dni = "direct_normal_radiation_wh_m2" in data.columns and pd.to_numeric(
        data["direct_normal_radiation_wh_m2"], errors="coerce"
    ).notna().any()
    if has_ghi and has_dhi and not has_dni:
        data = derive_direct_normal_radiation(data)
    return data


def albedo_source_diagnostics(df: pd.DataFrame) -> dict[str, float | int] | None:
    """Describe source albedo without changing the underlying EPW observations.

    An extreme modal albedo is a plausibility warning, not proof that an EPW
    field is incorrect. The analysis distinguishes invalid numeric entries,
    missing values, and physically possible but unusually high reflectance.
    """
    if "albedo" not in df.columns:
        return None
    raw = pd.to_numeric(df["albedo"], errors="coerce")
    valid_mask = np.isfinite(raw) & raw.between(0.0, 1.0)
    valid = raw.loc[valid_mask]
    if valid.empty:
        return {
            "total_count": int(len(raw)), "valid_count": 0,
            "missing_count": int(raw.isna().sum()),
            "invalid_count": int((raw.notna() & ~valid_mask).sum()),
            "high_count": 0, "high_fraction": 0.0,
        }
    rounded = valid.round(3)
    mode_counts = rounded.value_counts()
    dominant = float(mode_counts.index[0])
    return {
        "total_count": int(len(raw)),
        "valid_count": int(len(valid)),
        "missing_count": int(raw.isna().sum()),
        "invalid_count": int((raw.notna() & ~valid_mask).sum()),
        "mean": float(valid.mean()),
        "minimum": float(valid.min()),
        "maximum": float(valid.max()),
        "high_count": int((valid >= 0.5).sum()),
        "high_fraction": float((valid >= 0.5).mean()),
        "dominant_value": dominant,
        "dominant_count": int(mode_counts.iloc[0]),
    }


def source_ground_albedo(df: pd.DataFrame) -> pd.Series:
    """Resolve EPW/provider albedo *only* when explicitly selected by the user.

    Source entries outside the physical 0..1 range fail rather than being
    silently clipped. Only genuinely missing entries use the documented
    standard-ground fallback (0.20); original source data are never overwritten.
    """
    if "albedo" not in df.columns:
        raise ValueError("Source ground albedo is unavailable for this climate.")
    raw = pd.to_numeric(df["albedo"], errors="coerce")
    invalid = raw.notna() & (~np.isfinite(raw) | ~raw.between(0.0, 1.0))
    if invalid.any():
        raise ValueError(
            f"Source ground albedo contains {int(invalid.sum())} values outside 0..1; "
            "review the source data before using this mode."
        )
    if not raw.notna().any():
        raise ValueError("Source ground albedo has no valid numeric observations.")
    return raw.fillna(DEFAULT_ALBEDO)


def _resolved_albedo(df: pd.DataFrame, albedo: float | pd.Series | None) -> float | pd.Series:
    """Standard ground is the default, even when the EPW contains albedo.

    Callers choosing source observations must explicitly pass
    ``source_ground_albedo(df)``. A numeric argument is an explicit custom
    constant. No numeric values are silently clipped.
    """
    if isinstance(albedo, pd.Series):
        values = pd.to_numeric(albedo.reindex(df.index), errors="coerce")
        invalid = values.notna() & (~np.isfinite(values) | ~values.between(0.0, 1.0))
        if invalid.any():
            raise ValueError("Ground albedo series contains values outside 0..1.")
        return values.fillna(DEFAULT_ALBEDO)
    if albedo is None:
        return DEFAULT_ALBEDO
    value = float(albedo)
    if not np.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("Albedo must be finite and between 0 and 1.")
    return value


def surface_irradiance_components(
    df: pd.DataFrame,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    albedo: float | pd.Series | None = None,
) -> pd.DataFrame:
    """Return the coincident direct, sky-diffuse, ground and total POA irradiation.

    All outputs are interval energies in Wh/m², masked when mandatory radiation
    or solar-geometry fields are missing. The default calculation uses standard
    ground reflectance 0.20; EPW/provider albedo is never selected implicitly.

    Ground reflection assumes an unobstructed isotropic horizontal ground
    surface and therefore does not represent urban canyon view-factor effects.
    """
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

    solar_zenith = pd.to_numeric(df["solar_apparent_zenith_deg"], errors="coerce").clip(lower=0, upper=180)
    solar_azimuth = pd.to_numeric(df["solar_azimuth_deg"], errors="coerce")
    dni = pd.to_numeric(df["direct_normal_radiation_wh_m2"], errors="coerce")
    ghi = pd.to_numeric(df["global_horizontal_radiation_wh_m2"], errors="coerce")
    dhi = pd.to_numeric(df["diffuse_horizontal_radiation_wh_m2"], errors="coerce")
    valid_inputs = solar_zenith.notna() & solar_azimuth.notna() & dni.notna() & ghi.notna() & dhi.notna()

    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=float(surface_tilt_deg),
        surface_azimuth=float(surface_azimuth_deg),
        solar_zenith=solar_zenith,
        solar_azimuth=solar_azimuth,
        dni=dni.fillna(0).clip(lower=0),
        ghi=ghi.fillna(0).clip(lower=0),
        dhi=dhi.fillna(0).clip(lower=0),
        albedo=_resolved_albedo(df, albedo),
    )
    columns = {
        "poa_direct_wh_m2": "poa_direct",
        "poa_sky_diffuse_wh_m2": "poa_sky_diffuse",
        "poa_ground_diffuse_wh_m2": "poa_ground_diffuse",
        "poa_global_wh_m2": "poa_global",
    }
    result = pd.DataFrame(
        {name: np.asarray(poa[source], dtype=float) for name, source in columns.items()},
        index=df.index,
    )
    result = result.where(valid_inputs, axis=0)
    result.attrs["albedo_origin"] = (
        "standard ground 0.20 (explicit default)" if albedo is None
        else "explicit hourly source/series with missing-value fallback 0.20"
        if isinstance(albedo, pd.Series)
        else f"explicit constant {float(albedo):g}"
    )
    result.attrs["surface_tilt_deg"] = float(surface_tilt_deg)
    result.attrs["surface_azimuth_deg"] = float(surface_azimuth_deg)
    return result


def surface_irradiance_series(
    df: pd.DataFrame,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    albedo: float | pd.Series | None = None,
) -> pd.Series:
    """Calculate total POA interval irradiation; default is ground albedo 0.20."""
    components = surface_irradiance_components(
        df, surface_tilt_deg, surface_azimuth_deg, albedo=albedo,
    )
    result = components["poa_global_wh_m2"].rename("poa_global_wh_m2")
    result.attrs.update(components.attrs)
    return result


def orientation_annual_radiation(
    df: pd.DataFrame, tilt_deg: float = 90.0,
    albedo: float | pd.Series | None = None,
) -> pd.DataFrame:
    """Return annual/selected-period radiation sums for façade orientations."""
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
        poa = surface_irradiance_series(df, tilt_deg, azimuth, albedo=albedo)
        rows.append({"orientation": label, "azimuth_deg": azimuth, "annual_kwh_m2": poa.sum() / 1000.0})
    return pd.DataFrame(rows)


def orientation_tilt_matrix(
    df: pd.DataFrame,
    tilt_values: list[float] | None = None,
    azimuth_values: list[float] | None = None,
    albedo: float | pd.Series | None = None,
) -> pd.DataFrame:
    """Calculate a kWh/m² matrix for orientation and tilt combinations."""
    if tilt_values is None:
        tilt_values = list(np.arange(0, 91, 10))
    if azimuth_values is None:
        azimuth_values = list(np.arange(0, 360, 15))

    rows = []
    for tilt in tilt_values:
        for azimuth in azimuth_values:
            poa = surface_irradiance_series(df, float(tilt), float(azimuth), albedo=albedo)
            rows.append(
                {
                    "tilt_deg": float(tilt),
                    "azimuth_deg": float(azimuth),
                    "annual_kwh_m2": poa.sum() / 1000.0,
                }
            )
    return pd.DataFrame(rows).pivot(index="tilt_deg", columns="azimuth_deg", values="annual_kwh_m2")


def monthly_orientation_radiation(
    df: pd.DataFrame, tilt_deg: float = 90.0,
    albedo: float | pd.Series | None = None,
) -> pd.DataFrame:
    """Return monthly radiation sums for main façade orientations."""
    orientations = {"North": 0.0, "East": 90.0, "South": 180.0, "West": 270.0}
    result = pd.DataFrame(index=range(1, 13))
    for label, azimuth in orientations.items():
        poa = surface_irradiance_series(df, tilt_deg, azimuth, albedo=albedo)
        result[label] = poa.groupby(df["month_index"]).sum() / 1000.0
    result.index.name = "month"
    return result
