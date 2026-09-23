from pathlib import Path

path = Path("tools/climate_analyzer/app.py")
text = path.read_text(encoding="utf-8")

old = '''    resolutions = available_resolution_labels(df)\n    n_series = st.slider("Number of series", min_value=1, max_value=6, value=2, step=1)\n'''
new = '''    resolutions = available_resolution_labels(df)\n    overlay_resolution_context = (\n        str(time_basis(df)),\n        str(df.attrs.get("canonical_native_resolution", "")).strip().lower(),\n        tuple(resolutions),\n    )\n    if st.session_state.get("_overlay_resolution_context") != overlay_resolution_context:\n        for overlay_index in range(6):\n            st.session_state.pop(f"overlay_resolution_{overlay_index}", None)\n        st.session_state["_overlay_resolution_context"] = overlay_resolution_context\n\n    n_series = st.slider("Number of series", min_value=1, max_value=6, value=2, step=1)\n'''

if old not in text:
    raise SystemExit("Expected overlay resolution block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
