"""Small live-source health probe; not an independent climate validation.

Keeps original catalogue, point-subset and station-metadata responses in a new
directory. No full annual climate is built and no station weather is fetched.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools/climate_analyzer"))
from epw_climate_analyzer import geosphere as geo
from epw_climate_analyzer.geosphere_station_year import RESOURCE
from epw_climate_analyzer.engine.f1_sources import (SignalRequest, catalog_url, catalog_path,
    subset_url, decode_point, download, matching_saved_nex_packet)
from epw_climate_analyzer.engine.model_sources import bounded_zip


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(); args.out.mkdir(parents=True, exist_ok=False)
    request = SignalRequest(47.0707, 15.4395)
    original = bounded_zip(matching_saved_nex_packet(request), member_limit=640)
    report = {"schema": "IGE_DONOR_RECOVERY_SOURCE_HEALTH_v1", "request": request.to_dict(),
              "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "independent_accuracy_qualified": False, "public_deployment_of_new_code_verified": False}
    def check(variable):
        start = time.monotonic(); s, year = "ssp245", 2040
        url = catalog_url(request, s, variable)
        catalog = download(url)
        (args.out/f"catalog_{s}_{variable}.xml").write_bytes(catalog)
        path = catalog_path(catalog, request, s, year, variable)
        point_url = subset_url(request, path, year, variable)
        body = download(point_url)
        name = f"{s}_{year}_{variable}.nc"; (args.out/name).write_bytes(body)
        values, months, proof = decode_point(body, variable, year, request)
        expected, _, _ = decode_point(original[name], variable, year, request)
        difference = float(np.max(np.abs(values-expected)))
        if difference != 0: raise ValueError(f"Live v2 source changed from retained values: {variable}: {difference}")
        return {"variable": variable, "catalog_url": url, "catalog_sha256": sha256(catalog).hexdigest(),
                "subset_url": point_url, "subset_sha256": sha256(body).hexdigest(),
                "daily_rows": len(values), "grid": proof["grid"], "unit": proof["unit"],
                "max_abs_change_from_original_values": difference, "seconds": time.monotonic()-start}
    with ThreadPoolExecutor(max_workers=3) as pool:
        report["NASA"] = list(pool.map(check, ("pr", "tas", "huss")))
    def capture(url, query, body):
        (args.out/"station_locations.original.json").write_bytes(body)
        report["station_metadata_source"] = {"url": url, "sha256": sha256(body).hexdigest(), "bytes": len(body)}
    metadata = geo.fetch_metadata(resource_id=RESOURCE, timeout_s=12, response_capture=capture)
    sites = geo.parse_stations(metadata)
    report["mapped_single_site_locations"] = sum(s.station_type != "COMBINED" for s in sites)
    if not report["mapped_single_site_locations"]: raise ValueError("No real station locations")
    report["status"] = "PASS"
    (args.out/"source-health.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
