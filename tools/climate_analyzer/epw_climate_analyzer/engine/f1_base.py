"""F1 annual base and reference admission; no inferred climate reference period.

An actual year supplies chronology, a declared representative EPW or a separate
same-location climatology supplies the local climate level. They are distinct.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
from hashlib import sha256
import io
import re

import numpy as np
import pandas as pd

from ..climate_model import ClimateLocation
from .contracts import HistoricalRequest
from .epw import EPW_FIELDS, EPW_BOUNDS
from .future import T, TD, RH, P, Q, GHI, LW, WS, PR
from .point_interpolation import saturation_buck_hpa, dewpoint_buck_c
from .thermodynamics import (saturation_water_pa, dew_point_water_c, q_from_e,
    e_from_q, state_from_vapour, pressure_at_2m)

SURFACE = "SURFACE_PROXY_WITH_0_TO_2M_ADAPTER"
COLLOCATED = "PRESSURE_AT_TRH_OR_DECLARED_COLLOCATED_PROXY"
MK, BUCK = "MURPHY_KOOP_WATER", "BUCK_WATER"
MAX_EPW = 12*1024**2
PROVIDER_ROUNDING = "B0_PROVIDER_T_TD_0P1K_VAPOUR_PROJECTION_v1"


def water_es(t, curve):
    if curve == MK: return saturation_water_pa(t)
    if curve == BUCK: return 100*saturation_buck_hpa(t)
    raise ValueError("F1_WATER_CURVE_NOT_ADMITTED")


def water_dew(e, curve):
    if curve == MK: return dew_point_water_c(e)
    if curve == BUCK: return dewpoint_buck_c(np.asarray(e)/100)
    raise ValueError("F1_WATER_CURVE_NOT_ADMITTED")


@dataclass(frozen=True)
class BaseYear:
    request: HistoricalRequest
    location: ClimateLocation
    data: pd.DataFrame
    epw: bytes
    identity: dict
    pressure_contract: str
    water_curve: str
    vapour_authority: str
    calendar_kind: str
    source_years: tuple

    def __post_init__(self):
        object.__setattr__(self, "data", self.data.copy(deep=True))

    @property
    def sha256(self): return sha256(self.epw).hexdigest()

    def vapour_state(self):
        t, td, rh, p = (self.data[k].to_numpy(float) for k in (T, TD, RH, P))
        e = water_es(td, self.water_curve) if self.vapour_authority == "DEW_POINT" else rh/100*water_es(t, self.water_curve)
        if self.identity.get("source_rounding_admission", {}).get("policy") == PROVIDER_ROUNDING:
            # Admission below proves both 0.1 K quantisation and the upper bound.
            # This changes the derived F1 vapour only; source T/Td/RH and EPW
            # remain immutable. No general-purpose supersaturation repair.
            bad = td > t+1e-10
            if (self.vapour_authority != "DEW_POINT" or np.any(td[bad]-t[bad] > .100001)
                    or self.water_curve != MK or not np.allclose(t[bad]*10, np.round(t[bad]*10), rtol=0, atol=1e-7)
                    or not np.allclose(td[bad]*10, np.round(td[bad]*10), rtol=0, atol=1e-7)
                    or int(bad.sum()) != self.identity["source_rounding_admission"]["hours"]
                    or self.identity["source_kind"] not in ("IGE_B0_BACKGROUND", "IGE_B0_REFERENCE")):
                raise ValueError("F1_SOURCE_ROUNDING_ADMISSION_CHANGED")
            e = np.minimum(e, water_es(t, self.water_curve))
        if np.any(e > water_es(t, self.water_curve)+1e-7):
            raise ValueError("F1_BASE_VAPOUR_ABOVE_SATURATION_REQUIRES_SEPARATE_ADMISSION")
        if self.pressure_contract == SURFACE: return state_from_vapour(t, e, p)
        return q_from_e(e, p), p.copy()


def admit_base(epw, *, calendar_kind, pressure_contract, water_curve,
               vapour_authority="RH", source_kind="UPLOADED_EPW", signal_site=None,
               extras=None, provenance=None, rounding_policy=None):
    if len(epw) > MAX_EPW: raise ValueError("F1_BASE_EPW_SIZE_LIMIT")
    if pressure_contract not in (SURFACE, COLLOCATED) or water_curve not in (MK, BUCK) or vapour_authority not in ("RH", "DEW_POINT"):
        raise ValueError("F1_EXPLICIT_PRESSURE_AND_WATER_CONTRACT_REQUIRED")
    if calendar_kind not in ("ACTUAL_YEAR", "REPRESENTATIVE_YEAR"):
        raise ValueError("F1_DECLARE_ACTUAL_OR_REPRESENTATIVE_CALENDAR")
    rows = list(csv.reader(io.StringIO(epw.decode("utf-8-sig"))))
    keys = ["LOCATION", "DESIGN CONDITIONS", "TYPICAL/EXTREME PERIODS", "GROUND TEMPERATURES",
        "HOLIDAYS/DAYLIGHT SAVINGS", "COMMENTS 1", "COMMENTS 2", "DATA PERIODS"]
    if len(rows) < 8 or [r[0] if r else "" for r in rows[:8]] != keys:
        raise ValueError("F1_EPW_EIGHT_HEADER_CONTRACT")
    header, records = rows[:8], rows[8:]
    descriptor = " ".join(" ".join(r) for r in header)
    if re.search(r"REPRESENTATIVE FUTURE|IGE_(?:BM1|F1)_", descriptor, re.I):
        raise ValueError("F1_FUTURE_OUTPUT_CANNOT_BECOME_HISTORICAL_BASE")
    if calendar_kind == "ACTUAL_YEAR" and re.search(r"\b(?:TMY\w*|TRY|IWEC\w*|CWEC\w*|Meteonorm)\b", descriptor, re.I):
        raise ValueError("F1_TMY_IS_NOT_AN_ACTUAL_OBSERVED_YEAR")
    if len(header[0]) < 10 or header[7][1:3] != ["1", "1"] or len(records) not in (8760, 8784) or any(len(r) != 35 for r in records):
        raise ValueError("F1_COMPLETE_SINGLE_HOURLY_EPW_YEAR_REQUIRED")
    lat, lon, offset, height = map(float, header[0][6:10])
    if not np.isfinite([lat, lon, offset, height]).all() or not -500 <= height <= 9000 or offset != int(offset):
        raise ValueError("F1_EPW_FINITE_HEIGHT_AND_WHOLE_HOUR_STANDARD_OFFSET_REQUIRED")
    year = int(records[0][0]) if calendar_kind == "ACTUAL_YEAR" else (2000 if len(records) == 8784 else 2001)
    label = re.sub(r"[,\r\n\x00]", " ", header[0][1]).strip()[:100] or "Selected base"
    request = HistoricalRequest(lat, lon, year, int(offset)*60, label)
    if len(request.local_starts) != len(records): raise ValueError("F1_LEAP_CALENDAR_MISMATCH")
    for row, stamp in zip(records, request.local_starts):
        values = list(map(int, row[:5]))
        if values[1:] != [stamp.month, stamp.day, stamp.hour+1, 60] or (calendar_kind == "ACTUAL_YEAR" and values[0] != year):
            raise ValueError("F1_MISSING_REORDERED_DUPLICATE_OR_WRONG_EPW_HOUR")
        if float(row[33]) > 0 and float(row[34]) != 1:
            raise ValueError("F1_LIQUID_RAIN_REQUIRES_ONE_HOUR_ACCUMULATION_PERIOD")
    f = pd.DataFrame({k: [float(r[col]) for r in records] for k, (col, _, _) in EPW_FIELDS.items()}, index=request.utc_starts)
    for key, (low, high) in EPW_BOUNDS.items():
        v = f[key].to_numpy(float)
        if not np.isfinite(v).all() or np.any((v < low) | (v > high)):
            raise ValueError("F1_BASE_MISSING_OR_OUT_OF_RANGE_"+key)
    if np.any(f[TD] > f[T]+.100001) or np.any(f["diffuse_horizontal_radiation_wh_m2"] > f[GHI]+.100001):
        raise ValueError("F1_BASE_DEWPOINT_OR_RADIATION_INCONSISTENT")
    if extras is not None:
        if (len(extras) != len(f) or not isinstance(extras.index, pd.DatetimeIndex) or extras.index.tz is None
                or not extras.index.tz_convert("UTC").equals(request.utc_starts)):
            raise ValueError("F1_BASE_SIDECAR_HOUR_CENSUS_OR_CLOCK")
        for key in set(extras) & set(EPW_FIELDS):
            v = extras[key].to_numpy(float); expected = f[key].to_numpy(float)
            tolerance = .500001 if key == "total_sky_cover_tenths" else np.maximum(1e-7, 1e-9*np.abs(expected))
            if not np.isfinite(v).all() or np.any(np.abs(v-expected) > tolerance):
                raise ValueError("F1_BASE_SIDECAR_CORE_VALUES_MISMATCH_"+key)
        for key in (PR, "direct_horizontal_radiation_wh_m2"):
            if key in extras:
                v = extras[key].to_numpy(float)
                if not np.isfinite(v).all() or np.any(v < 0): raise ValueError("F1_BASE_INVALID_SIDECAR_"+key)
                f[key] = v
        if PR in f and np.any(f[PR]+.100001 < f["liquid_precipitation_depth_mm"]):
            raise ValueError("F1_BASE_LIQUID_EXCEEDS_TOTAL")
    site = list(signal_site or (lat, lon))
    # SignalRequest separately verifies source coverage; never replace the site
    # with an old pilot's NASA cell. A background request and its returned grid
    # cell remain different geometries in the provenance.
    identity = {"EPW_sha256": sha256(epw).hexdigest(), "source_kind": source_kind,
        "EPW_location": [lat, lon, height], "signal_site": site, "calendar_kind": calendar_kind,
        "pattern_year": year, "original_source_years": sorted({int(r[0]) for r in records}),
        "pressure_contract": pressure_contract, "water_curve": water_curve,
        "vapour_authority": vapour_authority, "source_provenance": provenance or {}}
    if rounding_policy is not None:
        if (rounding_policy != PROVIDER_ROUNDING or source_kind not in ("IGE_B0_BACKGROUND", "IGE_B0_REFERENCE")
                or vapour_authority != "DEW_POINT" or water_curve != MK):
            raise ValueError("F1_SOURCE_ROUNDING_POLICY_ONLY_FOR_KNOWN_B0_DEWPOINT")
        t, td = f[T].to_numpy(float), f[TD].to_numpy(float)
        bad = td > t+1e-10
        if bad.any():
            if (np.any(td[bad]-t[bad] > .100001)
                    or not np.allclose(t[bad]*10, np.round(t[bad]*10), rtol=0, atol=1e-7)
                    or not np.allclose(td[bad]*10, np.round(td[bad]*10), rtol=0, atol=1e-7)):
                raise ValueError("F1_B0_EXCESS_NOT_EXPLAINED_BY_0P1K_SOURCE_QUANTISATION")
            original, admitted = water_es(td[bad], water_curve), water_es(t[bad], water_curve)
            identity["source_rounding_admission"] = {"policy": PROVIDER_ROUNDING, "hours": int(bad.sum()),
                "method": "minimum absolute vapour change e*=min(e_source,es(T)); fixed source T and p",
                "maximum_Td_minus_T_K": float(np.max(td[bad]-t[bad])),
                "original_EPW_modified": False, "independent_accuracy_qualified": False,
                "adjustments": [{"interval_start_utc": str(f.index[i]), "source_T_C": float(t[i]),
                    "source_Td_C": float(td[i]), "source_RH_pct": float(f[RH].iloc[i]),
                    "source_vapour_Pa": float(a), "admitted_vapour_Pa": float(b), "delta_vapour_Pa": float(b-a)}
                    for i, a, b in zip(np.flatnonzero(bad), original, admitted)]}
    base = BaseYear(request, ClimateLocation(lat, lon, height, label), f, epw, identity,
        pressure_contract, water_curve, vapour_authority, calendar_kind, tuple(identity["original_source_years"]))
    base.vapour_state()
    return base


def climatology(bases):
    """Equal-hour noleap estimator; all original leap-day rows remain in packets."""
    frames, days = [], []
    for base in bases:
        f = base.data.copy(); f[Q] = base.vapour_state()[0]
        clock = base.request.local_starts; f["month"] = clock.month
        frames.append(f.iloc[np.flatnonzero(~((clock.month == 2) & (clock.day == 29)))])
        t = f[T].to_numpy().reshape(-1, 24); d = clock[::24]
        keep = ~((d.month == 2) & (d.day == 29))
        days.append(pd.DataFrame({"month": d.month[keep], "midrange": ((t.min(1)+t.max(1))/2)[keep], "dtr": (t.max(1)-t.min(1))[keep]}))
    f, d = pd.concat(frames), pd.concat(days)
    keys = [k for k in (Q, GHI, LW, WS, PR, "liquid_precipitation_depth_mm") if k in f]
    return {m: {"midrange_c": float(d[d.month == m].midrange.mean()), "dtr_K": float(d[d.month == m].dtr.mean()),
        **{k: float(f.loc[f.month == m, k].mean()) for k in keys}} for m in range(1, 13)}


def epw_reference(base, reference, window, evidence):
    if not evidence.strip(): raise ValueError("F1_REFERENCE_PERIOD_REQUIRES_SOURCE_EVIDENCE")
    if reference.calendar_kind != "REPRESENTATIVE_YEAR":
        raise ValueError("F1_LOCAL_REFERENCE_MUST_REPRESENT_DECLARED_CLIMATE_PERIOD")
    a, b = base.location, reference.location
    if (abs(a.latitude-b.latitude) > 1e-4 or abs((a.longitude-b.longitude+180)%360-180) > 1e-4
            or abs(a.elevation_m-b.elevation_m) > .1 or base.request.utc_offset_minutes != reference.request.utc_offset_minutes):
        raise ValueError("F1_REFERENCE_POINT_HEIGHT_OR_FIXED_CLOCK_MISMATCH")
    if base.pressure_contract != reference.pressure_contract:
        raise ValueError("F1_REFERENCE_PRESSURE_CONTRACT_MISMATCH")
    return climatology([reference]), {"kind": "DECLARED_REPRESENTATIVE_EPW", "reference_window": list(window),
        "period_evidence": evidence, "reference_base": reference.identity, "reference_EPW_sha256": reference.sha256,
        "reference_sampling_uncertainty_qualified": False,
        "period_is_user_declared_not_verified_from_TMY_row_years": True}
