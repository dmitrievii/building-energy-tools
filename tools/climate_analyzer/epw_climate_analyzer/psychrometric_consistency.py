"""Independent physical-closure gate for derived historical psychrometrics.

A long GeoSphere hourly export (33,045 timestamps) has produced implausible
humidity ratios while measured T, RH, pressure, saturation pressure and
calculated enthalpy remained plausible. The short view (32,709 timestamps)
did not exhibit this error. This final-frame guard detects cross-column
inconsistency independently of PsychroLib's humidity-ratio implementation
and reconstructs *derived* properties only when their source inputs are
physically valid. Provider observations are never modified.

The original runtime defect may be outside the numerical core. This guard
is a production protection and diagnostic, not a claim to identify that cause.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import math

import numpy as np
import pandas as pd


# Streamlit may keep a pre-hotfix consistency module after source redeployment.
_RUNTIME_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


_CORRECTED_FIELDS = (
    "saturation_vapor_pressure_pa",
    "humidity_ratio_kg_kg",
    "humidity_ratio_g_kg",
    "vapor_pressure_pa",
    "moist_air_enthalpy_kj_kg",
    "specific_volume_m3_kg",
    "moist_air_density_kg_m3",
    "degree_of_saturation",
)
_ABS_TOL = {
    "saturation_vapor_pressure_pa": 0.5,
    "humidity_ratio_kg_kg": 1e-7,
    "humidity_ratio_g_kg": 1e-4,
    "vapor_pressure_pa": 0.05,
    "moist_air_enthalpy_kj_kg": 0.005,
    "specific_volume_m3_kg": 1e-4,
    "moist_air_density_kg_m3": 5e-4,
    "degree_of_saturation": 1e-4,
}


def _numeric(data: pd.DataFrame, column: str) -> np.ndarray:
    if column not in data.columns:
        return np.full(len(data), np.nan, dtype=float)
    return pd.to_numeric(data[column], errors="coerce").to_numpy(dtype=float)


def _reference_saturation_pa(t: np.ndarray) -> np.ndarray:
    """Magnus water/ice reference for validating supplied ASHRAE pressure."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        return np.where(
            t >= 0.0,
            610.94 * np.exp(17.625 * t / (243.04 + t)),
            610.94 * np.exp(22.587 * t / (273.86 + t)),
        )


def _ashrae_saturation_pressure_pa(t_c: np.ndarray) -> np.ndarray:
    """Independent vectorized ASHRAE saturation pressure [Pa] from °C.

    This deliberately does not call PsychroLib. Both the ice and liquid-water
    equations reproduce ASHRAE/PsychroLib SI saturation pressure without
    depending on global PsychroLib unit/Numba state.
    """
    t_k = np.asarray(t_c, dtype=float) + 273.15
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        log_ice = (
            -5.6745359e3 / t_k + 6.3925247 - 9.677843e-3 * t_k
            + 6.2215701e-7 * t_k**2 + 2.0747825e-9 * t_k**3
            - 9.484024e-13 * t_k**4 + 4.1635019 * np.log(t_k)
        )
        log_water = (
            -5.8002206e3 / t_k + 1.3914993 - 4.8640239e-2 * t_k
            + 4.1764768e-5 * t_k**2 - 1.4452093e-8 * t_k**3
            + 6.5459673 * np.log(t_k)
        )
        return np.exp(np.where(np.asarray(t_c, dtype=float) <= 0.0, log_ice, log_water))


def _scalar_ashrae_saturation_pressure_pa(temp_c: float) -> float:
    """Scalar, NumPy-independent ASHRAE 2017 water/ice saturation [Pa].

    Used only for exceptional rows when a vector result violates an
    independent saturation reference. It must not share vector intermediates.
    """
    kelvin = float(temp_c) + 273.15
    if not (-100.0 <= temp_c <= 200.0):
        raise ValueError("Psychrometric source temperature outside ASHRAE -100..200 °C.")
    if temp_c <= 0.0:
        log_p = (
            -5.6745359e3 / kelvin + 6.3925247 - 9.677843e-3 * kelvin
            + 6.2215701e-7 * kelvin**2 + 2.0747825e-9 * kelvin**3
            - 9.484024e-13 * kelvin**4 + 4.1635019 * math.log(kelvin)
        )
    else:
        log_p = (
            -5.8002206e3 / kelvin + 1.3914993 - 4.8640239e-2 * kelvin
            + 4.1764768e-5 * kelvin**2 - 1.4452093e-8 * kelvin**3
            + 6.5459673 * math.log(kelvin)
        )
    return math.exp(log_p)


