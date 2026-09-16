from __future__ import annotations

from pathlib import Path
import re

APP = Path("tools/climate_analyzer/app.py")
text = APP.read_text(encoding="utf-8")
original = text

cache_anchor = '''@st.cache_data(show_spinner=False, max_entries=8)
def _cached_station_group_options(
    map_cache_key: str,
    limit: int,
    _station_groups: pd.DataFrame,
) -> dict[str, str]:
    """Cache the manual station-group selector derived from the same immutable groups."""
    return station_group_options_from_groups(_station_groups, limit=limit)
'''
cache_insert = cache_anchor + '''

@st.cache_data(show_spinner=False, max_entries=8)
def _cached_station_marker_payload(
    map_cache_key: str,
    _station_groups: pd.DataFrame,
) -> list[list[object]]:
    """Cache the compact browser marker payload for one immutable map/filter state."""
    return station_marker_payload(_station_groups)


@st.cache_data(show_spinner=False, max_entries=512)
def _cached_catalog_rows_for_station_group(
    map_cache_key: str,
    station_group_id: str,
    _catalog: pd.DataFrame,
    _station_group: object,
) -> pd.DataFrame:
    """Cache one station group's climate rows for the exact catalog/filter identity."""
    return catalog_rows_for_station_group(_catalog, _station_group)
'''
if cache_anchor not in text:
    raise SystemExit("cache anchor not found")
text = text.replace(cache_anchor, cache_insert, 1)

pattern = re.compile(
    r"def station_catalog_fast_selectable_map\(.*?\n\ndef station_group_from_tooltip\(",
    re.S,
)
replacement = '''def station_marker_payload(station_groups: pd.DataFrame) -> list[list[object]]:
    """Return the minimal stable marker payload needed by the browser map.

    The right-hand station panel owns rich metadata.  The map therefore sends
    only coordinates, a positional station index and a short label.  This keeps
    the world-map transfer bounded while preserving exact click resolution.
    """
    payload: list[list[object]] = []
    if station_groups.empty:
        return payload
    columns = list(station_groups.columns)
    lat_idx = columns.index("latitude")
    lon_idx = columns.index("longitude")
    name_idx = columns.index("name")
    country_idx = columns.index("country")
    for station_idx, row in enumerate(station_groups.itertuples(index=False, name=None)):
        try:
            lat = float(row[lat_idx])
            lon = float(row[lon_idx])
        except (TypeError, ValueError):
            continue
        if pd.isna(lat) or pd.isna(lon):
            continue
        name = _map_text(row[name_idx])
        country = _map_text(row[country_idx])
        label = f"{name} — {country}" if country else name
        payload.append([lat, lon, int(station_idx), label])
    return payload


def station_catalog_persistent_map_layers(
    station_groups: pd.DataFrame,
    marker_payload: list[list[object]] | None = None,
    center: list[float] | None = None,
    zoom: int = 2,
    detail_zoom_threshold: int = 8,
) -> tuple[folium.Map, folium.FeatureGroup]:
    """Build a lightweight base map plus a dynamically managed marker layer.

    ``streamlit-folium`` keeps the mounted Leaflet map alive when marker data are
    supplied via ``feature_group_to_add``.  The feature-group string is compared
    in the browser, so an unchanged station layer is not recreated after a
    station click.  A fresh Python Folium base object is still used on every
    rerun to avoid mutable-JS identifier reuse.
    """
    center_lat = float(station_groups["latitude"].mean()) if center is None and not station_groups.empty else (center[0] if center else 20.0)
    center_lon = float(station_groups["longitude"].mean()) if center is None and not station_groups.empty else (center[1] if center else 0.0)
    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=int(zoom),
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    feature_group = folium.FeatureGroup(name="Climate stations", overlay=True, control=False)
    data = marker_payload if marker_payload is not None else station_marker_payload(station_groups)
    callback = """
    function (row) {
        var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {
            radius: 6,
            color: '#7c3aed',
            fillColor: '#7c3aed',
            fillOpacity: 0.86,
            weight: 1
        });
        marker.bindTooltip('station_idx=' + row[2] + ' | ' + row[3], {sticky: true});
        return marker;
    }
    """
    if data:
        FastMarkerCluster(
            data,
            callback=callback,
            name=f"Station clusters ({len(data):,})",
            disableClusteringAtZoom=int(detail_zoom_threshold),
            spiderfyOnMaxZoom=True,
            showCoverageOnHover=False,
            chunkedLoading=True,
        ).add_to(feature_group)
    return fmap, feature_group


def station_catalog_fast_selectable_map(
    station_groups: pd.DataFrame,
    selected_group_id: str | None = None,
    center: list[float] | None = None,
    zoom: int = 2,
    detail_zoom_threshold: int = 8,
) -> folium.Map:
    """Compatibility wrapper returning a standalone selectable Folium map."""
    fmap, marker_group = station_catalog_persistent_map_layers(
        station_groups,
        center=center,
        zoom=zoom,
        detail_zoom_threshold=detail_zoom_threshold,
    )
    marker_group.add_to(fmap)
    return fmap


def station_group_from_tooltip('''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"selectable-map function replacement count={count}")

