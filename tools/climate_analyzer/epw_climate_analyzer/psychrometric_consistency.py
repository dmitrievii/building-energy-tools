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

import numpy as np
import pandas as pd


_CORRECTED_FIELDS = (
    "humidity_ratio_kg_kg",
    "humidity_ratio_g_kg",
    "vapor_pressure_pa",
    "moist_air_enthalpy_kj_kg",
    "specific_volume_m3_kg",
    "moist_air_density_kg_m3",
    "degree_of_saturation",
)
_ABS_TOL = {
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


def reconcile_historical_psychrometrics(
    frame: pd.DataFrame,
    *,
    fallback_pressure_pa: float = 101325.0,
) -> pd.DataFrame:
    """Check and, if necessary, repair cross-field psychrometric consistency.

    The reference is derived exclusively from the measured dry-bulb, RH,
    resolved station pressure and independently checked saturation pressure.
    Correction is restricted to materialized derived quantities. Unphysical
    source saturation pressure or p_v >= p_total fails closed and never
    produces artificial huge humidity ratios.

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

    typical = valid & (t >= -50.0) & (t <= 60.0)
    if typical.any():
        reference_sat = _reference_saturation_pa(t[typical])
        if np.any(~np.isfinite(sat[typical]) | (sat[typical] <= 0.0)
                  | (np.abs(sat[typical] - reference_sat) > 0.15 * reference_sat)):
            raise ValueError(
                "Psychrometric closure: saturated vapour pressure is inconsistent "
                "with dry-bulb temperature; derived properties cannot be recovered safely."
            )

    # A missing saturation-pressure result on an otherwise physically valid
    # source row is itself an error, never a reason to silently lose the row.
    if np.any(valid & (~np.isfinite(sat) | (sat <= 0))):
        raise ValueError("Psychrometric closure: valid source rows lack saturation pressure.")

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

    inconsistent = np.zeros(n, dtype=bool)
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
