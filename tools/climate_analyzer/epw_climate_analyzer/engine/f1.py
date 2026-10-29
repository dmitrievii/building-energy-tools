"""F1 monthly morph of an admitted selected annual pattern.

Reuses B-M1's rank-temperature transform and unique q box/sum projection.
This contract does not enforce native NASA daily constraints or hurs, predict
future pressure, generate new event chronology, or qualify local accuracy.
"""
from __future__ import annotations

from dataclasses import asdict
import csv
import io

import numpy as np
import pandas as pd

from .contracts import ClimateResult, FieldDefinition, QualityStatus
from .epw import EPW_FIELDS, serialize_epw, validate_epw_bytes
from .future import temperature_morph, T, TD, RH, P, Q, GHI, LW, WS, PR
from .f1_base import BaseYear, SURFACE, water_es, water_dew
from .thermodynamics import (q_from_e, e_from_q, state_from_vapour, pressure_at_2m,
    project_monthly_q)

CONTRACT = "IGE_F1_SELECTED_BASE_MONTHLY_FUTURE_v1"


def pressure(t, q, original_p, contract):
    return pressure_at_2m(t, q, original_p) if contract == SURFACE else original_p.copy()


def saturation_capacity(t, original_p, contract, es):
    q = state_from_vapour(t, es, original_p)[0] if contract == SURFACE else q_from_e(es, original_p)
    for _ in range(32):
        bad = e_from_q(q, pressure(t, q, original_p, contract)) > es
        if not np.any(bad): return q
        q = np.where(bad, np.nextafter(q, 0.), q)
    raise ValueError("F1_SATURATION_BOUND_DIRECTED_ROUNDING_FAILED")


def check_state(frame, curve):
    t, td, rh, p, q = (frame[k].to_numpy(float) for k in (T, TD, RH, P, Q))
    e = e_from_q(q, p)
    error_rh = float(np.max(np.abs(100*(e/water_es(t, curve))-rh)))
    error_e = float(np.max(np.abs(water_es(td, curve)-e)))
    if (not np.isfinite(np.stack((t, td, rh, p, q))).all() or np.any((rh < 0) | (rh > 100))
            or error_rh > 1e-7 or error_e > 1e-5):
        raise ValueError("F1_COMMON_T_P_Q_RH_TD_STATE_CLOSURE_FAILED")
    return {"max_RH_closure_residual_pp": error_rh, "max_dewpoint_vapour_residual_Pa": error_e}


