"""Source-neutral psychrometric derived quantities and chart curves.

The module uses PsychroLib for ASHRAE-style moist-air calculations and accepts
ordinary timestamped pandas DataFrames.  Provider/source adapters only need to
supply canonical dry-bulb temperature, relative humidity and (when available)
station pressure; missing pressure falls back explicitly to the caller-selected
reference pressure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import psychrolib

psychrolib.SetUnitSystem(psychrolib.SI)

DEFAULT_PRESSURE_PA = 101325.0
VARIABLE_ORIGIN_ATTR = "canonical_variable_origin"


def pressure_from_altitude_m(altitude_m: float) -> float:
    """Return standard atmospheric pressure in Pa for a given altitude in metres."""
    return float(psychrolib.GetStandardAtmPressure(float(altitude_m)))


def resolve_pressure_pa(
    pressure_pa: float | None,
    altitude_m: float | None,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
) -> float:
    """Resolve pressure from explicit pressure, altitude or default pressure."""
    if pressure_pa is not None and pressure_pa > 0:
        return float(pressure_pa)
    if altitude_m is not None:
        return pressure_from_altitude_m(float(altitude_m))
    return float(fallback_pressure_pa)


def _safe_station_pressure(row_pressure: float | None, fallback_pressure_pa: float) -> float:
    """Return a valid pressure for row-wise psychrometric calculations."""
    if pd.notna(row_pressure) and 30_000 <= float(row_pressure) <= 120_000:
        return float(row_pressure)
    return float(fallback_pressure_pa)


def _numeric_column_or_nan(df: pd.DataFrame, column: str) -> np.ndarray:
    if column not in df.columns:
        return np.full(len(df), np.nan, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)


def _record_variable_origin(df: pd.DataFrame, column: str, description: str) -> None:
    origins = dict(df.attrs.get(VARIABLE_ORIGIN_ATTR, {}))
    origins[str(column)] = str(description)
    df.attrs[VARIABLE_ORIGIN_ATTR] = origins


def add_psychrometric_properties(df: pd.DataFrame, fallback_pressure_pa: float = DEFAULT_PRESSURE_PA) -> pd.DataFrame:
    """Add psychrometric properties to a canonical climate DataFrame.

    Existing source dew-point observations are preserved.  Where dew point is
    absent or missing, it is calculated from the same dry-bulb/RH state used for
    the other psychrometric quantities and the affected rows are marked in
    ``dew_point_temperature_is_calculated``.  This keeps EPW source dew point
    intact while giving measured sources such as GeoSphere the same complete
    psychrometric state without dataset-specific code.

    Added/filled fields:
        - dew_point_temperature_c
        - dew_point_temperature_is_calculated
        - vapor_pressure_pa
        - saturation_vapor_pressure_pa
        - humidity_ratio_kg_kg
        - humidity_ratio_g_kg
        - moist_air_enthalpy_kj_kg
        - wet_bulb_temperature_c
        - specific_volume_m3_kg
        - moist_air_density_kg_m3
        - degree_of_saturation
    """
    attrs = dict(df.attrs)
    data = df.copy()
    data.attrs.update(attrs)
    n = len(data)
    if n == 0:
        return data

    fallback = float(fallback_pressure_pa)
    if not 30_000.0 <= fallback <= 120_000.0:
        raise ValueError("Psychrometric fallback pressure must be within 30000...120000 Pa.")

    t = _numeric_column_or_nan(data, "dry_bulb_temperature_c")
    rh_pct = _numeric_column_or_nan(data, "relative_humidity_pct")
    pressure_raw = _numeric_column_or_nan(data, "atmospheric_station_pressure_pa")
    pressure = np.where(
        np.isfinite(pressure_raw) & (pressure_raw >= 30_000.0) & (pressure_raw <= 120_000.0),
        pressure_raw,
        fallback,
    )

    valid = np.isfinite(t) & np.isfinite(rh_pct) & np.isfinite(pressure)
    rh = np.clip(rh_pct / 100.0, 0.0, 1.0)

    w = np.full(n, np.nan, dtype=float)
    h = np.full(n, np.nan, dtype=float)
    twb = np.full(n, np.nan, dtype=float)
    tdp_calculated = np.full(n, np.nan, dtype=float)
    v = np.full(n, np.nan, dtype=float)
    rho = np.full(n, np.nan, dtype=float)
    vap = np.full(n, np.nan, dtype=float)
    sat_vap = np.full(n, np.nan, dtype=float)
    degree = np.full(n, np.nan, dtype=float)

    if valid.any():
        idx = np.where(valid)[0]
        t_valid = t[idx]
        rh_valid = rh[idx]
        p_valid = pressure[idx]

        sat = np.array([psychrolib.GetSatVapPres(float(tv)) for tv in t_valid], dtype=float)
        pv = rh_valid * sat
        pv = np.minimum(pv, p_valid * 0.999999)
        w_valid = 0.621945 * pv / np.maximum(p_valid - pv, 1e-9)
        w_valid = np.maximum(w_valid, psychrolib.MIN_HUM_RATIO)

        h_valid = 1.006 * t_valid + w_valid * (2501.0 + 1.86 * t_valid)
        t_k = t_valid + 273.15
        v_valid = 287.042 * t_k * (1.0 + 1.607858 * w_valid) / p_valid
        rho_valid = (1.0 + w_valid) / v_valid
        w_sat = 0.621945 * sat / np.maximum(p_valid - sat, 1e-9)
        degree_valid = w_valid / np.maximum(w_sat, 1e-12)

        w[idx] = w_valid
        h[idx] = h_valid
        v[idx] = v_valid
        rho[idx] = rho_valid
        vap[idx] = pv
        sat_vap[idx] = sat
        degree[idx] = degree_valid

        # Wet-bulb and dew-point inversions stay delegated to PsychroLib.  The
        # loop is restricted to valid source rows and therefore remains modest
        # compared with repeated pandas row access.
        for out_i, tv, rh_value, wv, pv_press in zip(
            idx, t_valid, rh_valid, w_valid, p_valid, strict=False
        ):
            try:
                twb[out_i] = psychrolib.GetTWetBulbFromHumRatio(float(tv), float(wv), float(pv_press))
            except Exception:
                twb[out_i] = np.nan
            try:
                # PsychroLib defines dew point from dry-bulb and vapour pressure;
                # GetTDewPointFromRelHum performs that inversion consistently.
                tdp_calculated[out_i] = psychrolib.GetTDewPointFromRelHum(float(tv), float(rh_value))
            except Exception:
                tdp_calculated[out_i] = np.nan

    source_dew = _numeric_column_or_nan(data, "dew_point_temperature_c")
    dew_fill_mask = ~np.isfinite(source_dew) & np.isfinite(tdp_calculated)
    resolved_dew = source_dew.copy()
    resolved_dew[dew_fill_mask] = tdp_calculated[dew_fill_mask]

    data["dew_point_temperature_c"] = resolved_dew
    data["dew_point_temperature_is_calculated"] = dew_fill_mask
    data["humidity_ratio_kg_kg"] = w
    data["humidity_ratio_g_kg"] = w * 1000.0
    data["moist_air_enthalpy_kj_kg"] = h
    data["wet_bulb_temperature_c"] = twb
    data["specific_volume_m3_kg"] = v
    data["moist_air_density_kg_m3"] = rho
    data["vapor_pressure_pa"] = vap
    data["saturation_vapor_pressure_pa"] = sat_vap
    data["degree_of_saturation"] = degree

    if dew_fill_mask.any():
        if np.isfinite(source_dew).any():
            origin = "source values preserved; missing rows calculated from dry-bulb temperature and relative humidity (PsychroLib)"
        else:
            origin = "calculated from dry-bulb temperature and relative humidity (PsychroLib)"
        _record_variable_origin(data, "dew_point_temperature_c", origin)
    _record_variable_origin(data, "wet_bulb_temperature_c", "calculated from canonical moist-air state (PsychroLib)")
    _record_variable_origin(data, "humidity_ratio_g_kg", "calculated from dry-bulb temperature, relative humidity and pressure")
    _record_variable_origin(data, "moist_air_enthalpy_kj_kg", "calculated from dry-bulb temperature and humidity ratio")
    data.attrs.update({key: value for key, value in attrs.items() if key != VARIABLE_ORIGIN_ATTR})
    return data


def psychrometric_rh_curves(
    chart_type: str,
    pressure_pa: float = DEFAULT_PRESSURE_PA,
    t_min_c: float = -10.0,
    t_max_c: float = 50.0,
    t_step_c: float = 0.5,
) -> list[dict[str, object]]:
    """Generate relative-humidity curves for T-d or i-d psychrometric charts."""
    t_values = np.arange(t_min_c, t_max_c + t_step_c, t_step_c)
    curves: list[dict[str, object]] = []
    for rh in np.arange(0.1, 1.01, 0.1):
        x_values: list[float] = []
        y_values: list[float] = []
        for t in t_values:
            try:
                w = psychrolib.GetHumRatioFromRelHum(float(t), float(rh), pressure_pa)
                d = w * 1000.0
                h = psychrolib.GetMoistAirEnthalpy(float(t), w) / 1000.0
            except Exception:
                continue
            if chart_type == "i-d":
                x_values.append(d)
                y_values.append(h)
            else:
                x_values.append(float(t))
                y_values.append(d)
        curves.append(
            {
                "label": f"RH {int(rh * 100)}%",
                "rh": float(rh),
                "x": x_values,
                "y": y_values,
            }
        )
    return curves
