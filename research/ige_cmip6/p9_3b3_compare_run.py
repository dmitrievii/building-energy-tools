"""First implementation increment: P1 metadata gates and C1 source census.

No station error fitting, statistical corrections, EPW, or independent holdout.
The original B3 remains an immutable control. Outputs contain aggregates and
fingerprints rather than original hourly source observations.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from p9_3b3_compare_identified_set import MeanInterval, PressureBox, identified_bounds
from p9_3b3_compare_operators import DiscreteOperator
from p9_3b3_compare_vertical_frame import fingerprint


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = Path(__file__).with_name("p9_3b3_compare_protocol.json")


def load_protocol(path=DEFAULT_PROTOCOL):
    protocol = json.loads(Path(path).read_text())
    expected = {"phase": "P9.3B3_P1_C1_FOUNDATION_20261021",
                "countries": ["AT", "DE", "CH"], "years": [2013, 2014],
                "source_values_immutable": True, "merge_main": False,
                "new_independent_holdout": False, "pressure_B4_qualified": False}
    if any(protocol.get(k) != v for k, v in expected.items()):
        raise ValueError("P93COMPARE_FROZEN_SCOPE_DRIFT")
    if protocol["pressure_scenarios"] != [
        {"name": "FIXED_REGISTERED_DONOR_REFERENCE", "half_width_Pa": 0,
         "interpretation": "FIXED_CONDITIONAL_REFERENCE"},
        {"name": "RECTANGULAR_PM500_PA_STRESS_NOT_CI", "half_width_Pa": 500,
         "interpretation": "SENSITIVITY_BOX_NOT_CI"}]:
        raise ValueError("P93COMPARE_PRESSURE_SCENARIO_DRIFT")
    if protocol["source_phase"] != "WATER_ICE" or protocol["temperature_operator"] != "DERIVED_TAS_MIDRANGE":
        raise ValueError("P93COMPARE_SOURCE_OPERATOR_DRIFT")
    return protocol


def control_integrity(protocol):
    results = []
    for relative, expected in protocol["protected_control_sha256"].items():
        actual = hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("P93COMPARE_FROZEN_CONTROL_CHANGED_"+relative)
        results.append({"path": relative, "sha256": actual, "status": "UNCHANGED"})
    return results


def metadata_audit(protocol):
    """Availability-only audit. Ground metadata cannot fabricate sensor heights."""
    rows = []
    for station in protocol["station_metadata"]:
        bar, thermo = station.get("barometer_coordinate"), station.get("thermo_coordinate")
        missing = []
        for name, value, role in (("barometer", bar, "BAROMETER"),
                                  ("thermo", thermo, "THERMO_SENSOR")):
            if value is None:
                missing.append(name+"_height_not_source_verified")
            elif value.get("role") != role or value.get("verified") is not True:
                missing.append(name+"_reference_unqualified")
        rows.append({"country": station["country"], "station": station["station"],
            "known_ground_height_m": station["ground_height_m"],
            "ground_height_is_not_barometer_height": True,
            "P1_sensor_reference_status": "SOURCE_BLOCKED" if missing else "METADATA_AVAILABLE_PROFILE_STILL_PROVISIONAL",
            "blockers": missing, "evidence": station["evidence"],
            "independent_accuracy": "NOT_TESTED", "pressure_model_qualified": False})
    op_common = {"weights": (1/24,)*24, "spatial_support": "NEX_GRID_POINT_SOURCE_SUPPORT_UNQUALIFIED",
                 "evidence": "REGISTERED_B3_SOURCE_AUDIT",
                 "hypothesis": "UTC_DAY_EQUAL_DISCRETE_NODES_NOT_VERIFIED_NATIVE_INTERVAL"}
    ops = [DiscreteOperator("tas", "MIDRANGE", unit="K", independent_observation=False, **op_common),
           DiscreteOperator("huss", "MEAN", unit="kg/kg", **op_common),
           DiscreteOperator("hurs", "MEAN", unit="%", phase="WATER_ICE", **op_common)]
    return {"stations": rows, "operators": [op.metadata() for op in ops],
            "NASA_native_averaging_intervals": "NOT_FULLY_IDENTIFIED_NO_NEW_BOUNDS_EVIDENCE",
            "station_RH_phase": "NOT_PROVIDER_CERTIFIED_ALL_THREE_SITES",
            "new_station_validation_performed": False}


def compare_repair_record(census_day, baseline_day):
    """A relaxed outer bound must never reject a prior exact witness's domain."""
    nominal = census_day["scenarios"][0]
    status = baseline_day["status"]
    if status == "EXACT_DEFINED_OPERATORS":
        if nominal["status"] == "ALL_DONORS_CERTIFIED_INFEASIBLE":
            raise AssertionError("P93COMPARE_FALSE_REJECTION_OF_PRIOR_EXACT_"+census_day["date"])
        return "PRIOR_EXACT_DOMAIN_NOT_EXCLUDED_NO_NEW_WITNESS_CLAIM"
    if status == "CERTIFIED_INFEASIBLE":
        if nominal["status"] != "ALL_DONORS_CERTIFIED_INFEASIBLE":
            raise AssertionError("P93COMPARE_REGISTERED_CERTIFICATE_NOT_REPRODUCED_"+census_day["date"])
        return "PRIOR_CONDITIONAL_CERTIFICATE_REPRODUCED"
    raise ValueError("P93COMPARE_UNEXPECTED_REPAIR_BASELINE_STATUS")


