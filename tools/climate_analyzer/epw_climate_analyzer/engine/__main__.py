"""CLI for the first integrated historical background route."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts import HistoricalRequest, FutureRequest
from .historical import run_historical
from .future import run_future
from .model_sources import SEMANTICS_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description="IGE research climate engine; no independent accuracy qualification")
    parser.add_argument("mode", choices=["historical", "future"])
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--utc-offset-minutes", type=int, required=True, help="Fixed local standard time, never DST")
    parser.add_argument("--label", default="IGE background")
    parser.add_argument("--out", type=Path, required=True, help="New directory; existing paths are never overwritten")
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--source-bundle-sha256")
    parser.add_argument("--reference-sources", type=Path)
    parser.add_argument("--nex-sources", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--historical-base-sha256")
    parser.add_argument("--model", default="CanESM5")
    parser.add_argument("--member", default="r1i1p1f1")
    parser.add_argument("--scenario", default="ssp245")
    parser.add_argument("--reference-start-year", type=int, default=2002)
    parser.add_argument("--reference-end-year", type=int, default=2014)
    parser.add_argument("--future-start-year", type=int, default=2040)
    parser.add_argument("--future-end-year", type=int, default=2059)
    args = parser.parse_args()
    if bool(args.source_bundle) != bool(args.source_bundle_sha256):
        parser.error("--source-bundle and --source-bundle-sha256 must be supplied together")
    request = HistoricalRequest(args.latitude, args.longitude, args.year, args.utc_offset_minutes, label=args.label)
    if args.mode == "historical":
        result = run_historical(request, args.out, source_bundle=args.source_bundle, source_bundle_sha256=args.source_bundle_sha256)
    else:
        from .future import PATTERN_SOURCE_SHA
        if not all((args.source_bundle, args.reference_sources, args.nex_sources, args.protocol, args.historical_base_sha256)):
            parser.error("future requires pattern/reference/NEX source packets, registered protocol and historical base SHA")
        if args.source_bundle_sha256 != PATTERN_SOURCE_SHA:
            parser.error("the first registered future pilot requires the pinned original A0 pattern source")
        future = FutureRequest(args.historical_base_sha256, args.model, args.member, args.scenario,
            (args.reference_start_year, args.reference_end_year), (args.future_start_year, args.future_end_year),
            SEMANTICS_VERSION, request.year)
        result = run_future(request, future, pattern_sources=args.source_bundle, reference_sources=args.reference_sources,
            nex_sources=args.nex_sources, protocol=args.protocol, output=args.out)
    print(json.dumps({"output": str(args.out), "records": len(result.data), "quality": asdict(result.quality)}, indent=2))


if __name__ == "__main__":
    main()
