from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CLIMATE_SOURCES = ROOT / "epw_climate_analyzer" / "climate_sources.py"

text = APP.read_text(encoding="utf-8")
original = text

# 1) Leaflet/browser owns ordinary pan and zoom state. Streamlit only receives
# a station-click event, so viewport interaction cannot drive Python reruns.
pattern = re.compile(
    r"    # Initialize map view only once\. After that, always preserve the user's\n"
    r"    # current zoom and center, especially after clicking another station\.\n"
    r"    default_center = \[float\(station_groups_all\[\"latitude\"\]\.mean\(\)\), float\(station_groups_all\[\"longitude\"\]\.mean\(\)\)\]\n"
    r"    center = st\.session_state\.get\(\"station_map_center\", default_center\)\n"
    r"    zoom = int\(st\.session_state\.get\(\"station_map_zoom\", 2\)\)\n"
    r"    bounds = st\.session_state\.get\(\"station_map_bounds\"\)\n\n"
    r"    if st\.button\(\"Reset map view to filtered stations\"\):\n"
    r"        st\.session_state\[\"station_map_center\"\] = default_center\n"
    r"        st\.session_state\[\"station_map_zoom\"\] = 2 if len\(station_groups_all\) > 25 else 6\n"
    r"        st\.session_state\.pop\(\"station_map_bounds\", None\)\n"
    r"        st\.rerun\(\)\n"
)
replacement = '''    # Leaflet/browser owns ordinary pan and zoom state. Do not return center,
    # zoom or bounds to Streamlit: those values change continuously and used to
    # trigger Python reruns that could race with a freshly rendered Leaflet view.
    # A reset is explicit and remounts only the map component via a view epoch.
    default_center = [float(station_groups_all["latitude"].mean()), float(station_groups_all["longitude"].mean())]
    initial_zoom = 2 if len(station_groups_all) > 25 else 6
    if "station_map_view_epoch" not in st.session_state:
        st.session_state["station_map_view_epoch"] = 0

    if st.button("Reset map view to filtered stations"):
        st.session_state["station_map_view_epoch"] = int(st.session_state.get("station_map_view_epoch", 0)) + 1
        st.rerun()
'''
text, count = pattern.subn(replacement, text, count=1)
assert count == 1, f"map view-state block replacement count={count}"

old = '''        selected_flag = 1 if group_id == str(selected_group_id) else 0
        data.append([
            float(row["latitude"]),
            float(row["longitude"]),
            group_id,
            name,
            country,
            region,
            dataset,
            climate_count,
            selected_flag,
        ])
'''
new = '''        data.append([
            float(row["latitude"]),
            float(row["longitude"]),
            group_id,
            name,
            country,
            region,
            dataset,
            climate_count,
        ])
'''
assert old in text, "selected marker payload block not found"
text = text.replace(old, new, 1)

old = '''        var color = row[8] === 1 ? '#7c3aed' : '#7c3aed';
        var radius = row[8] === 1 ? 8 : 6;
        var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {
            radius: radius,
            color: color,
            fillColor: color,
            fillOpacity: 0.86,
            weight: row[8] === 1 ? 2 : 1
        });
'''
new = '''        var color = '#7c3aed';
        var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {
            radius: 6,
            color: color,
            fillColor: color,
            fillOpacity: 0.86,
            weight: 1
        });
'''
assert old in text, "selected marker callback block not found"
text = text.replace(old, new, 1)

old = '''            station_catalog_fast_selectable_map(
                station_groups_for_map,
                selected_group_id=selected_group_id,
                center=center,
                zoom=zoom,
                detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),
            ),
            height=620,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip", "center", "zoom", "bounds"],
            key="climate_onebuilding_selectable_cluster_map",
        )

    update_station_map_view_state(map_state)
'''
new = '''            station_catalog_fast_selectable_map(
                station_groups_for_map,
                selected_group_id=selected_group_id,
                center=[20.0, 0.0],
                zoom=2,
                detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),
            ),
            height=620,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip"],
            center=tuple(default_center),
            zoom=initial_zoom,
            key=f"climate_onebuilding_selectable_cluster_map_{int(st.session_state.get('station_map_view_epoch', 0))}",
        )
'''
assert old in text, "st_folium map block not found"
text = text.replace(old, new, 1)

old = '''            "The map no longer switches between separate Streamlit components while zooming."
'''
new = '''            "Pan and zoom stay in the browser and do not trigger a Streamlit rerun; only station selection or an explicit reset returns control to the app."
'''
assert old in text, "map caption sentence not found"
text = text.replace(old, new, 1)

assert text != original
APP.write_text(text, encoding="utf-8")

