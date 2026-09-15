from pathlib import Path

APP = Path("tools/climate_analyzer/app.py")


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    head_marker = "<<<<<<< HEAD"
    end_marker = ">>>>>>> origin/climate-geosphere-0.3-public-historical-selection"
    if text.count(head_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit("Expected exactly one known app.py merge conflict")

    start = text.index(head_marker)
    end = text.index(end_marker, start) + len(end_marker)
    replacement = '''@st.cache_data(show_spinner=False, ttl=3600)
def cached_geosphere_metadata() -> dict:
    """Cache current GeoSphere metadata for one hour within a user session/runtime."""
    from epw_climate_analyzer.geosphere import fetch_metadata

    return fetch_metadata()


@st.cache_resource(show_spinner=False, max_entries=1)'''
    resolved = text[:start] + replacement + text[end:]
    if any(marker in resolved for marker in ("<<<<<<<", "|||||||", "=======", ">>>>>>>")):
        raise SystemExit("Conflict markers remain in app.py")

    APP.write_text(resolved, encoding="utf-8")
    print(
        "Resolved app.py: retained GeoSphere metadata TTL cache and "
        "current memory-safe station catalog cache_resource."
    )


if __name__ == "__main__":
    main()
