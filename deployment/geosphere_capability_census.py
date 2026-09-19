from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from epw_climate_analyzer.climate_model import CANONICAL_VARIABLES
from epw_climate_analyzer.geosphere import (
    available_resource_specs,
    fetch_metadata,
    parse_parameters,
    parse_stations,
    supported_parameter_mapping,
)
from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.ui_contract import NAVIGATION_PAGES


CORE_CANONICAL = {
    "dry_bulb_temperature_c",
    "relative_humidity_pct",
    "atmospheric_station_pressure_pa",
    "wind_speed_m_s",
    "wind_direction_deg",
}
SOLAR_CANONICAL = {
    "global_horizontal_radiation_wh_m2",
    "diffuse_horizontal_radiation_wh_m2",
}


def static_page_audit(canonical_columns: set[str]) -> dict[str, object]:
    idx = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    frame = pd.DataFrame({column: [1.0] * len(idx) for column in sorted(canonical_columns)}, index=idx)
    historical = list(available_historical_pages(frame))
    epw = list(NAVIGATION_PAGES)
    return {
        "epw_navigation_pages": epw,
        "geosphere_pages_with_all_resource_mapped_observations": historical,
        "missing_geosphere_pages": [page for page in epw if page not in historical],
        "shared_pages": [page for page in epw if page in historical],
    }