def stable_saturation_pressure_pa(t_c: np.ndarray) -> tuple[np.ndarray, int]:
    """Calculate and validate ASHRAE saturation with bounded vector batches.

    The historical long-series incident crosses 2**15 elements. Batches below
    that threshold ensure the numerical reference and saturated-pressure
    arrays are never evaluated as a single 33k-element operation. This is
    the sole saturation-reference comparison in the historical calculation.
    Values failing a 2% independent Magnus check are re-evaluated with scalar
    Python-math ASHRAE and verified again; irrecoverable states fail closed.
    """
    t = np.asarray(t_c, dtype=float)
    if t.ndim != 1:
        raise ValueError("Psychrometric saturation calculation expects a one-dimensional temperature series.")
    sat = np.full(len(t), np.nan, dtype=float)
    recovery_count = 0
    # A bounded batch avoids both a long NumPy temporary and different
    # >2**15 reference-array sizes caused by missing RH observations.
    batch_size = 8192
    for offset in range(0, len(t), batch_size):
        chunk = t[offset:offset + batch_size]
        computed = np.asarray(_ashrae_saturation_pressure_pa(chunk), dtype=float).copy()
        if computed.shape != chunk.shape:
            raise ValueError("Psychrometric saturation calculation returned an unexpected array shape.")
        finite = np.isfinite(chunk)
        bad = finite & (~np.isfinite(computed) | (computed <= 0.0))
        typical = finite & (chunk >= -50.0) & (chunk <= 60.0)
        if typical.any():
            magnus = _reference_saturation_pa(chunk[typical])
            observed = computed[typical]
            mismatched = (~np.isfinite(observed) | (observed <= 0.0)
                          | (np.abs(observed - magnus) > 0.02 * magnus))
            bad[typical] |= mismatched

        if bad.any():
            for local_pos in np.flatnonzero(bad):
                temp = float(chunk[local_pos])
                corrected = _scalar_ashrae_saturation_pressure_pa(temp)
                if not math.isfinite(corrected) or corrected <= 0.0:
                    raise ValueError("Psychrometric scalar saturation recovery returned a nonphysical value.")
                if -50.0 <= temp <= 60.0:
                    ref = float(_reference_saturation_pa(np.array([temp]))[0])
                    if not math.isfinite(ref) or ref <= 0.0 or abs(corrected - ref) > 0.02 * ref:
                        raise ValueError("Psychrometric independent scalar saturation checks disagree.")
                computed[local_pos] = corrected
            recovery_count += int(bad.sum())
        sat[offset:offset + len(chunk)] = computed
    return sat, recovery_count


