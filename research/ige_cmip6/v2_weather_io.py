"""V2 two-phase original acquisition with exact inventory and elapsed deadlines.

No observation or model request is made by importing this module. Linux
SIGALRM bounds the entire blocking open/read attempt, not just socket idleness.
All attempted response bytes, including failed prefixes/error bodies, survive.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
import zipfile

from v2_weather_registration import (R, INPUTS, CONTROLS, REG, LEDGER, registered, publication_gate)
from v2_metadata import NoRedirect
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive

PART_SIZE = 5_500_000


@contextmanager
def elapsed_deadline(seconds):
    def expired(signum, frame):
        raise TimeoutError("V2_TOTAL_ATTEMPT_DEADLINE")
    old = signal.signal(signal.SIGALRM, expired)
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        signal.signal(signal.SIGALRM, old)
        raise ValueError("V2_NESTED_REALTIME_TIMER_FORBIDDEN")
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def allowed_spec(spec, phase, plan):
    if phase not in ("inputs", "controls") or spec not in plan[phase]:
        raise ValueError("V2_UNREGISTERED_OR_WRONG_PHASE_ASSET")
    if phase == "inputs" and (spec["role"] == "control" or
            spec["kind"] == "station_temperature" and spec["station_key"] in plan["target_keys"]):
        raise ValueError("V2_TARGET_T_OR_QC_IN_PREDICTORS")
    if phase == "controls" and spec["role"] != "control":
        raise ValueError("V2_NOT_A_REGISTERED_CONTROL")
    if spec["source_block"] or not spec["url"]:
        raise ValueError("V2_PREWEATHER_SOURCE_BLOCK")


def control_admission(plan, ledger):
    expected = {(k, w["season"]) for k in plan["target_keys"] for w in plan["windows"]}
    cases = ledger["cases"]
    if len(cases) != 72 or {(c["target_key"], c["season"]) for c in cases} != expected:
        raise ValueError("V2_CONTROL_GATE_CASE_CENSUS")
    for c in cases:
        n = c["finite_paired_forecast_hours"]
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 168:
            raise ValueError("V2_CONTROL_GATE_INVALID_COUNT")
    return {k: {"open": any(c["target_key"] == k and c["finite_paired_forecast_hours"] >= 160 for c in cases),
                "criterion": "AT_LEAST_ONE_CASE_WITH_160_PAIRED_B0_R1_FORECASTS; NO_TARGET_INPUT"}
            for k in plan["target_keys"]}


def store_packet(directory, name, manifest, members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, body in sorted({**members, "manifest.json": json_bytes(manifest)}.items()):
            info = zipfile.ZipInfo(member, (2000, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    raw = buffer.getvalue(); parts = []
    for i, offset in enumerate(range(0, len(raw), PART_SIZE), 1):
        member = name + f".part{i:03d}"; body = raw[offset:offset + PART_SIZE]
        write_exclusive(directory / member, body)
        parts.append({"name": member, "bytes": len(body), "sha256": sha256(body).hexdigest()})
    storage = {"schema": "IGE_V2_WEATHER_ORIGINAL_PARTS_v1", "name": name,
               "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "parts": parts}
    write_exclusive(directory / (name + ".storage.json"), json_bytes(storage))
    return storage


def read_packet(directory, name, phase):
    storage = json.loads((directory / (name + ".storage.json")).read_text())
    if storage["schema"] != "IGE_V2_WEATHER_ORIGINAL_PARTS_v1" or storage["name"] != name or not 1 <= len(storage["parts"]) <= 400:
        raise ValueError("V2_PACKET_STORAGE")
    pieces = []
    for i, p in enumerate(storage["parts"], 1):
        if p["name"] != name + f".part{i:03d}" or not 0 < p["bytes"] <= PART_SIZE:
            raise ValueError("V2_PACKET_PART_CENSUS")
        body = (directory / p["name"]).read_bytes()
        if len(body) != p["bytes"] or sha256(body).hexdigest() != p["sha256"]:
            raise ValueError("V2_PACKET_PART_HASH")
        pieces.append(body)
    raw = b"".join(pieces)
    if len(raw) != storage["bytes"] or sha256(raw).hexdigest() != storage["sha256"] or len(raw) > 2_010_000_000:
        raise ValueError("V2_PACKET_HASH_OR_BUDGET")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist(); names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 241 or any(Path(n).name != n or "\\" in n for n in names) or sum(e.file_size for e in entries) > 2_010_000_000:
            raise ValueError("V2_PACKET_MEMBER_CENSUS_OR_BUDGET")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["phase"] != phase or set(names) != set(manifest["member_sha256"]) | {"manifest.json"}:
            raise ValueError("V2_PACKET_PHASE_OR_MEMBERS")
        members = {n: archive.read(n) for n in manifest["member_sha256"]}
    if any(sha256(b).hexdigest() != manifest["member_sha256"][n] for n, b in members.items()):
        raise ValueError("V2_ORIGINAL_MEMBER_HASH")
    return members, manifest, storage


class Collector:
    def __init__(self, plan, *, previous_attempts=0, previous_bytes=0, opener=None, pause=time.sleep):
        self.plan = plan; self.attempts = previous_attempts; self.bytes = previous_bytes
        self.opener = opener or build_opener(NoRedirect).open; self.pause = pause
        b = plan["budget"]
        self.attempt_limit = b["HTTP_attempts_inputs_plus_controls_max"]
        self.byte_limit = b["body_bytes_all_attempts_inputs_plus_controls_max"]
        if not 0 <= self.attempts <= b["HTTP_attempts_inputs_plus_controls_max"] or not 0 <= self.bytes <= b["body_bytes_all_attempts_inputs_plus_controls_max"]:
            raise ValueError("V2_PREVIOUS_PHASE_BUDGET_INVALID")

    def attempt(self, spec, output, number):
        b = self.plan["budget"]; cap = spec["max_body_bytes"]
        note = {"number": number, "body_bytes_read": 0, "status": "FAILED", "retry": False,
                "started_UTC_runner_clock_untrusted": datetime.now(timezone.utc).isoformat()}
        if self.attempts >= self.attempt_limit or self.bytes >= self.byte_limit:
            note["error"] = "V2_GLOBAL_ATTEMPT_OR_BYTE_BUDGET"; note["HTTP_attempted"] = False
            return note
        self.attempts += 1; note["HTTP_attempted"] = True
        member = spec["id"] + f"_attempt{number}.bin"; target = output / member
        started = time.monotonic(); code = None; response = None; bytes_before_attempt = self.bytes
        try:
            with target.open("xb") as stream, elapsed_deadline(b["attempt_total_deadline_seconds"]):
                request = Request(spec["url"], headers={"Accept-Encoding": "identity", "User-Agent": "IGE-V2-preregistered-T/1"})
                try:
                    response = self.opener(request, timeout=b["attempt_total_deadline_seconds"])
                except HTTPError as exc:
                    response = exc
                with response:
                    code = response.code if isinstance(response, HTTPError) else response.status
                    note["HTTP_status"] = code
                    note["headers"] = {k: response.headers.get(k) for k in ("Content-Type", "Content-Length", "ETag", "Last-Modified")}
                    if response.geturl() != spec["url"] or response.headers.get("Content-Encoding", "identity") != "identity":
                        raise ValueError("V2_ORIGINAL_ENDPOINT_OR_ENCODING_CHANGED")
                    declared = int(response.headers.get("Content-Length", "0"))
                    if declared > min(cap, self.byte_limit - self.bytes):
                        raise ValueError("V2_DECLARED_ASSET_TOO_LARGE")
                    while True:
                        remaining = self.byte_limit - self.bytes
                        if remaining <= 0:
                            raise ValueError("V2_GLOBAL_BYTE_BUDGET_BEFORE_EOF")
                        block = response.read(min(65536, cap - note["body_bytes_read"] + 1, remaining))
                        if not block:
                            break
                        stream.write(block); note["body_bytes_read"] += len(block); self.bytes += len(block)
                        if note["body_bytes_read"] > cap:
                            raise ValueError("V2_ASSET_STREAM_BUDGET; one oversize probe byte counted")
                    if code != 200:
                        note["retry"] = code in (429, 500, 502, 503, 504)
                        raise ValueError("V2_HTTP_" + str(code))
                    if not note["body_bytes_read"] or declared and declared != note["body_bytes_read"]:
                        raise ValueError("V2_EMPTY_OR_TRUNCATED_ORIGINAL")
                    note["status"] = "ORIGINAL_BODY_RECEIVED"
        except (URLError, OSError, ValueError) as exc:
            note["error"] = type(exc).__name__ + ":" + str(exc)[:220]
            note["retry"] = note["retry"] or isinstance(exc, (URLError, TimeoutError, ConnectionError))
        finally:
            note["elapsed_seconds"] = time.monotonic() - started
            if target.exists():
                raw = target.read_bytes(); note.update(member=member, bytes=len(raw), sha256=sha256(raw).hexdigest())
                # An elapsed interrupt can land between a completed local write
                # and Python counter updates. Retained bytes are authoritative.
                note["body_bytes_read"] = len(raw); self.bytes = bytes_before_attempt + len(raw)
            write_exclusive(output / (spec["id"] + f"_attempt{number}.receipt.json"), json_bytes(note))
        return note

    def run(self, phase, output, gate):
        plan = self.plan; output.mkdir(parents=True, exist_ok=False)
        start_attempts, start_bytes = self.attempts, self.bytes
        if phase == "inputs":
            self.attempt_limit -= plan["budget"].get("reserved_control_first_attempt_slots", 0)
            self.byte_limit -= plan["budget"].get("reserved_control_first_body_caps_bytes", 0)
        admission = None
        if phase == "controls":
            ledger = json.loads((R / LEDGER).read_text()); admission = control_admission(plan, ledger)
            if admission != ledger["control_admission"]:
                raise ValueError("V2_CHANGED_PRECONTROL_SOURCE_GATE")
        rows = []
        for s in plan[phase]:
            reason = s["source_block"]
            if phase == "controls" and not admission[s["station_key"]]["open"]:
                reason = "NO_160_HOUR_PREDICTION_CASE; CONTROL_NOT_OPENED"
            rows.append({"spec": s, "status": "SOURCE_BLOCKED", "reason": reason, "attempts": []})
        # Complete the first pass before spending the remaining global budget on retries.
        for number in range(1, plan["budget"]["attempts_per_asset_max"] + 1):
            for row in rows:
                s = row["spec"]
                if row["reason"] or row["status"] == "ORIGINAL_BODY_RECEIVED" or number > 1 and not row["attempts"][-1]["retry"]:
                    continue
                allowed_spec(s, phase, plan)
                if self.attempts >= self.attempt_limit or self.bytes >= self.byte_limit:
                    row["reason"] = "WEATHER_PHASE_BUDGET_EXHAUSTED; control first-pass reserve retained"; continue
                if number > 1:
                    self.pause(plan["budget"]["retry_delays_seconds"][number - 2])
                note = self.attempt(s, output, number); row["attempts"].append(note)
                if note["status"] == "ORIGINAL_BODY_RECEIVED":
                    row.update(status=note["status"], original_member=note["member"])
                print(s["id"], number, note["status"], note["body_bytes_read"], flush=True)
            (output / "acquisition_journal.json").write_bytes(json_bytes({"phase": phase, "sources": rows, "cumulative_HTTP_attempts": self.attempts, "cumulative_body_bytes": self.bytes}))
        for row in rows:
            if row["status"] != "ORIGINAL_BODY_RECEIVED" and not row["reason"]:
                row["reason"] = row["attempts"][-1].get("error", "NO_ORIGINAL_BODY") if row["attempts"] else "SOURCE_BLOCKED"
        members = {p.name: p.read_bytes() for p in output.glob("*_attempt*.bin")}
        manifest = {"schema": "IGE_V2_WEATHER_ORIGINALS_v1", "phase": phase, "publication_gate": gate,
            "registration_sha256": sha256((R / REG).read_bytes()).hexdigest(), "sources": rows,
            "HTTP_attempts_phase": self.attempts - start_attempts, "body_bytes_phase": self.bytes - start_bytes,
            "cumulative_HTTP_attempts": self.attempts, "cumulative_body_bytes": self.bytes,
            "effective_phase_attempt_limit": self.attempt_limit, "effective_phase_byte_limit": self.byte_limit,
            "member_sha256": {n: sha256(raw).hexdigest() for n, raw in members.items()},
            "control_bodies_opened": phase == "controls" and any(r["attempts"] for r in rows),
            "raw_entire_containers_count_as_exposure": True,
            "attribution": "GeoSphere Austria; DWD CDC; MeteoSwiss OGD; Open-Meteo / Copernicus ECMWF ERA5; exact URLs retained"}
        name = INPUTS if phase == "inputs" else CONTROLS
        store_packet(output, name, manifest, members)
        write_exclusive(output / "manifest.json", json_bytes(manifest))
        return manifest


def collect(phase, output, commit):
    plan = registered(); gate = publication_gate(commit, predictions=phase == "controls")
    attempts = used = 0
    if phase == "controls":
        _, m, _ = read_packet(R, INPUTS, "inputs")
        attempts, used = m["cumulative_HTTP_attempts"], m["cumulative_body_bytes"]
    return Collector(plan, previous_attempts=attempts, previous_bytes=used).run(phase, output, gate)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--phase", choices=("inputs", "controls"), required=True)
    p.add_argument("--out", type=Path, required=True); p.add_argument("--published-commit", required=True)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        collect(args.phase, args.out, args.published_commit)
    else:
        # Hard process limit also covers decompression/packet serialization,
        # not just sockets. A killed partial run has no complete source packet
        # or prediction seal and cannot authorize opening controls.
        limit = registered()["budget"]["workflow_job_deadline_minutes"] * 60
        subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"],
                       check=True, timeout=limit)