def morph_selected(base: BaseYear, reference, signals, signal_request, *, reference_evidence,
                   nex_evidence, allow_liquid_precipitation_proxy=False):
    if reference_evidence.get("reference_window") != list(signal_request.reference_window):
        raise ValueError("F1_LOCAL_AND_GCM_REFERENCE_PERIODS_MUST_MATCH")
    if list(base.identity["signal_site"]) != [signal_request.latitude, signal_request.longitude]:
        raise ValueError("F1_NEX_SIGNALS_MUST_BELONG_TO_SELECTED_BASE_SITE")
    has_total = PR in base.data and all(PR in reference[m] for m in range(1, 13))
    if not has_total and not allow_liquid_precipitation_proxy:
        raise ValueError("F1_TOTAL_PRECIPITATION_UNKNOWN_EXPLICIT_LIQUID_RAIN_PROXY_REQUIRED")
    f = base.data.copy()
    if not has_total: f = f.drop(columns=[PR], errors="ignore")
    months = base.request.local_starts.month.to_numpy()
    t0, p0 = (f[k].to_numpy(float).copy() for k in (T, P))
    q0, p_base = base.vapour_state()
    t, temperature = temperature_morph(t0, months[::24], reference, signals)
    es = water_es(t, base.water_curve)  # one identical evaluation for bound and RH
    upper = saturation_capacity(t, p0, base.pressure_contract, es)
    q, prior = np.empty(len(f)), np.empty(len(f))
    monthly = []
    precip = PR if has_total else "liquid_precipitation_depth_mm"
    for m in range(1, 13):
        ix = np.flatnonzero(months == m); ref, sig = reference[m], signals[m]
        target = ref[Q]*sig["huss_ratio"]
        mean = float(q0[ix].mean())
        if mean <= 0: raise ValueError("F1_ZERO_PATTERN_Q_REQUIRES_OTHER_GENERATOR")
        prior[ix] = q0[ix]*target/mean
        try: q[ix], lam = project_monthly_q(prior[ix], upper[ix])
        except ValueError as exc:
            raise ValueError(f"F1_MONTH_{m}_Q_INFEASIBLE target={target:.12g} capacity={upper[ix].mean():.12g}; {exc}") from exc
        row = {"month": m, "hours": len(ix), "target_mean_q_kgkg": target,
            "actual_mean_q_kgkg": float(q[ix].mean()), "capacity_mean_q_kgkg": float(upper[ix].mean()),
            "projection_lambda_kgkg": lam, "projection_objective_half_squared": float(.5*np.sum((q[ix]-prior[ix])**2)),
            "projected_hours": int(np.sum(q[ix] != prior[ix])),
            "NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED": sig["NASA_hurs_delta_pp_DIAGNOSTIC_NOT_ENFORCED"]}
        for name, model in ((GHI, "rsds"), (LW, "rlds"), (WS, "sfcWind"), (precip, "pr")):
            desired = ref[name]*sig[model+"_ratio"]
            mean = float(base.data[name].iloc[ix].mean())
            if mean <= 0 and desired > 0:
                raise ValueError("F1_ZERO_PATTERN_AMOUNT_REQUIRES_OTHER_GENERATOR_"+name)
            factor = desired/mean if mean > 0 else 0.
            columns = [GHI, "direct_normal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2"] if name == GHI else [name]
            if name == GHI and "direct_horizontal_radiation_wh_m2" in f: columns.append("direct_horizontal_radiation_wh_m2")
            if name == PR: columns.append("liquid_precipitation_depth_mm")
            for column in columns: f.iloc[ix, f.columns.get_loc(column)] = base.data[column].iloc[ix].to_numpy()*factor
            row[name] = {"target_mean": desired, "actual_mean": float(f[name].iloc[ix].mean()),
                "combined_factor": factor, "NEX_ratio": sig[model+"_ratio"]}
        monthly.append(row)
    p = pressure(t, q, p0, base.pressure_contract); e = e_from_q(q, p)
    f[T], f[P], f[Q] = t, p, q
    f[RH], f[TD] = 100*(e/es), water_dew(e, base.water_curve)
    f["humidity_ratio_g_kg"] = 1000*q/(1-q)
    closure = check_state(f, base.water_curve)
    pressure_residual = float(np.max(np.abs(p-pressure(t, q, p0, base.pressure_contract))))
    ledger = pd.DataFrame({"base_T_c": t0, "future_T_c": t, "temperature_change_K": t-t0,
        "source_pressure_Pa": p0, "base_state_pressure_Pa": p_base, "future_state_pressure_Pa": p,
        "base_provider_RH_pct": base.data[RH], "base_reinterpreted_water_RH_pct": 100*e_from_q(q0, p_base)/water_es(t0, base.water_curve),
        "q_prior_kgkg": prior, "q_projected_kgkg": q, "q_adjustment_kgkg": q-prior,
        "source_dewpoint_c": base.data[TD], "base_reinterpreted_dewpoint_c": water_dew(e_from_q(q0, p_base), base.water_curve)}, index=f.index)
    for row in monthly:
        if abs(row["actual_mean_q_kgkg"]-row["target_mean_q_kgkg"]) > 1e-12:
            raise ValueError("F1_INTERNAL_MONTHLY_Q_TARGET_LOST")
    diagnostics = {"base": base.identity, "reference": reference_evidence, "NEX": nex_evidence,
        "signal_request": signal_request.to_dict(), "temperature_months": temperature,
        "monthly_signals_and_constraints": monthly, "water_curve": base.water_curve,
        "pressure_contract": base.pressure_contract, "closure": closure,
        "max_pressure_contract_residual_Pa": pressure_residual,
        "precipitation_signal_field": precip, "total_precipitation_available": has_total,
        "precipitation_contract": "TOTAL_AND_INHERITED_LIQUID_FRACTION" if has_total else "TOTAL_GCM_PR_RATIO_USED_AS_EXPLICIT_LIQUID_RAIN_PROXY; TOTAL_AND_SNOW_UNKNOWN",
        "NASA_hurs_signal_enforced": False, "NASA_hurs_phase_confirmed": False,
        "native_NASA_daily_constraints_enforced": False, "GCM_pressure_signal_available": False,
        "wind_direction_cloud_event_timing_inherited": True, "future_DNI_DHI_independently_predicted": False,
        "pattern_is_actual_future_date_forecast": False, "is_selected_TMY": False,
        "B4_qualified": False, "P2_advantage_qualified": False,
        "independent_accuracy_qualified": False, "IV1_station_observations_opened": False}
    fields = {k: FieldDefinition(unit, op, "f1_morph", "selected base geometry; "+base.pressure_contract,
        f"F1 monthly transfer; {k}; water curve {base.water_curve}") for k, (_, unit, op) in EPW_FIELDS.items()}
    for key in set(f)-set(fields):
        unit, op = ("mm", "interval_amount") if key == PR else (("Wh/m²", "interval_energy") if key == "direct_horizontal_radiation_wh_m2" else ("kg/kg moist air", "instant_at_interval_end") if key == Q else ("g/kg dry air", "instant_at_interval_end"))
        fields[key] = FieldDefinition(unit, op, "f1_morph", "selected base geometry", key)
    result = ClimateResult(base.request, f, base.location, fields,
        ({"id": "f1_morph", "dataset": CONTRACT, "base_sha256": base.sha256,
          "NEX_sha256": nex_evidence["source_packet_sha256"]},),
        ({"operation": CONTRACT, "monthly_signals": monthly, "temperature": temperature},), (),
        QualityStatus("COMPLETE_CALCULATION_PENDING_EXPORT", "CONDITIONAL_WATER_STATE_CLOSURE_PASS",
            "NOT_INDEPENDENTLY_VALIDATED", "RESEARCH_SELECTED_BASE_FUTURE", False), diagnostics)
    payload, screen = serialize_epw(result)
    rows = list(csv.reader(io.StringIO(payload.decode())))
    r = signal_request
    rows[0][1] = base.request.label+" REPRESENTATIVE FUTURE RESEARCH"
    rows[0][4] = f"IGE_F1_{r.model}_{r.scenario}"
    rows[5] = ["COMMENTS 1", f"F1 {r.model} {r.member} {r.scenario} {r.future_window[0]}-{r.future_window[1]}; reference {r.reference_window[0]}-{r.reference_window[1]}; pattern {base.request.year}. NOT an actual future forecast or selected TMY."]
    rows[6] = ["COMMENTS 2", f"{base.water_curve}; {base.pressure_contract}. Wind direction/cloud/event timing inherited; hurs not enforced; no station accuracy qualification. See ui_report.json and adjustment_ledger.csv.gz."]
    rows[7][3] = f"F1 REPRESENTATIVE FUTURE {r.future_window[0]}-{r.future_window[1]} PATTERN {base.request.year}"
    stream = io.StringIO(newline=""); csv.writer(stream, lineterminator="\n").writerows(rows)
    payload = stream.getvalue().encode()
    screen.update(validate_epw_bytes(payload, result))
    screen.update(verify_export(result, payload, base.water_curve))
    return result, payload, ledger, screen


