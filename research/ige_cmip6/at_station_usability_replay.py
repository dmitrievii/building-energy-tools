"""Replay disclosed real-station development cases; no target-truth scoring."""
from hashlib import sha256
import json
from pathlib import Path

from epw_climate_analyzer.engine.point_interpolation import PointRequest
from epw_climate_analyzer.point_interpolation import run_point_product
from s1_replay_audit import compare_portable_epw

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "research/ige_cmip6/at_station_usability_20261102.json"


def replay_at_station_pilot(output=None):
    """Rebuild from original station and background HTTP bytes, entirely offline."""
    contract = json.loads(CONTRACT.read_bytes())
    research = CONTRACT.parent
    def read_source(key):
        entry = contract[key]
        raw = (research / entry["file"]).read_bytes()
        assert sha256(raw).hexdigest() == entry["sha256"], key
        return raw
    inputs, background, reference = (read_source(key) for key in ("inputs", "background", "reference"))
    point = run_point_product(PointRequest(**contract["request"]), input_packet=inputs,
        expected_sha256=contract["inputs"]["sha256"], include_background=True,
        background_packet=background, background_sha256=contract["background"]["sha256"])
    report = point.report
    assert report["status"] == "POINT_YEAR_COMPLETE_RESEARCH"
    assert report["EPW_status"] == "ADMITTED_MIXED_SOURCE_RESEARCH"
    assert report["hours"] == contract["hours"] == 8760
    assert report["selected_donors"] == contract["selected_donors"]
    assert report["source_mode"] == "GEOSPHERE"
    assert len([row for row in report["donor_admission"] if row["selected"]]) == 4
    assert all(row["source_kind"] == "GEOSPHERE_H1_ENDPOINTS_BUCK_RH_ASSUMPTION"
               for row in report["donor_admission"])
    assert all(row["fields"][key]["usable_for_epw_hours"] == 8760
               for row in report["station_core_coverage"] if row["selected"]
               for key in ("dry_bulb_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa"))
    reference_epw = reference
    assert sha256(reference_epw).hexdigest() == contract["output_EPW_sha256"]
    portability = json.loads((research / "s1_output_numeric_portability_contract_20261028.json").read_bytes())
    comparison = compare_portable_epw(point.files["climate.epw"], reference_epw, portability)
    assert not report["engine_gap_fill"]
    assert not report["new_fit_or_tuning"]
    assert not report["quality"]["production_ready"]
    negative = contract["negative_2025"]
    raw = (research / negative["file"]).read_bytes()
    assert sha256(raw).hexdigest() == negative["sha256"]
    blocked = run_point_product(PointRequest(**negative["request"]), input_packet=raw,
        expected_sha256=negative["sha256"])
    assert blocked.report["status"] == "POINT_YEAR_BLOCKED"
    assert len(blocked.report["donor_admission"]) == 20
    assert sum(row["eligible"] for row in blocked.report["donor_admission"]) == 0
    assert "climate.epw" not in blocked.files
    summary = {"schema": "IGE_AT_REAL_STATION_DEVELOPMENT_REPLAY_v1", "status": "PASS",
        "hours": report["hours"], "checked_stations": len(report["donor_admission"]),
        "selected_donors": report["selected_donors"], "real_station_core_sources": True,
        "point_EPW_sha256": sha256(point.files["climate.epw"]).hexdigest(),
        "reference_EPW_sha256": contract["output_EPW_sha256"], "comparison": comparison,
        "station_core_coverage": report["station_core_coverage"],
        "quality": report["quality"], "offline_replay": True,
        "negative_2025": {"checked_stations": 20, "eligible_stations": 0,
                          "EPW_absence_correctly_enforced": True},
        "new_independent_accuracy_validation": False, "engine_gap_fill": False,
        "future_climate_or_multiyear_reference_qualified": False}
    if output is not None:
        output = Path(output); output.mkdir(parents=True, exist_ok=True)
        year = contract["request"]["year"]
        (output / f"at-station-point-{year}.zip").write_bytes(point.archive)
        (output / f"at-station-point-{year}-replay.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = replay_at_station_pilot(args.out)
    print(json.dumps({key: value for key, value in result.items() if key != "station_core_coverage"},indent=2))
