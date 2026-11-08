#!/usr/bin/env python3
"""IGE: automatic spatial regression calibration from offline AT/DE/CH downloads."""
from __future__ import annotations

import os
# Set before importing numerical libraries, including in Windows spawned workers.
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
from pathlib import Path
import sys
import traceback

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    from ige_auto import VERSION
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    default = Path(__file__).resolve().parent/"config_auto_regression.json"
    for name in ("run", "prepare", "fit", "check-config"):
        s = sub.add_parser(name)
        s.add_argument("--config", type=Path, default=default)
        if name == "fit":
            s.add_argument("--cube", type=Path, required=True)
        elif name != "check-config":
            s.add_argument("--rehash", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("--run", type=Path, required=True)
    e.add_argument("--repeat", action="store_true", help="Record another C exposure after a first opening, including a failed attempt")
    sub.add_parser("self-check", help="Small analytical controls; no Database needed")
    args = p.parse_args(argv)
    root = None
    try:
        from ige_local.common import log, new_run, now, write_json
        from ige_auto.config import load, native_config
        if args.command == "self-check":
            from ige_auto.oracles import self_check
            import json
            print(json.dumps(self_check(), indent=2))
            return 0
        if args.command == "evaluate":
            from ige_auto.experiment import evaluate
            return evaluate(args.run, args.repeat)["exit_code"]
        c = load(args.config)
        if args.command == "check-config":
            import json
            print(json.dumps({"configuration_valid": True,
                              **{k: c[k] for k in ("config_source_path", "database", "results")}},
                             ensure_ascii=False, indent=2))
            return 0
        from ige_auto.data import build
        from ige_auto.experiment import evaluate, train
        root = new_run(c["results"])
        log("IGE automatic regression " + VERSION)
        log("Database (read only): " + c["database"])
        log("Run: " + str(root)); write_json(root/"effective_config.json", c)
        if args.command == "fit":
            cube = args.cube
        else:
            from ige_local.audit import audit
            snapshot, report = audit(native_config(c), root/"E0", rehash=args.rehash)
            cube = build(snapshot, c, root/"cube", audit_summary=report)
            if args.command == "prepare":
                log("Prepared cube: " + str(cube))
                return 2 if report["plan_errors"] or any(x["quarantined_jobs"] for x in report["countries"].values()) else 0
        result = train(cube, c, root)
        log("REPORT: " + str(root/"REPORT_RU.md"))
        log("SUMMARY: " + str(root/"summary.json"))
        if c["evaluate_holdout"]:
            result["exit_code"] = max(result["exit_code"], evaluate(root)["exit_code"])
        return result["exit_code"]
    except ImportError as exc:
        print("Dependency unavailable: " + str(exc))
        print("Install: python -m pip install -r requirements_regression.txt")
        return 2
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc))
        if root:
            from ige_local.common import write_json, now
            write_json(root/"failure.json", {"at_utc": now(), "error": type(exc).__name__+": "+str(exc), "traceback": traceback.format_exc()})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
