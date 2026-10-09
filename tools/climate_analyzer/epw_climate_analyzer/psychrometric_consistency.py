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
    """Check and, if necessary, repair cross-field psychrometric consistency.

    The reference is derived exclusively from measured dry-bulb, RH and
    resolved station pressure. Derived saturation pressure is independently
    reconstructed from vectorized ASHRAE equations if the materialized value
    is inconsistent; all subsequent derived quantities are then reconciled.
    Correction never overwrites measured inputs. Vapour pressure at/above
    total pressure still fails closed rather than producing huge ratios.

    The routine is vectorized and therefore applies the same contract below
    and above the 2**15 record-length boundary. A stable, correct frame is
    returned unchanged. Any repair records a diagnostic in `frame.attrs`.
    """
    if "humidity_ratio_g_kg" not in frame.columns:
        return frame
    for required in ("dry_bulb_temperature_c", "relative_humidity_pct", "saturation_vapor_pressure_pa"):
        if required not in frame.columns:
            raise ValueError(f"Psychrometric closure cannot validate missing column {required!r}.")
    fallback = float(fallback_pressure_pa)
    if not np.isfinite(fallback) or not 30000.0 <= fallback <= 120000.0:
        raise ValueError("Psychrometric closure requires fallback pressure 30000..120000 Pa.")

    n = len(frame)
    if n == 0:
        return frame
    t = _numeric(frame, "dry_bulb_temperature_c")
    rh_pct = _numeric(frame, "relative_humidity_pct")
    raw_p = _numeric(frame, "atmospheric_station_pressure_pa")
    p = np.where(
        np.isfinite(raw_p) & (raw_p >= 30000.0) & (raw_p <= 120000.0),
        raw_p, fallback,
    )
    sat = _numeric(frame, "saturation_vapor_pressure_pa")
    valid = np.isfinite(t) & np.isfinite(rh_pct) & rh_pct.__ge__(0.0) & rh_pct.__le__(100.0)
    if not valid.any():
        return frame

    # Saturation pressure is *derived*, not a station observation. A stale
    # or incorrectly materialized value must be recovered from measured T,
    # rather than raising an unhandled ValueError for the entire Streamlit UI.
    # These ASHRAE equations are defined for -100..200 °C; impossible source
    # temperatures still fail closed instead of being silently normalized.
    if np.any(valid & ((t < -100.0) | (t > 200.0))):
        raise ValueError("Psychrometric closure: source temperature outside ASHRAE -100..200 °C.")
    reference_sat, saturation_vector_repairs = stable_saturation_pressure_pa(t)
    if np.any(valid & (~np.isfinite(reference_sat) | (reference_sat <= 0.0))):
        raise ValueError("Psychrometric closure: cannot reconstruct saturation pressure from source temperature.")
    # Saturation has already passed the stricter independent 2% check in
    # stable_saturation_pressure_pa(), including scalar recovery where needed.
    # Never recompute a second Magnus reference with a different array length:
    # after RH/quality filtering it can cross a distinct 2**15-sized path.

    invalid_sat = valid & (
        ~np.isfinite(sat) | (sat <= 0.0)
        | (np.abs(sat - reference_sat) > np.maximum(0.5, 0.01 * reference_sat))
    )
    # Keep valid existing ASHRAE values untouched. Only reconstruct suspect
    # derived saturation pressure, then reconcile all dependent derived fields.
    sat = np.where(invalid_sat, reference_sat, sat)

    pv = rh_pct / 100.0 * sat
    if np.any(valid & (~np.isfinite(pv) | (pv >= p))):
        raise ValueError(
            "Psychrometric closure rejected vapour pressure >= atmospheric pressure; "
            "check source units before using derived humidity."
        )

    # Operate only on valid source rows; nonvalid values remain NaN in reference.
    ref = {field: np.full(n, np.nan, dtype=float) for field in _CORRECTED_FIELDS}
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        w = np.maximum(0.621945 * pv / (p - pv), 1e-7)
        h = 1.006 * t + w * (2501.0 + 1.86 * t)
        volume = 287.042 * (t + 273.15) * (1.0 + 1.607858 * w) / p
        density = (1.0 + w) / volume
        wsat = 0.621945 * sat / (p - sat)
        degree = w / np.maximum(wsat, 1e-12)

    values = {
        "saturation_vapor_pressure_pa": sat,
        "humidity_ratio_kg_kg": w,
        "humidity_ratio_g_kg": w * 1000.0,
        "vapor_pressure_pa": pv,
        "moist_air_enthalpy_kj_kg": h,
        "specific_volume_m3_kg": volume,
        "moist_air_density_kg_m3": density,
        "degree_of_saturation": degree,
    }
    # Do not generate a saturated state when p_sat exceeds atmospheric p.
    physically_defined_degree = valid & (sat < p)
    values["degree_of_saturation"] = np.where(physically_defined_degree, degree, np.nan)

    inconsistent = invalid_sat.copy()
    for field, expected in values.items():
        original = _numeric(frame, field)
        ref[field][valid] = expected[valid]
        expected_valid = np.isfinite(ref[field]) & valid
        incorrect = expected_valid & (
            ~np.isfinite(original) | (np.abs(original - ref[field]) > _ABS_TOL[field])
        )
        # Reject invalid degree values for physically undefined saturation.
        if field == "degree_of_saturation":
            incorrect |= valid & ~physically_defined_degree & np.isfinite(original)
        inconsistent |= incorrect

    if not inconsistent.any():
        return frame

    repaired = frame.copy()
    for field in _CORRECTED_FIELDS:
        original = _numeric(frame, field)
        corrected = np.where(inconsistent & valid, ref[field], original)
        repaired[field] = corrected

    measured_w = _numeric(frame, "humidity_ratio_g_kg")
    expected_w = ref["humidity_ratio_g_kg"]
    deviation = np.abs(measured_w[inconsistent] - expected_w[inconsistent])
    deviation = deviation[np.isfinite(deviation)]
    repaired.attrs.update(dict(frame.attrs))
    repaired.attrs["psychrometric_physical_closure"] = {
        "status": "reconciled",
        "repaired_rows": int(inconsistent.sum()),
        "reconstructed_saturation_pressure_rows": int(invalid_sat.sum()),
        "scalar_saturation_recovery_rows": int(saturation_vector_repairs),
        "valid_source_rows": int(valid.sum()),
        "total_rows": n,
        "maximum_humidity_ratio_deviation_g_kg": float(deviation.max()) if len(deviation) else None,
        "method": "T/RH/pressure, ASHRAE saturation-pressure cross-check and independent algebraic recovery",
    }
    origins = dict(repaired.attrs.get("canonical_variable_origin", {}))
    for field in _CORRECTED_FIELDS:
        origins[field] = "physically reconciled from measured T/RH/pressure; source measurements unchanged"
    repaired.attrs["canonical_variable_origin"] = origins
    return repaired