def verify_export(result, payload, curve):
    records = list(csv.reader(io.StringIO(payload.decode())))[8:]
    f = pd.DataFrame({k: [float(r[col]) for r in records] for k, (col, _, _) in EPW_FIELDS.items()})
    f[Q] = q_from_e(f[RH].to_numpy()/100*water_es(f[T].to_numpy(), curve), f[P].to_numpy())
    # EPW numeric serialization is checked separately against every internal
    # value. These tolerances cover only decimal readback, not model accuracy.
    e_error = float(np.max(np.abs(water_es(f[TD].to_numpy(), curve)-e_from_q(f[Q], f[P]))))
    if e_error > 1e-4: raise ValueError("F1_EPW_READBACK_VAPOUR_CLOSURE_LOST")
    months = result.request.local_starts.month.to_numpy(); temp = f[T].to_numpy().reshape(-1, 24)
    targets = {r["month"]: r for r in result.diagnostics["temperature_months"]}
    reports = []
    for row in result.diagnostics["monthly_signals_and_constraints"]:
        m = row["month"]; ix = months == m; days = months[::24] == m
        center = float(((temp[days].min(1)+temp[days].max(1))/2).mean())
        dtr = float((temp[days].max(1)-temp[days].min(1)).mean())
        q_error = float(f.loc[ix, Q].mean()-row["target_mean_q_kgkg"])
        if abs(q_error) > 1e-10 or abs(center-targets[m]["target_midrange_c"]) > 1e-6 or abs(dtr-targets[m]["target_DTR_K"]) > 1e-6:
            raise ValueError("F1_EPW_READBACK_TEMPERATURE_OR_Q_MONTHLY_TARGET_LOST")
        for key in (GHI, LW, WS, result.diagnostics["precipitation_signal_field"]):
            if key == PR:
                # EPW contains only liquid rain. Total is retained and checked
                # in the hourly CSV, never invented from the liquid column.
                if abs(float(result.data.loc[ix, PR].mean())-row[PR]["target_mean"]) > 1e-9:
                    raise ValueError("F1_TOTAL_PRECIPITATION_CSV_TARGET_LOST")
                continue
            if abs(float(f.loc[ix, key].mean())-row[key]["target_mean"]) > max(1e-8, 1e-9*abs(row[key]["target_mean"])):
                raise ValueError("F1_EPW_READBACK_MONTHLY_AMOUNT_OR_WIND_SIGNAL_LOST_"+key)
        reports.append({"month": m, "q_mean_residual_kgkg": q_error, "midrange_c": center, "DTR_K": dtr})
    return {"F1_monthly_EPW_readback": "PASS", "monthly_readback": reports,
        "max_export_dewpoint_vapour_residual_Pa": e_error, "independent_accuracy_qualified": False}
