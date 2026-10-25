"""B-M1: reference-normalized monthly future weather with a real hourly pattern.

Not a forecast for specific future dates, not a selected TMY, not the daily
joint C2 generator. The common reference period is independent of the chosen
pattern year, preventing a second application of historical warming.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, replace
import gzip
import io
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import pandas as pd

from .contracts import ClimateResult, FutureRequest, HistoricalRequest, FieldDefinition, QualityStatus, specific_humidity_to_mixing_ratio_g_kg
from .epw import serialize_epw, validate_weather, write_exclusive
from .historical import assemble_historical, read_source_bundle, digest, json_bytes
from .model_sources import (NEX_PACKET_SHA, REFERENCE_PACKET_SHA, SEMANTICS_VERSION, admit_nex,
    monthly_nex_signals, read_pinned, bounded_zip, sha)
from .thermodynamics import (baseline_vapour_state, saturation_water_pa, saturation_nasa_phase_pa,
    q_saturation_at_2m, pressure_at_2m, e_from_q, q_from_e, dew_point_water_c, project_monthly_q)

PATTERN_SOURCE_SHA = "2575be295bc41be68ac56940524a76c5ef9f9b5010a83f20b6eec21c49dce273"
SCHEMA = "IGE_B_M1_MONTHLY_FUTURE_v1"
T, TD, RH, P = "dry_bulb_temperature_c", "dew_point_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa"
Q = "specific_humidity_kg_kg"
GHI, LW, WS, PR = "global_horizontal_radiation_wh_m2", "horizontal_infrared_radiation_intensity_wh_m2", "wind_speed_m_s", "total_precipitation_depth_mm"


def reference_climatology(packet: Path, pattern: ClimateResult, protocol_sha256: str) -> tuple[dict, dict]:
    bodies = bounded_zip(read_pinned(packet, REFERENCE_PACKET_SHA))
    manifest = json.loads(bodies["manifest.json"])
    if (manifest.get("reference_window") != [2002, 2014] or manifest.get("protocol_sha256") != protocol_sha256
            or sha(bodies["registered_protocol.json"]) != protocol_sha256):
        raise ValueError("BM1_REFERENCE_PROTOCOL_OR_WINDOW_CHANGED")
    names = {f"Graz_{year}_original_sources.zip" for year in range(2002, 2015)}
    if set(bodies) != names | {"manifest.json", "registered_protocol.json"} or set(manifest["members"]) != names:
        raise ValueError("BM1_REFERENCE_YEAR_CENSUS_CHANGED")
    climates, daily, details = [], [], []
    for year in range(2002, 2015):
        name = f"Graz_{year}_original_sources.zip"
        entry, data = manifest["members"][name], bodies[name]
        if entry["year"] != year or entry["sha256"] != sha(data) or entry["bytes"] != len(data):
            raise ValueError("BM1_REFERENCE_ORIGINAL_BYTES_CHANGED")
        request = replace(pattern.request, year=year)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "source.zip"; path.write_bytes(data)
            raw, receipts = read_source_bundle(path, entry["sha256"], request)
            reference = assemble_historical(request, raw, receipts)
        if reference.location != pattern.location:
            raise ValueError("BM1_REFERENCE_SELECTED_CELL_OR_HEIGHT_CHANGED")
        f = reference.data.copy()
        q, p2, _ = baseline_vapour_state(f[T], f[TD], f[P])
        f[Q] = q
        f["NASA_phase_RH_pct"] = 100*e_from_q(q, p2)/saturation_nasa_phase_pa(f[T])
        # With fixed UTC+1, each 24-row block contains UTC state nodes 00..23.
        # Flux intervals are one hour earlier: monthly transfer of seasonal
        # deltas to the local-standard clock is explicitly approximate.
        times = request.local_starts
        mask = ~((times.month == 2) & (times.day == 29))
        f["month"] = times.month
        climates.append(f.iloc[np.flatnonzero(mask)])
        values = f[T].to_numpy().reshape(-1, 24)
        days = times[::24]
        day_mask = ~((days.month == 2) & (days.day == 29))
        daily.append(pd.DataFrame({"month": days.month[day_mask],
            "c": ((values.min(axis=1)+values.max(axis=1))/2)[day_mask],
            "dtr": (values.max(axis=1)-values.min(axis=1))[day_mask]}))
        details.append({"year": year, "source_sha256": entry["sha256"], "original_hours": len(f),
            "noleap_estimator_hours": int(mask.sum()), "original_data_not_deleted": True})
    full, days = pd.concat(climates), pd.concat(daily)
    means = {}
    for m in range(1, 13):
        hourly, d = full[full.month == m], days[days.month == m]
        means[m] = {"midrange_c": float(d.c.mean()), "dtr_K": float(d.dtr.mean()),
            **{key: float(hourly[key].mean()) for key in (T, Q, GHI, LW, WS, PR, "NASA_phase_RH_pct")}}
    return means, {"reference_source_packet_sha256": REFERENCE_PACKET_SHA, "reference_years": details,
        "noleap_estimator_total_hours": len(full), "full_original_hours": sum(r["original_hours"] for r in details),
        "source_acquisition_HTTP_attempts": manifest["total_HTTP_attempts"],
        "source_acquisition_received_bytes": manifest["total_received_bytes"],
        "reference_window": [2002, 2014], "thirteen_year_reference_sampling_uncertainty_qualified": False,
        "raw_monthly_signal_clock": "NASA daily UTC climatology",
        "local_flux_clock_transfer": "MONTHLY_SEASONAL_RATIO_TRANSFER_TO_FIXED_LOCAL_STANDARD_HOURS; NOT_EXACT_NATIVE_UTC_DAILY_EQUALITIES"}


def temperature_morph(t: np.ndarray, month_by_day: np.ndarray, reference: dict, signals: dict) -> tuple[np.ndarray, list]:
    t = np.asarray(t, dtype=float)
    if t.ndim != 1 or len(t) != 8760 or month_by_day.shape != (365,):
        raise ValueError("BM1_TEMPERATURE_REQUIRES_COMPLETE_NONLEAP_PATTERN")
    days = t.reshape(365, 24)
    centers = (days.min(axis=1)+days.max(axis=1))/2
    ranges = days.max(axis=1)-days.min(axis=1)
    output, diagnostics = np.empty_like(days), []
    for m in range(1, 13):
        ix = np.flatnonzero(month_by_day == m)
        c, dtr, sig, ref = centers[ix], ranges[ix], signals[m], reference[m]
        if not len(ix) or dtr.mean() <= 0:
            raise ValueError("BM1_DEGENERATE_PATTERN_MONTH_REQUIRES_OTHER_METHOD")
        # Midrank ECDF treats ties symmetrically. Quantile deltas are centered
        # independently of their mean, preserving the declared monthly signal.
        sorted_c = np.sort(c)
        rank = ((np.searchsorted(sorted_c, c, side="left")+np.searchsorted(sorted_c, c, side="right")-1)
            / (2*(len(c)-1))) if len(c) > 1 else np.full(c.shape, .5)
        raw_delta = np.quantile(sig["future_midrange_sorted_c"], rank)-np.quantile(sig["historical_midrange_sorted_c"], rank)
        rank_delta = raw_delta - raw_delta.mean() + sig["midrange_delta_K"]
        rebase = ref["midrange_c"] - float(c.mean())
        beta = ref["dtr_K"] / float(dtr.mean()) * sig["dtr_ratio"]
        output[ix] = c[:, None] + rebase + rank_delta[:, None] + beta*(days[ix]-c[:, None])
        new = output[ix]
        diagnostics.append({"month": m, "pattern_mean_midrange_c": float(c.mean()),
            "reference_mean_midrange_c": ref["midrange_c"], "pattern_to_reference_rebase_K": rebase,
            "NEX_midrange_delta_K": sig["midrange_delta_K"], "DTR_combined_scale": beta,
            "NEX_DTR_ratio": sig["dtr_ratio"], "target_midrange_c": ref["midrange_c"]+sig["midrange_delta_K"],
            "target_DTR_K": ref["dtr_K"]*sig["dtr_ratio"],
            "actual_midrange_c": float(((new.min(axis=1)+new.max(axis=1))/2).mean()),
            "actual_DTR_K": float((new.max(axis=1)-new.min(axis=1)).mean()),
            "hourly_time_mean_T_c_DIAGNOSTIC_NOT_NEX_tas": float(new.mean())})
    return output.reshape(-1), diagnostics


def morph_future(pattern: ClimateResult, future: FutureRequest, reference: dict, signals: dict,
                 reference_evidence: dict, nex_evidence: dict) -> ClimateResult:
    if (pattern.request.year != future.representative_pattern_year or calendar.isleap(pattern.request.year)
            or pattern.request.utc_offset_minutes != 60):
        raise ValueError("BM1_FIRST_PILOT_REQUIRES_NONLEAP_UTC_PLUS_1_PATTERN")
    _, base_epw = serialize_epw(pattern)
    if base_epw["sha256"] != future.historical_base_sha256:
        raise ValueError("BM1_HISTORICAL_BASE_EPW_HASH_MISMATCH")
    if abs(pattern.location.latitude-46.875) > .4 or abs(pattern.location.longitude-15.375) > .4:
        raise ValueError("BM1_NEX_CELL_OUTSIDE_DECLARED_PILOT_REPRESENTATIVENESS_LIMIT")
    frame = pattern.data.copy()
    months = pattern.request.local_starts.month.to_numpy()
    t0, td0, surface = (frame[c].to_numpy().copy() for c in (T, TD, P))
    q0, p0, rh0 = baseline_vapour_state(t0, td0, surface)
    new_t, temp_report = temperature_morph(t0, months[::24], reference, signals)
    frame[T] = new_t
    frame["surface_pressure_proxy_pa"] = surface
    fields = dict(pattern.fields)
    fields["surface_pressure_proxy_pa"] = replace(fields[P], definition="Unchanged 2023 absolute model-surface pressure proxy; no future GCM ps signal")
    sources = (*pattern.sources,
        {"id": "reference_climatology", "sha256": REFERENCE_PACKET_SHA, "dataset": "ERA5-derived and POWER 2002-2014 same source chain"},
        {"id": "nex_gcm", "sha256": NEX_PACKET_SHA, "dataset": "CanESM5 r1i1p1f1 v2.0 selected frozen daily windows"},
        {"id": "bm1_morph", "dataset": SCHEMA, "parents": ["open_meteo", "nasa_power", "reference_climatology", "nex_gcm"]})
    transformations = list(pattern.transformations)
    month_report, adjustments = [], []
    q_out, q_target = np.empty(len(frame)), np.empty(len(frame))
    # Only the box upper bound needs an implicit saturation/pressure solve.
    upper = q_saturation_at_2m(new_t, surface)
    scaled_fields = {GHI: "rsds", LW: "rlds", WS: "sfcWind", PR: "pr"}
    for m in range(1, 13):
        ix = np.flatnonzero(months == m)
        sig, ref = signals[m], reference[m]
        target_mean = ref[Q]*sig["huss_ratio"]
        prior_mean = float(q0[ix].mean())
        if prior_mean <= 0:
            raise ValueError("BM1_ZERO_PATTERN_Q_REQUIRES_SEPARATE_ADMISSION")
        q_target[ix] = q0[ix]*target_mean/prior_mean
        try:
            q_out[ix], lam = project_monthly_q(q_target[ix], upper[ix])
        except ValueError as exc:
            raise ValueError(f"BM1_MONTH_{m}_Q_REJECTED target_mean={target_mean:.12g} capacity_mean={float(upper[ix].mean()):.12g}; {exc}") from exc
        row = {"month": m, "hours": len(ix), "reference_mean_q_kgkg": ref[Q],
            "NEX_huss_ratio": sig["huss_ratio"], "target_mean_q_kgkg": target_mean,
            "actual_mean_q_kgkg": float(q_out[ix].mean()), "q_projection_lambda_kgkg": lam,
            "raw_q_exceeds_saturation_hours": int((q_target[ix] > upper[ix]+1e-12).sum()),
            "q_projection_objective_half_sum_squared": float(.5*np.sum((q_out[ix]-q_target[ix])**2)),
            "max_abs_hourly_q_adjustment_kgkg": float(np.max(np.abs(q_out[ix]-q_target[ix]))),
            "NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED": sig["NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED"]}
        for name, model in scaled_fields.items():
            desired = ref[name]*sig[model+"_ratio"]
            original_mean = float(pattern.data[name].iloc[ix].mean())
            if original_mean <= 0 and desired > 0:
                raise ValueError("BM1_ZERO_PATTERN_AMOUNT_REQUIRES_OTHER_GENERATOR_" + name)
            factor = desired/original_mean if original_mean > 0 else 0.
            columns = (GHI, "direct_normal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2", "direct_horizontal_radiation_wh_m2") if name == GHI else (
                PR, "liquid_precipitation_depth_mm") if name == PR else (name,)
            for column in columns:
                frame.iloc[ix, frame.columns.get_loc(column)] = pattern.data[column].iloc[ix].to_numpy()*factor
            row[name] = {"reference_mean": ref[name], "NEX_ratio": sig[model+"_ratio"],
                "pattern_to_reference_factor": ref[name]/original_mean if original_mean else 0,
                "combined_factor": factor, "target_mean": desired, "actual_mean": float(frame[name].iloc[ix].mean())}
        month_report.append(row)
    p_out = pressure_at_2m(new_t, q_out, surface)
    e = e_from_q(q_out, p_out)
    rh = 100*(e/saturation_water_pa(new_t))
    if np.any(rh > 100+1e-8):
        raise ValueError("BM1_PROJECTED_WATER_RH_OUTSIDE_ENVELOPE")
    frame[P], frame[Q] = p_out, q_out
    frame[TD], frame[RH] = dew_point_water_c(e), rh
    frame["relative_humidity_NASA_phase_pct"] = 100*e/saturation_nasa_phase_pa(new_t)
    frame["humidity_ratio_g_kg"] = specific_humidity_to_mixing_ratio_g_kg(q_out)
    for name in (T, TD, RH, P, GHI, LW, WS, PR, "liquid_precipitation_depth_mm", "direct_normal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2", "direct_horizontal_radiation_wh_m2"):
        fields[name] = replace(fields[name], source_id="bm1_morph", definition="B-M1 reference-normalized monthly morph; " + name)
    fields[RH] = replace(fields[RH], definition="Murphy-Koop liquid-water RH from the hourly common T-p2m-q state; never the NASA water/ice hurs target")
    fields[TD] = replace(fields[TD], definition="Murphy-Koop water dew point from the same vapour pressure as q and water RH")
    fields[P] = replace(fields[P], vertical_reference="2m above model surface", definition="Conditional isothermal uniform-q hydrostatic 0-to-2m adapter; 2023 surface pressure proxy retained")
    for name, unit, definition in ((Q, "kg/kg moist air", "Specific humidity, water mass / moist-air mass; monthly time average target"),
            ("relative_humidity_NASA_phase_pct", "%", "Water RH at T>=0 C; ice RH below 0 C; diagnostic, hurs not forced"),
            ("humidity_ratio_g_kg", "g/kg dry air", "1000*q/(1-q), not specific humidity")):
        fields[name] = FieldDefinition(unit, "instant_at_interval_end", "bm1_morph", "2m above model surface", definition)
    # Every source-to-state and target-to-feasible adjustment is explicit.
    for i, stamp in enumerate(frame.index):
        adjustments.append({"UTC_interval_start": stamp.isoformat(), "base_RH_provider_pct": float(pattern.data[RH].iloc[i]),
            "base_RH_MK_water_pct": float(rh0[i]), "base_surface_p_Pa": float(surface[i]), "base_p2m_Pa": float(p0[i]),
            "future_p2m_Pa": float(p_out[i]), "target_q_kgkg": float(q_target[i]), "projected_q_kgkg": float(q_out[i]),
            "q_adjustment_kgkg": float(q_out[i]-q_target[i]), "T_change_from_pattern_K": float(new_t[i]-t0[i])})
    transformations.append({"operation": "B_M1_REFERENCE_NORMALIZATION_AND_NEX_SIGNAL", "temperature_months": temp_report,
        "monthly_projection_and_amounts": month_report, "full_hourly_adjustment_ledger_records": len(adjustments),
        "reference_window": [2002, 2014], "pattern_year": pattern.request.year,
        "hourly_T_time_mean_NOT_equal_to_NEX_tas_delta": True, "NASA_hurs_signal_enforced": False})
    for row in month_report:
        m = row["month"]; ix = np.flatnonzero(months == m)
        row["future_mean_NASA_phase_RH_pct_DIAGNOSTIC"] = float(frame["relative_humidity_NASA_phase_pct"].iloc[ix].mean())
        row["reference_mean_NASA_phase_RH_pct_DIAGNOSTIC"] = reference[m]["NASA_phase_RH_pct"]
        row["actual_NASA_phase_RH_delta_pp_DIAGNOSTIC"] = row["future_mean_NASA_phase_RH_pct_DIAGNOSTIC"]-row["reference_mean_NASA_phase_RH_pct_DIAGNOSTIC"]
        row["unforced_NASA_hurs_delta_residual_pp"] = (
            row["actual_NASA_phase_RH_delta_pp_DIAGNOSTIC"]-row["NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED"])
        row["saturated_water_RH_hours"] = int((np.abs(rh[ix]-100) < 1e-6).sum())
    diagnostics = {"reference": reference_evidence, "NEX": nex_evidence, "temperature_months": temp_report,
        "monthly_signals_and_constraints": month_report, "hourly_NASA_daily_constraints_enforced": False,
        "hurs_signal_enforced": False, "GCM_tas_operator": "MIDRANGE_NOT_TIME_MEAN",
        "pressure_assumption": "2023_SURFACE_PROXY_FIXED; ISOTHERMAL_UNIFORM_Q_TWO_METRE_LAYER",
        "pressure_accuracy_independently_qualified": False, "B4_qualified": False, "P2_advantage_qualified": False,
        "pattern_is_actual_future_date_forecast": False, "is_selected_TMY": False,
        "wind_direction_inherited": True, "precipitation_event_hours_and_liquid_fraction_inherited": True,
        "future_cloud_signal_available": False, "independent_DNI_DHI_future_signals_available": False,
        "max_adjacent_RH_jump_pp_DIAGNOSTIC": float(np.max(np.abs(np.diff(rh)))),
        "state_operator": "24_UNIFORM_UTC_STATE_NODES_APPROXIMATION; ENDPOINTS_FROM_SOURCE",
        "saturation_bound_numerics": "DIRECTED_ROUNDING_TO_FEASIBLE_FLOAT; NO_RH_CLIP_OR_CHANGE_TO_Q_TARGET",
        "flux_operator": "LOCAL_STANDARD_MONTHLY_SEASONAL_TRANSFER; NATIVE_NEX_DAILY_BOUNDS_NOT_VERIFIED",
        "IV1_station_observations_opened": False, "mixed_source_cross_variable_accuracy_qualified": False}
    result = ClimateResult(pattern.request, frame, pattern.location, fields, sources, tuple(transformations), tuple(adjustments),
        QualityStatus("SOURCE_AND_SIGNAL_CHECKS_PENDING", "CONDITIONAL_STATE_CLOSURE_PENDING",
            "NOT_INDEPENDENTLY_VALIDATED", "RESEARCH_REPRESENTATIVE_FUTURE_CLI; UI_NOT_CONNECTED"), diagnostics, future)
    validate_weather(result)
    return result


def verify_signals(result: ClimateResult, epw_payload: bytes) -> dict:
    """Recompute the monthly estimands from the serialized EPW itself."""
    import csv
    rows = list(csv.reader(io.StringIO(epw_payload.decode())))[8:]
    array = np.asarray([[float(r[i]) for i in (6, 8, 9, 12, 13, 21, 33, 7)] for r in rows])
    months = result.request.local_starts.month.to_numpy()
    recovered_q = q_from_e(array[:, 1]/100*saturation_water_pa(array[:, 0]), array[:, 2])
    expected_p = pressure_at_2m(array[:, 0], recovered_q, result.data["surface_pressure_proxy_pa"].to_numpy())
    pressure_error = float(np.max(np.abs(expected_p-array[:, 2])))
    vapour_error = float(np.max(np.abs(saturation_water_pa(array[:, 7])-
        array[:, 1]/100*saturation_water_pa(array[:, 0]))))
    # Ten significant decimal digits in EPW impose a finite readback error.
    # These absolute Pa tolerances are numerical, not pressure-skill metrics.
    if pressure_error > 1e-4 or vapour_error > 1e-4:
        raise ValueError("BM1_EXPORTED_PRESSURE_OR_VAPOUR_CLOSURE_LOST")
    targets = {r["month"]: r for r in result.diagnostics["temperature_months"]}
    constraints = {r["month"]: r for r in result.diagnostics["monthly_signals_and_constraints"]}
    reports = []
    for m in range(1, 13):
        ix = np.flatnonzero(months == m); t = array[ix, 0].reshape(-1, 24)
        c, dtr = float(((t.min(axis=1)+t.max(axis=1))/2).mean()), float((t.max(axis=1)-t.min(axis=1)).mean())
        row = {"month": m, "midrange_error_K": c-targets[m]["target_midrange_c"],
            "DTR_error_K": dtr-targets[m]["target_DTR_K"],
            "q_mean_error_kgkg": float(recovered_q[ix].mean())-constraints[m]["target_mean_q_kgkg"]}
        if max(abs(row["midrange_error_K"]), abs(row["DTR_error_K"])) > 1e-6 or abs(row["q_mean_error_kgkg"]) > 1e-9:
            raise ValueError("BM1_EXPORTED_TEMPERATURE_OR_HUMIDITY_SIGNAL_LOST")
        for name, column in ((LW, 3), (GHI, 4), (WS, 5)):
            target = constraints[m][name]["target_mean"]
            error = float(array[ix, column].mean())-target
            row[name+"_relative_error"] = error/max(abs(target), 1e-12)
            if abs(error) > 1e-8*max(abs(target), 1e-12):
                raise ValueError("BM1_EXPORTED_FLUX_OR_WIND_SIGNAL_LOST")
        total = result.data[PR].iloc[ix].to_numpy()
        if not np.allclose(total.mean(), constraints[m][PR]["target_mean"], rtol=1e-8, atol=1e-12):
            raise ValueError("BM1_TOTAL_PRECIPITATION_SIGNAL_LOST")
        # EPW contains liquid rain, not CMIP total precipitation. Check the
        # declared inherited fraction against the complete sidecar total.
        if np.any(array[ix, 6] > total + 1e-6):
            raise ValueError("BM1_EXPORTED_LIQUID_RAIN_EXCEEDS_TOTAL")
        reports.append(row)
    return {"status": "EXPORTED_MONTHLY_SIGNALS_AND_CONDITIONAL_THERMODYNAMIC_STATE_PASS",
        "monthly_readback": reports, "records": len(rows), "independent_accuracy_qualified": False,
        "max_exported_hydrostatic_pressure_residual_Pa": pressure_error,
        "max_exported_T_Td_RH_vapour_residual_Pa": vapour_error,
        "numerical_pressure_and_vapour_readback_tolerance_Pa": 1e-4}


def verify_sidecar(result: ClimateResult, path: Path) -> dict:
    """Verify q and total precipitation in the actual saved hourly CSV."""
    saved = pd.read_csv(path, index_col=0)
    if len(saved) != 8760 or not pd.DatetimeIndex(pd.to_datetime(saved.index, utc=True)).equals(result.request.utc_starts):
        raise ValueError("BM1_EXPORTED_SIDECAR_CLOCK_LOST")
    if not pd.DatetimeIndex(pd.to_datetime(saved["interval_end_utc"], utc=True)).equals(result.request.utc_ends):
        raise ValueError("BM1_EXPORTED_SIDECAR_ENDPOINTS_LOST")
    columns = list(result.data.columns)
    if not np.isfinite(saved[columns].to_numpy(dtype=float)).all():
        raise ValueError("BM1_EXPORTED_SIDECAR_NONFINITE")
    months = result.request.local_starts.month.to_numpy()
    reports = []
    for row in result.diagnostics["monthly_signals_and_constraints"]:
        ix = np.flatnonzero(months == row["month"])
        q_error = float(saved[Q].iloc[ix].mean())-row["target_mean_q_kgkg"]
        target = row[PR]["target_mean"]
        pr_error = float(saved[PR].iloc[ix].mean())-target
        if abs(q_error) > 1e-9 or abs(pr_error) > 1e-8*max(abs(target), 1e-12):
            raise ValueError("BM1_EXPORTED_SIDECAR_Q_OR_TOTAL_PRECIPITATION_SIGNAL_LOST")
        reports.append({"month": row["month"], "q_mean_error_kgkg": q_error,
            "total_precipitation_mean_error_mm_per_hour": pr_error})
    return {"status": "SAVED_SIDECAR_CLOCK_Q_AND_TOTAL_PRECIPITATION_PASS", "months": reports}


def run_future(pattern_request: HistoricalRequest, future_request: FutureRequest, *, pattern_sources: Path,
               reference_sources: Path, nex_sources: Path, protocol: Path, output: Path) -> ClimateResult:
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    try:
        protocol_raw = Path(protocol).read_bytes()
        original_protocol = json.loads(protocol_raw)
        if original_protocol["reference_window"] != list(future_request.historical_window):
            raise ValueError("BM1_REQUEST_REFERENCE_WINDOW_DIFFERS_FROM_REGISTERED_PROTOCOL")
        raw, receipts = read_source_bundle(Path(pattern_sources), PATTERN_SOURCE_SHA, pattern_request)
        pattern = assemble_historical(pattern_request, raw, receipts)
        historical, future, nex_evidence = admit_nex(Path(nex_sources), future_request)
        signals = monthly_nex_signals(historical, future)
        reference, reference_evidence = reference_climatology(Path(reference_sources), pattern, sha(protocol_raw))
        result = morph_future(pattern, future_request, reference, signals, reference_evidence, nex_evidence)
        payload, epw_report = serialize_epw(result)
        signal_report = verify_signals(result, payload)
        result = replace(result, quality=QualityStatus("ORIGINAL_SOURCES_CALENDAR_AND_MONTHLY_SIGNAL_READBACK_PASS",
            "CONDITIONAL_T_P2M_Q_WATER_RH_CLOSURE_AND_BOUNDS_PASS", "NOT_INDEPENDENTLY_VALIDATED",
            "RESEARCH_REPRESENTATIVE_FUTURE_CLI; UI_NOT_CONNECTED"))
        write_exclusive(output / "climate.epw", payload)
        frame = result.data.copy(); frame.insert(0, "interval_start_local_standard", pattern_request.local_starts)
        frame.insert(1, "interval_end_utc", pattern_request.utc_ends)
        write_exclusive(output / "hourly.csv.gz", gzip.compress(frame.to_csv(index_label="interval_start_utc", float_format="%.12g").encode(), mtime=0))
        signal_report["sidecar_readback"] = verify_sidecar(result, output / "hourly.csv.gz")
        ledger = json_bytes({"physical_and_definition_adjustments": list(result.adjustments),
            "transformations": list(result.transformations), "actual_water_mass_budget_claimed": False,
            "q_constraint_is_monthly_time_mean": True, "no_arbitrary_RH_floor": True})
        write_exclusive(output / "adjustment_ledger.json.gz", gzip.compress(ledger, mtime=0))
        write_exclusive(output / "monthly_signal_readback.json", json_bytes(signal_report))
        write_exclusive(output / "reference_climatology.json", json_bytes(reference))
        write_exclusive(output / "registered_protocol.json", protocol_raw)
        canonical = result.to_canonical()
        from ..epw_parser import parse_epw
        imported = parse_epw(output / "climate.epw")
        assert len(imported.data) == 8760
        files = {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in sorted(output.iterdir())}
        manifest = {"schema": SCHEMA, "pattern_request": pattern_request.to_dict(), "future_request": asdict(future_request),
            "quality": asdict(result.quality), "sources": result.sources, "field_definitions": {k: asdict(v) for k,v in result.fields.items()},
            "diagnostics": result.diagnostics, "EPW": epw_report, "signal_readback": signal_report,
            "source_packets": {"pattern": PATTERN_SOURCE_SHA, "reference": REFERENCE_PACKET_SHA, "NEX": NEX_PACKET_SHA},
            "registered_protocol_sha256": sha(protocol_raw), "files": files,
            "implementation_sha256": {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "weather_provider_requests_this_run": 0, "IV1_station_observations_opened": False,
            "canonical_calendar_mode": canonical.temporal.calendar_mode, "pattern_year": pattern_request.year,
            "scenario_period_is_not_EPW_event_year": True, "UI_connected": False,
            "EnergyPlus_building_simulation_run": False, "production_ready": False, "wall_seconds": time.monotonic()-start}
        write_exclusive(output / "manifest.json", json_bytes(manifest))
        return result
    except Exception as exc:
        write_exclusive(output / "failed.json", json_bytes({"status": "BLOCKED_NO_COMPLETE_FUTURE_RESULT",
            "error": type(exc).__name__+": "+str(exc), "pattern_request": pattern_request.to_dict(),
            "future_request": asdict(future_request), "production_ready": False}))
        raise
