"""Psychrometric derived quantities and chart curves.

The module uses PsychroLib for ASHRAE-style moist-air calculations. The app does
not reimplement these equations manually; PsychroLib is used as the calculation
backend for humidity ratio, enthalpy, wet-bulb temperature, dew point, specific
volume, density and standard atmosphere pressure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import psychrolib

psychrolib.SetUnitSystem(psychrolib.SI)

DEFAULT_PRESSURE_PA = 101325.0


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


def add_psychrometric_properties(df: pd.DataFrame, fallback_pressure_pa: float = DEFAULT_PRESSURE_PA) -> pd.DataFrame:
    """Add psychrometric properties to an EPW DataFrame.

    The implementation avoids ``DataFrame.iterrows()`` because that made EPW
    loading unnecessarily slow. Humidity ratio, vapour pressure, enthalpy,
    volume, density and degree of saturation are calculated with vectorized
    ASHRAE/PsychroLib-equivalent equations. Wet-bulb temperature is still
    calculated with PsychroLib because it is an iterative psychrometric
    inversion, but the loop is restricted to valid rows only.

    Added fields:
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
    data = df.copy()
    n = len(data)
    if n == 0:
        return data

    t = pd.to_numeric(data.get("dry_bulb_temperature_c"), errors="coerce").to_numpy(dtype=float)
    rh_pct = pd.to_numeric(data.get("relative_humidity_pct"), errors="coerce").to_numpy(dtype=float)
    pressure_raw = pd.to_numeric(data.get("atmospheric_station_pressure_pa"), errors="coerce").to_numpy(dtype=float)
    pressure = np.where((pressure_raw >= 30_000.0) & (pressure_raw <= 120_000.0), pressure_raw, float(fallback_pressure_pa))

    valid = np.isfinite(t) & np.isfinite(rh_pct) & np.isfinite(pressure)
    rh = np.clip(rh_pct / 100.0, 0.0, 1.0)

    w = np.full(n, np.nan, dtype=float)
    h = np.full(n, np.nan, dtype=float)
    twb = np.full(n, np.nan, dtype=float)
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

        # PsychroLib saturation pressure is scalar; this loop is cheap compared
        # with the wet-bulb inversion and keeps the saturation curve identical
        # to the PsychroLib implementation.
        sat = np.array([psychrolib.GetSatVapPres(float(tv)) for tv in t_valid], dtype=float)
        pv = rh_valid * sat
        pv = np.minimum(pv, p_valid * 0.999999)
        w_valid = 0.621945 * pv / np.maximum(p_valid - pv, 1e-9)
        w_valid = np.maximum(w_valid, psychrolib.MIN_HUM_RATIO)

        # ASHRAE/PsychroLib SI equations.
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

        # Wet-bulb temperature remains delegated to PsychroLib. This is the
        # slowest part of EPW loading, but using ndarray inputs and valid-row
        # iteration avoids the major overhead of row-wise pandas access.
        for out_i, tv, wv, pv_press in zip(idx, t_valid, w_valid, p_valid, strict=False):
            try:
                twb[out_i] = psychrolib.GetTWetBulbFromHumRatio(float(tv), float(wv), float(pv_press))
            except Exception:
                twb[out_i] = np.nan

    data["humidity_ratio_kg_kg"] = w
    data["humidity_ratio_g_kg"] = w * 1000.0
    data["moist_air_enthalpy_kj_kg"] = h
    data["wet_bulb_temperature_c"] = twb
    data["specific_volume_m3_kg"] = v
    data["moist_air_density_kg_m3"] = rho
    data["vapor_pressure_pa"] = vap
    data["saturation_vapor_pressure_pa"] = sat_vap
    data["degree_of_saturation"] = degree
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
