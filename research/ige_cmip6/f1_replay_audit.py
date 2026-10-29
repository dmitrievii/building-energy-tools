"""Offline replay of the retained F1 integration example; no accuracy claim."""
from hashlib import sha256
import csv
import io
import json
from pathlib import Path
import zipfile

from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
from epw_climate_analyzer.engine.f1_sources import SignalRequest
from epw_climate_analyzer.engine.epw import EPW_FIELDS
from epw_climate_analyzer.future_selected import base_from_engine, run_selected_future

ROOT = Path(__file__).resolve().parent


def compare_output(actual, expected):
    a = list(csv.reader(io.StringIO(actual.decode())))
    b = list(csv.reader(io.StringIO(expected.decode())))
    if len(a) != len(b) or a[:8] != b[:8]: raise AssertionError("F1_REFERENCE_EPW_HEADERS_OR_CENSUS_CHANGED")
    numeric = {col for col, _, _ in EPW_FIELDS.values()}
    maximum = 0.
    for row, ref in zip(a[8:], b[8:]):
        if len(row) != 35 or len(ref) != 35: raise AssertionError("F1_REFERENCE_EPW_WIDTH")
        for i,(value,original) in enumerate(zip(row,ref)):
            if i in numeric:
                error = abs(float(value)-float(original)); maximum = max(maximum,error)
                if error > max(1e-7, 1e-9*abs(float(original))): raise AssertionError("F1_REFERENCE_NUMERIC_VALUE_CHANGED")
            elif value != original: raise AssertionError("F1_REFERENCE_NONWEATHER_CELL_CHANGED")
    return {"bitwise_same_EPW": actual == expected, "maximum_absolute_numeric_difference_mixed_units": maximum,
        "comparison": "PASS_EXISTING_EPW_READBACK_PRECISION_1E_7_OR_1E_9_RELATIVE"}


def replay_f1_example(output=None):
    c = json.loads((ROOT/"f1_selected_base_replay_contract_20261029.json").read_bytes())
    packet = (ROOT/c["NASA_packet"]).read_bytes()
    values = c["signal_request"]
    request = SignalRequest(**{**values, "reference_window": tuple(values["reference_window"]), "future_window": tuple(values["future_window"])})
    historical = run_historical_product(pilot_historical_request())
    base = base_from_engine(historical)
    if base.sha256 != c["selected_base_EPW_sha256"]: raise AssertionError("F1_SELECTED_BASE_CHANGED")
    product = run_selected_future(base, request, reference_mode="BACKGROUND_REFERENCE",
        nex_packet=packet, nex_packet_sha256=c["NASA_packet_sha256"],
        retained_sources={"selected_base.sources.zip": historical.files["sources.zip"]})
    reference = (ROOT/c["output_reference"]).read_bytes()
    if sha256(reference).hexdigest() != c["output_reference_sha256"]: raise AssertionError("F1_FROZEN_REFERENCE_BYTES_CHANGED")
    with zipfile.ZipFile(io.BytesIO(reference)) as z: original = z.read("climate.epw")
    comparison = compare_output(product.files["climate.epw"], original)
    audit = {"status": "PASS", "hours": len(product.dataset.data), "source_packet_sha256": c["NASA_packet_sha256"],
        "output_EPW_sha256_this_execution": sha256(product.files["climate.epw"]).hexdigest(),
        "original_output_EPW_sha256": c["original_output_EPW_sha256"], "output_comparison": comparison,
        "NASA_grid": product.report["source_geometry"]["NASA_grid"],
        "selected_base_geometry": product.report["source_geometry"]["selected_base"],
        "quality": product.report["quality"], "new_independent_accuracy_validation": False,
        "production_ready": False}
    if output is not None:
        output = Path(output); output.mkdir(parents=True,exist_ok=True)
        (output/"f1-selected-base-future.zip").write_bytes(product.archive)
        (output/"f1-replay-audit.json").write_text(json.dumps(audit,indent=2)+"\n")
    return product,audit


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--out",type=Path)
    _, report = replay_f1_example(p.parse_args().out);print(json.dumps(report,indent=2))
