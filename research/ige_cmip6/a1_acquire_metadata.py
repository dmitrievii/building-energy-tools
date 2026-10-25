"""A1.1 original metadata only: no station observation or model endpoint.

The URL allowlist is exact. Historic station measurement ZIPs/CSVs and IV1
endpoints cannot be requested through this acquisition command.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

DWD = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/"
SWISS = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/"
URLS = {
    "AT_hourly_v2_metadata.json": "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h/metadata",
    "DE_TU_stations.txt": DWD + "air_temperature/historical/TU_Stundenwerte_Beschreibung_Stationen.txt",
    "DE_TU_description.pdf": DWD + "air_temperature/DESCRIPTION_obsgermany_climate_hourly_air_temperature_en.pdf",
    "DE_pressure_description.pdf": DWD + "pressure/DESCRIPTION_obsgermany_climate_hourly_pressure_en.pdf",
    "DE_pressure_stations.txt": DWD + "pressure/historical/P0_Stundenwerte_Beschreibung_Stationen.txt",
    "CH_stations.csv": SWISS + "ogd-smn_meta_stations.csv",
    "CH_parameters.csv": SWISS + "ogd-smn_meta_parameters.csv",
    "CH_inventory.csv": SWISS + "ogd-smn_meta_datainventory.csv",
    "CH_download_documentation.html": "https://opendatadocs.meteoswiss.ch/general/download",
}
LIMIT = 8_000_000


def fetch(name, url):
    if URLS.get(name) != url: raise ValueError("A1_METADATA_ONLY_EXACT_ALLOWLIST")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): raise ValueError("A1_METADATA_REDIRECT_BLOCKED")
    opener = urllib.request.build_opener(NoRedirect)
    clock = time.monotonic()
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "IGE-A1-source-metadata-only/1.0"})
            with opener.open(request, timeout=35) as response:
                if int(response.headers.get("Content-Length", "0")) > LIMIT: raise ValueError("A1_METADATA_SIZE_LIMIT")
                raw = response.read(LIMIT+1)
                if len(raw) > LIMIT: raise ValueError("A1_METADATA_SIZE_LIMIT")
                info = {"name": name, "url": url, "status": "ORIGINAL_METADATA_RECEIVED", "bytes": len(raw),
                    "sha256": sha256(raw).hexdigest(), "http_attempts": attempt+1,
                    "retrieved_utc": datetime.now(timezone.utc).isoformat(), "content_type": response.headers.get("Content-Type"),
                    "ETag": response.headers.get("ETag"), "Last-Modified": response.headers.get("Last-Modified"),
                    "wall_seconds": time.monotonic()-clock}
            return name, raw, info
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 1: error = exc; break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 1: error = exc; break
        except ValueError as exc: error = exc; break
        time.sleep(1)
    return name, None, {"name": name, "url": url, "status": "SOURCE_BLOCKED", "http_attempts": attempt+1,
        "error": type(error).__name__ + ": " + str(error), "wall_seconds": time.monotonic()-clock}


def acquire(output: Path, names=None):
    output.mkdir(parents=True, exist_ok=False)
    bodies, receipts = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, raw, receipt in pool.map(lambda pair: fetch(*pair), [(n, URLS[n]) for n in (names or URLS)]):
            receipts.append(receipt)
            if raw is not None:
                bodies[name] = raw
                with (output/name).open("xb") as stream: stream.write(raw)
            print(name, receipt["status"], receipt.get("bytes", 0), flush=True)
    manifest = {"schema": "IGE_A1_1_METADATA_ONLY_v1", "sources": receipts,
        "station_observation_or_weather_model_requests": 0, "IV1_station_observations_opened": False,
        "total_HTTP_attempts": sum(r["http_attempts"] for r in receipts),
        "total_received_bytes": sum(r.get("bytes", 0) for r in receipts), "production_ready": False}
    bodies["manifest.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False)+"\n").encode()
    with (output/"manifest.json").open("xb") as stream: stream.write(bodies["manifest.json"])
    packet = io.BytesIO()
    with zipfile.ZipFile(packet, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(bodies.items()):
            info = zipfile.ZipInfo(name, (2000,1,1,0,0,0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    with (output/"metadata_sources.zip").open("xb") as stream: stream.write(packet.getvalue())
    print(json.dumps({"HTTP_attempts": manifest["total_HTTP_attempts"], "bytes": manifest["total_received_bytes"],
        "packet_bytes": len(packet.getvalue()), "packet_sha256": sha256(packet.getvalue()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="+", choices=sorted(URLS))
    args=parser.parse_args(); acquire(args.out, args.only)
