"""Bounded A1.3 acquisition, with physically separate predictor/control phases."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
import zipfile

from a13_prepare import ROOT, R, registered, code_hashes, REGISTRATION, INPUTS, CONTROLS, SEAL, PREDICTIONS, LEDGER
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError("A13_SOURCE_REDIRECT_BLOCKED")


def allowed_spec(spec, phase, plan):
    if phase not in ("inputs", "controls"): raise ValueError("A13_UNKNOWN_SOURCE_PHASE")
    expected = {s["id"]: s for s in plan[phase]}
    if spec["id"] not in expected or spec != expected[spec["id"]]: raise ValueError("A13_UNREGISTERED_OR_WRONG_PHASE_SOURCE")
    if phase == "inputs" and spec["role"] == "control": raise ValueError("A13_CONTROL_BODY_BEFORE_SEAL")


def assert_seal_code(seal):
    if seal["code_sha256"] != code_hashes(): raise ValueError("A13_CODE_OR_PROTOCOL_CHANGED_AFTER_PREDICTION_SEAL")
    if seal["control_observation_bodies_opened"] is not False: raise ValueError("A13_NOT_A_PRECONTROL_SEAL")


def published_seal_gate(commit):
    """Check the exact remotely-published/fetched commit supplied by the caller.

    Git object checks bind its bytes; API publication is independently recorded
    by the orchestrator. This does not claim a cryptographic trusted timestamp.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""): raise ValueError("A13_PUBLISHED_SEAL_COMMIT_REQUIRED_BEFORE_CONTROLS")
    def git_body(name):
        return subprocess.check_output(["git", "show", commit+":research/ige_cmip6/"+name], cwd=ROOT)
    raw = git_body(SEAL)
    if raw != (R/SEAL).read_bytes(): raise ValueError("A13_PUBLISHED_AND_LOCAL_SEAL_DIFFER")
    seal = json.loads(raw); assert_seal_code(seal)
    for name in (INPUTS, PREDICTIONS, LEDGER):
        body = git_body(name)
        if sha256(body).hexdigest() != seal["frozen_files_sha256"][name] or body != (R/name).read_bytes():
            raise ValueError("A13_PUBLISHED_PREDICTOR_BYTES_DIFFER:"+name)
    return {"commit": commit, "seal_sha256": sha256(raw).hexdigest(), "git_object_bytes_checked": True,
        "API_publication_separately_verified_by_orchestrator": True}


def packet(path, *, expected_sha=None, expected_phase=None):
    raw = Path(path).read_bytes()
    if len(raw) > 200_000_000 or (expected_sha and sha256(raw).hexdigest() != expected_sha): raise ValueError("A13_PACKET_HASH_OR_SIZE")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist(); names = [e.filename for e in entries]
        if (len(names) > 50 or len(set(names)) != len(names) or any(Path(n).name != n or "\\" in n for n in names)
                or sum(e.file_size for e in entries) > 205_000_000): raise ValueError("A13_PACKET_MEMBER_BUDGET_OR_NAMES")
        manifest = json.loads(archive.read("manifest.json"))
        if expected_phase and manifest["phase"] != expected_phase: raise ValueError("A13_WRONG_SOURCE_PACKET_PHASE")
        if set(names) != set(manifest["original_body_sha256"]) | {"manifest.json"}: raise ValueError("A13_SOURCE_BODY_CENSUS")
        bodies = {n: archive.read(n) for n in manifest["original_body_sha256"]}
        for name, digest in manifest["original_body_sha256"].items():
            if sha256(bodies[name]).hexdigest() != digest: raise ValueError("A13_ORIGINAL_BODY_HASH:"+name)
    return bodies, manifest


