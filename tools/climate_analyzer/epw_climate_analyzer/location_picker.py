"""Linked point/map editor; changing location never acquires weather data.

The layout and Leaflet/OSM stack follow the GeoSphere source panel. A supplied
height describes user intent only; it is not a qualified weather correction.
"""
from __future__ import annotations

import math
import html
from collections.abc import MutableMapping


LATITUDE = "ige_point_latitude"
LONGITUDE = "ige_point_longitude"
HEIGHT = "ige_point_height_m"
HEIGHT_REFERENCE = "ige_point_height_reference"
SELECTED = "ige_point_selected_coordinates"
EPOCH = "ige_point_map_epoch"


def initialize_point(state: MutableMapping) -> None:
    # Austria-wide map centre, not a saved city or weather product.
    state.setdefault(LATITUDE, 47.5)
    state.setdefault(LONGITUDE, 14.2)
    state.setdefault(HEIGHT, None)
    state.setdefault(HEIGHT_REFERENCE, "")
    state.setdefault(SELECTED, (state[LATITUDE], state[LONGITUDE]))
    state.setdefault(EPOCH, 0)


def _coordinates(latitude: object, longitude: object, *, map_click: bool = False) -> tuple[float, float]:
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in (latitude, longitude)):
        raise ValueError("Location requires finite numeric latitude and longitude.")
    lat, lon = float(latitude), float(longitude)
    if map_click and not -180 <= lon <= 180:
        # Leaflet may report a longitude outside the canonical range after a
        # world-wrap pan. It represents the same geographic point.
        lon = (lon + 180.0) % 360.0 - 180.0
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude or longitude is outside its geographic range.")
    return lat, lon


def coordinates_edited(state: MutableMapping) -> bool:
    """Commit a manual edit; a height from the former point cannot follow it."""
    point = _coordinates(state[LATITUDE], state[LONGITUDE])
    if point == tuple(state[SELECTED]):
        return False
    state[SELECTED] = point
    state[HEIGHT] = None
    state[HEIGHT_REFERENCE] = ""
    state[EPOCH] += 1
    state.pop("ige_point_elevation_lookup", None)
    return True


def accept_map_click(state: MutableMapping, component_key: str) -> bool:
    if component_key != f"ige_selected_point_map_{state[EPOCH]}":
        return False
    event = state.get(component_key)
    click = event.get("last_clicked") if isinstance(event, dict) else None
    if not isinstance(click, dict):
        return False
    try:
        point = _coordinates(click.get("lat"), click.get("lng"), map_click=True)
    except ValueError:
        return False
    if point == tuple(state[SELECTED]):
        return False
    state[LATITUDE], state[LONGITUDE] = point
    return coordinates_edited(state)


