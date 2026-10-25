"""Generic full-year EPW serialization with explicit interval endpoint mapping.

No location/year/CET constants, no DST, no leap-day deletion, no zero fill.
This is format and bounded physical screening, not an EnergyPlus simulation or
an independent climate-accuracy certificate.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import math
from pathlib import Path

import numpy as np

from .contracts import ClimateResult


# Canonical field: (EPW column, unit, time operator). All are required here.
EPW_FIELDS = {
    "dry_bulb_temperature_c": (6, "°C", "instant_at_interval_end"),
    "dew_point_temperature_c": (7, "°C", "instant_at_interval_end"),
    "relative_humidity_pct": (8, "%", "instant_at_interval_end"),
    "atmospheric_station_pressure_pa": (9, "Pa", "instant_at_interval_end"),
    "horizontal_infrared_radiation_intensity_wh_m2": (12, "Wh/m²", "interval_energy"),
    "global_horizontal_radiation_wh_m2": (13, "Wh/m²", "interval_energy"),
    "direct_normal_radiation_wh_m2": (14, "Wh/m²", "interval_energy"),
    "diffuse_horizontal_radiation_wh_m2": (15, "Wh/m²", "interval_energy"),
    "wind_direction_deg": (20, "deg", "instant_at_interval_end"),
    "wind_speed_m_s": (21, "m/s", "instant_at_interval_end"),
    "total_sky_cover_tenths": (22, "tenths", "instant_at_interval_end"),
    "liquid_precipitation_depth_mm": (33, "mm", "interval_amount"),
}


def validate_weather(result: ClimateResult) -> dict:
    """Fail closed on missing fields/domain violations; retain provider rounding."""
    result.validate_contract()
    for name, (_, unit, operator) in EPW_FIELDS.items():
        definition = result.fields.get(name)
        if definition is None or definition.unit != unit or definition.operator != operator:
            raise ValueError(f"IGE_EPW_FIELD_UNIT_OR_OPERATOR_MISMATCH_{name}")
    f = result.data
    bounds = {
        "dry_bulb_temperature_c": (-70, 70), "dew_point_temperature_c": (-70, 70),
        "relative_humidity_pct": (0, 100), "atmospheric_station_pressure_pa": (31000, 120000),
        "horizontal_infrared_radiation_intensity_wh_m2": (0, 1000),
        "global_horizontal_radiation_wh_m2": (0, 2000),
        "direct_normal_radiation_wh_m2": (0, 2000),
        "diffuse_horizontal_radiation_wh_m2": (0, 2000),
        "wind_direction_deg": (0, 360), "wind_speed_m_s": (0, 90),
        "total_sky_cover_tenths": (0, 10), "liquid_precipitation_depth_mm": (0, 998),
    }
    for name, (lo, hi) in bounds.items():
        v = f[name].to_numpy(dtype=float)
        if not np.isfinite(v).all() or np.any((v < lo) | (v > hi)):
            raise ValueError(f"IGE_EPW_PHYSICAL_OR_FORMAT_DOMAIN_{name}")
    t = f["dry_bulb_temperature_c"].to_numpy()
    td = f["dew_point_temperature_c"].to_numpy()
    if np.any(td > t + 0.100001):
        raise ValueError("IGE_EPW_DEWPOINT_ABOVE_T_BEYOND_SOURCE_ROUNDING")
    ghi = f["global_horizontal_radiation_wh_m2"].to_numpy()
    dhi = f["diffuse_horizontal_radiation_wh_m2"].to_numpy()
    dni = f["direct_normal_radiation_wh_m2"].to_numpy()
    if np.any(dhi > ghi + 0.100001):
        raise ValueError("IGE_EPW_DHI_EXCEEDS_GHI")
    component_residual = None
    if "direct_horizontal_radiation_wh_m2" in f:
        direct = f["direct_horizontal_radiation_wh_m2"].to_numpy()
        component_residual = float(np.max(np.abs(ghi - direct - dhi)))
        if np.any(direct < 0) or component_residual > 0.200001 or np.any(direct > dni + 0.200001):
            raise ValueError("IGE_EPW_SOLAR_HORIZONTAL_COMPONENTS_INCONSISTENT")
    # Provider uses Magnus liquid-water RH, rounded to integer percent; T/Td
    # are independently rounded to 0.1 °C. This is a diagnostic, not a repair.
    rh_from_td = 100 * np.exp(17.625 * td / (243.04 + td) - 17.625 * t / (243.04 + t))
    rh = f["relative_humidity_pct"].to_numpy()
    residual = rh_from_td - rh
    quantization_failures = None
    if "liquid-water Magnus" in result.fields["relative_humidity_pct"].definition:
        # Propagate the declared 0.1 °C / 1 pp output quantization through the
        # monotonic Magnus relation. No fitted residual threshold is used.
        phi = lambda x: 17.625 * x / (243.04 + x)
        lower = 100 * np.exp(phi(td - .050001) - phi(t + .050001))
        upper = 100 * np.exp(phi(td + .050001) - phi(t - .050001))
        incompatible = (lower > np.minimum(rh + .500001, 100)) | (upper < np.maximum(rh - .500001, 0))
        quantization_failures = int(incompatible.sum())
        if quantization_failures:
            raise ValueError("IGE_EPW_SOURCE_T_TD_RH_QUANTIZATION_INTERVALS_INCOMPATIBLE")
    if "total_precipitation_depth_mm" in f:
        total = f["total_precipitation_depth_mm"].to_numpy()
        if np.any(total < 0):
            raise ValueError("IGE_NEGATIVE_TOTAL_PRECIPITATION")
        if np.any(total + 0.100001 < f["liquid_precipitation_depth_mm"].to_numpy()):
            raise ValueError("IGE_EPW_LIQUID_EXCEEDS_TOTAL_PRECIPITATION")
    exact_closure = False
    if result.future_request is not None:
        from .thermodynamics import e_from_q, saturation_water_pa, pressure_at_2m
        q = f["specific_humidity_kg_kg"].to_numpy()
        p = f["atmospheric_station_pressure_pa"].to_numpy()
        surface = f["surface_pressure_proxy_pa"].to_numpy()
        e = e_from_q(q, p)
        rh_error = float(np.max(np.abs(100*e/saturation_water_pa(t)-rh)))
        td_error = float(np.max(np.abs(saturation_water_pa(td)-e)))
        p_error = float(np.max(np.abs(pressure_at_2m(t, q, surface)-p)))
        if rh_error > 1e-7 or td_error > 1e-5 or p_error > 1e-7:
            raise ValueError("BM1_FUTURE_STATE_THERMODYNAMIC_OR_PRESSURE_CLOSURE_FAILED")
        exact_closure = True
    return {
        "screen": "BOUNDS_COMPONENTS_AND_PROVIDER_ROUNDING_PASS",
        "records": len(f), "hard_failure_count": 0,
        "max_GHI_minus_direct_horizontal_minus_DHI_Wh_m2": component_residual,
        "max_abs_provider_Magnus_RH_residual_pp": float(np.max(np.abs(residual))),
        "provider_T_Td_RH_quantization_interval_failures": quantization_failures,
        "T_Td_RH_exact_thermodynamic_closure_claimed": exact_closure,
        "provider_values_modified": result.future_request is not None,
        "mixed_source_longwave_cross_field_accuracy_qualified": False,
    }


def serialize_epw(result: ClimateResult) -> tuple[bytes, dict]:
    diagnostics = validate_weather(result)
    request, location = result.request, result.location
    if location.elevation_m is None or not math.isfinite(location.elevation_m):
        raise ValueError("IGE_EPW_EXPLICIT_ELEVATION_OR_LABELLED_PROXY_REQUIRED")
    if not -1000 <= location.elevation_m < 9999.9:
        raise ValueError("IGE_EPW_ELEVATION_OUT_OF_FORMAT_RANGE")
    headers = [
        ["LOCATION", request.label + " GRID BACKGROUND RESEARCH", "", "", "IGE_ERA5_DERIVED_POWER_LW", "999999",
            location.latitude, location.longitude, request.utc_offset_minutes / 60, location.elevation_m],
        ["DESIGN CONDITIONS", 0], ["TYPICAL/EXTREME PERIODS", 0], ["GROUND TEMPERATURES", 0],
        ["HOLIDAYS/DAYLIGHT SAVINGS", "Yes" if calendar.isleap(request.year) else "No", 0, 0, 0],
        ["COMMENTS 1", "Historical grid background; NO local height correction; elevation is unverified provider proxy. See manifest.json."],
        ["COMMENTS 2", "Fixed standard time; states at hour end; preceding-hour radiation and rain. POWER LW start labels aligned explicitly. Missing opaque cloud and photometry. NOT independently qualified."],
        ["DATA PERIODS", 1, 1, f"HISTORICAL {request.year} RESEARCH GRID BACKGROUND",
            calendar.day_name[request.local_starts[0].weekday()], "1/1", "12/31"],
    ]
    if result.future_request is not None:
        future = result.future_request
        headers[0][1] = request.label + " REPRESENTATIVE FUTURE RESEARCH"
        headers[0][4] = "IGE_BM1_" + future.model + "_" + future.scenario
        headers[5] = ["COMMENTS 1", f"Representative {future.model} {future.scenario} {future.future_window[0]}-{future.future_window[1]}; pattern {request.year}; local reference {future.historical_window[0]}-{future.historical_window[1]}. NOT actual future event dates or TMY."]
        headers[6] = ["COMMENTS 2", "MK water RH/Td; conditional surface pressure proxy with 2m hydrostatic adapter. Direction/cloud/precipitation phase chronology inherited. Height proxy unverified; no station accuracy or production qualification. See manifest.json."]
        headers[7][3] = f"REPRESENTATIVE FUTURE {future.future_window[0]}-{future.future_window[1]} PATTERN {request.year}"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(headers)
    for local, values in zip(request.local_starts, result.data.to_dict("records")):
        row = [local.year, local.month, local.day, local.hour + 1, 60, "?9" * 22,
            99.9, 99.9, 999, 999999, 9999, 9999, 9999, 9999, 9999, 9999,
            999999, 999999, 999999, 9999, 999, 999, 99, 99, 9999, 99999,
            9, "999999999", 999, 0.999, 999, 99, 999, 999, 99]
        for name, (column, _, _) in EPW_FIELDS.items():
            value = values[name]
            # Sky cover is conventionally encoded in whole tenths. The
            # quantization is recorded in the export ledger, not hidden.
            if column == 22:
                row[column] = int(round(value))
            elif result.future_request is not None and column in (6, 7, 8):
                # A fixed decimal grid removes CPU/libm differences in the
                # last significant digits, especially for Td close to zero.
                # Internal states/objective/targets and physical tolerances
                # are unchanged. Historical I1/A0 bytes remain unchanged.
                row[column] = format(float(value), ".7f")
            else:
                row[column] = format(float(value), ".10g")
        row[34] = 1  # measurement period is one hour, including zero-depth hours
        assert len(row) == 35
        writer.writerow(row)
    payload = stream.getvalue().encode("utf-8")
    diagnostics.update(validate_epw_bytes(payload, result))
    diagnostics["numeric_serialization"] = {"default": "10 significant decimal digits",
        "future_T_Td_RH_only": "7 fixed decimal places" if result.future_request is not None else None,
        "max_future_T_Td_RH_rounding_C_or_pp": 5e-8 if result.future_request is not None else None,
        "internal_state_objective_or_physics_changed": False}
    return payload, diagnostics


def validate_epw_bytes(payload: bytes, result: ClimateResult) -> dict:
    """Independent CSV readback including all dates/fields and numeric values."""
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
    records = rows[8:]
    if len(rows[:8]) != 8 or len(records) != len(result.request.utc_starts) or any(len(r) != 35 for r in records):
        raise ValueError("IGE_EPW_READBACK_INCOMPLETE_YEAR_OR_WIDTH")
    expected_header = ["LOCATION", "DESIGN CONDITIONS", "TYPICAL/EXTREME PERIODS", "GROUND TEMPERATURES",
        "HOLIDAYS/DAYLIGHT SAVINGS", "COMMENTS 1", "COMMENTS 2", "DATA PERIODS"]
    if [r[0] for r in rows[:8]] != expected_header:
        raise ValueError("IGE_EPW_READBACK_HEADER_ORDER")
    expected_location = [result.location.latitude, result.location.longitude,
        result.request.utc_offset_minutes / 60, result.location.elevation_m]
    if [float(v) for v in rows[0][6:10]] != expected_location:
        raise ValueError("IGE_EPW_READBACK_LOCATION_OR_STANDARD_OFFSET")
    if (rows[4][1] == "Yes") != calendar.isleap(result.request.year):
        raise ValueError("IGE_EPW_READBACK_LEAP_HEADER")
    for i, (row, local) in enumerate(zip(records, result.request.local_starts)):
        if list(map(int, row[:5])) != [local.year, local.month, local.day, local.hour + 1, 60]:
            raise ValueError("IGE_EPW_READBACK_SHIFTED_DUPLICATED_OR_DST_DATE")
        for name, (column, _, _) in EPW_FIELDS.items():
            expected = float(result.data[name].iloc[i])
            actual = float(row[column])
            tol = 0.500001 if column == 22 else max(1e-7, 1e-9 * abs(expected))
            if not math.isfinite(actual) or abs(actual - expected) > tol:
                raise ValueError("IGE_EPW_READBACK_VALUE_CHANGED_" + name)
        if row[34] != "1" or row[23] != "99" or row[16:20] != ["999999", "999999", "999999", "9999"]:
            raise ValueError("IGE_EPW_READBACK_MISSING_FIELD_OR_PRECIPITATION_PERIOD")
    return {"epw_format_readback": "PASS", "fields_per_record": 35, "headers": 8,
        "first_row": records[0][:5], "last_row": records[-1][:5],
        "leap_day_retained": calendar.isleap(result.request.year),
        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        "EnergyPlus_simulation_executed": False}


def write_exclusive(path: Path, payload: bytes) -> None:
    with Path(path).open("xb") as stream:
        stream.write(payload)