def _day_census(target, donors, wet, scenarios):
    eligible = sorted((d for d in donors if d.date[5:7] == target.date[5:7] and d.wet == wet),
                      key=lambda d: d.date)
    row = {"date": target.date, "eligible_donors": len(eligible),
           "source_q_mean_kgkg": target.q_mean_kgkg, "source_RH_mean_pp": target.RH_mean_pct,
           "scenarios": []}
    Q = MeanInterval(target.q_mean_kgkg, target.q_mean_kgkg, "kg/kg", "REGISTERED_NASA_CSV")
    R = MeanInterval(target.RH_mean_pct, target.RH_mean_pct, "%", "REGISTERED_NASA_CSV")
    for scenario in scenarios:
        records = []
        for donor in eligible:
            n = len(donor.pressure.values_Pa)
            p = np.asarray(donor.pressure.values_Pa)
            delta = scenario["half_width_Pa"]
            box = PressureBox(tuple(p-delta), tuple(p+delta), donor.pressure.frame,
                donor.pressure.fingerprint, scenario["interpretation"])
            b = identified_bounds(np.full(n, target.Tmin_K), np.full(n, target.Tmax_K), box,
                Q, R, np.full(n, 1/n), np.full(n, 1/n), phase=target.semantics.rh_phase)
            keys = ("status", "reason", "input_fingerprint", "RH_mean_lower_pp",
                    "RH_mean_upper_pp", "q_mean_capacity_upper", "separation_RH_pp")
            records.append({"donor_date": donor.date, **{k:b[k] for k in keys if k in b}})
        counts = dict(Counter(x["status"] for x in records))
        all_certified = bool(records) and counts.get("CERTIFIED_INFEASIBLE", 0) == len(records)
        lower = [x["RH_mean_lower_pp"] for x in records if "RH_mean_lower_pp" in x]
        upper = [x["RH_mean_upper_pp"] for x in records if "RH_mean_upper_pp" in x]
        info = {"name": scenario["name"], "interpretation": scenario["interpretation"],
            "status": ("SOURCE_BLOCKED_NO_ELIGIBLE_DONOR" if not records else
                       "ALL_DONORS_CERTIFIED_INFEASIBLE" if all_certified else "SOME_DONOR_DOMAINS_NOT_EXCLUDED"),
            "donor_status_counts": counts,
            "RH_outer_union_lower_pp": min(lower) if lower else None,
            "RH_outer_union_upper_pp": max(upper) if upper else None,
            "all_donor_evidence_sha256": fingerprint(records),
            "source_feasibility_established": False,
            "external_pressure_uncertainty_established": False,
            "continuous_pressure_box_covered": True,
            "continuous_time_trajectory_certified": False}
        if all_certified:
            info["certificates"] = records
        row["scenarios"].append(info)
    return row


