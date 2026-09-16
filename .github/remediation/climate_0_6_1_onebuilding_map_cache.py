from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    global catalog_runtime_summary, load_production_station_catalog, load_station_catalog_manifest, station_provenance_text\n''',
        '''    global catalog_runtime_summary, load_production_station_catalog, load_station_catalog_manifest, station_provenance_text\n    global load_station_group_snapshot\n''',
        "declare station snapshot loader",
    )

    old = '''    from epw_climate_analyzer.catalog_runtime import (\n        catalog_runtime_summary,\n        load_production_station_catalog,\n        load_station_catalog_manifest,\n        station_provenance_text,\n    )\n    _MAP_DEPENDENCIES_LOADED = True\n'''
    new = '''    from epw_climate_analyzer.catalog_runtime import (\n        catalog_runtime_summary,\n        load_production_station_catalog,\n        load_station_catalog_manifest,\n        station_provenance_text,\n    )\n    from epw_climate_analyzer.station_group_snapshot import load_station_group_snapshot\n    _MAP_DEPENDENCIES_LOADED = True\n'''
    text = replace_once(text, old, new, "import station snapshot loader")

    marker = '''    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)\n\n\ndef station_options_from_catalog'''
    replacement = '''    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)\n\n\ndef _onebuilding_map_cache_key(\n    catalog_identity: str,\n    search_text: str,\n    countries: list[str],\n    datasets: list[str],\n) -> str:\n    \"\"\"Return a deterministic identity for one immutable OneBuilding map/filter state.\"\"\"\n    country_key = ",".join(sorted(str(value).strip() for value in countries if str(value).strip()))\n    dataset_key = ",".join(sorted(str(value).strip() for value in datasets if str(value).strip()))\n    return f\"{catalog_identity}|q={search_text.strip().casefold()}|c={country_key}|d={dataset_key}\"\n\n\n@st.cache_resource(show_spinner=False, max_entries=4)\ndef _cached_station_group_snapshot(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:\n    \"\"\"Load the release-time physical-station snapshot once per immutable catalog identity.\"\"\"\n    return load_station_group_snapshot(catalog_version, catalog_sha256)\n\n\n@st.cache_resource(show_spinner=False, max_entries=4)\ndef _cached_catalog_filter_options(catalog_identity: str, _catalog: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:\n    \"\"\"Cache stable country/dataset selector values for one reviewed catalog snapshot.\"\"\"\n    countries = tuple(sorted(value for value in _catalog[\"country\"].dropna().unique().tolist() if str(value).strip()))\n    datasets = tuple(sorted(value for value in _catalog[\"dataset\"].dropna().unique().tolist() if str(value).strip()))\n    return countries, datasets\n\n\n@st.cache_resource(show_spinner=False, max_entries=8)\ndef _cached_grouped_station_catalog(map_cache_key: str, _catalog: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"Cache filtered physical-station grouping; the unfiltered route uses the release snapshot.\"\"\"\n    return grouped_station_catalog(_catalog)\n\n\n@st.cache_resource(show_spinner=False, max_entries=8)\ndef _cached_station_map_resource(\n    map_cache_key: str,\n    detail_zoom_threshold: int,\n    _station_groups: pd.DataFrame,\n):\n    \"\"\"Cache the immutable Folium map so station-click reruns do not rebuild ~26k markers.\"\"\"\n    return station_catalog_fast_selectable_map(\n        _station_groups,\n        selected_group_id=None,\n        center=[20.0, 0.0],\n        zoom=2,\n        detail_zoom_threshold=int(detail_zoom_threshold),\n    )\n\n\n@st.cache_data(show_spinner=False, max_entries=8)\ndef _cached_station_group_options(\n    map_cache_key: str,\n    limit: int,\n    _station_groups: pd.DataFrame,\n) -> dict[str, str]:\n    \"\"\"Cache the manual station-group selector derived from the same immutable groups.\"\"\"\n    return station_group_options_from_groups(_station_groups, limit=limit)\n\n\ndef station_options_from_catalog'''
    text = replace_once(text, marker, replacement, "insert OneBuilding caches")

    old = '''    countries = sorted([value for value in catalog["country"].dropna().unique().tolist() if str(value).strip()])\n    datasets = sorted([value for value in catalog["dataset"].dropna().unique().tolist() if str(value).strip()])\n    selected_countries = col_filter2.multiselect("Countries", countries, default=[])\n    selected_datasets = col_filter3.multiselect("Datasets", datasets, default=[])\n    filtered_catalog = filter_station_catalog(\n        catalog,\n        search_text=search_text,\n        countries=selected_countries if selected_countries else None,\n        datasets=selected_datasets if selected_datasets else None,\n    )\n'''
    new = '''    catalog_version = str(catalog["catalog_version"].iloc[0])\n    catalog_sha256 = str(catalog["catalog_sha256"].iloc[0])\n    catalog_identity = f"{catalog_version}:{catalog_sha256}"\n    countries, datasets = _cached_catalog_filter_options(catalog_identity, catalog)\n    selected_countries = col_filter2.multiselect("Countries", countries, default=[])\n    selected_datasets = col_filter3.multiselect("Datasets", datasets, default=[])\n    map_cache_key = _onebuilding_map_cache_key(catalog_identity, search_text, selected_countries, selected_datasets)\n    uses_full_catalog_snapshot = not search_text.strip() and not selected_countries and not selected_datasets\n    if uses_full_catalog_snapshot:\n        # Common world-map route: reuse the immutable reviewed catalog and a release-time\n        # physical-station snapshot. No 98k-row copy or live grouping is required.\n        filtered_catalog = catalog\n    else:\n        filtered_catalog = filter_station_catalog(\n            catalog,\n            search_text=search_text,\n            countries=selected_countries if selected_countries else None,\n            datasets=selected_datasets if selected_datasets else None,\n        )\n'''
    text = replace_once(text, old, new, "cache filter options and fast-path empty filters")

    text = replace_once(
        text,
        '''    station_groups_all = grouped_station_catalog(filtered_catalog)\n    if station_groups_all.empty:\n''',
        '''    if uses_full_catalog_snapshot:\n        try:\n            station_groups_all = _cached_station_group_snapshot(catalog_version, catalog_sha256)\n        except Exception as exc:\n            st.warning(f"Pre-grouped station snapshot is unavailable; rebuilding the map index once: {exc}")\n            station_groups_all = _cached_grouped_station_catalog(map_cache_key, filtered_catalog)\n    else:\n        station_groups_all = _cached_grouped_station_catalog(map_cache_key, filtered_catalog)\n    if station_groups_all.empty:\n''',
        "use pre-grouped station snapshot",
    )

    old = '''            station_catalog_fast_selectable_map(\n                station_groups_for_map,\n                selected_group_id=selected_group_id,\n                center=[20.0, 0.0],\n                zoom=2,\n                detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),\n            ),\n'''
    new = '''            _cached_station_map_resource(\n                f"{map_cache_key}|limit={int(st.session_state.get('station_selectable_cluster_limit', 50000))}|rows={len(station_groups_for_map)}",\n                int(st.session_state.get("station_detail_zoom_threshold", 8)),\n                station_groups_for_map,\n            ),\n'''
    text = replace_once(text, old, new, "cache Folium map resource")

    text = replace_once(
        text,
        '''        station_group_options = station_group_options_from_groups(station_groups_all, limit=10000)\n''',
        '''        station_group_options = _cached_station_group_options(map_cache_key, 10000, station_groups_all)\n''',
        "cache manual station options",
    )

    APP.write_text(text, encoding="utf-8")
    print("CLIMATE-0.6.1 OneBuilding map cache patch applied")


if __name__ == "__main__":
    main()
