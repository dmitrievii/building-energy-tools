from pathlib import Path


APP = Path("tools/climate_analyzer/app.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        selected_flag = 1 if group_id == str(selected_group_id) else 0\n''',
        '''        # Keep the Leaflet payload invariant when the selected station changes.\n        # Selection is rendered in the Streamlit detail panel instead of mutating\n        # marker geometry, so a station click does not force a map remount.\n        selected_flag = 0\n''',
        "stable marker payload",
    )

    text = replace_once(
        text,
        '''    # Initialize map view only once. After that, always preserve the user's\n    # current zoom and center, especially after clicking another station.\n    default_center = [float(station_groups_all["latitude"].mean()), float(station_groups_all["longitude"].mean())]\n    center = st.session_state.get("station_map_center", default_center)\n    zoom = int(st.session_state.get("station_map_zoom", 2))\n    bounds = st.session_state.get("station_map_bounds")\n\n    if st.button("Reset map view to filtered stations"):\n        st.session_state["station_map_center"] = default_center\n        st.session_state["station_map_zoom"] = 2 if len(station_groups_all) > 25 else 6\n        st.session_state.pop("station_map_bounds", None)\n        st.rerun()\n''',
        '''    # Leaflet owns interactive pan/zoom state. Mirroring every viewport event\n    # through Streamlit causes a rerun feedback loop in which the previous server\n    # center/zoom is written back into the browser. Only an explicit reset changes\n    # the component key and intentionally remounts the map.\n    default_center = [float(station_groups_all["latitude"].mean()), float(station_groups_all["longitude"].mean())]\n    default_zoom = 2 if len(station_groups_all) > 25 else 6\n    map_reset_token = int(st.session_state.get("station_map_reset_token", 0))\n\n    if st.button("Reset map view to filtered stations"):\n        st.session_state["station_map_reset_token"] = map_reset_token + 1\n        st.rerun()\n''',
        "browser-owned map viewport",
    )

    text = replace_once(
        text,
        '''                center=center,\n                zoom=zoom,\n''',
        '''                center=default_center,\n                zoom=default_zoom,\n''',
        "map default view",
    )

    text = replace_once(
        text,
        '''            returned_objects=["last_object_clicked_tooltip", "center", "zoom", "bounds"],\n            key="climate_onebuilding_selectable_cluster_map",\n''',
        '''            # Pan/zoom stays browser-local. Only a station click crosses the\n            # Streamlit component boundary and can trigger a Python rerun.\n            returned_objects=["last_object_clicked_tooltip"],\n            key=f"climate_onebuilding_selectable_cluster_map_{map_reset_token}",\n''',
        "st_folium event contract",
    )

    text = replace_once(
        text,
        '''\n    update_station_map_view_state(map_state)\n\n    clicked_group = None\n''',
        '''\n    clicked_group = None\n''',
        "remove viewport feedback write",
    )

    text = replace_once(
        text,
        '''            max_value=50000,\n            value=int(st.session_state.get("station_selectable_cluster_limit", 20000)),\n            step=1000,\n''',
        '''            max_value=100000,\n            value=int(st.session_state.get("station_selectable_cluster_limit", 50000)),\n            step=5000,\n''',
        "global map capacity control",
    )

    text = replace_once(
        text,
        '''    if len(station_groups_for_map) > int(st.session_state.get("station_selectable_cluster_limit", 20000)):\n''',
        '''    if len(station_groups_for_map) > int(st.session_state.get("station_selectable_cluster_limit", 50000)):\n''',
        "global map capacity gate",
    )

    APP.write_text(text, encoding="utf-8")
    print("WEB-1.1 map remediation applied")


if __name__ == "__main__":
    main()
