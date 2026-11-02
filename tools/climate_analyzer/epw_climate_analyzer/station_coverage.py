"""Explain H1 core-source availability without changing source admission.

Complete T/p/RH can supply S1 even when a station lacks other EPW fields.
Counts remain source/QC counts, not estimates of interpolation accuracy.
"""
from __future__ import annotations

CORE = {
    "dry_bulb_temperature_c": "T",
    "relative_humidity_pct": "RH",
    "atmospheric_station_pressure_pa": "p",
}
COUNTS = ("numeric_hours", "usable_for_epw_hours", "missing_value_hours",
          "out_of_bounds_hours", "missing_qc_hours", "rejected_qc_hours")


def coverage_messages(codes):
    """Readable UI explanations; stable machine reasons stay in the downloads."""
    patterns = {"NO_MEASUREMENTS": "No {} observations",
                "MISSING_OBSERVATIONS": "Missing {} observations",
                "OUT_OF_BOUNDS": "{} outside physical bounds",
                "MISSING_QC": "Missing {} quality flags",
                "REJECTED_QC": "{} quality flags rejected",
                "DEFINITION_NOT_ADMITTED": "Incompatible {} source definition"}
    fields = {"T": "temperature", "RH": "humidity", "p": "pressure"}
    global_messages = {"SOURCE_ACQUISITION_FAILED": "Source download incomplete",
                       "SOURCE_DEFINITION_CHANGED": "Source time definition changed",
                       "SOURCE_CLOCK_BLOCKED": "Source timestamps incompatible",
                       "PHYSICAL_OR_FORMAT_SCREEN_FAILED": "Physical or EPW checks failed",
                       "SOURCE_OR_STATION_ADMISSION_BLOCKED": "Station or source admission failed"}
    messages = []
    for code in codes:
        prefix, _, field = code.rpartition("_")
        if prefix in patterns and field in fields:
            message = patterns[prefix].format(fields[field])
            messages.append(message[0].upper() + message[1:])
        else:
            messages.append(global_messages.get(code, "Other source failure; see report"))
    return messages


def station_core_coverage(report):
    """Keep missing values, QC failures and definition failures distinct."""
    fields = {row["field"]: row for row in report["fields"]}
    result = {"station_id": report["request"]["station_id"],
              "station_name": report["location"]["city"],
              "year": report["request"]["year"],
              "expected_hours": report["expected_hours"],
              "station_only_EPW_admitted": report["status"] == "EPW_ADMITTED_RESEARCH",
              "core_sources_admitted": not report["global_blockers"],
              "fields": {}}
    reasons = []
    for name, label in CORE.items():
        row = fields[name]
        result[label + "_admitted_hours"] = row["usable_for_epw_hours"]
        result["fields"][name] = {key: row[key] for key in (*COUNTS, "definition_errors")}
        result["core_sources_admitted"] &= row["status"] == "ADMITTED"
        if row["missing_value_hours"] == report["expected_hours"]:
            reasons.append("NO_MEASUREMENTS_" + label)
        elif row["missing_value_hours"]:
            reasons.append("MISSING_OBSERVATIONS_" + label)
        if row["out_of_bounds_hours"]: reasons.append("OUT_OF_BOUNDS_" + label)
        if row["missing_qc_hours"]: reasons.append("MISSING_QC_" + label)
        if row["rejected_qc_hours"]: reasons.append("REJECTED_QC_" + label)
        if row["definition_errors"]: reasons.append("DEFINITION_NOT_ADMITTED_" + label)
    for error in report["global_blockers"]:
        if error.startswith("SOURCE_REQUEST_FAILED"):
            kind = "SOURCE_ACQUISITION_FAILED"
        elif "FREQUENCY" in error:
            kind = "SOURCE_DEFINITION_CHANGED"
        elif "LABELS" in error:
            kind = "SOURCE_CLOCK_BLOCKED"
        elif error.startswith("PHYSICAL_OR_FORMAT_SCREEN"):
            kind = "PHYSICAL_OR_FORMAT_SCREEN_FAILED"
        else:
            kind = "SOURCE_OR_STATION_ADMISSION_BLOCKED"
        if kind not in reasons: reasons.append(kind)
    result["blocker_types"] = reasons
    return result