def _resource_report(resource_id: str, timeout_s: int) -> dict[str, object]:
    spec = next(item for item in available_resource_specs() if item.resource_id == resource_id)
    metadata = fetch_metadata(resource_id=resource_id, timeout_s=timeout_s)
    parameters = parse_parameters(metadata)
    mapping = supported_parameter_mapping(metadata, resource_id=resource_id)
    stations = parse_stations(metadata)

    names = sorted(parameters)
    physical = [name for name in names if not name.endswith("_flag")]
    flags = [name for name in names if name.endswith("_flag")]
    supported_provider = sorted(mapping)
    unsupported_provider = sorted(set(physical) - set(supported_provider))
    canonical_supported = sorted({item.canonical_name for item in mapping.values()})
    canonical_set = set(canonical_supported)
    missing_core = sorted(CORE_CANONICAL - canonical_set)
    if missing_core:
        raise RuntimeError(
            f"GeoSphere live metadata for {resource_id} no longer satisfy the Climate Analyzer core contract: "
            + ", ".join(missing_core)
        )

    matching_flags = sorted(f"{name}_flag" for name in supported_provider if f"{name}_flag" in parameters)
    code_list_flags = sorted(
        name for name in matching_flags if parameters[name].code_list_ref
    )

    radiation = {
        name: {
            "provider": item.provider_name,
            "scale_to_interval_wh_m2": float(item.scale),
            "interval_semantics": item.interval_semantics,
        }
        for name, item in ((field.canonical_name, field) for field in mapping.values())
        if name in SOLAR_CANONICAL
    }

    # Fail closed on the two resource contracts that are critical to cadence
    # parity.  The provider can add fields freely, but it may not silently change
    # the hourly wind identity or radiation interval conversion underneath us.
    if resource_id == "klima-v2-1h":
        if int(spec.native_interval_minutes) != 60:
            raise RuntimeError("klima-v2-1h resource contract is no longer 60 minutes")
        hourly_wind = mapping.get("ff")
        if hourly_wind is None or hourly_wind.canonical_name != "wind_speed_m_s":
            raise RuntimeError("klima-v2-1h live metadata no longer validate ff -> wind_speed_m_s")
        for provider_name in ("cglo", "chim"):
            field = mapping.get(provider_name)
            if field is not None and abs(float(field.scale) - 1.0) > 1e-12:
                raise RuntimeError(f"klima-v2-1h {provider_name} radiation scale must remain 1.0 Wh/m² per W/m² hourly mean")
    elif resource_id == "klima-v2-10min":
        ten_min_wind = mapping.get("ffam")
        if ten_min_wind is None or ten_min_wind.canonical_name != "wind_speed_m_s":
            raise RuntimeError("klima-v2-10min live metadata no longer validate ffam -> wind_speed_m_s")

    return {
        "resource_id": resource_id,
        "label": spec.label,
        "doi": spec.doi,
        "dataset_page": spec.dataset_page,
        "native_interval_minutes": int(spec.native_interval_minutes),
        "station_count": len(stations),
        "parameter_count": len(names),
        "physical_parameter_count": len(physical),
        "quality_flag_count": len(flags),
        "supported_physical_parameters": supported_provider,
        "unsupported_physical_parameters": unsupported_provider,
        "matching_quality_flags_consumed": matching_flags,
        "matching_quality_flags_with_code_list_ref": code_list_flags,
        "canonical_variables_supported": canonical_supported,
        "canonical_variables_not_directly_mapped": sorted(set(CANONICAL_VARIABLES) - canonical_set),
        "core_contract": {
            "required": sorted(CORE_CANONICAL),
            "missing": missing_core,
            "pass": not missing_core,
        },
        "solar_horizontal_components": radiation,
        "page_parity": static_page_audit(canonical_set),
        "all_live_parameters": {
            name: {
                "long_name": parameters[name].long_name,
                "unit": parameters[name].unit,
                "description": parameters[name].description,
                "code_list_ref": parameters[name].code_list_ref,
            }
            for name in names
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_path", default="artifacts/geosphere-capability-census/census.json")
    parser.add_argument("--markdown", dest="markdown_path", default="artifacts/geosphere-capability-census/CENSUS.md")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    reports: dict[str, dict[str, object]] = {}
    for spec in available_resource_specs():
        reports[spec.resource_id] = _resource_report(spec.resource_id, args.timeout)

    canonical_sets = {
        resource_id: set(report["canonical_variables_supported"])
        for resource_id, report in reports.items()
    }
    canonical_union = sorted(set().union(*canonical_sets.values())) if canonical_sets else []
    canonical_intersection = sorted(set.intersection(*canonical_sets.values())) if canonical_sets else []

    report = {
        "schema": "climate-analyzer-geosphere-capability-census-v2",
        "resources": reports,
        "cross_resource": {
            "resource_ids": list(reports),
            "canonical_union": canonical_union,
            "canonical_intersection": canonical_intersection,
            "core_contract_shared": sorted(CORE_CANONICAL),
            "canonical_hourly_target_minutes": 60,
            "klima_v2_1h_fast_path_expected": reports.get("klima-v2-1h", {}).get("native_interval_minutes") == 60,
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
        "The Climate Analyzer uses one canonical adapter/engine for all listed GeoSphere historical resources.",
        "Live metadata are validated independently for every resource; a resource-specific provider field or unit change fails closed.",
        "",
    ]
    for resource_id, item in reports.items():
        lines.extend(
            [
                f"## {resource_id}",
                "",
                f"- Native cadence: **{item['native_interval_minutes']} min**",
                f"- Stations in live metadata: **{item['station_count']}**",
                f"- Live parameters: **{item['parameter_count']}**",
                f"- Physical parameters mapped: **{len(item['supported_physical_parameters'])} / {item['physical_parameter_count']}**",
                f"- Matching quality flags retained: **{len(item['matching_quality_flags_consumed'])}**",
                f"- Canonical variables mapped: **{len(item['canonical_variables_supported'])}**",
                f"- Core T/RH/p/wind contract: **PASS**",
                "",
                "### Mapped provider → canonical fields",
                "",
            ]
        )
        mapping = supported_parameter_mapping(
            fetch_metadata(resource_id=resource_id, timeout_s=args.timeout),
            resource_id=resource_id,
        )
        for provider_name, field in sorted(mapping.items()):
            lines.append(f"- `{provider_name}` → `{field.canonical_name}` (scale {field.scale:g})")
        lines.extend(["", "### Current page gaps with the complete mapped resource vocabulary", ""])
        gaps = item["page_parity"]["missing_geosphere_pages"]
        if gaps:
            lines.extend(f"- {page}" for page in gaps)
        else:
            lines.append("- None")
        lines.append("")

    lines.extend(
        [
            "## Cross-resource contract",
            "",
            f"- Canonical union: **{len(canonical_union)} variables**",
            f"- Canonical intersection: **{len(canonical_intersection)} variables**",
            "- Ordinary analysis target: **60 min canonical hourly**",
            "- `klima-v2-1h`: **native-hourly fast path expected** (no temporal resampling)",
            "- Native source resolution remains an explicit Time Series concern; ordinary charts use the canonical hourly frame.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