def reconcile_historical_psychrometrics(
    frame: pd.DataFrame,
    *,
    fallback_pressure_pa: float = 101325.0,
) -> pd.DataFrame:
    """Enforce physical closure using authoritative *scalar* ASHRAE equations.

    For long historical arrays, the observed corruption was not a modest
    floating point drift: in 32,941 rows both materialized humidity ratio
    [kg/kg] and degree of saturation contained precisely the same spurious
    thousands-scale value. Vector-to-vector comparisons and a second vector
    reconstruction did not protect the deployed UI.

    This routine builds each *derived* state from one source observation at a
    time, using Python's scalar math module. All seven other derived columns
    are checked against the same state, not one another. This is independent
    of PsychroLib, NumPy saturation arrays, display aggregation and series
    length; it takes ~0.1 s for 33,045 rows. Measured T/RH/station pressure
    and their missing-value flags are never changed.

    The original frame is returned by identity if its derived values are
    already consistent. Otherwise all physical derived columns are replaced
    from the independent scalar source state, *including after* 32,768 rows.
    """
    if "humidity_ratio_g_kg" not in frame.columns:
        return frame
    required = ("dry_bulb_temperature_c", "relative_humidity_pct")
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError("Psychrometric scalar closure missing measured columns: " + ", ".join(missing))
    fallback = float(fallback_pressure_pa)
    if not math.isfinite(fallback) or not 30000.0 <= fallback <= 120000.0:
        raise ValueError("Psychrometric scalar closure needs pressure within 30000..120000 Pa.")

    n = len(frame)
    if not n:
        return frame

    source_t = pd.to_numeric(frame["dry_bulb_temperature_c"], errors="coerce").tolist()
    source_rh = pd.to_numeric(frame["relative_humidity_pct"], errors="coerce").tolist()
    source_p = pd.to_numeric(
        frame.get("atmospheric_station_pressure_pa", pd.Series(math.nan, index=frame.index)),
        errors="coerce",
    ).tolist()
    existing = {
        field: pd.to_numeric(frame[field], errors="coerce").tolist()
        if field in frame.columns else [math.nan] * n
        for field in _CORRECTED_FIELDS
    }
    reference = {field: [math.nan] * n for field in _CORRECTED_FIELDS}
    invalid_rows = 0
    valid_rows = 0
    repaired_rows = 0
    repaired_sat_rows = 0
    max_w_deviation = 0.0

    for i, (temp, rh, p_src) in enumerate(zip(source_t, source_rh, source_p, strict=True)):
        # Preserve genuinely missing or invalid provider observations:
        # they cannot generate a psychrometric value.
        if not (math.isfinite(temp) and math.isfinite(rh) and 0.0 <= rh <= 100.0):
            invalid_rows += 1
            continue
        if not (-100.0 <= temp <= 200.0):
            raise ValueError(
                "Psychrometric scalar closure: measured temperature outside ASHRAE range "
                f"at row {i} (T={temp})."
            )
        valid_rows += 1
        p = p_src if math.isfinite(p_src) and 30000.0 <= p_src <= 120000.0 else fallback
        sat = _scalar_ashrae_saturation_pressure_pa(float(temp))
        pv = sat * (float(rh) / 100.0)
        if not math.isfinite(sat) or sat <= 0.0 or not math.isfinite(pv) or pv >= p:
            raise ValueError(
                "Psychrometric scalar closure: source state cannot describe an air-vapour mixture "
                f"at row {i}; T={temp}, RH={rh}, P={p}, P_v={pv} Pa."
            )

        w = max(0.621945 * pv / (p - pv), 1e-7)
        volume = 287.042 * (temp + 273.15) * (1.0 + 1.607858 * w) / p
        density = (1.0 + w) / volume
        wsat = 0.621945 * sat / (p - sat) if sat < p else math.nan
        degree = w / max(wsat, 1e-12) if math.isfinite(wsat) else math.nan
        state = {
            "saturation_vapor_pressure_pa": sat,
            "humidity_ratio_kg_kg": w,
            "humidity_ratio_g_kg": 1000.0 * w,
            "vapor_pressure_pa": pv,
            "moist_air_enthalpy_kj_kg": 1.006 * temp + w * (2501.0 + 1.86 * temp),
            "specific_volume_m3_kg": volume,
            "moist_air_density_kg_m3": density,
            "degree_of_saturation": degree,
        }
        row_inconsistent = False
        for field, value in state.items():
            reference[field][i] = value
            old = existing[field][i]
            if math.isfinite(value):
                if not math.isfinite(old) or abs(old - value) > _ABS_TOL[field]:
                    row_inconsistent = True
            elif math.isfinite(old):
                row_inconsistent = True

        if not math.isfinite(existing["saturation_vapor_pressure_pa"][i]) or (
            abs(existing["saturation_vapor_pressure_pa"][i] - sat)
            > max(0.5, 0.01 * sat)
        ):
            repaired_sat_rows += 1
        old_w = existing["humidity_ratio_g_kg"][i]
        if math.isfinite(old_w):
            max_w_deviation = max(max_w_deviation, abs(old_w - 1000.0 * w))
        repaired_rows += int(row_inconsistent)

    # Invalid measured rows must never retain a finite derived value.
    for i, (temp, rh) in enumerate(zip(source_t, source_rh, strict=True)):
        if math.isfinite(temp) and math.isfinite(rh) and 0.0 <= rh <= 100.0:
            continue
        if any(math.isfinite(existing[field][i]) for field in _CORRECTED_FIELDS):
            repaired_rows += 1

    if repaired_rows == 0:
        return frame
    repaired = frame.copy()
    for field, values in reference.items():
        repaired[field] = values

    # Final contract: do not send a numerically corrupted array to Plotly or
    # CSV even if a DataFrame assignment altered one of the materialized series.
    materialized_w = repaired["humidity_ratio_g_kg"].tolist()
    for i, (actual, expected) in enumerate(zip(materialized_w, reference["humidity_ratio_g_kg"], strict=True)):
        if math.isfinite(expected) and (not math.isfinite(actual) or abs(actual - expected) > 1e-7):
            raise RuntimeError(f"Psychrometric scalar closure failed materialization at row {i}.")
        if not math.isfinite(expected) and math.isfinite(actual):
            raise RuntimeError(f"Psychrometric scalar closure invented humidity at missing row {i}.")

    repaired.attrs.update(dict(frame.attrs))
    repaired.attrs["psychrometric_physical_closure"] = {
        "status": "reconciled",
        "repaired_rows": int(repaired_rows),
        "reconstructed_saturation_pressure_rows": int(repaired_sat_rows),
        "scalar_saturation_recovery_rows": 0,
        "valid_source_rows": int(valid_rows),
        "invalid_source_rows": int(invalid_rows),
        "total_rows": n,
        "maximum_humidity_ratio_deviation_g_kg": float(max_w_deviation),
        "method": "authoritative independent row-wise scalar ASHRAE T/RH/pressure closure",
    }
    origins = dict(repaired.attrs.get("canonical_variable_origin", {}))
    for field in _CORRECTED_FIELDS:
        origins[field] = "independently reconstructed scalar ASHRAE from measured T/RH/pressure"
    repaired.attrs["canonical_variable_origin"] = origins
    return repaired
