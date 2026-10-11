#!/usr/bin/env python3
"""Inspect immutable IGE Climate Research portable freeze ZIP, no extraction.

Scientific source/ZIP evidence integrity (not physical GCM weather validation).
Python standard library only. Every SHA256 checks the immutable ZIP stream
and every embedded original provider/derived member; coverage requires
40 original derived GCM windows, 20 station hourly years 1995-2014,
21 science-stage evidence ZIPs, 81 archives total.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import json,io

FREEZE_BASENAME="IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip"
KNOWN_SHA256="2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7"
KNOWN_LENGTH=68062328
MODELS={"ACCESS-CM2","CanESM5","EC-Earth3","GFDL-ESM4","IPSL-CM6A-LR",
        "MPI-ESM1-2-HR","MRI-ESM2-0","NorESM2-MM"}
WINDOWS={"historical-1995-2014","ssp245-2040-2059",
         "ssp245-2080-2099","ssp585-2040-2059","ssp585-2080-2099"}
REQUIRED={"model_window":40,"hourly_station_source":20,
          "research_stage_evidence":21}

def sha_of_stream(reader):
    sha=sha256()
    total=0
    while True:
        b=reader.read(1024*1024)
        if not b:break
        sha.update(b)
        total+=len(b)
    return sha.hexdigest(),total

def verify_zip(bundle:Path,*,enforce_canonical=True):
    failures=[]
    if not bundle.is_file():
        raise FileNotFoundError(bundle)
    if enforce_canonical:
        with bundle.open("rb") as f:digest,size=sha_of_stream(f)
        if size!=KNOWN_LENGTH:failures.append(f"Bundle size drift: {size}")
        if digest!=KNOWN_SHA256:failures.append(f"Bundle SHA256 drift: {digest}")
    with ZipFile(bundle) as z:
        manifest_names=[x for x in z.namelist() if x.endswith("/MANIFEST.json")]
        if len(manifest_names)!=1:raise ValueError("Expected exactly one scoped MANIFEST.json")
        root=manifest_names[0][:-len("MANIFEST.json")]
        m=json.loads(z.read(root+"MANIFEST.json"))
        records=m.get("archives",[])
        if len(records)!=m.get("archive_count"):
            failures.append("Manifest source count differs from stated")
        seen_paths=set();counts=Counter();models=set();years=set()
        for r in records:
            rel=r.get("path")
            if not isinstance(rel,str) or ".." in Path(rel).parts or rel.startswith("/"):
                failures.append("Unsafe archive member path: "+str(rel));continue
            if rel in seen_paths:failures.append("Duplicate manifest archive path: "+rel)
            seen_paths.add(rel)
            klass=r.get("role")
            counts[klass]+=1
            if klass=="model_window":
                models.add((r.get("model"),r.get("window")))
            if klass=="hourly_station_source":
                years.add(r.get("year"))
            target=root+rel
            try:
                blob=z.read(target)
            except KeyError:
                failures.append("Missing archived ZIP: "+target);continue
            if len(blob)!=r.get("bytes") or sha256(blob).hexdigest()!=r.get("sha256"):
                failures.append("ZIP checksum/byte mismatch: "+target);continue
            try:
                with ZipFile(io.BytesIO(blob)) as interior:
                    originals={v["path"]:v for v in r.get("zip_member_sha256",[])}
                    if interior.testzip():
                        failures.append("Embedded CRC error: "+target)
                    actual={a.filename for a in interior.infolist() if not a.is_dir()}
                    if set(originals)!=actual:
                        failures.append("Embedded path inventory mismatch: "+target)
                    for item,entry in originals.items():
                        with interior.open(item) as f:hash_value,n=sha_of_stream(f)
                        if hash_value!=entry["sha256"] or n!=entry["bytes"]:
                            failures.append("Embedded SHA256 mismatch: "+target+"!"+item)
            except BadZipFile:
                failures.append("Embedded ZIP unreadable: "+target)
        manifest_targets={root+r["path"] for r in records}
        actual_targets={p for p in z.namelist() if p.endswith(".zip")}
        if manifest_targets!=actual_targets:
            failures.append("Unindexed extra/missing ZIP files in portable bundle")
        if enforce_canonical:
            if any(counts[k]!=n for k,n in REQUIRED.items()):
                failures.append("Expected 40 GCM + 20 hourly years + 21 stages: "+str(dict(counts)))
            if models!={(mod,win) for mod in MODELS for win in WINDOWS}:
                failures.append("Incomplete 8-by-5 model/period Cartesian product")
            if years!=set(range(1995,2015)):
                failures.append("Expected station30 1995-2014 all 20 annual ZIPs")
            if sum(r.get("expected_hours",0) for r in records
                   if r.get("role")=="hourly_station_source")!=175320:
                failures.append("Expected 175,320 station hourly UTC source timestamps")
    return {"archive_count":len(records),"categories":dict(counts),
            "GCM_model_period_combinations":len(models),
            "hourly_station_source_years":len(years),
            "status":"PASS" if not failures else "FAIL",
            "errors":failures}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("bundle",type=Path,help="Exact portable scientific freeze ZIP")
    args=parser.parse_args()
    status=verify_zip(args.bundle)
    print(json.dumps(status,ensure_ascii=False,indent=2))
    raise SystemExit(0 if status["status"]=="PASS" else 1)
if __name__=="__main__":main()
