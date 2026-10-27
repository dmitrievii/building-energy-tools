"""Acquire a bounded, fixed list of documentation/metadata; no weather URLs.

Run once for a new evidence snapshot. Offline audits use the saved originals.
This program has no station measurement query or control-acquisition mode.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

SOURCES = {
    "AT_quality_indicators.pdf": "https://public.hub.geosphere.at/public/resources/misc/klima/DataHub-DE-Qualitaetsindikatoren.pdf",
    "AT_quality_indicators_legacy_path.pdf": "https://public.hub.geosphere.at/public/resources/misc/Qualitaetsindikatoren_in_den_Stationsdatensaetzen_der_GeoSphere_Austria.pdf",
    "AT_data_quality.pdf": "https://public.hub.geosphere.at/public/resources/misc/klima/DataHub-DE-Informationen-zur-Datenqualit%C3%A4t.pdf",
    "AT_hourly_metadata.json": "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata",
    "AT_hourly_product.html": "https://data.hub.geosphere.at/de/dataset/klima-v2-1h",
    "AT_API_changelog.html": "https://dataset.api.hub.geosphere.at/v1/docs/changelog.html",
    "OpenMeteo_archive_documentation.html": "https://open-meteo.com/en/docs/historical-weather-api",
}
PER_BODY_LIMIT = 4_000_000
TOTAL_LIMIT = 12_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def acquire(output: Path):
    if output.exists():
        raise FileExistsError(output)
    bodies, receipts, used = {}, {}, 0
    opener = build_opener(NoRedirect)
    for name, url in SOURCES.items():
        request = Request(url, headers={"User-Agent": "IGE-V1A-documentation-audit/1", "Accept-Encoding": "identity"})
        try:
            response = opener.open(request, timeout=45)
        except (HTTPError, URLError, OSError) as error:
            receipts[name] = {"url": url, "status": "SOURCE_BLOCKED", "error": str(error),
                "body_bytes_read": 0, "retrieved_UTC": datetime.now(timezone.utc).isoformat()}
            if isinstance(error, HTTPError):
                receipts[name]["HTTP_status"] = error.code
                error.close()
            print(name, "SOURCE_BLOCKED", str(error), flush=True)
            continue
        with response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("V1A_DOCUMENT_ORIGINAL_ENDPOINT_REQUIRED")
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("V1A_DOCUMENT_ENCODING")
            raw = response.read(min(PER_BODY_LIMIT, TOTAL_LIMIT - used) + 1)
            used += len(raw)
            if not raw or len(raw) > PER_BODY_LIMIT or used > TOTAL_LIMIT:
                raise ValueError("V1A_DOCUMENT_BYTE_BUDGET")
            if name.endswith(".pdf") and not raw.startswith(b"%PDF-"):
                raise ValueError("V1A_DOCUMENT_PDF_REQUIRED")
            if name.endswith(".json"):
                obj = json.loads(raw)
                if "stations" not in obj or "timestamps" in obj or "features" in obj:
                    raise ValueError("V1A_METADATA_NOT_MEASUREMENTS_REQUIRED")
            bodies[name] = raw
            receipts[name] = {"url": url, "status": "ORIGINAL_BODY_RECEIVED", "bytes": len(raw), "sha256": sha256(raw).hexdigest(),
                "retrieved_UTC": datetime.now(timezone.utc).isoformat(),
                "headers": {k: response.headers.get(k) for k in ("Content-Type", "Content-Length", "Last-Modified", "ETag")}}
        print(name, len(raw), flush=True)
    manifest = {"schema": "IGE_V1A_DOCUMENTATION_ONLY_ORIGINALS_v1", "date": "2026-10-27",
        "new_station_measurement_requests": 0, "AT_control_bodies_opened": False,
        "attempts_per_asset": 1, "actual_HTTP_requests": len(receipts), "body_bytes": used,
        "earlier_documentation_probe": {"HTTP_requests": 2, "known_body_bytes_read": 112271,
            "first_document_received_but_not_saved_before_failure": "AT_quality_indicators.pdf",
            "second_legacy_URL_status": 404, "error_body_read": False,
            "station_measurement_requests": 0, "first_probe_byte_identity_not_certified": True},
        "sources": receipts,
        "attribution": "GeoSphere Austria (CC BY 4.0 dataset/documentation) and Open-Meteo; URLs and hashes retained; no provider endorsement."}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        payloads = {**bodies, "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()}
        for name, body in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    with output.open("xb") as stream:
        stream.write(buffer.getvalue())
    print(json.dumps({"packet_sha256": sha256(buffer.getvalue()).hexdigest(), "packet_bytes": len(buffer.getvalue()), "weather_HTTP_requests": 0}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    acquire(parser.parse_args().out)
