"""H1: complete annual inventory and EPW admission, without weather gap filling.

Inputs are canonical values at explicit UTC source labels. The source adapter
owns unit conversion, definitions and QC evidence. This gate never infers an
instantaneous state from a mean, invents radiation or substitutes sea-level p.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta, timezone
import calendar
import csv
from hashlib import sha256
import io
import math
import re

import numpy as np
import pandas as pd

from ..climate_model import ClimateLocation
from .contracts import ClimateResult, FieldDefinition, QualityStatus
from .epw import EPW_BOUNDS, EPW_FIELDS, serialize_epw, validate_epw_bytes

SCHEMA = "IGE_H1_STATION_YEAR_ADMISSION_v1"
QC_POLICY = "H1_PER_FIELD_DECLARED_SOURCE_QC_v1"
ORIGINS = {"measured", "provider_derived", "derived", "modelled", "synthetic_test"}


@dataclass(frozen=True)
class StationYearRequest:
    station_id: str
    year: int
    utc_offset_minutes: int = 60
    label: str = "Station year"

    def __post_init__(self):
        if not isinstance(self.station_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,80}", self.station_id):
            raise ValueError("H1_STATION_ID_REQUIRED")
        if isinstance(self.year, bool) or not isinstance(self.year, int) or not 1800 <= self.year <= 2098:
            raise ValueError("H1_INVALID_YEAR")
        if (isinstance(self.utc_offset_minutes, bool) or not isinstance(self.utc_offset_minutes, int)
                or not -720 <= self.utc_offset_minutes <= 720 or self.utc_offset_minutes % 60):
            raise ValueError("H1_FIXED_WHOLE_HOUR_OFFSET_REQUIRED")
        if not self.label.strip() or len(self.label) > 120 or any(c in self.label for c in ",\n\r\x00"):
            raise ValueError("H1_INVALID_LABEL")

    @property
    def standard_timezone(self):
        return timezone(timedelta(minutes=self.utc_offset_minutes))

    @property
    def local_starts(self):
        return pd.date_range(f"{self.year}-01-01", f"{self.year+1}-01-01", inclusive="left",
                             freq="h", tz=self.standard_timezone, name="interval_start_local_standard")

    @property
    def utc_starts(self):
        return self.local_starts.tz_convert("UTC").rename("interval_start_utc")

    @property
    def utc_ends(self):
        return self.utc_starts + pd.Timedelta(hours=1)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class StationField:
    unit: str
    provider_field: str
    operator: str
    vertical_reference: str
    evidence_reference: str
    quality_column: str = ""
    origin: str = "measured"
    quantity_definition: str = ""
    definition_error: str = ""
    accepted_quality_codes: tuple[int, ...] = ()
    quality_policy_id: str = ""


@dataclass(frozen=True)
class StationYearAssessment:
    report: dict
    hourly: pd.DataFrame
    gaps: pd.DataFrame
    epw: bytes | None


def _ranges(mask, starts, reason, field):
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
    return [{"field": field, "reason": reason,
             "first_interval_start_utc": starts[int(g[0])].isoformat(),
             "last_interval_start_utc": starts[int(g[-1])].isoformat(),
             "hours": len(g)} for g in groups]


def _epw_operator(field, name):
    expected = EPW_FIELDS[name][2]
    if field.operator == "published_nominal_node" and expected == "instant_at_interval_end":
        # A published value at the labelled node, not an inverted hourly mean.
        return expected
    return field.operator


def assess_station_year(request: StationYearRequest, location: ClimateLocation,
                        source_end_frame: pd.DataFrame, fields: dict[str, StationField],
                        *, source_id: str, source_metadata: dict | None = None,
                        blockers: tuple[str, ...] = ()) -> StationYearAssessment:
    """Inventory every core field/hour before deciding whether export is allowed."""
    frame = source_end_frame.copy(deep=True)
    global_errors = list(blockers)
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or frame.index.hasnans:
        raise ValueError("H1_EXPLICIT_AWARE_SOURCE_CLOCK_REQUIRED")
    frame.index = frame.index.tz_convert("UTC")
    duplicate_mask = frame.index.duplicated(keep=False)
    duplicate_rows = int(duplicate_mask.sum())
    if duplicate_rows:
        global_errors.append("DUPLICATE_SOURCE_LABELS")
    extra_rows = int((~frame.index.isin(request.utc_ends)).sum())
    if extra_rows:
        global_errors.append("SOURCE_LABELS_OUTSIDE_ANNUAL_HOURLY_GRID")
    # Ambiguous duplicate values are never selected, averaged or silently filled.
    aligned = frame.loc[~duplicate_mask].reindex(request.utc_ends)
    aligned.index = request.utc_starts
    hourly = pd.DataFrame(index=request.utc_starts)
    rows, gap_rows = [], []
    for name, (_, unit, _) in EPW_FIELDS.items():
        definition = fields.get(name)
        present = definition is not None and name in aligned
        values = pd.to_numeric(aligned[name], errors="coerce").to_numpy(dtype=float) if present else np.full(len(aligned), np.nan)
        finite = np.isfinite(values)
        lo, hi = EPW_BOUNDS[name]
        in_bounds = finite & (values >= lo) & (values <= hi)
        metadata_errors = []
        if definition is None:
            metadata_errors.append("NO_DECLARED_FIELD_SOURCE")
        else:
            if definition.unit != unit: metadata_errors.append("UNIT_NOT_ADMITTED")
            if _epw_operator(definition, name) != EPW_FIELDS[name][2]:
                metadata_errors.append("TIME_OPERATOR_NOT_ADMITTED")
            if not definition.vertical_reference or not definition.evidence_reference:
                metadata_errors.append("SOURCE_EVIDENCE_OR_HEIGHT_REFERENCE_MISSING")
            if definition.origin not in ORIGINS: metadata_errors.append("UNDECLARED_ORIGIN")
            if definition.definition_error: metadata_errors.append(definition.definition_error)
            if name == "atmospheric_station_pressure_pa" and definition.quantity_definition != "absolute_station_pressure":
                metadata_errors.append("ABSOLUTE_STATION_PRESSURE_REQUIRED")
            if name == "liquid_precipitation_depth_mm" and definition.quantity_definition != "liquid_precipitation":
                metadata_errors.append("LIQUID_PHASE_NOT_ESTABLISHED")
        flags = np.full(len(aligned), np.nan)
        if definition and definition.quality_column and definition.quality_column in aligned:
            flags = pd.to_numeric(aligned[definition.quality_column], errors="coerce").to_numpy(dtype=float)
        qc_known = np.isfinite(flags)
        accepted_codes = definition.accepted_quality_codes if definition else ()
        qc_ok = qc_known & np.isin(flags, accepted_codes)
        qc_required = definition is None or definition.origin in ("measured", "provider_derived")
        if definition and qc_required and (not definition.quality_policy_id or not accepted_codes):
            metadata_errors.append("SOURCE_QC_POLICY_NOT_DECLARED")
        if not qc_required:
            qc_ok = np.ones(len(aligned), dtype=bool)
        usable = in_bounds & qc_ok & (not metadata_errors)
        hourly[name] = values  # Preserve supplied values, including rejected ones.
        counts = {format(float(code), ".15g"): int(np.sum(flags == code)) for code in np.unique(flags[qc_known])}
        row = {"field": name, "required": True, "unit": unit, "expected_hours": len(aligned),
               "numeric_hours": int(finite.sum()), "in_bounds_hours": int(in_bounds.sum()),
               "reviewed_in_bounds_hours": int((in_bounds & qc_ok).sum()),
               "usable_for_epw_hours": int(usable.sum()), "unusable_hours": int((~usable).sum()),
               "missing_value_hours": int((~finite).sum()),
               "out_of_bounds_hours": int((finite & ~in_bounds).sum()),
               "missing_qc_hours": int((finite & ~qc_known).sum()) if qc_required else 0,
               "rejected_qc_hours": int((finite & qc_known & ~qc_ok).sum()) if qc_required else 0,
               "quality_histogram": counts, "definition_errors": metadata_errors,
               "source": asdict(definition) if definition else None,
               "status": "ADMITTED" if usable.all() else "BLOCKED"}
        rows.append(row)
        reasons = {"MISSING_VALUE": ~finite, "OUT_OF_BOUNDS": finite & ~in_bounds}
        if qc_required:
            reasons.update({"MISSING_QC": finite & ~qc_known, "QC_NOT_REVIEWED": finite & qc_known & ~qc_ok})
        for error in metadata_errors: reasons[error] = np.ones(len(aligned), dtype=bool)
        for reason, mask in reasons.items():
            gap_rows.extend(_ranges(mask, request.utc_starts, reason, name))
    metadata = source_metadata or {}
    if location.elevation_m is None or not math.isfinite(location.elevation_m):
        global_errors.append("EPW_LOCATION_ELEVATION_UNAVAILABLE")
    if metadata.get("station_type") == "COMBINED":
        global_errors.append("COMBINED_SERIES_NOT_ADMITTED_AS_ONE_FIXED_SITE")
    result_epw, screen = None, None
    ready = not global_errors and all(row["status"] == "ADMITTED" for row in rows)
    if ready:
        definitions = {name: FieldDefinition(unit, _epw_operator(fields[name], name), source_id,
                         fields[name].vertical_reference,
                         f"{fields[name].origin}: {fields[name].provider_field}; source operator {fields[name].operator}; "
                         f"{fields[name].quantity_definition}; {fields[name].evidence_reference}")
                       for name, (_, unit, _) in EPW_FIELDS.items()}
        try:
            climate = ClimateResult(request, hourly, location, definitions,
                ({"id": source_id},), (), (),
                QualityStatus("H1_SOURCE_INVENTORY_COMPLETE", "PENDING_VALUE_SCREEN",
                              "NOT_INDEPENDENTLY_VALIDATED", "RESEARCH_STATION_YEAR"), {})
            result_epw, screen = serialize_epw(climate)
            records = list(csv.reader(io.StringIO(result_epw.decode("utf-8"))))
            records[0][1:6] = [request.label + " STATION YEAR RESEARCH", location.state,
                                  location.country, source_id + " station " + request.station_id, "999999"]
            records[5] = ["COMMENTS 1", "H1 station-source year; provider ID is not asserted to be a WMO ID. No engine gap fill or height correction; actual sensor datums and independent accuracy not qualified. See admission.json."]
            records[6] = ["COMMENTS 2", "Fixed standard time; source node states and preceding-hour energies/amounts; provider reviewed values may include provider corrections. No production qualification."]
            records[7][3] = f"HISTORICAL STATION YEAR {request.year} H1 RESEARCH"
            output = io.StringIO(newline=""); csv.writer(output, lineterminator="\n").writerows(records)
            result_epw = output.getvalue().encode("utf-8")
            screen.update(validate_epw_bytes(result_epw, climate))
        except ValueError as exc:
            result_epw = None
            global_errors.append("PHYSICAL_OR_FORMAT_SCREEN: " + str(exc))
    report = {"schema": SCHEMA, "request": request.to_dict(), "source_id": source_id,
              "location": asdict(location), "source_metadata": metadata,
              "status": "EPW_ADMITTED_RESEARCH" if result_epw else "EPW_BLOCKED",
              "expected_hours": len(request.utc_starts), "source_rows": len(frame),
              "duplicate_source_rows": duplicate_rows, "unexpected_source_rows": extra_rows,
              "source_first_utc": str(frame.index.min()) if len(frame) else None,
              "source_last_utc": str(frame.index.max()) if len(frame) else None,
              "calendar": {"fixed_utc_offset_minutes": request.utc_offset_minutes,
                           "first_interval_start_local": request.local_starts[0].isoformat(),
                           "last_interval_start_local": request.local_starts[-1].isoformat(),
                           "source_labels": "interval end / published nominal node", "leap_day_retained": calendar.isleap(request.year)},
              "fields": rows, "global_blockers": list(dict.fromkeys(global_errors)),
              "qc_policy": {"id": QC_POLICY,
                            "source_policies": {name: {"id": definition.quality_policy_id,
                                "accepted_codes": list(definition.accepted_quality_codes)}
                                for name, definition in fields.items() if definition.quality_policy_id},
                            "QC10_does_not_prove_original_unfilled_measurements": True,
                            "previous_V2_QC10_validation_policy_changed": False},
              "engine_missing_values_filled": 0, "engine_weather_values_corrected": 0,
              "gap_ledger_reason_ranges_can_overlap": True,
              "new_independent_validation": False, "production_ready": False,
              "quality": {"execution_correctness": "ANNUAL_INVENTORY_COMPLETED",
                          "physical_admissibility": "BOUNDS_AND_COMPONENT_SCREEN_PASS" if result_epw else "NO_COMPLETE_ADMITTED_EPW",
                          "independent_accuracy": "NOT_INDEPENDENTLY_VALIDATED",
                          "operational_and_application_scope": "RESEARCH_SOURCE_YEAR_NO_LOCAL_RECONSTRUCTION"},
              "weather_screen": screen,
              "EPW_sha256": sha256(result_epw).hexdigest() if result_epw else None,
              "optional_EPW_fields": "Existing engine missing sentinels; opaque cloud, photometry and other unmeasured optional fields are not invented."}
    gaps = pd.DataFrame(gap_rows, columns=["field", "reason", "first_interval_start_utc", "last_interval_start_utc", "hours"])
    return StationYearAssessment(report, hourly, gaps, result_epw)
