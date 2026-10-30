"""S1: explicit P8.2F-derived annual T/p/e interpolation, with active heights.

The frozen Buck-water, IDW, lapse and monthly reconciliation equations are
preserved. New source/clock adapters are separately named; their accuracy does
not inherit the old Swiss development metrics. No target weather enters a fit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from ..climate_model import ClimateLocation
from .contracts import HistoricalRequest
from .station_epw_admission import StationYearRequest
from .thermodynamics import q_from_e, e_from_q

T = "dry_bulb_temperature_c"
P = "atmospheric_station_pressure_pa"
E = "vapor_pressure_hpa"
RH = "relative_humidity_pct"
TD = "dew_point_temperature_c"
CORE = (T, P, E, RH)
SCHEMA = "IGE_S1_POINT_INTERPOLATION_v1"
METHOD = "S1_P82F_FROZEN_EQUATIONS_HOURLY_MONTHLY_ADAPTER_v1"
CALIBRATION_SHA = "b7efcae0840851515004f3eb820cc7b3c801695664cfa8ae0c89011bea79dfec"
RD, G = 287.05, 9.80665


@dataclass(frozen=True)
class PointRequest:
    latitude: float
    longitude: float
    elevation_m: float
    elevation_reference: str
    year: int
    utc_offset_minutes: int = 60
    label: str = "Selected point"
    assume_buck_water: bool = False
    allow_nominal_height_proxy: bool = False
    excluded_station_id: str = ""

    def __post_init__(self):
        self.background_request()  # Common bounds, clock and label validation.
        if type(self.assume_buck_water) is not bool or type(self.allow_nominal_height_proxy) is not bool:
            raise ValueError("S1_ASSUMPTIONS_REQUIRE_EXPLICIT_BOOLEAN_CHOICES")
        if self.elevation_m is None or not self.elevation_reference.strip():
            raise ValueError("S1_TARGET_HEIGHT_AND_REFERENCE_REQUIRED")
        StationYearRequest("S1", self.year, self.utc_offset_minutes, self.label)

    def background_request(self):
        return HistoricalRequest(self.latitude, self.longitude, self.year,
            self.utc_offset_minutes, self.label, site_elevation_m=self.elevation_m,
            site_elevation_reference=self.elevation_reference)

    @property
    def utc_starts(self):
        return self.background_request().utc_starts

    @property
    def local_starts(self):
        return self.background_request().local_starts

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class PointDonor:
    station_id: str
    location: ClimateLocation
    data: pd.DataFrame = field(repr=False, compare=False)
    year: int
    temperature_elevation_m: float | None
    pressure_elevation_m: float | None
    height_reference: str
    height_is_proxy: bool
    source_sha256: str
    source_kind: str
    blockers: tuple[str, ...] = ()
    # Published monthly e can be supplied by a qualified future adapter. The
    # current H1/EPW adapters explicitly use full-hourly monthly sample means.
    monthly_vapour_hpa: tuple[float, ...] | None = None
    monthly_origin: str = "COMPLETE_HOURLY_SAMPLE_MEAN_NOT_PUBLISHED_MONTHLY_SERIES"
    source_admission: dict = field(default_factory=dict, repr=False, compare=False)
    source_gaps_csv_gz: bytes = field(default=b"", repr=False, compare=False)


@dataclass(frozen=True)
class PointAssessment:
    report: dict
    hourly: pd.DataFrame
    adjustments: pd.DataFrame
    donor_months: pd.DataFrame


def calibration():
    body = (Path(__file__).parent / "data/p82f_calibration_20261014.json").read_bytes()
    if sha256(body).hexdigest() != CALIBRATION_SHA:
        raise ValueError("S1_FROZEN_CALIBRATION_HASH_CHANGED")
    return json.loads(body)


def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    dlat, dlon = b-a, math.radians(lon2-lon1)
    u = math.sin(dlat/2)**2 + math.cos(a)*math.cos(b)*math.sin(dlon/2)**2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1., max(0., u))))


def idw_weights(distances):
    d = np.asarray(distances, float)
    if not len(d) or not np.isfinite(d).all() or np.any(d < 0):
        raise ValueError("S1_INVALID_DONOR_DISTANCE")
    w = 1 / np.maximum(d, .25)**2
    return w / w.sum()


def outside_horizontal_hull(request, donors):
    """Metadata-only convex-hull diagnostic; no fitted representativeness claim."""
    points = sorted(set((((d.location.longitude-request.longitude+180) % 360-180)*math.cos(math.radians(request.latitude)),
                         d.location.latitude-request.latitude) for d in donors))
    def cross(a, b, c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    if len(points) < 3: return True
    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0: lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0: upper.pop()
        upper.append(point)
    hull = lower[:-1]+upper[:-1]
    if len(hull) < 3: return True
    return any(cross(hull[i], hull[(i+1) % len(hull)], (0., 0.)) < -1e-12 for i in range(len(hull)))


def saturation_buck_hpa(t_c):
    t = np.asarray(t_c, float)
    if not np.isfinite(t).all() or np.any((t < -85) | (t > 65)):
        raise ValueError("S1_BUCK_DOMAIN")
    return 6.1121 * np.exp((18.678-t/234.5)*(t/(257.14+t)))


def dewpoint_buck_c(e):
    e = np.asarray(e, float)
    if not np.isfinite(e).all() or np.any((e <= .01) | (e >= 80)):
        raise ValueError("S1_FROZEN_DEWPOINT_DOMAIN")
    lo, hi = np.full(e.shape, -85.), np.full(e.shape, 65.)
    for _ in range(55):
        mid = (lo+hi)/2
        below = saturation_buck_hpa(mid) < e
        lo = np.where(below, mid, lo); hi = np.where(below, hi, mid)
    return (lo+hi)/2


def hypsometric_pressure_hpa(p_hpa, t_c, dz):
    p, t = np.broadcast_arrays(np.asarray(p_hpa, float), np.asarray(t_c, float))
    if (not np.isfinite(p).all() or not np.isfinite(t).all() or not math.isfinite(dz)
            or np.any((p <= 300) | (p >= 1150) | (t <= -75) | (t >= 65)) or abs(dz) >= 5000):
        raise ValueError("S1_FROZEN_HYPSOMETRIC_INPUT_DOMAIN")
    tm = t + 273.15 - G*dz/(2*1004.0)
    if np.any(tm < 175):
        raise ValueError("S1_FROZEN_LAYER_TEMPERATURE_DOMAIN")
    return p*np.exp(-G*dz/(RD*tm))


def reconcile_vapour(goal, shape, t, p_hpa):
    """Frozen P8.2C scalar water filling; never silently lower a monthly goal."""
    cap = np.minimum(saturation_buck_hpa(t), .98*np.asarray(p_hpa, float))
    return _reconcile_capacity(goal, shape, cap)


def _reconcile_capacity(goal, shape, cap):
    """Same scalar root with one already evaluated physical capacity vector."""
    shape, cap = np.asarray(shape, float), np.asarray(cap, float)
    if (shape.shape != cap.shape or not np.isfinite(shape).all() or np.any(shape <= 0)
            or not np.isfinite(cap).all() or np.any(cap <= 0)):
        raise ValueError("S1_INVALID_MOISTURE_SHAPE")
    if not math.isfinite(goal) or goal <= 1e-6:
        raise ValueError("S1_INVALID_MONTHLY_VAPOUR")
    if goal > float(cap.mean()) + 1e-8:
        raise ValueError("INFEASIBLE_MONTHLY_MEAN_UNDER_HOURLY_SATURATION")
    lo, hi = 0., max(2*goal/float(shape.mean()), 1e-6)
    for _ in range(90):
        if np.minimum(hi*shape, cap).mean() >= goal-1e-8:
            break
        hi *= 2
    else:
        raise ValueError("S1_MONTHLY_ROOT_NOT_BRACKETED")
    for _ in range(90):
        mid = (lo+hi)/2
        if np.minimum(mid*shape, cap).mean() < goal:
            lo = mid
        else:
            hi = mid
    scale = (lo+hi)/2
    e = np.minimum(scale*shape, cap)
    if np.any(e <= 0) or abs(float(e.mean())-goal) > 1e-8:
        raise ValueError("S1_MONTHLY_RECONCILIATION_RESIDUAL")
    return e, scale, cap


def qualify_donor(request, donor, *, max_distance_km=100., max_height_difference_m=1500.):
    """Full annual admission precedes selection; caps are operational, not accuracy gates."""
    errors = list(donor.blockers)
    if not re.fullmatch(r"[0-9a-f]{64}", donor.source_sha256): errors.append("HASHED_SOURCE_IDENTITY_REQUIRED")
    distance = distance_km(request.latitude, request.longitude, donor.location.latitude, donor.location.longitude)
    if donor.station_id == request.excluded_station_id and request.excluded_station_id:
        errors.append("TARGET_STATION_EXCLUDED")
    if donor.year != request.year: errors.append("SOURCE_YEAR_MISMATCH")
    if not donor.data.index.equals(request.utc_starts): errors.append("EXACT_UTC_ANNUAL_CLOCK_REQUIRED")
    if distance > max_distance_km: errors.append("OUTSIDE_OPERATIONAL_RADIUS")
    if donor.height_is_proxy and not request.allow_nominal_height_proxy:
        errors.append("NOMINAL_HEIGHT_PROXY_REQUIRES_EXPLICIT_ACCEPTANCE")
    if not request.assume_buck_water: errors.append("BUCK_WATER_ASSUMPTION_NOT_ACCEPTED")
    if not donor.height_reference: errors.append("DONOR_HEIGHT_REFERENCE_MISSING")
    for z in (donor.temperature_elevation_m, donor.pressure_elevation_m):
        if z is None or not math.isfinite(z): errors.append("DONOR_HEIGHT_UNAVAILABLE")
        elif abs(request.elevation_m-z) > max_height_difference_m: errors.append("OUTSIDE_OPERATIONAL_HEIGHT_DIFFERENCE")
    counts = {}
    for col, bounds in {T: (-75, 65), P: (30000, 115000), E: (.01, 80), RH: (0, 105)}.items():
        v = pd.to_numeric(donor.data[col], errors="coerce").to_numpy(float) if col in donor.data else np.array([])
        good = np.isfinite(v) & (v > bounds[0]) & (v < bounds[1])
        if col == RH: good = np.isfinite(v) & (v >= 0) & (v <= 105)
        counts[col] = int(good.sum())
        if len(v) != len(request.utc_starts) or not good.all(): errors.append("INCOMPLETE_OR_INVALID_"+col)
    if donor.monthly_vapour_hpa is not None:
        m = np.asarray(donor.monthly_vapour_hpa, float)
        if m.shape != (12,) or not np.isfinite(m).all() or np.any(m <= 0):
            errors.append("TWELVE_POSITIVE_MONTHLY_VAPOUR_VALUES_REQUIRED")
    moisture_residual = None
    if all(col in donor.data for col in (T, E, RH)):
        valid = donor.data[[T, E, RH]].apply(pd.to_numeric, errors="coerce")
        valid = valid[np.isfinite(valid).all(axis=1) & valid[T].between(-75, 65)]
        if len(valid):
            moisture_residual = float(np.max(np.abs(100*valid[E]/saturation_buck_hpa(valid[T])-valid[RH])))
    return {"station_id": donor.station_id, "station_name": donor.location.city, "source_kind": donor.source_kind,
            "latitude": donor.location.latitude, "longitude": donor.location.longitude,
            "source_sha256": donor.source_sha256, "distance_km": distance,
            "temperature_elevation_m": donor.temperature_elevation_m,
            "pressure_elevation_m": donor.pressure_elevation_m,
            "height_reference": donor.height_reference, "height_is_proxy": donor.height_is_proxy,
            "complete_in_bounds_hours": counts, "monthly_origin": donor.monthly_origin,
            "max_abs_source_RH_vs_Buck_e_T_pp": moisture_residual,
            "source_RH_not_independently_enforced_after_e_is_defined": True,
            "eligible": not errors, "reasons": list(dict.fromkeys(errors)), "selected": False}


def interpolate_point(request: PointRequest, donors: list[PointDonor]) -> PointAssessment:
    config = calibration()
    admissions = [qualify_donor(request, donor) for donor in donors]
    report = {"schema": SCHEMA, "method": METHOD, "request": request.to_dict(),
        "calibration_sha256": CALIBRATION_SHA, "calibration_lineage": config,
        "operational_caps": {"candidate_limit": 20, "distance_km": 100, "height_difference_m": 1500,
                             "caps_are_not_empirical_accuracy_qualification": True},
        "donor_admission": admissions, "global_blockers": [], "selected_donors": [],
        "target_weather_used": False, "new_fit_or_tuning": False, "engine_gap_fill": False,
        "output_fields": {T: {"unit": "°C", "definition": "height-corrected donor blend"},
            P: {"unit": "Pa", "definition": "absolute pressure; conditional dry-temperature transfer"},
            E: {"unit": "hPa", "definition": "Buck-water vapour pressure with monthly reconciliation"},
            RH: {"unit": "%", "definition": "100 e / Buck liquid-water saturation at all T"},
            TD: {"unit": "°C", "definition": "inverse Buck liquid-water saturation"},
            "specific_humidity_kg_kg": {"unit": "kg/kg moist air", "definition": "shared q(e,p) algebra; conditional on pressure height proxy"}},
        "clock": {"rows": "interval start UTC", "states": "right endpoint / published nominal node",
                  "monthly_groups": "fixed local standard interval-start calendar", "DST": False},
        "quality": {"execution_correctness": "ADMISSION_COMPLETED", "physical_admissibility": "NO_COMPLETE_POINT_YEAR",
                    "independent_accuracy": "NOT_INDEPENDENTLY_QUALIFIED_FOR_NEW_ADAPTERS",
                    "operational_and_application_scope": "RESTRICTED_RESEARCH_POINT_INTERPOLATION",
                    "production_ready": False},
        "limitations": ["Monthly AT-trained regional slopes do not resolve hourly inversions or valley sheltering.",
            "Dry-temperature pressure transfer uses source T as barometer-layer proxy; sensor collocation is not established.",
            "Buck liquid-water phase is an explicit source interpretation, not a NASA phase definition.",
            "Hourly-derived monthly e is not the independent published monthly e used by the accepted P8.2F experiment.",
            "Donor spread and height envelope are diagnostics, not calibrated uncertainty or independent accuracy."]}
    ids = [d.station_id for d in donors]
    digests = [d.source_sha256 for d in donors]
    if len(ids) != len(set(ids)) or len(digests) != len(set(digests)):
        report["global_blockers"].append("DUPLICATED_DONOR_ID_OR_SOURCE_BYTES")
    eligible = sorted(((r["distance_km"], d.station_id, d, r) for d, r in zip(donors, admissions) if r["eligible"]),
                      key=lambda item: (item[0], item[1]))
    if len(eligible) < 4: report["global_blockers"].append("FOUR_COMPLETE_ELIGIBLE_DONORS_REQUIRED")
    empty = pd.DataFrame(index=request.utc_starts)
    if report["global_blockers"]:
        report["status"] = "POINT_YEAR_BLOCKED"
        return PointAssessment(report, empty, empty.copy(), pd.DataFrame())
    chosen = eligible[:4]
    for _, _, _, r in chosen: r["selected"] = True
    report["selected_donors"] = [v[1] for v in chosen]
    w = idw_weights([v[0] for v in chosen])
    mon = request.local_starts.month.to_numpy()
    n = len(mon)
    tt, pp, ee, means, donor_months = [], [], [], [], []
    slopes = config["training"]
    t_rates = np.asarray(slopes["temperature_slope_K_m"])
    e_rates = np.asarray(slopes["log_vapour_slope_m_inv"])
    try:
        for weight, (_, sid, donor, admission) in zip(w, chosen):
            admission["weight"] = float(weight)
            raw_t = donor.data[T].to_numpy(float)
            raw_p = donor.data[P].to_numpy(float)/100
            raw_e = donor.data[E].to_numpy(float)
            dz_t = request.elevation_m-donor.temperature_elevation_m
            dz_p = request.elevation_m-donor.pressure_elevation_m
            tt.append(raw_t+t_rates[mon-1]*dz_t)
            pp.append(hypsometric_pressure_hpa(raw_p, raw_t, dz_p))
            ee.append(raw_e)
            monthly = np.array(donor.monthly_vapour_hpa if donor.monthly_vapour_hpa is not None
                else [raw_e[mon == m].mean() for m in range(1, 13)])
            means.append(monthly)
            for m in range(1, 13):
                donor_months.append({"station_id": sid, "month": m, "weight": float(weight),
                    "delta_z_temperature_m": dz_t, "delta_z_pressure_m": dz_p,
                    "temperature_lapse_K_m": float(t_rates[m-1]), "temperature_correction_K": float(t_rates[m-1]*dz_t),
                    "log_e_lapse_m_inv": float(e_rates[m-1]), "log_e_correction": float(e_rates[m-1]*dz_t),
                    "source_monthly_e_hpa": float(monthly[m-1]), "monthly_origin": donor.monthly_origin})
        tt, pp, ee, means = map(np.asarray, (tt, pp, ee, means))
        t = w@tt; p_hpa = w@pp
        # Reuse this very same floating-point saturation in both the monthly
        # cap and final RH, including SIMD/tail evaluation differences.
        es_water = saturation_buck_hpa(t)
        capacity = np.minimum(es_water, .98*p_hpa)
        e, shape, unconstrained = (np.zeros(n) for _ in range(3))
        monthly_audit = []
        for m in range(1, 13):
            ix = mon == m
            goal = float(np.exp(w@(np.log(means[:, m-1])+e_rates[m-1]*np.array([
                request.elevation_m-v[2].temperature_elevation_m for v in chosen]))))
            a = np.exp(w@np.log(ee[:, ix]/means[:, m-1, None]))
            values, scale, cap = _reconcile_capacity(goal, a, capacity[ix])
            e[ix], shape[ix], unconstrained[ix], capacity[ix] = values, a, scale*a, cap
            monthly_audit.append({"month": m, "target_e_mean_hpa": goal, "output_e_mean_hpa": float(values.mean()),
                                  "residual_hpa": float(values.mean()-goal), "scale_hpa": float(scale),
                                  "saturated_hours": int(np.sum(scale*a > cap)), "hours": int(ix.sum())})
        # Divide first: e<=e_sw implies a floating-point ratio <=1. Computing
        # (100*e)/e_sw can round an exactly saturated state above 100 by one
        # ulp on another CPU. No e, monthly target or RH bound is changed.
        rh = 100*(e/es_water)
        td = dewpoint_buck_c(e)
        if (np.any(rh > 100+1e-7) or np.any(td > t+1e-7) or np.any(e >= p_hpa)
                or not np.isfinite(np.vstack((t, p_hpa, e, rh, td))).all()):
            raise ValueError("S1_POINTWISE_PHYSICAL_CLOSURE_FAILURE")
    except ValueError as exc:
        report["global_blockers"].append(str(exc)); report["status"] = "POINT_YEAR_BLOCKED"
        return PointAssessment(report, empty, empty.copy(), pd.DataFrame(donor_months))
    q = q_from_e(e*100, p_hpa*100)
    hourly = pd.DataFrame({T: t, P: p_hpa*100, E: e, RH: rh, TD: td, "specific_humidity_kg_kg": q}, index=request.utc_starts)
    raw_t = w@np.asarray([v[2].data[T] for v in chosen])
    raw_p = w@np.asarray([v[2].data[P] for v in chosen])
    ledger = pd.DataFrame({"T_before_height_c": raw_t, "T_after_height_c": t, "T_height_delta_K": t-raw_t,
        "p_before_height_pa": raw_p, "p_after_height_pa": p_hpa*100, "p_height_delta_pa": p_hpa*100-raw_p,
        "e_relative_shape": shape, "e_before_saturation_hpa": unconstrained, "e_capacity_hpa": capacity,
        "e_after_reconciliation_hpa": e, "e_saturation_adjustment_hpa": e-unconstrained,
        "donor_T_weighted_RMS_spread_K": np.sqrt(w@((tt-t)**2)),
        "donor_p_weighted_RMS_spread_pa": 100*np.sqrt(w@((pp-p_hpa)**2))}, index=request.utc_starts)
    z = [v[2].temperature_elevation_m for v in chosen]
    report.update({"status": "POINT_YEAR_COMPLETE_RESEARCH", "hours": n, "monthly_reconciliation": monthly_audit,
        "target_height_outside_donor_envelope": not min(z) <= request.elevation_m <= max(z),
        "target_outside_horizontal_donor_hull": outside_horizontal_hull(request, [v[2] for v in chosen]),
        "max_abs_temperature_height_correction_K": float(np.max(np.abs(t-raw_t))),
        "max_abs_pressure_height_correction_pa": float(np.max(np.abs(p_hpa*100-raw_p))),
        "saturation_adjustment_hours": int(np.sum(unconstrained > capacity)),
        "max_RH_closure_pp": float(np.max(np.abs(100*e/saturation_buck_hpa(t)-rh))),
        "max_q_to_e_closure_pa": float(np.max(np.abs(e_from_q(q, p_hpa*100)-e*100))),
        "max_Td_closure_hpa": float(np.max(np.abs(saturation_buck_hpa(td)-e)))})
    report["quality"].update(execution_correctness="ANNUAL_INTERPOLATION_COMPLETED",
        physical_admissibility="T_P_E_RH_TD_BUCK_WATER_CLOSURE_AND_MONTHLY_E_PASS")
    return PointAssessment(report, hourly, ledger, pd.DataFrame(donor_months))
