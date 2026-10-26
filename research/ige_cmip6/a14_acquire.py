"""Bounded original A1.4 background acquisition after published registration."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener
import zipfile

from a14_prepare import ROOT,R,REGISTRATION,SOURCES,registered,code_hashes
from a13_acquire import NoRedirect,packet
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive


def publication_gate(commit):
    if not re.fullmatch(r"[0-9a-f]{40}",commit):raise ValueError("A14_PUBLISHED_REGISTRATION_COMMIT_REQUIRED")
    for name in ["research/ige_cmip6/"+REGISTRATION,*code_hashes()]:
        if subprocess.check_output(["git","show",commit+":"+name],cwd=ROOT)!=(ROOT/name).read_bytes():
            raise ValueError("A14_PUBLISHED_CODE_OR_REGISTRATION_CHANGED:"+name)
    return {"commit":commit,"code_sha256":code_hashes(),"registration_sha256":sha256((R/REGISTRATION).read_bytes()).hexdigest()}


def collect(output,commit):
    plan=registered();gate=publication_gate(commit)
    output.mkdir(parents=True,exist_ok=False)
    bodies={};receipts=[];used=0;opener=build_opener(NoRedirect)
    for spec in plan["new_source_plan"]:
        note={k:spec[k] for k in ("id","station_key","kind","url","member")}
        note.update(status="SOURCE_BLOCKED",attempts=[])
        for attempt in range(plan["source_budget"]["attempts_per_asset"]):
            timing=time.monotonic();a={"number":attempt+1,"started_UTC":datetime.now(timezone.utc).isoformat(),"body_bytes_read":0}
            note["attempts"].append(a)
            try:
                if used>=plan["source_budget"]["max_decoded_body_bytes_all_attempts"]:raise ValueError("A14_BODY_BUDGET")
                with opener.open(Request(spec["url"],headers={"User-Agent":"IGE-A1.4-research/1","Accept-Encoding":"identity"}),timeout=45) as response:
                    if response.status!=200 or response.geturl()!=spec["url"] or response.headers.get("Content-Encoding","identity")!="identity":
                        raise ValueError("A14_ORIGINAL_IDENTITY_200_RESPONSE_REQUIRED")
                    length=int(response.headers.get("Content-Length","0"))
                    if length>spec["max_body_bytes"]:raise ValueError("A14_HEADER_BUDGET")
                    chunks=[];n=0
                    while True:
                        chunk=response.read(min(65536,spec["max_body_bytes"]-n+1))
                        if not chunk:break
                        n+=len(chunk);used+=len(chunk);a["body_bytes_read"]+=len(chunk)
                        if n>spec["max_body_bytes"] or used>plan["source_budget"]["max_decoded_body_bytes_all_attempts"]:
                            raise ValueError("A14_BODY_BUDGET")
                        chunks.append(chunk)
                    raw=b"".join(chunks)
                    if not raw or (length and len(raw)!=length):raise ValueError("A14_EMPTY_OR_TRUNCATED_BODY")
                    note["headers"]={k:response.headers.get(k) for k in ("Content-Type","Content-Length","ETag","Last-Modified")}
                note.update(status="ORIGINAL_BODY_RECEIVED",bytes=len(raw),sha256=sha256(raw).hexdigest())
                bodies[spec["member"]]=raw;write_exclusive(output/spec["member"],raw);a["status"]="RECEIVED";break
            except (HTTPError,URLError,OSError,ValueError) as exc:
                a.update(status="FAILED",error=type(exc).__name__+": "+str(exc)[:200])
                retry=(isinstance(exc,HTTPError) and exc.code in (429,500,502,503,504)) or isinstance(exc,(URLError,TimeoutError,ConnectionError))
                if not retry or attempt==2:break
                time.sleep(2**(attempt+1))
            finally:a["wall_seconds"]=time.monotonic()-timing
        receipts.append(note);write_exclusive(output/(spec["id"]+"_receipt.json"),json_bytes(note))
        print(spec["id"],note["status"],note.get("bytes",0),flush=True)
    manifest={"schema":"IGE_A14_ORIGINAL_SOURCES_v1","phase":"A14_BACKGROUND_ONLY","publication_gate":gate,
        "registration_sha256":sha256((R/REGISTRATION).read_bytes()).hexdigest(),"sources":receipts,
        "original_body_sha256":{n:sha256(b).hexdigest() for n,b in bodies.items()},
        "status":"COMPLETE" if len(bodies)==11 else "PARTIAL_WITH_SOURCE_BLOCKS",
        "HTTP_attempts":sum(len(r["attempts"]) for r in receipts),"decoded_body_bytes_all_attempts":used,
        "new_station_observation_requests":0,"target_observations_used_as_predictors":False,
        "attribution":"MeteoSwiss OGD reused donor originals; Open-Meteo / Copernicus ERA5-derived; NASA POWER SYN1DEG longwave"}
    write_exclusive(output/"manifest.json",json_bytes(manifest))
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in sorted({**bodies,"manifest.json":json_bytes(manifest)}.items()):
            info=zipfile.ZipInfo(n,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,b)
    write_exclusive(output/SOURCES,stream.getvalue())
    if manifest["status"]!="COMPLETE":raise RuntimeError("A14_SOURCE_BLOCK; original receipts and partial packet retained")
    return manifest


def checked_sources(path):
    plan=registered();bodies,manifest=packet(path,expected_phase="A14_BACKGROUND_ONLY")
    if manifest["registration_sha256"]!=sha256((R/REGISTRATION).read_bytes()).hexdigest():raise ValueError("A14_SOURCE_REGISTRATION_HASH")
    gate=publication_gate(manifest["publication_gate"]["commit"])
    if gate!=manifest["publication_gate"]:raise ValueError("A14_PUBLISHED_GATE_CHANGED")
    expected={s["id"]:s for s in plan["new_source_plan"]}
    if len(manifest["sources"])!=11 or {r["id"] for r in manifest["sources"]}!=set(expected):raise ValueError("A14_SOURCE_CENSUS")
    for r in manifest["sources"]:
        s=expected[r["id"]]
        if any(r[k]!=s[k] for k in ("url","member","kind","station_key")):raise ValueError("A14_SOURCE_SPEC_CHANGED")
        if r["status"]!="ORIGINAL_BODY_RECEIVED" or len(bodies[r["member"]])!=r["bytes"] or sha256(bodies[r["member"]]).hexdigest()!=r["sha256"]:
            raise ValueError("A14_ORIGINAL_SOURCE_BLOCK_OR_HASH")
    if set(bodies)!={s["member"] for s in expected.values()}:raise ValueError("A14_UNREGISTERED_BODY")
    return bodies,manifest


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--out",type=Path,required=True);p.add_argument("--registration-commit",required=True)
    a=p.parse_args();collect(a.out,a.registration_commit)
