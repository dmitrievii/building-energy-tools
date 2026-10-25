"""Bind a decoded temperature series to dated, metadata-only A1.2 evidence.

No humidity/pressure height is certified by a temperature admission. Source
geometry, strict 2-m compatibility and temporal support are separate checks.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math

import pandas as pd

from .station_reconstruction import StationBatch, StationReference, T

ADMITTED_OPERATORS = {"published_nominal_node", "mean_six_10min_nominal_nodes"}
FIELDS = {"AT": "tl", "DE": "TT_TU", "CH": "tre200h0"}


def physical_identity(country: str, station_id: str, *, group_id=None, wsi=None) -> str:
    """A missing group is not evidence that unrelated stations are aliases."""
    if country == "AT":
        if group_id is None or str(group_id).strip().lower() in ("", "none", "null"):
            return "AT_STATION:" + station_id
        return "AT_GROUP:" + str(group_id)
    if country == "CH" and wsi:
        return "CH_WIGOS:" + wsi
    if country in ("DE", "CH"):
        return country + "_STATION:" + station_id
    raise ValueError("A12_AT_DE_CH_IDENTITY_REQUIRED")


def admitted_reference(record: dict) -> StationReference:
    if not record.get("temperature_source_eligible"):
        raise ValueError("A12_TEMPERATURE_SOURCE_BLOCKED:" + ";".join(record.get("source_block_reasons", [])))
    g = record["geometry"]
    if (record.get("geometry_status") != "DATED_TEMPERATURE_SENSOR_CONFIRMED"
            or not record.get("strict_2m_compatible") or g.get("AGL_m") != 2.
            or g.get("local_reference_surface") not in ("localGround", "naturalGround")):
        raise ValueError("A12_ACTUAL_DATED_2M_GEOMETRY_REQUIRED")
    if record["time_contract"]["operator"] not in ADMITTED_OPERATORS:
        raise ValueError("A12_UNKNOWN_OPERATOR")
    # The evidence hashes travel with the series. They do not certify that the
    # model resolves a sensor filter, subhourly path or vertical datum.
    evidence = record["source_evidence_sha256"]
    if not evidence or any(len(s) != 64 or any(c not in "0123456789abcdef" for c in s) for s in evidence.values()):
        raise ValueError("A12_METADATA_EVIDENCE_HASH_REQUIRED")
    for name in ("latitude", "longitude", "geospatial_z_as_reported_m"):
        if not math.isfinite(g[name]): raise ValueError("A12_GEOMETRY_NONFINITE")
    nominal = record["frozen_station"]
    reference = StationReference(**{k: nominal[k] for k in StationReference.__dataclass_fields__})
    return replace(reference, latitude=g["latitude"], longitude=g["longitude"],
        identity_group=record["resolved_identity_group"], historical_geometry_verified=True)


@dataclass(frozen=True)
class AdmittedTemperature:
    station: StationReference
    values: pd.Series
    quality_accepted: pd.Series
    admission_sha256: str


def admit_temperature(batch: StationBatch, record: dict) -> AdmittedTemperature:
    """Copy only T and its native primary-QC mask; never change raw batches."""
    station = admitted_reference(record)
    if batch.station.key != record["station_key"] or station.key != batch.station.key:
        raise ValueError("A12_CROSS_STATION_ADMISSION")
    field = batch.fields[T]
    if (field["unit"] != "°C" or field["provider_field"] != FIELDS[station.country]
            or field["time_operator"] != record["time_contract"]["operator"]):
        raise ValueError("A12_TEMPERATURE_DEFINITION_MISMATCH")
    first, last = (pd.Timestamp(record[k]) for k in ("reference_first_UTC", "reference_last_UTC"))
    index = batch.data.index
    if first.tz is None or last.tz is None or first > last or len(index) == 0 or not ((index >= first) & (index <= last)).all():
        raise ValueError("A12_SERIES_OUTSIDE_DATED_ADMISSION_WINDOW")
    mask = batch.data["quality_accepted__" + T]
    if not pd.api.types.is_bool_dtype(mask.dtype): raise ValueError("A12_NATIVE_QC_NOT_BOOLEAN_MASK")
    receipt = sha256(json.dumps(record, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    values = batch.data[T].copy(deep=True)
    values.attrs.update({"reference_operator": field["time_operator"], "unit": "°C",
        "source_sha256": batch.source_sha256, "source_evidence_sha256": dict(record["source_evidence_sha256"]),
        "admission_sha256": receipt, "sensor_AGL_m": record["geometry"]["AGL_m"],
        "temperature_height_history_verified": True, "RH_or_pressure_height_certified": False,
        "true_sensor_filter_or_subhourly_model_path_known": False, "independent_accuracy_qualified": False})
    return AdmittedTemperature(station, values, mask.copy(deep=True), receipt)
