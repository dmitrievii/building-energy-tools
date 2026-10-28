"""A1 station contracts and an experimental temperature residual estimator.

Raw references retain their time/QC/vertical definitions. No station is silently
turned into a point-accurate weather generator, and no result is auto-promoted
into an EPW. Actual acquisition/scoring is separate from these pure adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import csv
import io
import json
import math
from typing import Literal

import numpy as np
import pandas as pd

T = "dry_bulb_temperature_c"
RH = "relative_humidity_pct"
P = "atmospheric_station_pressure_pa"
Operator = Literal["published_nominal_node", "mean_six_10min_nominal_nodes", "unknown"]


@dataclass(frozen=True)
class StationReference:
    country: str
    station_id: str
    name: str
    latitude: float
    longitude: float
    nominal_site_elevation_m: float
    source_metadata_sha256: str
    identity_group: str = ""
    historical_geometry_verified: bool = False

    def __post_init__(self):
        if self.country not in ("AT", "DE", "CH") or not self.station_id:
            raise ValueError("A1_AT_DE_CH_IDENTITY_REQUIRED")
        if not (math.isfinite(self.latitude) and math.isfinite(self.longitude)
                and -90 <= self.latitude <= 90 and -180 <= self.longitude <= 180
                and math.isfinite(self.nominal_site_elevation_m)):
            raise ValueError("A1_STATION_GEOGRAPHY_INVALID")
        if len(self.source_metadata_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_metadata_sha256):
            raise ValueError("A1_SOURCE_METADATA_HASH_REQUIRED")

    @property
    def key(self):
        return self.country + ":" + self.station_id


@dataclass(frozen=True)
class StationBatch:
    station: StationReference
    data: pd.DataFrame
    fields: dict
    source_sha256: str

    def __post_init__(self):
        data = self.data
        if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
            raise ValueError("A1_AWARE_REFERENCE_TIMESTAMP_REQUIRED")
        if data.index.has_duplicates or not data.index.is_monotonic_increasing:
            raise ValueError("A1_DUPLICATE_OR_REORDERED_SOURCE_REFERENCE")
        if np.any(data.index.asi8 % 3_600_000_000_000):
            raise ValueError("A1_EXPECTED_FULL_HOUR_REFERENCE")
        if any(column not in data for column in self.fields):
            raise ValueError("A1_FIELD_CONTRACT_INCOMPLETE")
        object.__setattr__(self, "data", data.copy(deep=True))

    def series(self, column: str, *, require_historical_geometry=True) -> pd.Series:
        if require_historical_geometry and not self.station.historical_geometry_verified:
            raise ValueError("A1_HISTORICAL_STATION_GEOMETRY_UNVERIFIED")
        data = self.data[column].copy()
        data.attrs.update({"reference_operator": self.fields[column]["time_operator"],
            "unit": self.fields[column]["unit"], "source_sha256": self.source_sha256})
        return data


def _csv(raw):
    try: source = raw.decode("utf-8-sig")
    except UnicodeDecodeError: source = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(source), delimiter=";")
    if not reader.fieldnames: raise ValueError("A1_CSV_HEADER_MISSING")
    reader.fieldnames = [k.strip() for k in reader.fieldnames]
    if len(set(reader.fieldnames)) != len(reader.fieldnames): raise ValueError("A1_CSV_DUPLICATE_COLUMNS")
    rows = list(reader)
    if any(None in row for row in rows): raise ValueError("A1_CSV_UNEXPECTED_EXTRA_COLUMNS")
    return rows, tuple(reader.fieldnames)


def _number(raw):
    if raw is None or str(raw).strip() in ("", "-999", "-999.0"): return float("nan")
    value = float(raw)
    if not math.isfinite(value): raise ValueError("A1_NONFINITE_SOURCE_NUMBER")
    return value


def _build(station, raw, times, values, flags, fields, qc_policy):
    if len(times) == 0: raise ValueError("A1_EMPTY_SOURCE_RECORDS")
    index = pd.DatetimeIndex(times, name="reference_time_utc")
    if index.tz is None: raise ValueError("A1_SOURCE_UTC_REFERENCE_REQUIRED")
    data = pd.DataFrame(values, index=index.tz_convert("UTC"))
    for column, definition in fields.items():
        flag = np.asarray(flags[column], dtype=object)
        if len(flag) != len(data): raise ValueError("A1_SOURCE_QC_AXIS_MISMATCH")
        lo, hi = definition["domain"]
        value = data[column].to_numpy(dtype=float)
        valid = np.isfinite(value) & (value >= lo) & (value <= hi)
        data["quality_flag__" + column] = flag
        data["quality_accepted__" + column] = valid & np.isin(flag, qc_policy["primary"])
        data["secondary_quality__" + column] = valid & np.isin(flag, qc_policy["secondary"])
    data.attrs.update({"reference_clock": "provider UTC timestamp; never relabelled as interval start",
        "source_fields": fields, "quality_policy": qc_policy, "source_metadata_sha256": station.source_metadata_sha256,
        "source_sha256": sha256(raw).hexdigest(), "historical_geometry_verified": station.historical_geometry_verified,
        "independent_accuracy_qualified": False, "pressure_and_TRH_collocated_assumed": False})
    return StationBatch(station, data, fields, sha256(raw).hexdigest())


def _field(source, unit, operator, pressure_kind=None):
    return {"provider_field": source, "unit": unit, "time_operator": operator,
        "domain": (-80., 65.) if unit == "°C" else (0., 100.) if unit == "%" else (30_000., 120_000.),
        "pressure_kind": pressure_kind, "RH_phase": "SOURCE_PHASE_UNVERIFIED" if unit == "%" else None,
        "sensor_height_history_verified": False}


def decode_dwd_hourly(raw: bytes, station: StationReference, *, product="TU") -> StationBatch:
    """Climate hourly P0 = station pressure; P = reduced pressure, never used.

    Urban P0_ST_10 / PP_ST_10 are a separate product. Field names must not be
    transported between these two schemas. QC10 and QC3 remain separate tiers.
    The generic hourly description does not prove an instantaneous operator.
    """
    if station.country != "DE" or product not in ("TU", "P0"):
        raise ValueError("A1_DWD_PRODUCT_OR_COUNTRY")
    rows, header = _csv(raw)
    quality = "QN_9" if product == "TU" else "QN_8"
    if not {"STATIONS_ID", "MESS_DATUM", quality}.issubset(header): raise ValueError("A1_DWD_REQUIRED_COLUMNS")
    specs = {T: _field("TT_TU", "°C", "unknown"), RH: _field("RF_TU", "%", "unknown")} if product == "TU" else {
        P: _field("P0", "Pa", "unknown", "absolute_at_station_barometer")}
    if product == "TU" and not {"TT_TU", "RF_TU"}.issubset(header): raise ValueError("A1_DWD_T_RH_FIELDS_REQUIRED")
    # If P0 is absent, retain missing station pressure even when P is numeric.
    values = {column: [] for column in specs}; flags = {column: [] for column in specs}; times = []
    for row in rows:
        if int(row["STATIONS_ID"]) != int(station.station_id): raise ValueError("A1_CROSS_STATION_RECORD")
        stamp = str(row["MESS_DATUM"]).strip()
        if len(stamp) != 10 or not stamp.isdigit(): raise ValueError("A1_DWD_INVALID_HOUR")
        times.append(pd.to_datetime(stamp, format="%Y%m%d%H", utc=True))
        flag = str(row[quality]).strip()
        for column, spec in specs.items():
            values[column].append(_number(row.get(spec["provider_field"])) * (100 if column == P else 1))
            flags[column].append(flag)
    return _build(station, raw, times, values, flags, specs, {"primary": ["10"], "secondary": ["3"],
        "label": "DWD_QN10_finished; QN3_automatic_correction_secondary; not equivalent to GeoSphere flags"})


def decode_geosphere_hourly(raw: bytes, station: StationReference) -> StationBatch:
    if station.country != "AT": raise ValueError("A1_GEOSPHERE_COUNTRY")
    obj = json.loads(raw); times = pd.to_datetime(obj["timestamps"], utc=False)
    features = obj.get("features", [])
    if len(features) != 1: raise ValueError("A1_ONE_EXPLICIT_INDIVIDUAL_STATION_REQUIRED")
    properties = features[0]["properties"]; sid = properties["station"]
    sid = sid["id"] if isinstance(sid, dict) else sid
    if str(sid) != station.station_id: raise ValueError("A1_CROSS_STATION_RECORD")
    parameters = properties["parameters"]
    specs, values, flags = {}, {}, {}
    for column, provider, unit in ((T,"tl","°C"),(RH,"rf","%"),(P,"p","hPa")):
        if provider not in parameters: continue
        record = parameters[provider]
        if record.get("unit") != unit or provider + "_flag" not in parameters:
            raise ValueError("A1_GEOSPHERE_UNIT_OR_NATIVE_QC_MISSING")
        specs[column] = _field(provider, "Pa" if column == P else unit, "published_nominal_node",
            "absolute_at_station_barometer" if column == P else None)
        specs[column]["operator_basis"] = "prior frozen v1-base-node to v2 rename chain; instrument filter duration unverified"
        values[column] = [_number(v) * (100 if column == P else 1) for v in record["data"]]
        flags[column] = [str(q) for q in parameters[provider+"_flag"]["data"]]
    if not specs: raise ValueError("A1_NO_SUPPORTED_GEOSPHERE_PARAMETER")
    return _build(station, raw, times, values, flags, specs, {"primary": ["22"], "secondary": ["12"],
        "label": "GeoSphere manual_original primary; automatic_original secondary; changed/unknown-origin excluded"})


def decode_meteoswiss_hourly(raw: bytes, station: StationReference) -> StationBatch:
    if station.country != "CH": raise ValueError("A1_METEOSWISS_COUNTRY")
    rows, header = _csv(raw)
    if not {"station_abbr", "reference_timestamp"}.issubset(header): raise ValueError("A1_SWISS_SOURCE_COLUMNS")
    specs = {column: _field(provider, unit, "mean_six_10min_nominal_nodes", pressure)
        for column,provider,unit,pressure in ((T,"tre200h0","°C",None),(RH,"ure200h0","%",None),
            (P,"prestah0","Pa","absolute_at_station_barometer")) if provider in header}
    if not specs: raise ValueError("A1_NO_SUPPORTED_SWISS_PARAMETER")
    if any(spec["provider_field"]+suffix in header for spec in specs.values() for suffix in ("_flag", "_qc")):
        raise ValueError("A1_UNDOCUMENTED_SWISS_QC_COLUMN")
    values = {c: [] for c in specs}; flags = {c: [] for c in specs}; times = []
    for row in rows:
        if str(row["station_abbr"]).strip().upper() != station.station_id.upper(): raise ValueError("A1_CROSS_STATION_RECORD")
        time = pd.to_datetime(row["reference_timestamp"], format="%d.%m.%Y %H:%M", utc=True)
        if time.year < 2018: raise ValueError("A1_SWISS_PRE_2018_DIFFERENT_HOURLY_OPERATOR_NOT_ADMITTED")
        times.append(time)
        for column,spec in specs.items():
            values[column].append(_number(row[spec["provider_field"]])*(100 if column == P else 1))
            flags[column].append("PUBLISHED_NO_ROW_QC")
    return _build(station, raw, times, values, flags, specs, {"primary": ["PUBLISHED_NO_ROW_QC"], "secondary": [],
        "label": "published historical OGD, no per-row native flag; separate quality stratum, not QC10-equivalent"})


def model_reference_operator(points: pd.Series, references: pd.DatetimeIndex, operator: Operator) -> pd.Series:
    """Project model nodes to the declared reference, without claiming true support.

    For six samples H-50,...,H minutes, piecewise-linear hourly model nodes
    yield 5/12*T(H-1h)+7/12*T(H). This is a disclosed subhourly surrogate,
    not exact knowledge of the ERA5 path or the instrument filter.
    """
    if points.attrs.get("unit") != "°C": raise ValueError("A1_EXPLICIT_CELSIUS_MODEL_UNIT_REQUIRED")
    if points.index.tz is None or references.tz is None or points.index.has_duplicates:
        raise ValueError("A1_UNIQUE_AWARE_MODEL_CLOCK_REQUIRED")
    if operator == "unknown": raise ValueError("A1_UNKNOWN_TEMPORAL_OPERATOR_BLOCKS_PRIMARY_COMPARISON")
    current = points.reindex(references).to_numpy(dtype=float)
    if operator == "published_nominal_node": values = current
    elif operator == "mean_six_10min_nominal_nodes":
        previous = points.reindex(references-pd.Timedelta(hours=1)).to_numpy(dtype=float)
        values = (5*previous + 7*current)/12
    else: raise ValueError("A1_TIME_OPERATOR_NOT_ADMITTED")
    result = pd.Series(values, index=references, name=points.name)
    result.attrs["reference_operator"] = operator
    result.attrs["unit"] = "°C"
    result.attrs["true_subhourly_path_or_sensor_filter_known"] = False
    return result


def distance_km(a: StationReference, b: StationReference) -> float:
    lat1, lat2 = map(math.radians, (a.latitude, b.latitude))
    dlat, dlon = lat2-lat1, math.radians(b.longitude-a.longitude)
    return 6371*2*math.asin(min(1., math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)))


def select_donors(target: StationReference, catalog: list[StationReference], *, heldout: list[StationReference]) -> list[StationReference]:
    """Metadata-only fixed three-nearest selection; never inspect observations."""
    excluded = {x.key for x in heldout} | {target.key}
    groups = {x.identity_group for x in [target,*heldout] if x.identity_group}
    anchors = [target,*heldout]
    ordered = []
    for station in catalog:
        if station.country != target.country or station.key in excluded or (station.identity_group and station.identity_group in groups): continue
        if min(distance_km(station, anchor) for anchor in anchors) < 5.: continue
        distance = distance_km(target, station)
        if distance <= 150.: ordered.append((distance, station.key, station))
    selected, identities = [], set()
    for _,_,station in sorted(ordered):
        identity = station.identity_group or station.key
        if identity in identities: continue
        selected.append(station); identities.add(identity)
        if len(selected) == 3: break
    return selected


def reconstruct_temperature(target: StationReference, baseline_at_target: pd.Series,
        frozen_donors: list[StationReference], donor_observed: dict[str, pd.Series],
        baseline_at_donors: dict[str, pd.Series], donor_qc_accepted: dict[str, pd.Series]) -> tuple[pd.Series, pd.DataFrame]:
    """R1: inverse-distance squared interpolation of same-support T residuals.

    Inputs must already use the same admitted reference operator. There is no
    target-observation argument, no lapse-rate fit or target bias calibration.
    QC/physical-source admission remains an explicit upstream responsibility.
    Ineligible hours are NaN, never a disguised fallback to the grid baseline.
    """
    clock = baseline_at_target.index
    if clock.tz is None or clock.has_duplicates: raise ValueError("A1_TARGET_MODEL_CLOCK")
    if not target.historical_geometry_verified or any(not d.historical_geometry_verified for d in frozen_donors):
        raise ValueError("A1_HISTORICAL_STATION_GEOMETRY_UNVERIFIED")
    operator = baseline_at_target.attrs.get("reference_operator")
    if operator not in ("published_nominal_node", "mean_six_10min_nominal_nodes"):
        raise ValueError("A1_TARGET_TIME_OPERATOR_UNVERIFIED")
    if baseline_at_target.attrs.get("unit") != "°C": raise ValueError("A1_EXPLICIT_CELSIUS_UNIT_REQUIRED")
    if not 2 <= len(frozen_donors) <= 3: raise ValueError("A1_TWO_TO_THREE_FROZEN_DONORS_REQUIRED")
    if len({d.key for d in frozen_donors}) != len(frozen_donors): raise ValueError("A1_DUPLICATE_DONOR")
    if len({d.identity_group or d.key for d in frozen_donors}) != len(frozen_donors): raise ValueError("A1_DONOR_IDENTITY_ALIAS")
    residuals, weights, eligible = [], [], []
    for donor in frozen_donors:
        distance = distance_km(target, donor)
        if (donor.country != target.country or donor.key == target.key or distance < 5 or distance > 150
                or (target.identity_group and target.identity_group == donor.identity_group)):
            raise ValueError("A1_TARGET_ALIAS_OR_UNREGISTERED_DONOR_GEOMETRY")
        observed_series, model_series = donor_observed[donor.key], baseline_at_donors[donor.key]
        for series in (observed_series, model_series):
            if series.attrs.get("reference_operator") != operator or series.attrs.get("unit") != "°C":
                raise ValueError("A1_MIXED_TIME_OPERATOR_OR_UNIT")
            if series.index.tz is None or series.index.has_duplicates: raise ValueError("A1_DONOR_SOURCE_CLOCK")
        mask_source = donor_qc_accepted[donor.key]
        if not pd.api.types.is_bool_dtype(mask_source.dtype): raise ValueError("A1_QC_MASK_REQUIRES_BOOL_NOT_NATIVE_QN_CODE")
        observed = observed_series.reindex(clock).to_numpy(dtype=float)
        model = model_series.reindex(clock).to_numpy(dtype=float)
        accepted = mask_source.reindex(clock).fillna(False).to_numpy(dtype=bool)
        valid = np.isfinite(observed) & np.isfinite(model) & accepted
        valid &= (observed >= -80) & (observed <= 65) & (model >= -80) & (model <= 65)
        residuals.append(np.where(valid, observed-model, 0.)); weights.append(distance**-2); eligible.append(valid)
    mask = np.column_stack(eligible); weighted = mask*np.asarray(weights)[None,:]
    divisor = weighted.sum(axis=1); counts = mask.sum(axis=1)
    normalized = np.divide(weighted, divisor[:,None], out=np.zeros_like(weighted), where=divisor[:,None] > 0)
    change = (np.column_stack(residuals)*normalized).sum(axis=1)
    baseline = baseline_at_target.to_numpy(dtype=float); proposal = baseline+change
    admitted = ((counts >= 2) & np.isfinite(baseline) & (baseline >= -80) & (baseline <= 65)
        & (proposal >= -70) & (proposal <= 70))
    output = pd.Series(np.where(admitted, proposal, np.nan), index=clock, name=T)
    output.attrs.update({"method": "A1_R1_THREE_NEAREST_IDW2_TEMPERATURE_RESIDUAL", "independent_accuracy_qualified": False,
        "EPW_export_or_default_promotion_allowed": False, "physical_full_weather_state_qualified": False,
        "target_observations_used": False, "source_support_admission_required_upstream": True})
    ledger = pd.DataFrame({"baseline_C": baseline, "proposed_delta_K": change, "accepted_donor_count": counts,
        "candidate_admitted": admitted, "candidate_C": output}, index=clock)
    for index, donor in enumerate(frozen_donors): ledger["weight__"+donor.key] = normalized[:,index]
    return output, ledger
