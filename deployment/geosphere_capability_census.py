from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.climate_model import CANONICAL_VARIABLES
from epw_climate_analyzer.geosphere import FIELD_SPEC_BY_PROVIDER, fetch_metadata, parse_parameters
from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES

HIGH_PRIORITY_MISSING = {
    "ffx": "maximum 10-minute wind gust speed",
    "ddx": "wind direction at maximum gust",
    "so": "sunshine duration",
    "tlmin": "10-minute minimum 2 m air temperature",
    "tlmax": "10-minute maximum 2 m air temperature",
}
SECONDARY_BUILDING_RELEVANT = {
    "tb10": "soil temperature at -10 cm",
    "tb20": "soil temperature at -20 cm",
    "tb50": "soil temperature at -50 cm",
    "ts": "air temperature at 5 cm",
    "tsmin": "10-minute minimum air temperature at 5 cm",
    "tsmax": "10-minute maximum air temperature at 5 cm",
    "zeitx": "time of maximum gust inside the 10-minute interval",
}
LOW_PRIORITY_OR_REDUNDANT = {
    "ff": "vector-mean 10 m wind speed; arithmetic mean ffam is already used",
    "pred": "sea-level-reduced pressure; station pressure p is the correct psychrometric input",
}


def static_page_audit() -> dict[str, object]:
    idx = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    data: dict[str, list[float]] = {}
    for spec in FIELD_SPEC_BY_PROVIDER.values():
        data[spec.canonical_name] = [1.0] * len(idx)
    frame = pd.DataFrame(data, index=idx)
    historical = list(available_historical_pages(frame))
    epw = list(NAVIGATION_PAGES)
    return {
        "epw_navigation_pages": epw,
        "geosphere_current_pages_with_all_supported_observations": historical,
        "missing_geosphere_pages": [page for page in epw if page not in historical],
        "shared_pages": [page for page in epw if page in historical],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="artifacts/geosphere-capability-census/census.json")
    parser.add_argument("--markdown", dest="markdown_path", default="artifacts/geosphere-capability-census/CENSUS.md")
    args = parser.parse_args()

    metadata = fetch_metadata(timeout_s=60)
    parameters = parse_parameters(metadata)
    names = sorted(parameters)
    physical = [name for name in names if not name.endswith("_flag")]
    flags = [name for name in names if name.endswith("_flag")]
    supported = sorted(set(physical) & set(FIELD_SPEC_BY_PROVIDER))
    unsupported = sorted(set(physical) - set(FIELD_SPEC_BY_PROVIDER))
    high = [name for name in unsupported if name in HIGH_PRIORITY_MISSING]
    secondary = [name for name in unsupported if name in SECONDARY_BUILDING_RELEVANT]
    low = [name for name in unsupported if name in LOW_PRIORITY_OR_REDUNDANT]
    uncategorized = sorted(set(unsupported) - set(high) - set(secondary) - set(low))

    consumed_flags = sorted(
        flag_name
        for name in supported
        for flag_name in (f"{name}_flag",)
        if flag_name in parameters
    )
    unconsumed_flags = sorted(set(flags) - set(consumed_flags))

    canonical_supported = sorted({FIELD_SPEC_BY_PROVIDER[name].canonical_name for name in supported})
    canonical_missing = sorted(set(CANONICAL_VARIABLES) - set(canonical_supported))
    page_audit = static_page_audit()

    report = {
        "resource": "klima-v2-10min",
        "parameter_count": len(names),
        "physical_parameter_count": len(physical),
        "quality_flag_count": len(flags),
        "supported_physical_parameters": supported,
        "unsupported_physical_parameters": unsupported,
        "high_priority_missing": {name: HIGH_PRIORITY_MISSING[name] for name in high},
        "secondary_building_relevant_missing": {name: SECONDARY_BUILDING_RELEVANT[name] for name in secondary},
        "low_priority_or_redundant": {name: LOW_PRIORITY_OR_REDUNDANT[name] for name in low},
        "uncategorized_physical_parameters": uncategorized,
        "quality_flags_consumed_for_mapped_parameters": consumed_flags,
        "quality_flags_not_consumed_by_adapter": unconsumed_flags,
        "canonical_variables_supported_by_geosphere_adapter": canonical_supported,
        "canonical_variables_not_directly_mapped_from_geosphere": canonical_missing,
        "page_parity": page_audit,
        "all_live_parameters": {
            name: {
                "long_name": parameters[name].long_name,
                "unit": parameters[name].unit,
                "description": parameters[name].description,
            }
            for name in names
        },
    }

    json_path = Path(args.json_path)
    md_path = Path(args.markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# GeoSphere capability census",
        "",
        f"- Live parameters: **{len(names)}**",
        f"- Physical parameters: **{len(physical)}**",
        f"- Quality flags: **{len(flags)}**",
        f"- Physical parameters currently mapped: **{len(supported)} / {len(physical)}**",
        f"- Matching quality flags consumed for mapped parameters: **{len(consumed_flags)} / {len(flags)}**",
        f"- EPW navigation pages: **{len(page_audit['epw_navigation_pages'])}**",
        f"- GeoSphere pages with all currently mapped observations present: **{len(page_audit['geosphere_current_pages_with_all_supported_observations'])}**",
        "",
        "## Current page gaps",
        "",
    ]
    for page in page_audit["missing_geosphere_pages"]:
        lines.append(f"- {page}")
    lines.extend(["", "## High-priority provider fields not mapped", ""])
    if high:
        for name in high:
            p = parameters[name]
            lines.append(f"- `{name}` — {p.long_name or HIGH_PRIORITY_MISSING[name]} [{p.unit}]")
    else:
        lines.append("- None. The Priority-A provider fields identified by the 0.7.2 audit are mapped.")
    lines.extend(["", "## Secondary building-relevant provider fields not mapped", ""])
    for name in secondary:
        p = parameters[name]
        lines.append(f"- `{name}` — {p.long_name or SECONDARY_BUILDING_RELEVANT[name]} [{p.unit}]")
    lines.extend(["", "## Quality flags", ""])
    lines.append(
        f"The live resource exposes {len(flags)} `*_flag` fields. The adapter consumes the exact matching flag for each mapped physical parameter when it is present in live metadata: **{len(consumed_flags)} consumed**, **{len(unconsumed_flags)} not consumed**."
    )
    lines.append(
        "Consumed flags are retained as provider-native diagnostic metadata and are not promoted to physical canonical variables."
    )
    if unconsumed_flags:
        lines.append("")
        lines.append("Unconsumed flags belong to physical provider fields that are themselves not mapped:")
        for name in unconsumed_flags:
            lines.append(f"- `{name}`")
    lines.extend(["", "## Complete unsupported physical parameter list", ""])
    for name in unsupported:
        p = parameters[name]
        lines.append(f"- `{name}` — {p.long_name} [{p.unit}]")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
