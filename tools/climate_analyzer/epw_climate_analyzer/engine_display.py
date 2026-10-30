"""Adapt engine years to the established analysis panels without re-importing EPW."""
from __future__ import annotations

import numpy as np

from .analysis_clock import add_calendar_columns
from .engine_analysis import prepare_engine_analysis_frame, T, P


def prepare_engine_display_frame(dataset, *, include_solar=False):
    data = add_calendar_columns(prepare_engine_analysis_frame(dataset))
    phase = dataset.data.attrs.get("ige_RH_phase", "")
    if phase == "PROVIDER_MAGNUS_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO":
        curve = "PROVIDER_MAGNUS_WATER"
    elif phase == "MURPHY_KOOP_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO":
        curve = "MURPHY_KOOP_WATER"
    else:
        curve = phase
    data.attrs["ige_display_water_curve"] = curve
    data.attrs["canonical_native_interval_minutes"] = 60
    data.attrs["canonical_analysis_interval_minutes"] = 60
    data.attrs["canonical_calendar_mode"] = dataset.temporal.calendar_mode
    data.attrs["canonical_frame_role"] = "hourly-analysis"
    data.attrs["canonical_interval_semantics"] = "interval_start"
    data["humidity_ratio_kg_kg"] = data["humidity_ratio_g_kg"]/1000
    from .engine.thermodynamics import EPSILON
    sat = data["saturation_vapor_pressure_pa"]
    ws = EPSILON*sat/(data[P]-sat)
    data["degree_of_saturation"] = data["humidity_ratio_kg_kg"]/ws
    # Missing optional fields remain missing. No ice-RH conversion or invented
    # wet bulb, illuminance, snow depth, visibility, opaque cloud, etc.
    from .epw_parser import EPW_COLUMNS
    for column in (*EPW_COLUMNS, "wet_bulb_temperature_c"):
        if column not in data:
            data[column] = np.nan
    from .decisions import add_degree_metrics
    data = add_degree_metrics(data)
    if include_solar:
        from .solar import add_solar_position_for_site
        data = add_solar_position_for_site(data, latitude=dataset.location.latitude,
            longitude=dataset.location.longitude, elevation_m=dataset.location.elevation_m)
    data.attrs["ige_display_source_values_modified"] = False
    return data
