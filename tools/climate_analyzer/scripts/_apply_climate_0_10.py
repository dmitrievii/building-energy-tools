from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CLIMATE_SOURCES = ROOT / "epw_climate_analyzer" / "climate_sources.py"

text = APP.read_text(encoding="utf-8")
original = text

# 1) Remove the server-side zoom/center feedback loop. Leaflet owns ordinary
# pan/zoom state. The server controls only the initial/reset viewport.
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

# 2) Make rendered map content invariant to which station is selected. Selection
# belongs in the right-hand panel; changing marker JS would remount the map and
# destroy the browser-owned viewport.
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

# 3) Restrict component return values to the only interaction that must cause a
# Streamlit rerun: a station selection. Pass viewport through st_folium's dynamic
# center/zoom API and use an epoch key only for explicit resets.
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

# 4) User-facing explanation must match the new browser-owned viewport model.
old = '''            "The map no longer switches between separate Streamlit components while zooming."
'''
new = '''            "Pan and zoom stay in the browser and do not trigger a Streamlit rerun; only station selection or an explicit reset returns control to the app."
'''
assert old in text, "map caption sentence not found"
text = text.replace(old, new, 1)

assert text != original
APP.write_text(text, encoding="utf-8")

# 5) Make catalog-build failures auditable instead of swallowing four upstream
# exceptions into one aggregate count.
source = CLIMATE_SOURCES.read_text(encoding="utf-8")
old = '''        except Exception:
            failed += 1
            continue
'''
new = '''        except Exception as exc:
            failed += 1
            report(
                f"FAILED catalog: {url} [{kind}] "
                f"{type(exc).__name__}: {exc}"
            )
            continue
'''
assert source.count(old) == 1, f"catalog failure handler count={source.count(old)}"
source = source.replace(old, new, 1)
CLIMATE_SOURCES.write_text(source, encoding="utf-8")

print("CLIMATE-0.10 map patch + catalog diagnostics applied")