def source_census(original_zip, baseline_path, protocol, output):
    from p9_3b3_regression_audit import native_targets, read_registered
    from p9_3b3_source_semantics import SourceSemantics
    from p9_3b3_generator import from_legacy_day
    from p9_2d_original_canesm5_2013_annual_source_epw_pilot import original_era5_year
    from p9_3a_original_canesm5_2014_year_pressure_temperature_q import EXPECTED_ERA5_CANONICAL_SHA

    raw_baseline = Path(baseline_path).read_bytes()
    if hashlib.sha256(raw_baseline).hexdigest() != protocol["baseline_repair_json_sha256"]:
        raise ValueError("P93COMPARE_IMMUTABLE_REPAIR_ARTIFACT_SHA_MISMATCH")
    baseline = json.loads(raw_baseline)
    rows, source = read_registered(original_zip)
    donors, provenance = [], []
    for year in (2019, 2020):
        old, meta = original_era5_year(year)
        if meta["canonical_source_weather_sha256"] != EXPECTED_ERA5_CANONICAL_SHA[year]:
            raise ValueError("P93COMPARE_ORIGINAL_DONOR_WEATHER_DRIFT")
        donors.extend(from_legacy_day(d) for d in old)
        provenance.append(meta)
    output.update(source=source, donor_provenance=provenance, years=[])
    start = time.monotonic()
    comparison_counts = Counter()
    for year in protocol["years"]:
        targets, wet = native_targets(rows, year, SourceSemantics("DERIVED_TAS_MIDRANGE", "WATER_ICE"))
        members = [m for m in baseline["members"] if m["year"] == year and m["variant"] == "L3_JOINT_SOURCE_PHASE"]
        if len(members) != 1:
            raise ValueError("P93COMPARE_REPAIR_BASELINE_YEAR_NOT_UNIQUE")
        prior = {d["date"]:d for d in members[0]["days"]}
        if len(prior) != len(targets) or set(prior) != {t.date for t in targets}:
            raise ValueError("P93COMPARE_BASELINE_CALENDAR_MISMATCH")
        days = []
        for target in targets:
            row = _day_census(target, donors, wet[target.date], protocol["pressure_scenarios"])
            row["repair_comparison"] = compare_repair_record(row, prior[target.date])
            comparison_counts[row["repair_comparison"]] += 1
            days.append(row)
        counts = {s["name"]: dict(Counter(d["scenarios"][i]["status"] for d in days))
                  for i, s in enumerate(protocol["pressure_scenarios"])}
        output["years"].append({"year": year, "including_boundary_records": len(days),
                                "counts": counts, "days": days})
        print("P93COMPARE_C1_YEAR", json.dumps({"year":year, "counts":counts}), flush=True)
    output.update(elapsed_source_census_seconds=time.monotonic()-start,
                  repair_comparison_counts=dict(comparison_counts),
                  original_727_states_rerun=False,
                  interpretation="DOMAIN_CONSISTENCY_WITH_IMMUTABLE_WITNESS_RECORDS_NOT_A_NEW_SOLVER_RUN")
    expected = {"PRIOR_EXACT_DOMAIN_NOT_EXCLUDED_NO_NEW_WITNESS_CLAIM": 727,
                "PRIOR_CONDITIONAL_CERTIFICATE_REPRODUCED": 5}
    if dict(comparison_counts) != expected:
        raise AssertionError("P93COMPARE_727_PLUS_5_ACCOUNTING_DRIFT")
    return output


def run(out, protocol_path=DEFAULT_PROTOCOL, original_zip=None, baseline_path=None):
    protocol = load_protocol(protocol_path)
    controls = control_integrity(protocol)
    if (original_zip is None) != (baseline_path is None):
        raise ValueError("P93COMPARE_BOTH_ORIGINAL_AND_IMMUTABLE_BASELINE_REQUIRED")
    out = Path(out)
    # Never overwrite an older artifact or turn a new run into an old result.
    out.mkdir(parents=True, exist_ok=False)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit = "UNAVAILABLE"
        dirty = None
    implementation = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(Path(__file__).parent.glob("*p9_3b3_compare_*.py"))}
    report = {"phase": protocol["phase"], "protocol_sha256": fingerprint(protocol),
        "algorithm_commit": commit, "working_tree_dirty": dirty,
        "implementation_file_sha256": implementation,
        "implementation_manifest_sha256": fingerprint(implementation), "controls": controls,
        "metadata_audit": metadata_audit(protocol),
        "implementation_scope": ["P1_TYPED_SENSOR_HYDROSTATICS", "C1_DISCRETE_INTERVAL_OUTER_BOUNDS"],
        "not_implemented_in_this_increment": ["C2", "P2", "P3", "C3", "J1"],
        "claim_status": {"code_correctness": "SEE_SEPARATE_TEST_LOG",
                         "physical_admissibility": "CONDITIONAL_ON_DECLARED_DISCRETE_MODEL",
                         "independent_accuracy": "NOT_TESTED", "operational_ready": False},
        "pressure_model_qualified": False, "production_epw_ready": False,
        "B4_independent_negative_result_retained": True,
        "source_values_modified": False, "independent_holdout_opened": False}
    if original_zip is not None:
        try:
            source_census(original_zip, baseline_path, protocol, report)
            report["source_census_status"] = "COMPLETED_CONDITIONAL_BOUNDS_NOT_INDEPENDENT_VALIDATION"
        except Exception as error:
            report["source_census_status"] = ("SOURCE_BLOCKED_EXTERNAL_READ" if
                isinstance(error, (OSError, TimeoutError)) else "CONTRACT_OR_NUMERICAL_FAILURE")
            report["error"] = {"type": type(error).__name__, "message": str(error)}
            (out/"p1_c1_comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
            raise
    else:
        report["source_census_status"] = "NOT_RUN_METADATA_AUDIT_ONLY"
    (out/"p1_c1_comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--out", required=True)
    parser.add_argument("--original-canesm5-registered-zip")
    parser.add_argument("--immutable-repair-audit")
    args = parser.parse_args()
    run(args.out, args.protocol, args.original_canesm5_registered_zip, args.immutable_repair_audit)