# 2) Climate.OneBuilding commonly provides the same logical catalog in XLSX and
# KML. Parse both to retain any format-specific records, but fail promotion only
# if every representation of a logical catalog fails. Raw source-file failures
# remain separately counted and logged for auditability.
source = CLIMATE_SOURCES.read_text(encoding="utf-8")
old_dataclass = '''class CatalogBuildReport:
    """Summary of a Climate.OneBuilding catalog build operation."""

    station_count: int
    xlsx_catalog_count: int
    kml_catalog_count: int
    failed_catalog_count: int
    cache_path: Path
'''
new_dataclass = '''class CatalogBuildReport:
    """Summary of a Climate.OneBuilding catalog build operation.

    ``failed_catalog_count`` counts logical catalogs for which no published
    representation could be parsed. ``source_file_failure_count`` counts raw
    XLSX/KML failures even when another representation recovered the catalog.
    """

    station_count: int
    xlsx_catalog_count: int
    kml_catalog_count: int
    failed_catalog_count: int
    source_file_failure_count: int
    recovered_source_file_failure_count: int
    cache_path: Path
'''
assert old_dataclass in source, "CatalogBuildReport block not found"
source = source.replace(old_dataclass, new_dataclass, 1)

old_build = '''    catalog_links = discover_onebuilding_catalog_links(timeout_s=timeout_s, region_pages=region_pages)
    frames: list[pd.DataFrame] = []
    xlsx_ok = 0
    kml_ok = 0
    failed = 0

    for index, item in enumerate(catalog_links, start=1):
        url = item["url"]
        kind = item["kind"]
        report(f"Reading {index}/{len(catalog_links)}: {Path(urlparse(url).path).name}")
        try:
            response = _http_get(url, timeout_s=timeout_s)
            if kind == "xlsx":
                frame = _catalog_from_xlsx(response.content, source_url=url, source_label=item["label"])
                xlsx_ok += 1
            else:
                frame = _catalog_from_kml(response.content, source_url=url, source_label=item["label"])
                kml_ok += 1
            if not frame.empty:
                frames.append(frame)
        except Exception:
            failed += 1
            continue

    if frames:
        catalog = pd.concat(frames, ignore_index=True)
        catalog = _finalize_catalog(catalog)
    else:
        catalog = _empty_catalog()

    cache_path = save_onebuilding_catalog(catalog)
    return CatalogBuildReport(
        station_count=len(catalog),
        xlsx_catalog_count=xlsx_ok,
        kml_catalog_count=kml_ok,
        failed_catalog_count=failed,
        cache_path=cache_path,
    )
'''
new_build = '''    catalog_links = discover_onebuilding_catalog_links(timeout_s=timeout_s, region_pages=region_pages)
    frames: list[pd.DataFrame] = []
    xlsx_ok = 0
    kml_ok = 0
    source_file_failures = 0
    successful_logical_catalogs: set[str] = set()
    failed_files_by_logical_catalog: dict[str, list[str]] = {}

    def logical_catalog_key(url: str) -> str:
        path = urlparse(url).path
        return path.rsplit(".", 1)[0].lower()

    for index, item in enumerate(catalog_links, start=1):
        url = item["url"]
        kind = item["kind"]
        logical_key = logical_catalog_key(url)
        report(f"Reading {index}/{len(catalog_links)}: {Path(urlparse(url).path).name}")
        try:
            response = _http_get(url, timeout_s=timeout_s)
            if kind == "xlsx":
                frame = _catalog_from_xlsx(response.content, source_url=url, source_label=item["label"])
                xlsx_ok += 1
            else:
                frame = _catalog_from_kml(response.content, source_url=url, source_label=item["label"])
                kml_ok += 1
            if frame.empty:
                raise ValueError("parsed catalog contains zero usable station records")
            frames.append(frame)
            successful_logical_catalogs.add(logical_key)
        except Exception as exc:
            source_file_failures += 1
            failed_files_by_logical_catalog.setdefault(logical_key, []).append(url)
            report(
                f"FAILED source representation: {url} [{kind}] "
                f"{type(exc).__name__}: {exc}"
            )

    uncovered_logical_catalogs = {
        key: urls
        for key, urls in failed_files_by_logical_catalog.items()
        if key not in successful_logical_catalogs
    }
    failed_logical_catalog_count = len(uncovered_logical_catalogs)
    unrecovered_source_failures = sum(len(urls) for urls in uncovered_logical_catalogs.values())
    recovered_source_failures = source_file_failures - unrecovered_source_failures

    for key, urls in sorted(uncovered_logical_catalogs.items()):
        report(f"UNRECOVERED logical catalog: {key} | failed representations: {len(urls)}")
    if recovered_source_failures:
        report(
            f"Recovered {recovered_source_failures} failed source representation(s) "
            "through another published representation of the same logical catalog."
        )

    if frames:
        catalog = pd.concat(frames, ignore_index=True)
        catalog = _finalize_catalog(catalog)
    else:
        catalog = _empty_catalog()

    cache_path = save_onebuilding_catalog(catalog)
    return CatalogBuildReport(
        station_count=len(catalog),
        xlsx_catalog_count=xlsx_ok,
        kml_catalog_count=kml_ok,
        failed_catalog_count=failed_logical_catalog_count,
        source_file_failure_count=source_file_failures,
        recovered_source_file_failure_count=recovered_source_failures,
        cache_path=cache_path,
    )
'''
assert old_build in source, "catalog build block not found"
source = source.replace(old_build, new_build, 1)
CLIMATE_SOURCES.write_text(source, encoding="utf-8")

print("CLIMATE-0.10 stable map + logical catalog recovery patch applied")
