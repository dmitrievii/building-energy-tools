"""Phase-aware analysis of engine states, without the legacy water/ice path.

This is a presentation adapter. It never repairs, re-dates, re-saturates or
re-exports weather. Historical rounded water-Magnus RH is authoritative for
derived vapour; future q and its conditional 2 m pressure are authoritative.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .climate_model import CanonicalClimateDataset
from .engine.thermodynamics import RD, RV, EPSILON, e_from_q, q_from_e, saturation_water_pa

UI_CONTRACT = "IGE_U1_SOURCE_PHASE_AND_PATTERN_CALENDAR_v1"
T, TD, RH, P = ("dry_bulb_temperature_c", "dew_point_temperature_c",
    "relative_humidity_pct", "atmospheric_station_pressure_pa")
Q = "specific_humidity_kg_kg"


def is_engine_dataset(dataset: CanonicalClimateDataset) -> bool:
    return dataset.data.attrs.get("ige_engine_ui_contract") == UI_CONTRACT


def prepare_engine_analysis_frame(dataset: CanonicalClimateDataset) -> pd.DataFrame:
    """Keep the original hourly clock and values, deriving only labelled fields.

    No ASHRAE ice-RH conversion, humidity floor, fallback pressure or wet-bulb
    inversion is performed. In particular, supersaturation relative to ice does
    not remove valid liquid-water states. Formulae for h/v/rho are engineering
    ideal-mixture estimates, not a qualification of source pressure accuracy.
    """
    if not is_engine_dataset(dataset):
        raise ValueError("IGE_U1_EXPLICIT_ENGINE_CONTRACT_REQUIRED")
    data = dataset.data.copy(deep=True)
    if dataset.temporal.native_interval_minutes != 60 or not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("IGE_U1_REQUIRES_NATIVE_HOURLY_CLOCK")
    if data.index.tz is None or data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("IGE_U1_INVALID_ENGINE_CLOCK")
    if len(data) < 2 or not np.all(np.diff(data.index.asi8) == 3_600_000_000_000):
        raise ValueError("IGE_U1_GAPPED_OR_REDATED_ENGINE_CLOCK")
    required = {T, TD, RH, P}
    if not required.issubset(data):
        raise ValueError("IGE_U1_REQUIRED_STATE_MISSING")
    t, td, rh, p = (data[k].to_numpy(dtype=float) for k in (T, TD, RH, P))
    if not np.isfinite(np.stack([t, td, rh, p])).all() or np.any((rh < 0) | (rh > 100) | (p <= 0)):
        raise ValueError("IGE_U1_INVALID_STATE_NO_FALLBACK_OR_CLIPPING")
    phase = data.attrs.get("ige_RH_phase")
    if dataset.temporal.calendar_mode == "climatology":
        if phase != "MURPHY_KOOP_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO" or Q not in data:
            raise ValueError("IGE_U1_FUTURE_Q_OR_WATER_PHASE_MISSING")
        q = data[Q].to_numpy(dtype=float)
        e = e_from_q(q, p)
        sat = saturation_water_pa(t)
        if (np.max(np.abs(100 * e / sat - rh)) > 1e-7
                or np.max(np.abs(saturation_water_pa(td) - e)) > 1e-5):
            raise ValueError("IGE_U1_FUTURE_STATE_CLOSURE_CHANGED")
        definition = "Murphy-Koop liquid water; vapour from original q and conditional p2m"
        pressure_scope = "conditional two-metre hydrostatic pressure from historical surface-pressure proxy"
    elif dataset.temporal.calendar_mode == "historical":
        if phase != "PROVIDER_MAGNUS_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO":
            raise ValueError("IGE_U1_HISTORICAL_WATER_PHASE_MISSING")
        sat = 610.94 * np.exp(17.625 * t / (243.04 + t))
        e = rh / 100 * sat
        q = q_from_e(e, p)
        definition = "provider liquid-water Magnus; vapour from original rounded T/RH, not rounded Td"
        pressure_scope = "model-surface pressure proxy used for display; not collocated with two-metre T/RH"
    else:
        raise ValueError("IGE_U1_ENGINE_CALENDAR_MODE_UNSUPPORTED")
    if np.any((e < 0) | (e >= p)):
        raise ValueError("IGE_U1_VAPOUR_EXCEEDS_TOTAL_PRESSURE")
    w = q / (1 - q)
    if "humidity_ratio_g_kg" in data and not np.allclose(data["humidity_ratio_g_kg"], 1000*w, rtol=1e-11, atol=1e-10):
        raise ValueError("IGE_U1_SOURCE_MIXING_RATIO_CHANGED")
    data["analysis_specific_humidity_kg_kg"] = q
    if "humidity_ratio_g_kg" not in data:
        data["humidity_ratio_g_kg"] = 1000*w
    data["vapor_pressure_pa"] = e
    data["saturation_vapor_pressure_pa"] = sat
    data["moist_air_enthalpy_kj_kg"] = 1.006*t + w*(2501.0 + 1.86*t)
    data["specific_volume_m3_kg"] = RD*(t + 273.15)*(1 + w/EPSILON)/p
    data["moist_air_density_kg_m3"] = (1 + w)/data["specific_volume_m3_kg"]
    data.attrs["ige_UI_humidity_phase_adapter_required"] = False
    data.attrs["ige_ui_analysis"] = {
        "contract": UI_CONTRACT, "humidity_definition": definition,
        "pressure_scope": pressure_scope, "gas_constants_J_kg_K": {"dry_air": RD, "vapour": RV},
        "historical_q_is_display_estimate_not_source_observation": dataset.temporal.calendar_mode == "historical",
        "source_T_Td_RH_p_and_q_modified": False, "calendar_or_time_support_modified": False,
        "ice_supersaturation_clipped": False, "wet_bulb_or_frost_point_inferred": False,
        "legacy_ASHRAE_psychrometric_chart_used": False,
        "independent_station_accuracy_qualified": False,
    }
    return data


def monthly_engine_summary(data: pd.DataFrame) -> pd.DataFrame:
    """State-sample statistics and conserved sums; never mean an energy field."""
    rows = []
    for month, group in data.groupby(data.index.month):
        rows.append({"Month": int(month), "Hours": len(group),
            "T sample mean [°C]": float(group[T].mean()),
            "T sample min [°C]": float(group[T].min()), "T sample max [°C]": float(group[T].max()),
            "RH water mean [%]": float(group[RH].mean()),
            "Humidity ratio mean [g/kg dry air]": float(group["humidity_ratio_g_kg"].mean()),
            "GHI [kWh/m²]": float(group["global_horizontal_radiation_wh_m2"].sum()/1000),
            "Liquid rain [mm]": float(group["liquid_precipitation_depth_mm"].sum()),
            "Total precipitation [mm]": float(group["total_precipitation_depth_mm"].sum())})
    return pd.DataFrame(rows).set_index("Month")
