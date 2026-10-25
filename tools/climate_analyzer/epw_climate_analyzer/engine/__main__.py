"""CLI for the first integrated historical background route."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts import HistoricalRequest
from .historical import run_historical


def main() -> None:
    parser = argparse.ArgumentParser(description="IGE research climate engine; no independent accuracy qualification")
    parser.add_argument("mode", choices=["historical"])
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--utc-offset-minutes", type=int, required=True, help="Fixed local standard time, never DST")
    parser.add_argument("--label", default="IGE background")
    parser.add_argument("--out", type=Path, required=True, help="New directory; existing paths are never overwritten")
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--source-bundle-sha256")
    args = parser.parse_args()
    if bool(args.source_bundle) != bool(args.source_bundle_sha256):
        parser.error("--source-bundle and --source-bundle-sha256 must be supplied together")
    request = HistoricalRequest(args.latitude, args.longitude, args.year, args.utc_offset_minutes, label=args.label)
    result = run_historical(request, args.out, source_bundle=args.source_bundle, source_bundle_sha256=args.source_bundle_sha256)
    print(json.dumps({"output": str(args.out), "records": len(result.data), "quality": asdict(result.quality)}, indent=2))


if __name__ == "__main__":
    main()