def collect(phase, output, *, seal_commit=None, opener=None, pause=time.sleep):
    plan = registered()
    gate = published_seal_gate(seal_commit) if phase == "controls" else None
    if phase not in ("inputs", "controls"): raise ValueError("A13_UNKNOWN_SOURCE_PHASE")
    used = 0
    if phase == "controls":
        _, prior = packet(R/INPUTS, expected_phase="inputs")
        used = prior["decoded_body_bytes_read_all_attempts"]
    output.mkdir(parents=True, exist_ok=False)
    write_exclusive(output/REGISTRATION, (R/REGISTRATION).read_bytes())
    opener = opener or build_opener(NoRedirect).open
    budget = plan["source_budget"]["max_decoded_body_bytes_all_attempts_inputs_plus_controls"]
    bodies, receipts = {}, []
    for spec in plan[phase]:
        allowed_spec(spec, phase, plan)
        receipt = {"id": spec["id"], "station_key": spec["station_key"], "kind": spec["kind"], "role": spec["role"],
            "url": spec["url"], "member": spec["member"], "attempts": [], "status": "SOURCE_BLOCKED"}
        for attempt in range(plan["source_budget"]["attempts_per_asset"]):
            note = {"number": attempt+1, "started_UTC": datetime.now(timezone.utc).isoformat(), "body_bytes_read": 0}
            begin = time.monotonic(); receipt["attempts"].append(note)
            try:
                if used >= budget: raise ValueError("A13_CUMULATIVE_BODY_BUDGET_EXHAUSTED")
                request = Request(spec["url"], headers={"User-Agent": "IGE-A1.3-temperature-research/1", "Accept-Encoding": "identity"})
                with opener(request, timeout=plan["source_budget"]["timeout_seconds"]) as response:
                    if response.status != 200 or response.geturl() != spec["url"]: raise ValueError("A13_ORIGINAL_200_ENDPOINT_REQUIRED")
                    if response.headers.get("Content-Encoding", "identity") != "identity": raise ValueError("A13_UNREGISTERED_CONTENT_ENCODING")
                    length = int(response.headers.get("Content-Length", "0"))
                    if length > min(spec["max_body_bytes"], budget-used): raise ValueError("A13_HEADER_BODY_BUDGET")
                    note["headers"] = {k: response.headers.get(k) for k in ("Content-Type", "Content-Length", "ETag", "Last-Modified")}
                    chunks, n = [], 0
                    while True:
                        chunk = response.read(min(65536, spec["max_body_bytes"]-n+1, budget-used+1))
                        if not chunk: break
                        n += len(chunk); used += len(chunk); note["body_bytes_read"] += len(chunk)
                        if n > spec["max_body_bytes"] or used > budget: raise ValueError("A13_STREAM_BODY_BUDGET")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    if not raw or (length and len(raw) != length): raise ValueError("A13_EMPTY_OR_TRUNCATED_ORIGINAL_BODY")
                receipt.update({"status": "ORIGINAL_BODY_RECEIVED", "bytes": len(raw), "sha256": sha256(raw).hexdigest(),
                    "retrieved_UTC": datetime.now(timezone.utc).isoformat()})
                bodies[spec["member"]] = raw
                write_exclusive(output/spec["member"], raw)
                note["status"] = "RECEIVED"; break
            except (HTTPError, URLError, OSError, ValueError) as exc:
                note["status"] = "FAILED"; note["error"] = type(exc).__name__+": "+str(exc)[:200]
                retry = (isinstance(exc, HTTPError) and exc.code in (429, 500, 502, 503, 504)) or isinstance(exc, (URLError, TimeoutError, ConnectionError))
                if not retry or attempt+1 == plan["source_budget"]["attempts_per_asset"]: break
                pause(2**(attempt+1))
            finally:
                note["wall_seconds"] = time.monotonic()-begin
        receipts.append(receipt)
        write_exclusive(output/(spec["id"]+"_receipt.json"), json_bytes(receipt))
        print(spec["id"], receipt["status"], receipt.get("bytes", 0), flush=True)
    manifest = {"schema": "IGE_A13_ORIGINAL_SOURCES_v1", "phase": phase,
        "registration_sha256": sha256((R/REGISTRATION).read_bytes()).hexdigest(), "published_seal_gate": gate,
        "original_body_sha256": {n: sha256(b).hexdigest() for n,b in bodies.items()}, "sources": receipts,
        "status": "COMPLETE" if all(r["status"] == "ORIGINAL_BODY_RECEIVED" for r in receipts) else "PARTIAL_WITH_SOURCE_BLOCKS",
        "HTTP_attempts_this_phase": sum(len(r["attempts"]) for r in receipts),
        "decoded_body_bytes_read_this_phase": sum(a["body_bytes_read"] for r in receipts for a in r["attempts"]),
        "decoded_body_bytes_read_all_attempts": used, "control_bodies_opened_this_phase": phase == "controls",
        "full_original_provider_bodies_preserved": True,
        "attribution": {"station": "Source: MeteoSwiss, SwissMetNet Open Government Data, original URLs and retrieval receipts included",
            "background": "Open-Meteo ERA5-derived historical API; Copernicus/ECMWF ERA5; original request parameters included"}}
    write_exclusive(output/"manifest.json", json_bytes(manifest))
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted({**bodies, "manifest.json": json_bytes(manifest)}.items()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; archive.writestr(info, raw)
    name = INPUTS if phase == "inputs" else CONTROLS
    write_exclusive(output/name, result.getvalue())
    print(json.dumps({"packet": name, "bytes": len(result.getvalue()), "sha256": sha256(result.getvalue()).hexdigest(),
        "HTTP_attempts_this_phase": manifest["HTTP_attempts_this_phase"], "decoded_body_bytes_cumulative": used, "status": manifest["status"]}))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("inputs", "controls"), required=True)
    parser.add_argument("--out", type=Path, required=True); parser.add_argument("--published-seal-commit")
    args = parser.parse_args(); collect(args.phase, args.out, seal_commit=args.published_seal_commit)
