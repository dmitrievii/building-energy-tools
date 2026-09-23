from pathlib import Path

path = Path("tools/climate_analyzer/app.py")
text = path.read_text(encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {count}")
    return source.replace(old, new, 1)


text = replace_once(
    text,
    '''    resolutions = available_resolution_labels(df)\n    n_series = st.slider("Number of series", min_value=1, max_value=6, value=2, step=1)\n''',
    '''    resolutions = available_resolution_labels(df)\n    # Streamlit rehydrates widget state by key from the browser.  Resolution\n    # choices are only reusable while their temporal/native-resolution context\n    # is unchanged; a context-specific widget key prevents a stale Monthly\n    # choice from leaking into an Interannual/native-monthly view.\n    overlay_resolution_context = f"{time_basis(df)}|{'|'.join(resolutions)}"\n    n_series = st.slider("Number of series", min_value=1, max_value=6, value=2, step=1)\n''',
    "overlay resolution context",
)

text = replace_once(
    text,
    '''            key=f"overlay_resolution_{i}",\n''',
    '''            key=f"overlay_resolution_{overlay_resolution_context}_{i}",\n''',
    "overlay resolution widget key",
)

path.write_text(text, encoding="utf-8")
