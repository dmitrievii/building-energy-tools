"""Linked point/map editor; changing location never acquires weather data.

The layout and Leaflet/OSM stack follow the GeoSphere source panel. A supplied
height describes user intent only; it is not a qualified weather correction.
"""
from __future__ import annotations

import math
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


def render_location_map(state: MutableMapping, *, height: int = 560, purpose: str = "background") -> None:
    """Render the live component; callback runs before the next widget pass."""
    import folium
    from streamlit_folium import st_folium

    lat, lon = _coordinates(state[LATITUDE], state[LONGITUDE])
    centre = [max(-85.0, min(85.0, lat)), lon]
    fmap = folium.Map(location=centre, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    supplied_height = state[HEIGHT]
    suffix = "used by interpolation" if purpose == "interpolation" else "not applied"
    height_label = "height unspecified" if supplied_height is None else f"requested height {supplied_height:g} m ({suffix})"
    folium.Marker([lat, lon], tooltip=f"Selected point · {lat:.5f}°, {lon:.5f}° · {height_label}").add_to(fmap)
    key = f"ige_selected_point_map_{state[EPOCH]}"
    st_folium(fmap, height=height, use_container_width=True, returned_objects=["last_clicked"],
              center=tuple(centre), key=key, on_change=lambda: accept_map_click(state, key))


def render_point_picker(st, *, purpose: str = "background") -> tuple[float, float, float | None, str]:
    initialize_point(st.session_state)
    left, right = st.columns([2, 1])
    # Render the widgets before the component, so map callbacks can update their
    # state before the subsequent script run. Layout still places the map left.
    with right:
        st.markdown("#### Selected point")
        st.number_input("Latitude [°]", -90.0, 90.0, format="%.5f", key=LATITUDE,
                        on_change=lambda: coordinates_edited(st.session_state))
        st.number_input("Longitude [°]", -180.0, 180.0, format="%.5f", key=LONGITUDE,
                        on_change=lambda: coordinates_edited(st.session_state))
        st.number_input("Site elevation [m] — required" if purpose == "interpolation" else "Site elevation [m] — optional", -500.0, 9000.0, value=None,
                        placeholder="Enter a known site elevation", key=HEIGHT)
        st.text_input("Elevation source / vertical datum", key=HEIGHT_REFERENCE,
                      placeholder="Required when elevation is supplied")
        st.caption("Moving the point clears its previous elevation. Enter elevation after choosing the point.")
        if purpose == "interpolation":
            st.info("This elevation is used in the temperature, vapour-pressure and pressure corrections. Supply its source and vertical reference. Monthly regional corrections do not resolve local inversions.")
        else:
            st.info("Site elevation is recorded with the request. This background route does not apply a local height correction; the EPW keeps the source grid location and height.")
    with left:
        st.caption("Click the map to select a point. Editing the coordinates moves the marker. Map edits do not request weather data.")
        if st.button("Reset map", key="ige_point_reset_map"):
            st.session_state[EPOCH] += 1
        if purpose == "background":
            render_location_map(st.session_state)
        else:
            render_location_map(st.session_state, purpose=purpose)
    return (float(st.session_state[LATITUDE]), float(st.session_state[LONGITUDE]),
            st.session_state[HEIGHT], str(st.session_state[HEIGHT_REFERENCE]).strip())
