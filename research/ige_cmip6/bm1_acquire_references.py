"""Acquire original I1/A0 source pairs for the predeclared common reference.

New data only, gridded sources only, no stations/IV1 and no model fitting.
Retain every original annual pair and a SHA-pinned portable packet.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from epw_climate_analyzer.engine import HistoricalRequest
from epw_climate_analyzer.engine.historical import source_plan, fetch_original, make_source_bundle, assemble_historical, json_bytes


def acquire(year: int, out: Path) -> tuple[str, bytes, dict]:
    request = HistoricalRequest(47.0707, 15.4395, year, 60, label="Graz")
    raw, receipts = {}, []
    for key, spec in source_plan(request).items():
        print(f"BM1_REFERENCE_ACQUIRE {year} {key}", flush=True)
        payload, receipt = fetch_original(key, spec)
        raw[key] = payload; receipts.append(receipt)
    bundle = make_source_bundle(request, raw, receipts)
    path = out / f"Graz_{year}_original_sources.zip"
    with path.open("xb") as stream: stream.write(bundle)
    result = assemble_historical(request, raw, receipts)
    info = {"year": year, "sha256": hashlib.sha256(bundle).hexdigest(), "bytes": len(bundle),
        "records": len(result.data), "received_bytes": sum(r["bytes"] for r in receipts),
        "HTTP_attempts": sum(r["http_attempts"] for r in receipts), "sources": receipts}
    print(f"BM1_REFERENCE_COMPLETE {year} {info['records']}", flush=True)
    return path.name, bundle, info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    protocol_path = ROOT / "research/ige_cmip6/bm1_protocol_20261025.json"
    original_protocol = protocol_path.read_bytes()
    manifest = {"schema": "IGE_BM1_REFERENCE_SOURCE_PACKET_v1", "protocol_sha256": hashlib.sha256(original_protocol).hexdigest(),
        "reference_window": [2002, 2014], "members": {}, "independent_station_values_opened": False}
    successes = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(acquire, year, args.out) for year in range(2002, 2015)]
        for future in as_completed(futures):
            name, data, info = future.result(); manifest["members"][name] = info; successes.append((name, data))
            with (args.out / "acquisition_progress.json").open("w") as stream: json.dump(manifest, stream, indent=2)
    assert len(successes) == 13
    assert sum(x["received_bytes"] for x in manifest["members"].values()) <= 48 * 1024**2
    manifest["total_HTTP_attempts"] = sum(x["HTTP_attempts"] for x in manifest["members"].values())
    manifest["total_received_bytes"] = sum(x["received_bytes"] for x in manifest["members"].values())
    output = args.out / "bm1_reference_sources_2002_2014.zip"
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json_bytes(manifest))
        archive.writestr("registered_protocol.json", original_protocol)
        for name, raw in sorted(successes): archive.writestr(name, raw)
    print(json.dumps({"path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "bytes": output.stat().st_size, "received_bytes": manifest["total_received_bytes"], "HTTP_attempts": manifest["total_HTTP_attempts"]}, indent=2))


if __name__ == "__main__": main()