def render_location_map(state: MutableMapping, *, height: int = 620, purpose: str = "background",
                        sources: tuple | list = (), editable: bool = True, key_suffix: str = "") -> None:
    """Render the live component; callback runs before the next widget pass."""
    import folium
    from folium.plugins import MarkerCluster
    from streamlit_folium import st_folium

    lat, lon = _coordinates(state[LATITUDE], state[LONGITUDE])
    centre = [max(-85.0, min(85.0, lat)), lon]
    fmap = folium.Map(location=centre, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    supplied_height = state[HEIGHT]
    suffix = "used by interpolation" if purpose == "interpolation" else "not applied"
    height_label = "height unspecified" if supplied_height is None else f"requested height {supplied_height:g} m ({suffix})"
    folium.Marker([lat, lon], tooltip=f"Selected point · {lat:.5f}°, {lon:.5f}° · {height_label}").add_to(fmap)
    if sources:
        cluster = MarkerCluster(name="Climate sources", disableClusteringAtZoom=8, showCoverageOnHover=False).add_to(fmap)
        for item in sources:
            color = "#7c3aed" if item.get("selected", False) else "#94a3b8"
            resolution = item.get("nominal_resolution_deg")
            if resolution is not None:
                half = resolution/2
                folium.Rectangle([[max(-90., item["latitude"]-half), max(-180., item["longitude"]-half)],
                                  [min(90., item["latitude"]+half), min(180., item["longitude"]+half)]],
                    color=color, weight=1, fill=True, fill_opacity=.08,
                    tooltip="Nominal ERA5 delivery-cell footprint (0.25°); native model-cell boundaries are unverified").add_to(fmap)
            folium.CircleMarker([item["latitude"], item["longitude"]], radius=7,
                color=color, fill=True, fill_color=color, fill_opacity=.86, weight=2,
                tooltip=html.escape(str(item["label"])),
                popup=folium.Popup(html.escape(str(item.get("detail", item["label"]))), max_width=360)).add_to(cluster)
            if item.get("selected"):
                folium.PolyLine([[lat, lon], [item["latitude"], item["longitude"]]],
                                color=color, weight=1, dash_array="4 5").add_to(fmap)
    key = f"ige_selected_point_map_{state[EPOCH]}" + key_suffix
    options = {"on_change": lambda: accept_map_click(state, key)} if editable else {}
    st_folium(fmap, height=height, use_container_width=True, returned_objects=["last_clicked"] if editable else [],
              center=tuple(centre), key=key, **options)


def elevation_edited(state: MutableMapping) -> None:
    from .site_elevation import MANUAL
    state[HEIGHT_REFERENCE] = MANUAL if state[HEIGHT] is not None else ""


def reset_elevation(state: MutableMapping) -> None:
    state[HEIGHT] = None
    state[HEIGHT_REFERENCE] = ""
    state.pop("ige_point_elevation_lookup", None)


def resolve_point_elevation(state: MutableMapping) -> None:
    """One automatic attempt per selected point; manual edits survive reruns."""
    from .site_elevation import lookup_elevation
    if state[HEIGHT] is not None and not state.get(HEIGHT_REFERENCE):
        elevation_edited(state)
    point = (float(state[LATITUDE]), float(state[LONGITUDE]))
    previous = state.get("ige_point_elevation_lookup", {})
    if previous.get("point") == point or state[HEIGHT] is not None:
        return
    try:
        receipt = lookup_elevation(*point)
        state[HEIGHT] = receipt["elevation_m"]
        state[HEIGHT_REFERENCE] = receipt["source"]
        state["ige_point_elevation_lookup"] = {"point": point, "receipt": receipt}
    except Exception as exc:
        state["ige_point_elevation_lookup"] = {"point": point, "error": str(exc)}


def render_point_picker(st, *, purpose: str = "background", sources: tuple | list = ()) -> tuple[float, float, float | None, str]:
    initialize_point(st.session_state)
    resolve_point_elevation(st.session_state)
    left, right = st.columns([2, 1])
    # Render the widgets before the component, so map callbacks can update their
    # state before the subsequent script run. Layout still places the map left.
    with right:
        st.markdown("#### Selected point")
        st.number_input("Latitude [°]", -90.0, 90.0, format="%.5f", key=LATITUDE,
                        on_change=lambda: coordinates_edited(st.session_state))
        st.number_input("Longitude [°]", -180.0, 180.0, format="%.5f", key=LONGITUDE,
                        on_change=lambda: coordinates_edited(st.session_state))
        st.number_input("Site elevation [m]", -500.0, 9000.0, value=None,
                        placeholder="Automatic, or enter a known elevation", key=HEIGHT,
                        on_change=lambda: elevation_edited(st.session_state))
        st.caption("Elevation is filled automatically from Copernicus GLO-90 via Open-Meteo. You can overwrite it.")
        if st.session_state.get("ige_point_elevation_lookup", {}).get("error"):
            st.caption("Automatic elevation is unavailable. Enter the height manually; no height has been assumed.")
        st.button("Restore automatic elevation", key="ige_point_auto_elevation",
                  on_click=lambda: reset_elevation(st.session_state))
        if purpose == "interpolation":
            st.info("This elevation is used in temperature, moisture and pressure corrections. Terrain-model and sensor-height differences remain uncertain; local inversions are not resolved.")
        else:
            st.info("Site elevation is recorded with the request. This background route does not apply a local height correction; the EPW keeps the source grid location and height.")
    with left:
        st.caption("Click the map or edit coordinates to choose a point. Violet markers show selected sources; grey markers show other candidates. Moving the point refreshes terrain elevation, without requesting weather.")
        if st.button("Reset map", key="ige_point_reset_map"):
            st.session_state[EPOCH] += 1
        if not sources and purpose == "background":
            render_location_map(st.session_state)
        else:
            render_location_map(st.session_state, purpose=purpose, sources=sources)
    return (float(st.session_state[LATITUDE]), float(st.session_state[LONGITUDE]),
            st.session_state[HEIGHT], str(st.session_state[HEIGHT_REFERENCE]).strip())
