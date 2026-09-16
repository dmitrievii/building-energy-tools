from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
TEST = ROOT / "tools" / "climate_analyzer" / "tests" / "test_onebuilding_map_cache_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    app = APP.read_text(encoding="utf-8")
    old_func = '''\n@st.cache_resource(show_spinner=False, max_entries=8)\ndef _cached_station_map_resource(\n    map_cache_key: str,\n    detail_zoom_threshold: int,\n    _station_groups: pd.DataFrame,\n):\n    \"\"\"Cache the immutable Folium map so station-click reruns do not rebuild ~26k markers.\"\"\"\n    return station_catalog_fast_selectable_map(\n        _station_groups,\n        selected_group_id=None,\n        center=[20.0, 0.0],\n        zoom=2,\n        detail_zoom_threshold=int(detail_zoom_threshold),\n    )\n\n'''
    app = replace_once(app, old_func, "\n", "remove mutable Folium cache")

    old_call = '''            _cached_station_map_resource(\n                f"{map_cache_key}|limit={int(st.session_state.get('station_selectable_cluster_limit', 50000))}|rows={len(station_groups_for_map)}",\n                int(st.session_state.get("station_detail_zoom_threshold", 8)),\n                station_groups_for_map,\n            ),\n'''
    new_call = '''            station_catalog_fast_selectable_map(\n                station_groups_for_map,\n                selected_group_id=None,\n                center=[20.0, 0.0],\n                zoom=2,\n                detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),\n            ),\n'''
    app = replace_once(app, old_call, new_call, "restore fresh Folium map construction")
    APP.write_text(app, encoding="utf-8")

    test = TEST.read_text(encoding="utf-8")
    test = test.replace(
        '    def test_world_map_uses_snapshot_and_cached_folium_resource(self) -> None:\n',
        '    def test_world_map_uses_snapshot_and_fresh_folium_resource(self) -> None:\n',
    )
    test = test.replace('        self.assertIn("def _cached_station_map_resource(", app)\n', '')
    test = test.replace('        self.assertIn("_cached_station_map_resource(", app)\n', '        self.assertNotIn("def _cached_station_map_resource(", app)\n        self.assertIn("station_catalog_fast_selectable_map(", app)\n')
    TEST.write_text(test, encoding="utf-8")
    print("fresh Folium render hotfix applied")


if __name__ == "__main__":
    main()
