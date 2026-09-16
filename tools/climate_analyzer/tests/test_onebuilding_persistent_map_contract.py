from __future__ import annotations

import ast
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _function_source(name: str) -> str:
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {name!r} not found")


def test_persistent_map_uses_dynamic_feature_group() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert "feature_group_to_add=marker_group" in source
    assert "marker_payload = _cached_station_marker_payload" in source
    assert "base_map, marker_group = station_catalog_persistent_map_layers" in source


def test_marker_payload_is_compact_and_index_based() -> None:
    payload_source = _function_source("station_marker_payload")
    assert "station_idx" in payload_source
    assert "payload.append([lat, lon, int(station_idx), label])" in payload_source
    assert "region" not in payload_source
    assert "dataset" not in payload_source
    assert "climate_count" not in payload_source


def test_browser_marker_layer_has_no_per_marker_popup() -> None:
    layer_source = _function_source("station_catalog_persistent_map_layers")
    assert "prefer_canvas=True" in layer_source
    assert "FastMarkerCluster(" in layer_source
    assert "station_idx=" in layer_source
    assert "bindTooltip" in layer_source
    assert "bindPopup" not in layer_source
    assert "Region:" not in layer_source
    assert "Datasets:" not in layer_source


def test_tooltip_resolver_keeps_legacy_fallback() -> None:
    resolver = _function_source("station_group_from_tooltip")
    assert '"station_idx=" in tooltip' in resolver
    assert "station_groups.iloc[station_idx]" in resolver
    assert '"station_group_id="' in resolver


def test_selected_station_climates_are_cached_by_map_identity() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert "def _cached_catalog_rows_for_station_group(" in source
    assert "selected_climates = _cached_catalog_rows_for_station_group(" in source
