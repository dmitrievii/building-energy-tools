"""S1 retained disclosed examples: source and execution audit, not accuracy scoring."""
from hashlib import sha256
import csv
import io
import json
from pathlib import Path
import zipfile

import numpy as np

from epw_climate_analyzer.engine.point_interpolation import PointRequest
from epw_climate_analyzer.point_interpolation import run_point_product, replay_background

ROOT = Path(__file__).resolve().parents[2]


def compare_portable_epw(actual, reference, contract):
    """Existing EPW readback precision; source chronology and other fields exact.

    New solver results can differ at the last few floating-point digits across
    BLAS/CPU implementations. This does not relax weather bounds, source hashes
    or any climate constraint. The original output and its SHA remain frozen.
    """
    a = list(csv.reader(io.StringIO(actual.decode())))
    b = list(csv.reader(io.StringIO(reference.decode())))
    assert len(a) == len(b) and a[:8] == b[:8], "S1_REFERENCE_HEADERS_OR_RECORD_COUNT_CHANGED"
    columns = contract["thermal_columns"]
    diagnostics = {}
    for i, (row, old) in enumerate(zip(a[8:], b[8:])):
        assert len(row) == len(old) == 35, "S1_REFERENCE_RECORD_WIDTH_CHANGED"
        assert all(x == y for col, (x, y) in enumerate(zip(row, old)) if col not in columns), (
            "S1_REFERENCE_NONTHERMAL_OR_CALENDAR_CHANGED", i)
    for col in columns:
        values = np.array([float(row[col]) for row in a[8:]])
        old = np.array([float(row[col]) for row in b[8:]])
        error = np.abs(values-old)
        tolerance = np.maximum(contract["absolute_tolerance_floor"], contract["relative_tolerance"]*np.abs(old))
        bad = ~np.isfinite(values) | ~np.isfinite(old) | (error > tolerance)
        first = int(np.flatnonzero(bad)[0]) if bad.any() else None
        assert not bad.any(), {"S1_REFERENCE_NUMERIC_CHANGE_BEYOND_EXISTING_EPW_READBACK_PRECISION": col,
            "first_bad_row": first, "actual": float(values[first]), "reference": float(old[first]),
            "tolerance": float(tolerance[first]), "max_error": float(np.max(error))}
        diagnostics[str(col)] = {"changed_numeric_hours": int((values != old).sum()),
                                "max_abs_difference": float(error.max())}
    return {"comparison": "PASS_EXISTING_EPW_READBACK_PRECISION", "thermal_columns": diagnostics,
            "headers_calendar_and_nonthermal_cells_exact": True,
            "bitwise_same_output": actual == reference}


def replay_s1_examples(output=None):
    research = ROOT/"research/ige_cmip6"
    contract = json.loads((research/"s1_retained_integration_contract_20261028.json").read_bytes())
    positive, negative = contract["positive"], contract["negative"]
    portability = json.loads((research/"s1_output_numeric_portability_contract_20261028.json").read_bytes())
    assert sha256((research/"s1_retained_integration_contract_20261028.json").read_bytes()).hexdigest() == portability["original_integration_contract_sha256"]
    reference_zip = (research/portability["reference_archive"]).read_bytes()
    assert sha256(reference_zip).hexdigest() == portability["reference_archive_sha256"]
    with zipfile.ZipFile(io.BytesIO(reference_zip)) as reference_archive:
        reference_epw = reference_archive.read("climate.epw")
    assert sha256(reference_epw).hexdigest() == portability["reference_EPW_sha256"] == positive["expected_epw_sha256"]
    p_raw = (research/positive["input_file"]).read_bytes()
    background = (research/positive["background_file"]).read_bytes()
    p = run_point_product(PointRequest(**positive["request"]), input_packet=p_raw,
        expected_sha256=positive["input_sha256"], include_background=True,
        background_packet=background, background_sha256=positive["background_sha256"])
    assert p.report["status"] == positive["expected_status"]
    assert p.report["EPW_status"] == positive["expected_epw_status"], p.report["EPW_blockers"]
    assert p.report["EPW_sha256"] == sha256(p.files["climate.epw"]).hexdigest()
    numeric_comparison = compare_portable_epw(p.files["climate.epw"], reference_epw, portability)
    assert p.report["hours"] == positive["expected_hours"]
    assert p.report["selected_donors"] == positive["expected_selected_donors"]
    # Reconstruct each uploaded donor EPW from its original HTTP bodies. The
    # fixtures contain derived grid climate, never claimed station observations.
    lineage_raw = (research/positive["donor_lineage_file"]).read_bytes()
    assert sha256(lineage_raw).hexdigest() == positive["donor_lineage_sha256"]
    donor_hashes = []
    with zipfile.ZipFile(io.BytesIO(lineage_raw)) as lineage, zipfile.ZipFile(io.BytesIO(p_raw)) as inputs:
        for i in range(4):
            packet = lineage.read(f"donor_{i}.sources.zip")
            with zipfile.ZipFile(io.BytesIO(packet)) as source:
                original_request = json.loads(source.read("manifest.json"))["request"]
            request = PointRequest(original_request["latitude"], original_request["longitude"], 400.,
                "REPLAY ONLY: background height is not corrected here", original_request["year"], original_request["utc_offset_minutes"])
            original = replay_background(request, packet, sha256(packet).hexdigest())
            assert original.files["climate.epw"] == inputs.read(f"donor_{i:02d}.epw")
            donor_hashes.append(sha256(original.files["climate.epw"]).hexdigest())
    n_raw = (research/negative["input_file"]).read_bytes()
    n = run_point_product(PointRequest(**negative["request"]), input_packet=n_raw, expected_sha256=negative["input_sha256"])
    assert n.report["status"] == negative["expected_status"]
    assert len(n.report["donor_admission"]) == negative["expected_candidate_count"]
    assert sum(d["eligible"] for d in n.report["donor_admission"]) == negative["expected_eligible_count"]
    assert [d["station_id"] for d in n.report["donor_admission"] if d["eligible"]] == negative["expected_eligible_ids"]
    assert "climate.epw" not in n.files
    assert len(n.report["donor_source_reports"]) == negative["expected_candidate_count"]
    summary = {"status": "PASS", "positive_source_kind": positive["source_kind"],
        "positive_hours": p.report["hours"], "positive_EPW_sha256": p.report["EPW_sha256"],
        "reference_original_EPW_sha256": positive["expected_epw_sha256"],
        "positive_numeric_comparison": numeric_comparison,
        "four_input_EPWs_reconstructed_from_original_HTTP_bytes": donor_hashes,
        "negative_station_candidates": len(n.report["donor_admission"]),
        "negative_station_eligible": sum(d["eligible"] for d in n.report["donor_admission"]),
        "negative_EPW_absence_correctly_enforced": True, "new_independent_accuracy_validation": False}
    if output is not None:
        output = Path(output)
        (output/"s1-grid-epw-positive.zip").write_bytes(p.archive)
        (output/"s1-geosphere-negative.zip").write_bytes(n.archive)
        (output/"s1-replay-audit.json").write_text(json.dumps(summary, indent=2)+"\n")
    return summary
