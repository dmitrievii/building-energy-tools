import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")
DATA = ROOT / "epw_climate_analyzer" / "data"


def test_map_viewport_is_browser_owned():
    assert 'returned_objects=["last_object_clicked_tooltip"]' in APP
    assert 'returned_objects=["last_object_clicked_tooltip", "center", "zoom", "bounds"]' not in APP
    assert "update_station_map_view_state(map_state)" not in APP
    assert 'key=f"climate_onebuilding_selectable_cluster_map_{map_reset_token}"' in APP
    assert "station_map_reset_token" in APP


def test_station_selection_does_not_mutate_map_payload():
    assert "selected_flag = 0" in APP
    assert "selected_flag = 1 if group_id == str(selected_group_id) else 0" not in APP


def test_global_catalog_is_integrity_bound_and_not_bootstrap():
    manifest = json.loads((DATA / "station_catalog.meta.json").read_text(encoding="utf-8"))
    csv_bytes = (DATA / "station_catalog.csv").read_bytes()

    assert manifest["catalog_kind"] == "generated_provider_snapshot"
    assert manifest["station_count"] > 20
    assert len(manifest["build_evidence"]["regions"]) == 7
    assert manifest["build_evidence"]["failed_catalogs"] == 0
    assert hashlib.sha256(csv_bytes).hexdigest() == manifest["csv_sha256"]

    coverage = manifest["coverage"].lower()
    expected_regions = (
        "africa",
        "asia",
        "south america",
        "north and central america",
        "southwest pacific",
        "europe",
        "antarctica",
    )
    for region in expected_regions:
        assert region in coverage
