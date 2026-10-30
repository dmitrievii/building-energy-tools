"""Per-chart humidity convention. Context-local; never changes weather states.

Existing EPW/GeoSphere charts keep their ASHRAE default. Engine charts use the
same chart builders with their declared liquid-water guides, bins and mask.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps

import numpy as np
import psychrolib

_CURVE = ContextVar("climate_chart_water_curve", default=None)
_MIN_PRESSURE = ContextVar("climate_chart_minimum_source_pressure", default=None)


def source_humidity_chart(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        import pandas as pd
        df = kwargs.get("df")
        if df is None:
            df = next((arg for arg in args if isinstance(arg, pd.DataFrame)), None)
        if df is None:
            raise TypeError("A climate DataFrame is required")
        curve = df.attrs.get("ige_display_water_curve")
        token = _CURVE.set(curve if curve is not None else _CURVE.get())
        pressure = df.get("atmospheric_station_pressure_pa")
        minimum = float(pressure.min()) if curve is not None and pressure is not None and len(pressure) else _MIN_PRESSURE.get()
        pressure_token = _MIN_PRESSURE.set(minimum)
        try:
            return function(*args, **kwargs)
        finally:
            _MIN_PRESSURE.reset(pressure_token)
            _CURVE.reset(token)
    return wrapped


def current_water_curve():
    return _CURVE.get()


def mask_pressure(reference_pressure_pa):
    minimum = _MIN_PRESSURE.get()
    return min(reference_pressure_pa, minimum) if minimum is not None else reference_pressure_pa


def humidity_ratio(t_c, rh, pressure_pa):
    """Guide coordinates only; points retain their original hourly w and p."""
    curve = _CURVE.get()
    if curve is None:
        return psychrolib.GetHumRatioFromRelHum(float(t_c), float(rh), float(pressure_pa))
    from .engine.thermodynamics import EPSILON
    if curve == "PROVIDER_MAGNUS_WATER":
        sat = 610.94*np.exp(17.625*float(t_c)/(243.04+float(t_c)))
    else:
        from .engine.f1_base import water_es
        sat = float(water_es(np.array([t_c], dtype=float), curve)[0])
    e = float(rh)*sat
    if not 0 <= e < pressure_pa:
        raise ValueError("Chart guide vapour exceeds its reference pressure")
    return EPSILON*e/(pressure_pa-e)