old_tooltip = '''def station_group_from_tooltip(station_groups: pd.DataFrame, tooltip: str | None) -> pd.Series | None:
    """Resolve a clicked grouped station tooltip to a station-group row."""
    if not tooltip or "station_group_id=" not in tooltip:
        return None
    group_id = tooltip.split("station_group_id=", 1)[1].split(" | ", 1)[0].strip()
    matches = station_groups[station_groups["station_group_id"].astype(str) == group_id]
    if matches.empty:
        return None
    return matches.iloc[0]
'''
new_tooltip = '''def station_group_from_tooltip(station_groups: pd.DataFrame, tooltip: str | None) -> pd.Series | None:
    """Resolve a clicked grouped station tooltip to a station-group row."""
    if not tooltip:
        return None
    if "station_idx=" in tooltip:
        raw = tooltip.split("station_idx=", 1)[1].split(" | ", 1)[0].strip()
        try:
            station_idx = int(raw)
        except ValueError:
            return None
        if 0 <= station_idx < len(station_groups):
            return station_groups.iloc[station_idx]
        return None
    if "station_group_id=" not in tooltip:
        return None
    group_id = tooltip.split("station_group_id=", 1)[1].split(" | ", 1)[0].strip()
    matches = station_groups[station_groups["station_group_id"].astype(str) == group_id]
    if matches.empty:
        return None
    return matches.iloc[0]
'''
if old_tooltip not in text:
    raise SystemExit("tooltip resolver anchor not found")
text = text.replace(old_tooltip, new_tooltip, 1)

old_render = '''        map_state = st_folium(
            station_catalog_fast_selectable_map(
                station_groups_for_map,
                selected_group_id=None,
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
new_render = '''        marker_payload = _cached_station_marker_payload(map_cache_key, station_groups_for_map)
        base_map, marker_group = station_catalog_persistent_map_layers(
            station_groups_for_map,
            marker_payload=marker_payload,
            center=[20.0, 0.0],
            zoom=2,
            detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),
        )
        map_state = st_folium(
            base_map,
            feature_group_to_add=marker_group,
            height=620,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip"],
            center=tuple(default_center),
            zoom=initial_zoom,
            key=f"climate_onebuilding_selectable_cluster_map_{int(st.session_state.get('station_map_view_epoch', 0))}",
        )
'''
if old_render not in text:
    raise SystemExit("production map render anchor not found")
text = text.replace(old_render, new_render, 1)

old_rows = '''    selected_climates = catalog_rows_for_station_group(filtered_catalog, selected_group)
'''
new_rows = '''    selected_climates = _cached_catalog_rows_for_station_group(
        map_cache_key,
        str(selected_group.get("station_group_id", "")),
        filtered_catalog,
        selected_group,
    )
'''
if old_rows not in text:
    raise SystemExit("selected climates anchor not found")
text = text.replace(old_rows, new_rows, 1)

if text == original:
    raise SystemExit("patch produced no changes")
APP.write_text(text, encoding="utf-8")
print("CLIMATE-0.6.2 persistent-map patch applied")
